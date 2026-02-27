-- =====================================================
-- ECUCONDOR - Migración 007: UAFE Compliance
-- Sistema de cumplimiento anti-lavado (RESU/ROII)
-- =====================================================

-- =====================================================
-- TABLA: uafe_monitoreo_resu
-- Monitoreo de umbrales RESU ($10,000 USD mensuales)
-- =====================================================

CREATE TABLE IF NOT EXISTS uafe_monitoreo_resu (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Período
    anio INTEGER NOT NULL,
    mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    periodo VARCHAR(20) NOT NULL,  -- "2025-01"

    -- Cliente monitoreado
    cliente_tipo_id VARCHAR(2),
    cliente_identificacion VARCHAR(13) NOT NULL,
    cliente_razon_social VARCHAR(300) NOT NULL,

    -- Acumulado del mes
    total_transacciones INTEGER NOT NULL DEFAULT 0,
    monto_total_creditos DECIMAL(14, 2) NOT NULL DEFAULT 0,
    monto_total_debitos DECIMAL(14, 2) NOT NULL DEFAULT 0,
    monto_total_efectivo DECIMAL(14, 2) NOT NULL DEFAULT 0,  -- Suma de efectivo

    -- Umbral
    umbral_resu DECIMAL(14, 2) NOT NULL DEFAULT 10000.00,
    supera_umbral BOOLEAN NOT NULL DEFAULT false,

    -- Reporte
    reporte_generado BOOLEAN NOT NULL DEFAULT false,
    reporte_id UUID,
    fecha_reporte TIMESTAMPTZ,

    -- Metadatos
    transacciones_ids TEXT[],  -- Array de UUIDs de transacciones
    notas TEXT,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(periodo, cliente_identificacion)
);

CREATE INDEX idx_uafe_resu_periodo ON uafe_monitoreo_resu(periodo);
CREATE INDEX idx_uafe_resu_cliente ON uafe_monitoreo_resu(cliente_identificacion);
CREATE INDEX idx_uafe_resu_umbral ON uafe_monitoreo_resu(supera_umbral) WHERE supera_umbral = true;
CREATE INDEX idx_uafe_resu_reporte ON uafe_monitoreo_resu(reporte_generado) WHERE reporte_generado = false;

COMMENT ON TABLE uafe_monitoreo_resu IS 'Monitoreo mensual de umbrales RESU ($10,000)';
COMMENT ON COLUMN uafe_monitoreo_resu.umbral_resu IS 'Umbral RESU en USD (default: $10,000)';

-- =====================================================
-- TABLA: uafe_detecciones_roii
-- Detección de operaciones inusuales/sospechosas (ROII)
-- =====================================================

CREATE TABLE IF NOT EXISTS uafe_detecciones_roii (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Transacción o cliente relacionado
    transaccion_id UUID REFERENCES transacciones_bancarias(id),
    comprobante_id UUID REFERENCES comprobantes_electronicos(id),

    cliente_tipo_id VARCHAR(2),
    cliente_identificacion VARCHAR(13),
    cliente_razon_social VARCHAR(300),

    -- Tipo de detección
    tipo_deteccion VARCHAR(50) NOT NULL,  -- 'monto_inusual', 'frecuencia_alta', 'patron_fraccionamiento', etc.
    categoria VARCHAR(30) NOT NULL,  -- 'inusual', 'sospechoso', 'alto_riesgo'
    severidad INTEGER NOT NULL DEFAULT 1 CHECK (severidad BETWEEN 1 AND 5),

    -- Detalles
    descripcion TEXT NOT NULL,
    monto_involucrado DECIMAL(14, 2),
    fecha_deteccion DATE NOT NULL,

    -- Indicadores
    indicadores JSONB,  -- Indicadores específicos de la detección
    puntaje_riesgo DECIMAL(5, 2) CHECK (puntaje_riesgo BETWEEN 0 AND 100),

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'en_revision', 'reportado', 'descartado', 'falso_positivo')),

    -- Reporte
    debe_reportarse BOOLEAN NOT NULL DEFAULT false,
    reporte_generado BOOLEAN NOT NULL DEFAULT false,
    reporte_id UUID,
    fecha_reporte TIMESTAMPTZ,

    -- Auditoría
    revisado_por UUID,
    revisado_at TIMESTAMPTZ,
    notas_revision TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uafe_roii_transaccion ON uafe_detecciones_roii(transaccion_id);
CREATE INDEX idx_uafe_roii_comprobante ON uafe_detecciones_roii(comprobante_id);
CREATE INDEX idx_uafe_roii_cliente ON uafe_detecciones_roii(cliente_identificacion);
CREATE INDEX idx_uafe_roii_tipo ON uafe_detecciones_roii(tipo_deteccion);
CREATE INDEX idx_uafe_roii_estado ON uafe_detecciones_roii(estado);
CREATE INDEX idx_uafe_roii_severidad ON uafe_detecciones_roii(severidad) WHERE severidad >= 3;
CREATE INDEX idx_uafe_roii_pendientes ON uafe_detecciones_roii(estado) WHERE estado = 'pendiente';

