-- =====================================================
-- MIGRACION 011: CALCULO AUTOMATICO DE CREDITO TRIBUTARIO
-- Sistema Contable Ecucondor
-- =====================================================

-- =====================================================
-- TABLA: resumen_iva_mensual
-- Almacena el resumen de IVA por mes para declaración
-- =====================================================

CREATE TABLE IF NOT EXISTS resumen_iva_mensual (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Periodo
    anio INTEGER NOT NULL,
    mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),

    -- === VENTAS (IVA en Ventas) ===
    -- Base imponible de ventas gravadas
    ventas_gravadas_15 DECIMAL(14,2) DEFAULT 0,
    ventas_gravadas_0 DECIMAL(14,2) DEFAULT 0,
    ventas_no_objeto DECIMAL(14,2) DEFAULT 0,
    ventas_exentas DECIMAL(14,2) DEFAULT 0,

    -- IVA generado en ventas
    iva_ventas_15 DECIMAL(14,2) DEFAULT 0,

    -- === COMPRAS (IVA en Compras) ===
    -- Base imponible de compras
    compras_gravadas_15 DECIMAL(14,2) DEFAULT 0,
    compras_gravadas_0 DECIMAL(14,2) DEFAULT 0,
    compras_no_objeto DECIMAL(14,2) DEFAULT 0,
    compras_exentas DECIMAL(14,2) DEFAULT 0,

    -- IVA en compras
    iva_compras_15 DECIMAL(14,2) DEFAULT 0,

    -- === CREDITO TRIBUTARIO ===
    -- Factor de proporcionalidad (ventas gravadas / total ventas)
    factor_proporcionalidad DECIMAL(8,6) DEFAULT 1.0,

    -- Crédito tributario del mes
    credito_tributario_mes DECIMAL(14,2) DEFAULT 0,

    -- Crédito tributario arrastrado del mes anterior
    credito_tributario_anterior DECIMAL(14,2) DEFAULT 0,

    -- Crédito tributario total disponible
    credito_tributario_total DECIMAL(14,2) DEFAULT 0,

    -- === RESULTADO ===
    -- IVA a pagar (positivo) o crédito a favor (negativo)
    iva_a_pagar DECIMAL(14,2) DEFAULT 0,

    -- Crédito tributario a siguiente mes
    credito_siguiente_mes DECIMAL(14,2) DEFAULT 0,

    -- === RETENCIONES ===
    -- Retenciones de IVA efectuadas (a favor SRI)
    retenciones_iva_efectuadas DECIMAL(14,2) DEFAULT 0,

    -- Retenciones de IVA que le efectuaron (a favor contribuyente)
    retenciones_iva_recibidas DECIMAL(14,2) DEFAULT 0,

    -- === METADATA ===
    estado VARCHAR(20) DEFAULT 'borrador'
        CHECK (estado IN ('borrador', 'calculado', 'declarado')),
    fecha_calculo TIMESTAMPTZ,
    fecha_declaracion TIMESTAMPTZ,
    numero_formulario VARCHAR(50),

    -- Auditoria
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(anio, mes)
);

CREATE INDEX IF NOT EXISTS idx_resumen_iva_periodo ON resumen_iva_mensual(anio, mes);
CREATE INDEX IF NOT EXISTS idx_resumen_iva_estado ON resumen_iva_mensual(estado);

COMMENT ON TABLE resumen_iva_mensual IS 'Resumen mensual de IVA para declaración formulario 104';

-- =====================================================
-- TABLA: detalle_credito_tributario
-- Detalle de cada transacción que genera crédito
-- =====================================================

