-- =====================================================
-- MIGRACION 010: CONTABILIZACION AUTOMATICA GASTOS BANCARIOS
-- Sistema Contable Ecucondor
-- =====================================================

-- Agregar campo para vincular transaccion con asiento contable
ALTER TABLE transacciones_bancarias
ADD COLUMN IF NOT EXISTS asiento_id UUID REFERENCES asientos_contables(id),
ADD COLUMN IF NOT EXISTS contabilizada BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS fecha_contabilizacion TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_transacciones_asiento
    ON transacciones_bancarias(asiento_id) WHERE asiento_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_transacciones_contabilizada
    ON transacciones_bancarias(contabilizada) WHERE contabilizada = true;

COMMENT ON COLUMN transacciones_bancarias.asiento_id IS 'Referencia al asiento contable generado';
COMMENT ON COLUMN transacciones_bancarias.contabilizada IS 'Indica si la transaccion ya fue contabilizada';

-- =====================================================
-- TABLA: cuentas_bancarias_mapeadas
-- Mapeo de cuentas bancarias a cuentas contables
-- =====================================================

CREATE TABLE IF NOT EXISTS cuentas_bancarias_mapeadas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificacion del banco/cuenta
    banco VARCHAR(100) NOT NULL,
    numero_cuenta VARCHAR(50),
    tipo_cuenta VARCHAR(20) DEFAULT 'corriente',

    -- Cuenta contable asociada
    cuenta_contable VARCHAR(20) NOT NULL REFERENCES cuentas_contables(codigo),

    -- Descripcion
    descripcion VARCHAR(200),

    -- Estado
    activa BOOLEAN DEFAULT true,

    -- Auditoria
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(banco, numero_cuenta)
);

COMMENT ON TABLE cuentas_bancarias_mapeadas IS 'Mapeo de cuentas bancarias fisicas a cuentas contables';

-- Insertar mapeo inicial para Produbanco
INSERT INTO cuentas_bancarias_mapeadas (banco, numero_cuenta, cuenta_contable, descripcion)
VALUES
    ('PRODUBANCO', NULL, '1.1.1.02', 'Cuenta corriente Produbanco - Principal'),
    ('BANCO PICHINCHA', NULL, '1.1.1.02', 'Cuenta Banco Pichincha'),
    ('BANCO GUAYAQUIL', NULL, '1.1.1.02', 'Cuenta Banco Guayaquil')
ON CONFLICT DO NOTHING;

-- =====================================================
-- FUNCION: contabilizar_gasto_bancario
-- Genera asiento contable para gastos bancarios
-- =====================================================

CREATE OR REPLACE FUNCTION contabilizar_gasto_bancario(p_transaccion_id UUID)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_trans RECORD;
    v_asiento_id UUID;
    v_periodo_id UUID;
    v_cuenta_banco VARCHAR(20) := '1.1.1.02';  -- Bancos por defecto
    v_cuenta_gasto VARCHAR(20);
    v_concepto TEXT;
BEGIN
    -- Obtener datos de la transaccion
    SELECT
        t.id, t.fecha, t.monto, t.descripcion_original, t.descripcion,
        t.categoria_sugerida, t.cuenta_contable_sugerida, t.tipo,
        t.contabilizada, t.asiento_id,
        t.tipo_iva, t.base_imponible, t.valor_iva
    INTO v_trans
    FROM transacciones_bancarias t
    WHERE t.id = p_transaccion_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Transaccion no encontrada: %', p_transaccion_id;
    END IF;

    -- Verificar que no este ya contabilizada
    IF v_trans.contabilizada = true THEN
        RAISE NOTICE 'Transaccion ya contabilizada: %', p_transaccion_id;
        RETURN v_trans.asiento_id;
    END IF;

    -- Verificar que sea un debito (gasto)
    IF v_trans.tipo != 'debito' THEN
        RAISE NOTICE 'Solo se contabilizan debitos como gastos: %', p_transaccion_id;
        RETURN NULL;
    END IF;

    -- Determinar cuenta de gasto segun categoria
    v_cuenta_gasto := COALESCE(v_trans.cuenta_contable_sugerida, '5.1.2.03');

    -- Verificar que la cuenta de gasto exista
    IF NOT EXISTS (SELECT 1 FROM cuentas_contables WHERE codigo = v_cuenta_gasto) THEN
        v_cuenta_gasto := '5.1.2.03';  -- Fallback a comisiones bancarias
    END IF;

    -- Crear concepto descriptivo
    v_concepto := 'Gasto bancario: ' || COALESCE(v_trans.descripcion, v_trans.descripcion_original);
    IF LENGTH(v_concepto) > 450 THEN
        v_concepto := LEFT(v_concepto, 450);
    END IF;

    -- Obtener o crear periodo contable
    v_periodo_id := crear_periodo_si_no_existe(v_trans.fecha);

    -- Crear asiento contable
    INSERT INTO asientos_contables (
        fecha, concepto, tipo, referencia,
        origen_tipo, origen_id, estado
    )
    VALUES (
        v_trans.fecha,
        v_concepto,
        'automatico',
        'TRX-' || LEFT(v_trans.id::text, 8),
        'transaccion',
        v_trans.id,
        'borrador'
    )
    RETURNING id INTO v_asiento_id;

    -- Crear movimientos (partida doble)
    -- DEBE: Cuenta de gasto
    INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
    VALUES (v_asiento_id, v_cuenta_gasto, v_trans.monto, 0, v_concepto, 1);

    -- HABER: Bancos
    INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
    VALUES (v_asiento_id, v_cuenta_banco, 0, v_trans.monto, v_concepto, 2);

    -- Contabilizar el asiento
    PERFORM contabilizar_asiento(v_asiento_id);

    -- Marcar transaccion como contabilizada
    UPDATE transacciones_bancarias
    SET
        asiento_id = v_asiento_id,
        contabilizada = true,
        fecha_contabilizacion = NOW()
    WHERE id = p_transaccion_id;

    RETURN v_asiento_id;