COMMENT ON TABLE uafe_detecciones_roii IS 'Detecciones de operaciones inusuales o sospechosas (ROII)';

-- =====================================================
-- TABLA: uafe_reportes
-- Reportes generados para UAFE
-- =====================================================

CREATE TABLE IF NOT EXISTS uafe_reportes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Tipo de reporte
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('RESU', 'ROII')),
    numero_reporte VARCHAR(50),  -- Número correlativo

    -- Período
    anio INTEGER NOT NULL,
    mes INTEGER,
    periodo VARCHAR(20),
    fecha_reporte DATE NOT NULL,

    -- Contenido
    xml_reporte TEXT,  -- XML generado para UAFE
    json_datos JSONB,  -- Datos estructurados

    -- Estadísticas
    total_clientes INTEGER,
    total_transacciones INTEGER,
    monto_total DECIMAL(14, 2),

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'borrador'
        CHECK (estado IN ('borrador', 'generado', 'enviado', 'aceptado', 'rechazado')),

    fecha_generacion TIMESTAMPTZ,
    fecha_envio TIMESTAMPTZ,
    fecha_respuesta TIMESTAMPTZ,

    -- Respuesta UAFE
    respuesta_uafe TEXT,
    codigo_aceptacion VARCHAR(50),

    -- Metadatos
    generado_por UUID,
    enviado_por UUID,
    notas TEXT,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uafe_reportes_tipo ON uafe_reportes(tipo);
CREATE INDEX idx_uafe_reportes_periodo ON uafe_reportes(periodo);
CREATE INDEX idx_uafe_reportes_fecha ON uafe_reportes(fecha_reporte);
CREATE INDEX idx_uafe_reportes_estado ON uafe_reportes(estado);

COMMENT ON TABLE uafe_reportes IS 'Reportes generados para la UAFE (RESU/ROII)';

-- =====================================================
-- TABLA: uafe_parametros
-- Parámetros de configuración UAFE
-- =====================================================