CREATE TABLE IF NOT EXISTS detalle_credito_tributario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Periodo
    anio INTEGER NOT NULL,
    mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),

    -- Origen del crédito
    origen_tipo VARCHAR(30) NOT NULL
        CHECK (origen_tipo IN ('factura_recibida', 'transaccion_bancaria', 'nota_credito', 'ajuste')),
    origen_id UUID NOT NULL,

    -- Datos del documento
    fecha DATE NOT NULL,
    proveedor_identificacion VARCHAR(20),
    proveedor_nombre VARCHAR(300),
    numero_documento VARCHAR(50),

    -- Montos
    base_imponible DECIMAL(14,2) NOT NULL,
    porcentaje_iva DECIMAL(5,2) DEFAULT 15.00,
    valor_iva DECIMAL(14,2) NOT NULL,

    -- Porcentaje de crédito aplicable (100% para gastos deducibles)
    porcentaje_credito DECIMAL(5,2) DEFAULT 100.00,
    credito_tributario DECIMAL(14,2) NOT NULL,

    -- Retención IVA (si aplica)
    retencion_iva DECIMAL(14,2) DEFAULT 0,

    -- Estado
    incluido_declaracion BOOLEAN DEFAULT false,

    -- Auditoria
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(origen_tipo, origen_id)
);

CREATE INDEX IF NOT EXISTS idx_detalle_ct_periodo ON detalle_credito_tributario(anio, mes);
CREATE INDEX IF NOT EXISTS idx_detalle_ct_origen ON detalle_credito_tributario(origen_tipo, origen_id);

COMMENT ON TABLE detalle_credito_tributario IS 'Detalle de documentos que generan crédito tributario';

-- =====================================================
-- FUNCION: calcular_credito_facturas_recibidas
-- Calcula el crédito tributario desde facturas recibidas
-- =====================================================

