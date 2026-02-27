-- =====================================================
-- ECUCONDOR - Migración 006: Honorarios Administrador
-- Sistema de gestión de honorarios profesionales (IESS código 109)
-- =====================================================

-- =====================================================
-- TABLA: administradores
-- Registro de administradores de la empresa
-- =====================================================

CREATE TABLE IF NOT EXISTS administradores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    tipo_identificacion VARCHAR(2) NOT NULL CHECK (tipo_identificacion IN ('05', '04', '06', '07', '08')),
    identificacion VARCHAR(13) NOT NULL UNIQUE,
    nombres VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    razon_social VARCHAR(300) NOT NULL,  -- Nombre completo

    -- Contacto
    email VARCHAR(100),
    telefono VARCHAR(20),
    direccion TEXT,

    -- IESS
    numero_iess VARCHAR(20),  -- Número de afiliación IESS
    codigo_actividad VARCHAR(10) DEFAULT '109',  -- Código IESS (109 = Honorarios profesionales)

    -- Bancario
    banco VARCHAR(50),
    numero_cuenta VARCHAR(30),
    tipo_cuenta VARCHAR(20) CHECK (tipo_cuenta IN ('corriente', 'ahorros')),

    -- Estado
    activo BOOLEAN NOT NULL DEFAULT true,
    fecha_inicio DATE,
    fecha_fin DATE,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX idx_administradores_identificacion ON administradores(identificacion);
CREATE INDEX idx_administradores_activo ON administradores(activo);

COMMENT ON TABLE administradores IS 'Administradores de la empresa (IESS código 109)';
COMMENT ON COLUMN administradores.codigo_actividad IS 'Código IESS: 109 = Honorarios profesionales sin relación de dependencia';

-- =====================================================
-- TABLA: pagos_honorarios
-- Registro de pagos de honorarios al administrador
-- =====================================================

CREATE TABLE IF NOT EXISTS pagos_honorarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Relaciones
    administrador_id UUID NOT NULL REFERENCES administradores(id),

    -- Período
    anio INTEGER NOT NULL,
    mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    periodo VARCHAR(20) NOT NULL,  -- "2025-01" para indexación

    -- Montos
    honorario_bruto DECIMAL(10, 2) NOT NULL CHECK (honorario_bruto > 0),

    -- IESS (código 109)
    aporte_patronal DECIMAL(10, 2) NOT NULL DEFAULT 0,  -- 12.15%
    aporte_personal DECIMAL(10, 2) NOT NULL DEFAULT 0,  -- 9.45%
    total_iess DECIMAL(10, 2) NOT NULL DEFAULT 0,       -- 21.60%

    -- Retención en la fuente
    base_imponible_renta DECIMAL(10, 2) NOT NULL DEFAULT 0,
    retencion_renta DECIMAL(10, 2) NOT NULL DEFAULT 0,
    porcentaje_retencion DECIMAL(5, 2) NOT NULL DEFAULT 0,

    -- Neto a pagar
    neto_pagar DECIMAL(10, 2) NOT NULL DEFAULT 0,

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'aprobado', 'pagado', 'anulado')),

    -- Pago
    fecha_pago TIMESTAMPTZ,
    referencia_pago VARCHAR(100),
    asiento_id UUID REFERENCES asientos_contables(id),

    -- Comprobantes
    comprobante_retencion_id UUID,  -- Futuro: referencia a retención

    -- Observaciones
    notas TEXT,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    approved_by UUID,

    UNIQUE(administrador_id, periodo)
);

CREATE INDEX idx_pagos_honorarios_administrador ON pagos_honorarios(administrador_id);
CREATE INDEX idx_pagos_honorarios_periodo ON pagos_honorarios(periodo);
CREATE INDEX idx_pagos_honorarios_estado ON pagos_honorarios(estado);
CREATE INDEX idx_pagos_honorarios_fecha ON pagos_honorarios(anio, mes);

COMMENT ON TABLE pagos_honorarios IS 'Registro de pagos de honorarios profesionales (IESS 109)';
COMMENT ON COLUMN pagos_honorarios.aporte_patronal IS 'Aporte patronal IESS 12.15% (a cargo del empleador)';
COMMENT ON COLUMN pagos_honorarios.aporte_personal IS 'Aporte personal IESS 9.45% (se descuenta del honorario)';

-- =====================================================
-- TABLA: parametros_iess
-- Parámetros y porcentajes IESS
-- =====================================================

