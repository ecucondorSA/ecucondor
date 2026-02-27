-- =====================================================
-- MIGRACION 009: CLASIFICACION IVA EN TRANSACCIONES
-- Sistema Contable Ecucondor
-- =====================================================

-- Agregar campos de IVA a transacciones bancarias
ALTER TABLE transacciones_bancarias
ADD COLUMN IF NOT EXISTS tipo_iva VARCHAR(20) DEFAULT 'no_aplica'
    CHECK (tipo_iva IN ('gravado_15', 'gravado_0', 'no_objeto', 'exento', 'no_aplica')),
ADD COLUMN IF NOT EXISTS base_imponible DECIMAL(14,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS valor_iva DECIMAL(14,2) DEFAULT 0,
ADD COLUMN IF NOT EXISTS genera_credito_tributario BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS porcentaje_credito DECIMAL(5,2) DEFAULT 100.00,
ADD COLUMN IF NOT EXISTS factura_recibida_id UUID REFERENCES facturas_recibidas(id);

-- Indice para transacciones con credito tributario
CREATE INDEX IF NOT EXISTS idx_transacciones_credito_tributario
    ON transacciones_bancarias(genera_credito_tributario)
    WHERE genera_credito_tributario = true;

-- Indice para relacion con facturas
CREATE INDEX IF NOT EXISTS idx_transacciones_factura
    ON transacciones_bancarias(factura_recibida_id);

COMMENT ON COLUMN transacciones_bancarias.tipo_iva IS 'Clasificacion IVA: gravado_15, gravado_0, no_objeto, exento, no_aplica';
COMMENT ON COLUMN transacciones_bancarias.base_imponible IS 'Base imponible para calculo de IVA';
COMMENT ON COLUMN transacciones_bancarias.valor_iva IS 'Valor del IVA calculado o registrado';
COMMENT ON COLUMN transacciones_bancarias.genera_credito_tributario IS 'Si el IVA de esta transaccion genera credito tributario';
COMMENT ON COLUMN transacciones_bancarias.factura_recibida_id IS 'Referencia a factura recibida asociada (si aplica)';

-- =====================================================
-- ACTUALIZAR REGLAS DE CATEGORIZACION CON INFO DE IVA
-- =====================================================

-- Agregar campos de IVA a reglas de categorizacion
ALTER TABLE reglas_categorizacion
ADD COLUMN IF NOT EXISTS tipo_iva_default VARCHAR(20) DEFAULT 'no_aplica'
    CHECK (tipo_iva_default IN ('gravado_15', 'gravado_0', 'no_objeto', 'exento', 'no_aplica')),
ADD COLUMN IF NOT EXISTS genera_credito_default BOOLEAN DEFAULT false;

-- Actualizar reglas existentes con clasificacion IVA
UPDATE reglas_categorizacion SET tipo_iva_default = 'gravado_15', genera_credito_default = true
WHERE categoria IN ('gasto_combustible', 'gasto_mantenimiento', 'gasto_seguro', 'gasto_servicios');

UPDATE reglas_categorizacion SET tipo_iva_default = 'no_objeto', genera_credito_default = false
WHERE categoria IN ('gasto_bancario', 'impuesto_isd', 'impuesto_gmt');

UPDATE reglas_categorizacion SET tipo_iva_default = 'exento', genera_credito_default = false
WHERE categoria IN ('pago_impuesto_sri', 'pago_iess');

-- =====================================================
-- NUEVAS REGLAS PARA GASTOS BANCARIOS COMUNES
-- =====================================================

INSERT INTO reglas_categorizacion (nombre, patron_descripcion, tipo_transaccion, categoria, cuenta_contable, tipo_iva_default, genera_credito_default, confianza, prioridad)
VALUES
    -- Gastos bancarios (No objeto IVA)
    ('Comision transferencia', 'comision.*transfer|costo.*envio|cargo.*transfer', 'debito', 'gasto_bancario_transfer', '5.3.02', 'no_objeto', false, 0.95, 5),
    ('Mantenimiento cuenta', 'mantenimiento.*cuenta|costo.*mensual|cargo.*mensual', 'debito', 'gasto_bancario_mant', '5.3.02', 'no_objeto', false, 0.95, 5),
    ('Chequera', 'chequera|libreta.*cheque', 'debito', 'gasto_bancario_chequera', '5.3.02', 'no_objeto', false, 0.90, 10),
    ('Certificacion', 'certificacion|certificado.*bancario', 'debito', 'gasto_bancario_cert', '5.3.02', 'no_objeto', false, 0.90, 10),
    ('Banca electronica', 'banca.*electronica|token|clave.*dinamica', 'debito', 'gasto_bancario_digital', '5.3.02', 'no_objeto', false, 0.90, 10),

    -- Gastos con IVA (servicios profesionales, etc.)
    ('Servicios profesionales', 'honorario|asesoria|consultoria|profesional', 'debito', 'gasto_honorarios', '5.2.02', 'gravado_15', true, 0.85, 30),
    ('Arriendo', 'arriendo|alquiler|canon', 'debito', 'gasto_arriendo', '5.2.01', 'gravado_15', true, 0.90, 20),
    ('Publicidad', 'publicidad|marketing|propaganda|anuncio', 'debito', 'gasto_publicidad', '5.2.08', 'gravado_15', true, 0.85, 30),

    -- Compras de bienes
    ('Suministros oficina', 'papeleria|suministro|oficina|utiles', 'debito', 'gasto_suministros', '5.2.04', 'gravado_15', true, 0.85, 30),
    ('Tecnologia', 'computador|laptop|impresora|software|licencia', 'debito', 'gasto_tecnologia', '1.2.03', 'gravado_15', true, 0.80, 40)
ON CONFLICT DO NOTHING;

-- =====================================================
-- VISTA: RESUMEN IVA POR PERIODO
-- =====================================================

CREATE OR REPLACE VIEW v_resumen_iva_transacciones AS
SELECT
    DATE_TRUNC('month', fecha) AS periodo,
    tipo_iva,
    COUNT(*) AS cantidad,
    SUM(base_imponible) AS total_base,
    SUM(valor_iva) AS total_iva,
    SUM(CASE WHEN genera_credito_tributario THEN valor_iva * porcentaje_credito / 100 ELSE 0 END) AS credito_tributario
FROM transacciones_bancarias
WHERE estado NOT IN ('duplicada', 'descartada', 'error')
    AND tipo_iva != 'no_aplica'
GROUP BY DATE_TRUNC('month', fecha), tipo_iva
ORDER BY periodo DESC, tipo_iva;

COMMENT ON VIEW v_resumen_iva_transacciones IS 'Resumen de IVA por tipo y periodo desde transacciones bancarias';

-- =====================================================
-- FUNCION: CLASIFICAR TRANSACCION AUTOMATICAMENTE
-- =====================================================

CREATE OR REPLACE FUNCTION clasificar_transaccion_iva(p_transaccion_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_descripcion TEXT;
    v_tipo VARCHAR(10);
    v_monto DECIMAL(12,2);
    v_regla RECORD;
    v_base DECIMAL(14,2);
    v_iva DECIMAL(14,2);
BEGIN
    -- Obtener datos de la transaccion
    SELECT descripcion_original, tipo, monto
    INTO v_descripcion, v_tipo, v_monto
    FROM transacciones_bancarias
    WHERE id = p_transaccion_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    -- Buscar regla que coincida
    SELECT *
    INTO v_regla
    FROM reglas_categorizacion
    WHERE activa = true
        AND (tipo_transaccion IS NULL OR tipo_transaccion = v_tipo)
        AND (patron_descripcion IS NULL OR LOWER(v_descripcion) ~ patron_descripcion)
        AND (monto_minimo IS NULL OR v_monto >= monto_minimo)
        AND (monto_maximo IS NULL OR v_monto <= monto_maximo)
    ORDER BY prioridad ASC, confianza DESC
    LIMIT 1;

    IF FOUND THEN
        -- Calcular base e IVA segun tipo
        IF v_regla.tipo_iva_default = 'gravado_15' THEN
            v_base := v_monto / 1.15;
            v_iva := v_monto - v_base;
        ELSIF v_regla.tipo_iva_default IN ('gravado_0', 'no_objeto', 'exento') THEN
            v_base := v_monto;
            v_iva := 0;
        ELSE
            v_base := 0;
            v_iva := 0;
        END IF;

        -- Actualizar transaccion
        UPDATE transacciones_bancarias
        SET
            categoria_sugerida = v_regla.categoria,
            cuenta_contable_sugerida = v_regla.cuenta_contable,
            confianza_categoria = v_regla.confianza,
            tipo_iva = v_regla.tipo_iva_default,
            base_imponible = v_base,
            valor_iva = v_iva,
            genera_credito_tributario = v_regla.genera_credito_default
        WHERE id = p_transaccion_id;
    END IF;
END;
$$;

COMMENT ON FUNCTION clasificar_transaccion_iva IS 'Clasifica automaticamente una transaccion incluyendo tipo de IVA';

-- =====================================================
-- TRIGGER: CLASIFICAR NUEVAS TRANSACCIONES
-- =====================================================

CREATE OR REPLACE FUNCTION trigger_clasificar_nueva_transaccion()
RETURNS TRIGGER AS $$
BEGIN
    -- Solo clasificar debitos (gastos)
    IF NEW.tipo = 'debito' AND NEW.categoria_sugerida IS NULL THEN
        PERFORM clasificar_transaccion_iva(NEW.id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_clasificar_transaccion ON transacciones_bancarias;
CREATE TRIGGER trigger_clasificar_transaccion
    AFTER INSERT ON transacciones_bancarias
    FOR EACH ROW
    EXECUTE FUNCTION trigger_clasificar_nueva_transaccion();

-- =====================================================
-- FIN MIGRACION 009
-- =====================================================