CREATE OR REPLACE FUNCTION calcular_credito_facturas_recibidas(
    p_anio INTEGER,
    p_mes INTEGER
)
RETURNS TABLE(
    facturas_procesadas INTEGER,
    total_base_15 DECIMAL(14,2),
    total_iva_15 DECIMAL(14,2),
    total_credito DECIMAL(14,2)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_fecha_inicio DATE;
    v_fecha_fin DATE;
    v_factura RECORD;
    v_count INTEGER := 0;
    v_total_base DECIMAL(14,2) := 0;
    v_total_iva DECIMAL(14,2) := 0;
    v_total_credito DECIMAL(14,2) := 0;
BEGIN
    v_fecha_inicio := MAKE_DATE(p_anio, p_mes, 1);
    v_fecha_fin := (v_fecha_inicio + INTERVAL '1 month' - INTERVAL '1 day')::DATE;

    -- Procesar cada factura del período
    FOR v_factura IN
        SELECT
            fr.id,
            fr.fecha_emision,
            fr.proveedor_identificacion,
            fr.proveedor_razon_social,
            fr.numero_autorizacion,
            fr.subtotal_15,
            fr.iva_15,
            COALESCE(fr.retencion_iva, 0) AS retencion_iva
        FROM facturas_recibidas fr
        WHERE fr.fecha_emision BETWEEN v_fecha_inicio AND v_fecha_fin
          AND fr.estado NOT IN ('anulada', 'rechazada')
          AND fr.subtotal_15 > 0
          AND NOT EXISTS (
              SELECT 1 FROM detalle_credito_tributario dct
              WHERE dct.origen_tipo = 'factura_recibida'
                AND dct.origen_id = fr.id
          )
    LOOP
        -- Calcular crédito (100% para gastos deducibles)
        INSERT INTO detalle_credito_tributario (
            anio, mes, origen_tipo, origen_id,
            fecha, proveedor_identificacion, proveedor_nombre, numero_documento,
            base_imponible, porcentaje_iva, valor_iva,
            porcentaje_credito, credito_tributario, retencion_iva
        )
        VALUES (
            p_anio, p_mes, 'factura_recibida', v_factura.id,
            v_factura.fecha_emision,
            v_factura.proveedor_identificacion,
            v_factura.proveedor_razon_social,
            v_factura.numero_autorizacion,
            v_factura.subtotal_15,
            15.00,
            v_factura.iva_15,
            100.00,
            v_factura.iva_15,  -- 100% crédito
            v_factura.retencion_iva
        );

        v_count := v_count + 1;
        v_total_base := v_total_base + v_factura.subtotal_15;
        v_total_iva := v_total_iva + v_factura.iva_15;
        v_total_credito := v_total_credito + v_factura.iva_15;
    END LOOP;

    facturas_procesadas := v_count;
    total_base_15 := v_total_base;
    total_iva_15 := v_total_iva;
    total_credito := v_total_credito;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION calcular_credito_facturas_recibidas IS 'Calcula el crédito tributario desde facturas recibidas del período';

-- =====================================================
-- FUNCION: calcular_credito_transacciones
-- Calcula el crédito tributario desde transacciones bancarias
-- =====================================================

CREATE OR REPLACE FUNCTION calcular_credito_transacciones(
    p_anio INTEGER,
    p_mes INTEGER
)
RETURNS TABLE(
    transacciones_procesadas INTEGER,
    total_base_15 DECIMAL(14,2),
    total_iva_15 DECIMAL(14,2),
    total_credito DECIMAL(14,2)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_fecha_inicio DATE;
    v_fecha_fin DATE;
    v_trans RECORD;
    v_count INTEGER := 0;
    v_total_base DECIMAL(14,2) := 0;
    v_total_iva DECIMAL(14,2) := 0;
    v_total_credito DECIMAL(14,2) := 0;
    v_credito DECIMAL(14,2);
BEGIN
    v_fecha_inicio := MAKE_DATE(p_anio, p_mes, 1);
    v_fecha_fin := (v_fecha_inicio + INTERVAL '1 month' - INTERVAL '1 day')::DATE;

    -- Procesar transacciones con IVA gravado y crédito
    FOR v_trans IN
        SELECT
            t.id,
            t.fecha,
            t.descripcion_original,
            t.base_imponible,
            t.valor_iva,
            t.porcentaje_credito
        FROM transacciones_bancarias t
        WHERE t.fecha BETWEEN v_fecha_inicio AND v_fecha_fin
          AND t.tipo = 'debito'
          AND t.tipo_iva = 'gravado_15'
          AND t.genera_credito_tributario = true
          AND t.valor_iva > 0
          AND t.estado NOT IN ('duplicada', 'descartada', 'error')
          AND NOT EXISTS (
              SELECT 1 FROM detalle_credito_tributario dct
              WHERE dct.origen_tipo = 'transaccion_bancaria'
                AND dct.origen_id = t.id
          )
    LOOP
        -- Calcular crédito según porcentaje
        v_credito := v_trans.valor_iva * v_trans.porcentaje_credito / 100;

        INSERT INTO detalle_credito_tributario (
            anio, mes, origen_tipo, origen_id,
            fecha, proveedor_identificacion, proveedor_nombre, numero_documento,
            base_imponible, porcentaje_iva, valor_iva,
            porcentaje_credito, credito_tributario
        )
        VALUES (
            p_anio, p_mes, 'transaccion_bancaria', v_trans.id,
            v_trans.fecha,
            NULL,  -- Sin identificación del proveedor
            LEFT(v_trans.descripcion_original, 300),
            NULL,  -- Sin número de documento
            v_trans.base_imponible,
            15.00,
            v_trans.valor_iva,
            v_trans.porcentaje_credito,
            v_credito
        );

        v_count := v_count + 1;
        v_total_base := v_total_base + v_trans.base_imponible;
        v_total_iva := v_total_iva + v_trans.valor_iva;
        v_total_credito := v_total_credito + v_credito;
    END LOOP;

    transacciones_procesadas := v_count;
    total_base_15 := v_total_base;
    total_iva_15 := v_total_iva;
    total_credito := v_total_credito;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION calcular_credito_transacciones IS 'Calcula el crédito tributario desde transacciones bancarias clasificadas';

-- =====================================================
-- FUNCION: generar_resumen_iva_mensual
-- Genera o actualiza el resumen de IVA del mes
-- =====================================================

CREATE OR REPLACE FUNCTION generar_resumen_iva_mensual(
    p_anio INTEGER,
    p_mes INTEGER
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_resumen_id UUID;
    v_fecha_inicio DATE;
    v_fecha_fin DATE;
    v_credito_anterior DECIMAL(14,2) := 0;
    v_result_facturas RECORD;
    v_result_trans RECORD;
    v_total_compras_15 DECIMAL(14,2);
    v_total_iva_compras DECIMAL(14,2);
    v_total_credito DECIMAL(14,2);
    v_iva_ventas DECIMAL(14,2) := 0;
    v_iva_a_pagar DECIMAL(14,2);
    v_credito_siguiente DECIMAL(14,2);
BEGIN
    v_fecha_inicio := MAKE_DATE(p_anio, p_mes, 1);
    v_fecha_fin := (v_fecha_inicio + INTERVAL '1 month' - INTERVAL '1 day')::DATE;

    -- Obtener crédito tributario del mes anterior
    SELECT COALESCE(credito_siguiente_mes, 0)
    INTO v_credito_anterior
    FROM resumen_iva_mensual
    WHERE (anio = p_anio AND mes = p_mes - 1)
       OR (anio = p_anio - 1 AND mes = 12 AND p_mes = 1)
    ORDER BY anio DESC, mes DESC
    LIMIT 1;

    -- Calcular créditos de facturas recibidas
    SELECT * INTO v_result_facturas
    FROM calcular_credito_facturas_recibidas(p_anio, p_mes);

    -- Calcular créditos de transacciones bancarias
    SELECT * INTO v_result_trans
    FROM calcular_credito_transacciones(p_anio, p_mes);

    -- Totales de compras
    v_total_compras_15 := COALESCE(v_result_facturas.total_base_15, 0) +
                          COALESCE(v_result_trans.total_base_15, 0);
    v_total_iva_compras := COALESCE(v_result_facturas.total_iva_15, 0) +
                           COALESCE(v_result_trans.total_iva_15, 0);
    v_total_credito := COALESCE(v_result_facturas.total_credito, 0) +
                       COALESCE(v_result_trans.total_credito, 0);

    -- Calcular IVA en ventas del período (desde comprobantes emitidos)
    SELECT COALESCE(SUM(iva), 0)
    INTO v_iva_ventas
    FROM comprobantes_electronicos
    WHERE fecha_emision BETWEEN v_fecha_inicio AND v_fecha_fin
      AND estado IN ('autorizado', 'enviado')
      AND tipo_documento = '01';  -- Facturas

    -- Calcular IVA a pagar
    v_iva_a_pagar := v_iva_ventas - (v_total_credito + v_credito_anterior);

    -- Determinar crédito para siguiente mes
    IF v_iva_a_pagar < 0 THEN
        v_credito_siguiente := ABS(v_iva_a_pagar);
        v_iva_a_pagar := 0;
    ELSE
        v_credito_siguiente := 0;
    END IF;

    -- Insertar o actualizar resumen
    INSERT INTO resumen_iva_mensual (
        anio, mes,
        compras_gravadas_15, iva_compras_15,
        credito_tributario_mes, credito_tributario_anterior,
        credito_tributario_total,
        iva_ventas_15, iva_a_pagar, credito_siguiente_mes,
        estado, fecha_calculo
    )
    VALUES (
        p_anio, p_mes,
        v_total_compras_15, v_total_iva_compras,
        v_total_credito, v_credito_anterior,
        v_total_credito + v_credito_anterior,
        v_iva_ventas, v_iva_a_pagar, v_credito_siguiente,
        'calculado', NOW()
    )
    ON CONFLICT (anio, mes) DO UPDATE SET
        compras_gravadas_15 = EXCLUDED.compras_gravadas_15,
        iva_compras_15 = EXCLUDED.iva_compras_15,
        credito_tributario_mes = EXCLUDED.credito_tributario_mes,
        credito_tributario_anterior = EXCLUDED.credito_tributario_anterior,
        credito_tributario_total = EXCLUDED.credito_tributario_total,
        iva_ventas_15 = EXCLUDED.iva_ventas_15,
        iva_a_pagar = EXCLUDED.iva_a_pagar,
        credito_siguiente_mes = EXCLUDED.credito_siguiente_mes,
        estado = 'calculado',
        fecha_calculo = NOW(),
        updated_at = NOW()
    RETURNING id INTO v_resumen_id;

    RETURN v_resumen_id;
END;
$$;

COMMENT ON FUNCTION generar_resumen_iva_mensual IS 'Genera el resumen mensual de IVA para declaración';

-- =====================================================
-- VISTA: v_credito_tributario_detalle
-- Detalle de crédito tributario por período
-- =====================================================

CREATE OR REPLACE VIEW v_credito_tributario_detalle AS
SELECT
    dct.anio,
    dct.mes,
    dct.origen_tipo,
    dct.fecha,
    dct.proveedor_identificacion,
    dct.proveedor_nombre,
    dct.numero_documento,
    dct.base_imponible,
    dct.valor_iva,
    dct.porcentaje_credito,
    dct.credito_tributario,
    dct.retencion_iva,
    dct.incluido_declaracion
FROM detalle_credito_tributario dct
ORDER BY dct.anio DESC, dct.mes DESC, dct.fecha;

COMMENT ON VIEW v_credito_tributario_detalle IS 'Vista de detalle de crédito tributario';

-- =====================================================
-- VISTA: v_resumen_iva_declaracion
-- Resumen para formulario 104 del SRI
-- =====================================================

CREATE OR REPLACE VIEW v_resumen_iva_declaracion AS
SELECT
    r.anio,
    r.mes,
    r.anio::TEXT || '-' || LPAD(r.mes::TEXT, 2, '0') AS periodo,

    -- Ventas
    r.ventas_gravadas_15,
    r.ventas_gravadas_0,
    r.ventas_no_objeto,
    r.ventas_exentas,
    r.ventas_gravadas_15 + r.ventas_gravadas_0 + r.ventas_no_objeto + r.ventas_exentas AS total_ventas,
    r.iva_ventas_15 AS iva_causado,

    -- Compras
    r.compras_gravadas_15,
    r.compras_gravadas_0,
    r.compras_no_objeto,
    r.compras_exentas,
    r.compras_gravadas_15 + r.compras_gravadas_0 + r.compras_no_objeto + r.compras_exentas AS total_compras,
    r.iva_compras_15,

    -- Crédito tributario
    r.credito_tributario_anterior AS credito_mes_anterior,
    r.credito_tributario_mes AS credito_este_mes,
    r.credito_tributario_total AS credito_total,

    -- Retenciones
    r.retenciones_iva_efectuadas,
    r.retenciones_iva_recibidas,

    -- Resultado
    r.iva_a_pagar,
    r.credito_siguiente_mes,

    -- Estado
    r.estado,
    r.fecha_calculo,
    r.fecha_declaracion,
    r.numero_formulario

FROM resumen_iva_mensual r
ORDER BY r.anio DESC, r.mes DESC;

COMMENT ON VIEW v_resumen_iva_declaracion IS 'Vista resumen para declaración de IVA (formulario 104)';

-- =====================================================
-- VISTA: v_credito_tributario_acumulado
-- Evolución del crédito tributario
-- =====================================================

CREATE OR REPLACE VIEW v_credito_tributario_acumulado AS
SELECT
    r.anio,
    r.mes,
    r.anio::TEXT || '-' || LPAD(r.mes::TEXT, 2, '0') AS periodo,
    r.iva_ventas_15 AS iva_ventas,
    r.credito_tributario_mes AS credito_mes,
    r.credito_tributario_anterior AS credito_anterior,
    r.iva_a_pagar,
    r.credito_siguiente_mes AS credito_acumulado,
    r.estado
FROM resumen_iva_mensual r
ORDER BY r.anio, r.mes;

COMMENT ON VIEW v_credito_tributario_acumulado IS 'Evolución mensual del crédito tributario';

-- =====================================================
-- FIN MIGRACION 011
-- =====================================================