CREATE TABLE IF NOT EXISTS parametros_iess (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Período de vigencia
    codigo_actividad VARCHAR(10) NOT NULL,
    vigencia_desde DATE NOT NULL,
    vigencia_hasta DATE,

    -- Porcentajes (código 109)
    porcentaje_aporte_patronal DECIMAL(5, 4) NOT NULL DEFAULT 0.1215,  -- 12.15%
    porcentaje_aporte_personal DECIMAL(5, 4) NOT NULL DEFAULT 0.0945,  -- 9.45%

    -- Topes
    salario_basico_unificado DECIMAL(10, 2),  -- SBU Ecuador
    tope_maximo_aportacion DECIMAL(10, 2),     -- Tope máximo si aplica

    -- Estado
    activo BOOLEAN NOT NULL DEFAULT true,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_parametros_iess_codigo ON parametros_iess(codigo_actividad);
CREATE INDEX idx_parametros_iess_vigencia ON parametros_iess(vigencia_desde, vigencia_hasta);

COMMENT ON TABLE parametros_iess IS 'Parámetros y porcentajes IESS por código de actividad';

-- =====================================================
-- TABLA: parametros_retencion_renta
-- Tabla de retención en la fuente (impuesto a la renta)
-- =====================================================

CREATE TABLE IF NOT EXISTS parametros_retencion_renta (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Período fiscal
    anio INTEGER NOT NULL,
    tipo_servicio VARCHAR(50) NOT NULL DEFAULT 'honorarios_profesionales',

    -- Porcentajes
    porcentaje_retencion DECIMAL(5, 4) NOT NULL,  -- Ej: 0.10 = 10%
    base_minima DECIMAL(10, 2) NOT NULL DEFAULT 0,  -- Base mínima para aplicar retención

    -- Fracción básica y excedente (si aplica tabla progresiva)
    fraccion_basica DECIMAL(10, 2),
    exceso_hasta DECIMAL(10, 2),
    impuesto_fraccion_basica DECIMAL(10, 2),
    porcentaje_excedente DECIMAL(5, 4),

    -- Estado
    activo BOOLEAN NOT NULL DEFAULT true,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_parametros_retencion_anio ON parametros_retencion_renta(anio);
CREATE INDEX idx_parametros_retencion_tipo ON parametros_retencion_renta(tipo_servicio);

COMMENT ON TABLE parametros_retencion_renta IS 'Parámetros para cálculo de retención en la fuente';

-- =====================================================
-- VISTA: v_honorarios_pendientes
-- Honorarios pendientes de pago
-- =====================================================

CREATE OR REPLACE VIEW v_honorarios_pendientes AS
SELECT
    p.id,
    p.periodo,
    p.anio,
    p.mes,
    a.razon_social AS administrador,
    a.identificacion,
    p.honorario_bruto,
    p.total_iess,
    p.retencion_renta,
    p.neto_pagar,
    p.estado,
    p.created_at
FROM pagos_honorarios p
JOIN administradores a ON a.id = p.administrador_id
WHERE p.estado IN ('pendiente', 'aprobado')
ORDER BY p.anio DESC, p.mes DESC;

COMMENT ON VIEW v_honorarios_pendientes IS 'Pagos de honorarios pendientes';

-- =====================================================
-- VISTA: v_resumen_honorarios_anual
-- Resumen anual de honorarios por administrador
-- =====================================================

CREATE OR REPLACE VIEW v_resumen_honorarios_anual AS
SELECT
    p.administrador_id,
    a.razon_social,
    a.identificacion,
    p.anio,
    COUNT(*) AS total_pagos,
    SUM(p.honorario_bruto) AS total_honorarios,
    SUM(p.aporte_patronal) AS total_aporte_patronal,
    SUM(p.aporte_personal) AS total_aporte_personal,
    SUM(p.total_iess) AS total_iess,
    SUM(p.retencion_renta) AS total_retencion,
    SUM(p.neto_pagar) AS total_neto
FROM pagos_honorarios p
JOIN administradores a ON a.id = p.administrador_id
WHERE p.estado IN ('aprobado', 'pagado')
GROUP BY p.administrador_id, a.razon_social, a.identificacion, p.anio
ORDER BY p.anio DESC, a.razon_social;

COMMENT ON VIEW v_resumen_honorarios_anual IS 'Resumen anual de honorarios pagados';

-- =====================================================
-- FUNCIÓN: calcular_iess_109
-- Calcula aportes IESS para código 109
-- =====================================================

CREATE OR REPLACE FUNCTION calcular_iess_109(
    p_honorario_bruto DECIMAL(10, 2),
    p_fecha DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    aporte_patronal DECIMAL(10, 2),
    aporte_personal DECIMAL(10, 2),
    total_iess DECIMAL(10, 2)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_pct_patronal DECIMAL(5, 4);
    v_pct_personal DECIMAL(5, 4);
    v_aporte_patronal DECIMAL(10, 2);
    v_aporte_personal DECIMAL(10, 2);
BEGIN
    -- Obtener porcentajes vigentes
    SELECT
        porcentaje_aporte_patronal,
        porcentaje_aporte_personal
    INTO v_pct_patronal, v_pct_personal
    FROM parametros_iess
    WHERE codigo_actividad = '109'
      AND activo = true
      AND vigencia_desde <= p_fecha
      AND (vigencia_hasta IS NULL OR vigencia_hasta >= p_fecha)
    ORDER BY vigencia_desde DESC
    LIMIT 1;

    -- Si no hay parámetros, usar valores por defecto
    IF v_pct_patronal IS NULL THEN
        v_pct_patronal := 0.1215;  -- 12.15%
        v_pct_personal := 0.0945;  -- 9.45%
    END IF;

    -- Calcular aportes
    v_aporte_patronal := ROUND(p_honorario_bruto * v_pct_patronal, 2);
    v_aporte_personal := ROUND(p_honorario_bruto * v_pct_personal, 2);

    RETURN QUERY SELECT
        v_aporte_patronal,
        v_aporte_personal,
        v_aporte_patronal + v_aporte_personal;
END;
$$;

COMMENT ON FUNCTION calcular_iess_109 IS 'Calcula aportes IESS para código 109 (honorarios profesionales)';

-- =====================================================
-- FUNCIÓN: calcular_retencion_renta
-- Calcula retención en la fuente para honorarios
-- =====================================================

CREATE OR REPLACE FUNCTION calcular_retencion_renta(
    p_base_imponible DECIMAL(10, 2),
    p_anio INTEGER DEFAULT EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER
)
RETURNS TABLE (
    retencion DECIMAL(10, 2),
    porcentaje DECIMAL(5, 4)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_porcentaje DECIMAL(5, 4);
    v_base_minima DECIMAL(10, 2);
    v_retencion DECIMAL(10, 2);
BEGIN
    -- Obtener porcentaje vigente
    SELECT
        porcentaje_retencion,
        base_minima
    INTO v_porcentaje, v_base_minima
    FROM parametros_retencion_renta
    WHERE anio = p_anio
      AND tipo_servicio = 'honorarios_profesionales'
      AND activo = true
    ORDER BY created_at DESC
    LIMIT 1;

    -- Si no hay parámetros, usar 10% por defecto
    IF v_porcentaje IS NULL THEN
        v_porcentaje := 0.10;  -- 10%
        v_base_minima := 0;
    END IF;

    -- Calcular retención si supera base mínima
    IF p_base_imponible >= v_base_minima THEN
        v_retencion := ROUND(p_base_imponible * v_porcentaje, 2);
    ELSE
        v_retencion := 0;
    END IF;

    RETURN QUERY SELECT v_retencion, v_porcentaje;
END;
$$;

COMMENT ON FUNCTION calcular_retencion_renta IS 'Calcula retención en la fuente para honorarios profesionales';

-- =====================================================
-- TRIGGERS
-- =====================================================

CREATE TRIGGER set_updated_at_administradores
    BEFORE UPDATE ON administradores
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_pagos_honorarios
    BEFORE UPDATE ON pagos_honorarios
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_parametros_iess
    BEFORE UPDATE ON parametros_iess
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_parametros_retencion
    BEFORE UPDATE ON parametros_retencion_renta
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

-- =====================================================
-- RLS: Row Level Security
-- =====================================================

ALTER TABLE administradores ENABLE ROW LEVEL SECURITY;
ALTER TABLE pagos_honorarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE parametros_iess ENABLE ROW LEVEL SECURITY;
ALTER TABLE parametros_retencion_renta ENABLE ROW LEVEL SECURITY;

-- Políticas permisivas para service role
CREATE POLICY "Service role full access administradores"
    ON administradores FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access pagos_honorarios"
    ON pagos_honorarios FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access parametros_iess"
    ON parametros_iess FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access parametros_retencion"
    ON parametros_retencion_renta FOR ALL USING (true) WITH CHECK (true);

-- =====================================================
-- DATOS INICIALES
-- =====================================================

-- Parámetros IESS 2025 para código 109
INSERT INTO parametros_iess (
    codigo_actividad,
    vigencia_desde,
    porcentaje_aporte_patronal,
    porcentaje_aporte_personal,
    salario_basico_unificado
)
VALUES (
    '109',
    '2025-01-01',
    0.1215,  -- 12.15%
    0.0945,  -- 9.45%
    460.00   -- SBU 2025 (actualizar según decreto)
)
ON CONFLICT DO NOTHING;

-- Parámetros de retención 2025
INSERT INTO parametros_retencion_renta (
    anio,
    tipo_servicio,
    porcentaje_retencion,
    base_minima
)
VALUES (
    2025,
    'honorarios_profesionales',
    0.0800,  -- 8% para honorarios profesionales en Ecuador
    0.00     -- No hay base mínima (siempre se retiene)
)
ON CONFLICT DO NOTHING;