CREATE TABLE IF NOT EXISTS uafe_parametros (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Umbrales RESU
    umbral_resu_usd DECIMAL(14, 2) NOT NULL DEFAULT 10000.00,
    umbral_efectivo_usd DECIMAL(14, 2) NOT NULL DEFAULT 10000.00,

    -- Parámetros ROII
    umbral_monto_inusual DECIMAL(14, 2) NOT NULL DEFAULT 50000.00,
    umbral_frecuencia_diaria INTEGER NOT NULL DEFAULT 5,
    puntaje_riesgo_minimo DECIMAL(5, 2) NOT NULL DEFAULT 70.00,

    -- Vigencia
    vigencia_desde DATE NOT NULL,
    vigencia_hasta DATE,
    activo BOOLEAN NOT NULL DEFAULT true,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uafe_parametros_vigencia ON uafe_parametros(vigencia_desde, vigencia_hasta);

COMMENT ON TABLE uafe_parametros IS 'Parámetros y umbrales para cumplimiento UAFE';

-- =====================================================
-- VISTA: v_uafe_resu_pendientes
-- Clientes que superaron umbral RESU sin reportar
-- =====================================================

CREATE OR REPLACE VIEW v_uafe_resu_pendientes AS
SELECT
    m.id,
    m.periodo,
    m.anio,
    m.mes,
    m.cliente_identificacion,
    m.cliente_razon_social,
    m.monto_total_efectivo AS monto,
    m.total_transacciones,
    m.umbral_resu,
    (m.monto_total_efectivo - m.umbral_resu) AS exceso,
    m.created_at
FROM uafe_monitoreo_resu m
WHERE m.supera_umbral = true
  AND m.reporte_generado = false
ORDER BY m.periodo DESC, m.monto_total_efectivo DESC;

COMMENT ON VIEW v_uafe_resu_pendientes IS 'Clientes RESU pendientes de reporte';

-- =====================================================
-- VISTA: v_uafe_roii_alto_riesgo
-- Detecciones ROII de alto riesgo
-- =====================================================

CREATE OR REPLACE VIEW v_uafe_roii_alto_riesgo AS
SELECT
    r.id,
    r.fecha_deteccion,
    r.tipo_deteccion,
    r.categoria,
    r.severidad,
    r.cliente_identificacion,
    r.cliente_razon_social,
    r.monto_involucrado,
    r.puntaje_riesgo,
    r.descripcion,
    r.estado,
    r.debe_reportarse
FROM uafe_detecciones_roii r
WHERE r.severidad >= 3
  AND r.estado IN ('pendiente', 'en_revision')
ORDER BY r.severidad DESC, r.puntaje_riesgo DESC, r.fecha_deteccion DESC;

COMMENT ON VIEW v_uafe_roii_alto_riesgo IS 'Detecciones ROII de alto riesgo pendientes';

-- =====================================================
-- FUNCIÓN: actualizar_monitoreo_resu
-- Actualiza el monitoreo RESU para un cliente/período
-- =====================================================

CREATE OR REPLACE FUNCTION actualizar_monitoreo_resu(
    p_periodo VARCHAR(20),
    p_cliente_identificacion VARCHAR(13)
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_monitoreo_id UUID;
    v_anio INTEGER;
    v_mes INTEGER;
    v_umbral DECIMAL(14, 2);
    v_total_creditos DECIMAL(14, 2);
    v_total_debitos DECIMAL(14, 2);
    v_total_transacciones INTEGER;
BEGIN
    -- Extraer año y mes
    v_anio := SPLIT_PART(p_periodo, '-', 1)::INTEGER;
    v_mes := SPLIT_PART(p_periodo, '-', 2)::INTEGER;

    -- Obtener umbral vigente
    SELECT umbral_resu_usd INTO v_umbral
    FROM uafe_parametros
    WHERE activo = true
    ORDER BY vigencia_desde DESC
    LIMIT 1;

    IF v_umbral IS NULL THEN
        v_umbral := 10000.00;
    END IF;

    -- Calcular totales del período
    SELECT
        COUNT(*),
        COALESCE(SUM(CASE WHEN tipo = 'credito' THEN monto ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN tipo = 'debito' THEN monto ELSE 0 END), 0)
    INTO v_total_transacciones, v_total_creditos, v_total_debitos
    FROM transacciones_bancarias
    WHERE contraparte_identificacion = p_cliente_identificacion
      AND TO_CHAR(fecha, 'YYYY-MM') = p_periodo
      AND estado NOT IN ('duplicada', 'descartada');

    -- Insertar o actualizar monitoreo
    INSERT INTO uafe_monitoreo_resu (
        anio, mes, periodo,
        cliente_identificacion,
        total_transacciones,
        monto_total_creditos,
        monto_total_debitos,
        monto_total_efectivo,
        umbral_resu,
        supera_umbral
    )
    VALUES (
        v_anio, v_mes, p_periodo,
        p_cliente_identificacion,
        v_total_transacciones,
        v_total_creditos,
        v_total_debitos,
        v_total_creditos + v_total_debitos,
        v_umbral,
        (v_total_creditos + v_total_debitos) >= v_umbral
    )
    ON CONFLICT (periodo, cliente_identificacion) DO UPDATE SET
        total_transacciones = EXCLUDED.total_transacciones,
        monto_total_creditos = EXCLUDED.monto_total_creditos,
        monto_total_debitos = EXCLUDED.monto_total_debitos,
        monto_total_efectivo = EXCLUDED.monto_total_efectivo,
        supera_umbral = EXCLUDED.supera_umbral,
        updated_at = NOW()
    RETURNING id INTO v_monitoreo_id;

    RETURN v_monitoreo_id;
END;
$$;

COMMENT ON FUNCTION actualizar_monitoreo_resu IS 'Actualiza monitoreo RESU para un cliente/período';

-- =====================================================
-- TRIGGERS
-- =====================================================

CREATE TRIGGER set_updated_at_uafe_resu
    BEFORE UPDATE ON uafe_monitoreo_resu
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_uafe_roii
    BEFORE UPDATE ON uafe_detecciones_roii
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_uafe_reportes
    BEFORE UPDATE ON uafe_reportes
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_uafe_parametros
    BEFORE UPDATE ON uafe_parametros
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

-- =====================================================
-- RLS: Row Level Security
-- =====================================================

ALTER TABLE uafe_monitoreo_resu ENABLE ROW LEVEL SECURITY;
ALTER TABLE uafe_detecciones_roii ENABLE ROW LEVEL SECURITY;
ALTER TABLE uafe_reportes ENABLE ROW LEVEL SECURITY;
ALTER TABLE uafe_parametros ENABLE ROW LEVEL SECURITY;

-- Políticas permisivas para service role
CREATE POLICY "Service role full access uafe_resu"
    ON uafe_monitoreo_resu FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access uafe_roii"
    ON uafe_detecciones_roii FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access uafe_reportes"
    ON uafe_reportes FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access uafe_parametros"
    ON uafe_parametros FOR ALL USING (true) WITH CHECK (true);

-- =====================================================
-- DATOS INICIALES
-- =====================================================

-- Parámetros UAFE por defecto
INSERT INTO uafe_parametros (
    umbral_resu_usd,
    umbral_efectivo_usd,
    umbral_monto_inusual,
    umbral_frecuencia_diaria,
    puntaje_riesgo_minimo,
    vigencia_desde
)
VALUES (
    10000.00,  -- Umbral RESU
    10000.00,  -- Umbral efectivo
    50000.00,  -- Monto inusual
    5,         -- Frecuencia diaria
    70.00,     -- Puntaje riesgo mínimo
    '2025-01-01'
)
ON CONFLICT DO NOTHING;