END;
$$;

COMMENT ON FUNCTION contabilizar_gasto_bancario IS 'Genera asiento contable automatico para gastos bancarios';

-- =====================================================
-- FUNCION: contabilizar_gasto_bancario_con_iva
-- Genera asiento con desglose de IVA si aplica
-- =====================================================

CREATE OR REPLACE FUNCTION contabilizar_gasto_bancario_con_iva(p_transaccion_id UUID)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_trans RECORD;
    v_asiento_id UUID;
    v_periodo_id UUID;
    v_cuenta_banco VARCHAR(20) := '1.1.1.02';
    v_cuenta_gasto VARCHAR(20);
    v_cuenta_iva VARCHAR(20) := '1.1.3.01';  -- IVA en compras (credito tributario)
    v_concepto TEXT;
BEGIN
    -- Obtener datos de la transaccion
    SELECT
        t.id, t.fecha, t.monto, t.descripcion_original, t.descripcion,
        t.categoria_sugerida, t.cuenta_contable_sugerida, t.tipo,
        t.contabilizada, t.asiento_id,
        t.tipo_iva, t.base_imponible, t.valor_iva, t.genera_credito_tributario
    INTO v_trans
    FROM transacciones_bancarias t
    WHERE t.id = p_transaccion_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Transaccion no encontrada: %', p_transaccion_id;
    END IF;

    -- Verificar que no este ya contabilizada
    IF v_trans.contabilizada = true THEN
        RETURN v_trans.asiento_id;
    END IF;

    -- Verificar que sea un debito
    IF v_trans.tipo != 'debito' THEN
        RETURN NULL;
    END IF;

    -- Determinar cuenta de gasto
    v_cuenta_gasto := COALESCE(v_trans.cuenta_contable_sugerida, '5.1.2.03');
    IF NOT EXISTS (SELECT 1 FROM cuentas_contables WHERE codigo = v_cuenta_gasto) THEN
        v_cuenta_gasto := '5.1.2.03';
    END IF;

    -- Concepto
    v_concepto := 'Gasto bancario: ' || COALESCE(v_trans.descripcion, v_trans.descripcion_original);
    IF LENGTH(v_concepto) > 450 THEN
        v_concepto := LEFT(v_concepto, 450);
    END IF;

    -- Periodo
    v_periodo_id := crear_periodo_si_no_existe(v_trans.fecha);

    -- Crear asiento
    INSERT INTO asientos_contables (
        fecha, concepto, tipo, referencia,
        origen_tipo, origen_id, estado
    )
    VALUES (
        v_trans.fecha, v_concepto, 'automatico',
        'TRX-' || LEFT(v_trans.id::text, 8),
        'transaccion', v_trans.id, 'borrador'
    )
    RETURNING id INTO v_asiento_id;

    -- Movimientos segun tipo de IVA
    IF v_trans.tipo_iva = 'gravado_15' AND v_trans.genera_credito_tributario = true
       AND v_trans.base_imponible > 0 AND v_trans.valor_iva > 0 THEN
        -- Con IVA y credito tributario: 3 movimientos
        -- DEBE: Gasto (base imponible)
        INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
        VALUES (v_asiento_id, v_cuenta_gasto, v_trans.base_imponible, 0,
                'Base imponible: ' || v_concepto, 1);

        -- DEBE: IVA Credito Tributario
        INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
        VALUES (v_asiento_id, v_cuenta_iva, v_trans.valor_iva, 0,
                'IVA 15% credito tributario', 2);

        -- HABER: Bancos (total)
        INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
        VALUES (v_asiento_id, v_cuenta_banco, 0, v_trans.monto, v_concepto, 3);
    ELSE
        -- Sin IVA o sin credito tributario: 2 movimientos simples
        INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
        VALUES (v_asiento_id, v_cuenta_gasto, v_trans.monto, 0, v_concepto, 1);

        INSERT INTO movimientos_contables (asiento_id, cuenta_codigo, debe, haber, concepto, orden)
        VALUES (v_asiento_id, v_cuenta_banco, 0, v_trans.monto, v_concepto, 2);
    END IF;

    -- Contabilizar
    PERFORM contabilizar_asiento(v_asiento_id);

    -- Marcar como contabilizada
    UPDATE transacciones_bancarias
    SET
        asiento_id = v_asiento_id,
        contabilizada = true,
        fecha_contabilizacion = NOW()
    WHERE id = p_transaccion_id;

    RETURN v_asiento_id;
END;
$$;

COMMENT ON FUNCTION contabilizar_gasto_bancario_con_iva IS 'Genera asiento con desglose de IVA y credito tributario';

-- =====================================================
-- FUNCION: contabilizar_transacciones_pendientes
-- Contabiliza en lote transacciones clasificadas
-- =====================================================

CREATE OR REPLACE FUNCTION contabilizar_transacciones_pendientes(
    p_categoria_like VARCHAR DEFAULT 'gasto_bancario%'
)
RETURNS TABLE(
    transaccion_id UUID,
    asiento_generado UUID,
    resultado TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_trans RECORD;
    v_asiento UUID;
BEGIN
    FOR v_trans IN
        SELECT id, categoria_sugerida
        FROM transacciones_bancarias
        WHERE tipo = 'debito'
          AND contabilizada = false
          AND categoria_sugerida LIKE p_categoria_like
          AND estado NOT IN ('duplicada', 'descartada', 'error')
        ORDER BY fecha
    LOOP
        BEGIN
            v_asiento := contabilizar_gasto_bancario_con_iva(v_trans.id);
            transaccion_id := v_trans.id;
            asiento_generado := v_asiento;
            resultado := 'OK';
            RETURN NEXT;
        EXCEPTION WHEN OTHERS THEN
            transaccion_id := v_trans.id;
            asiento_generado := NULL;
            resultado := 'ERROR: ' || SQLERRM;
            RETURN NEXT;
        END;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION contabilizar_transacciones_pendientes IS 'Contabiliza en lote las transacciones bancarias pendientes';

-- =====================================================
-- VISTA: v_transacciones_contabilizacion
-- Estado de contabilizacion de transacciones
-- =====================================================

CREATE OR REPLACE VIEW v_transacciones_contabilizacion AS
SELECT
    t.id,
    t.fecha,
    t.descripcion_original,
    t.monto,
    t.tipo,
    t.categoria_sugerida,
    t.cuenta_contable_sugerida,
    t.tipo_iva,
    t.base_imponible,
    t.valor_iva,
    t.genera_credito_tributario,
    t.contabilizada,
    t.asiento_id,
    a.numero_asiento,
    a.estado AS estado_asiento
FROM transacciones_bancarias t
LEFT JOIN asientos_contables a ON a.id = t.asiento_id
WHERE t.tipo = 'debito'
  AND t.estado NOT IN ('duplicada', 'descartada', 'error')
ORDER BY t.fecha DESC;

COMMENT ON VIEW v_transacciones_contabilizacion IS 'Vista de transacciones con estado de contabilizacion';

-- =====================================================
-- VISTA: v_resumen_contabilizacion
-- Resumen de transacciones pendientes/contabilizadas
-- =====================================================

CREATE OR REPLACE VIEW v_resumen_contabilizacion AS
SELECT
    categoria_sugerida,
    tipo_iva,
    COUNT(*) FILTER (WHERE contabilizada = false) AS pendientes,
    COUNT(*) FILTER (WHERE contabilizada = true) AS contabilizadas,
    SUM(monto) FILTER (WHERE contabilizada = false) AS monto_pendiente,
    SUM(monto) FILTER (WHERE contabilizada = true) AS monto_contabilizado
FROM transacciones_bancarias
WHERE tipo = 'debito'
  AND estado NOT IN ('duplicada', 'descartada', 'error')
  AND categoria_sugerida IS NOT NULL
GROUP BY categoria_sugerida, tipo_iva
ORDER BY categoria_sugerida;

COMMENT ON VIEW v_resumen_contabilizacion IS 'Resumen de contabilizacion por categoria';

-- =====================================================
-- FIN MIGRACION 010
-- =====================================================
