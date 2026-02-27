-- =====================================================
-- MIGRACIÓN 012: Calendario Tributario Mejorado
-- =====================================================
-- Tablas y funciones para gestión de obligaciones tributarias
-- con alertas y seguimiento de cumplimiento.
-- =====================================================

-- =====================================================
-- 1. CATÁLOGO DE TIPOS DE OBLIGACIÓN
-- =====================================================
CREATE TABLE IF NOT EXISTS tipos_obligacion_tributaria (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(20) UNIQUE NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    formulario_sri VARCHAR(20),  -- Form 103, Form 104, etc.
    frecuencia VARCHAR(20) NOT NULL DEFAULT 'mensual', -- mensual, semestral, anual
    requiere_ats BOOLEAN DEFAULT false,
    es_retencion BOOLEAN DEFAULT false,
    prioridad VARCHAR(10) DEFAULT 'media', -- alta, media, baja
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insertar tipos de obligación estándar
INSERT INTO tipos_obligacion_tributaria (codigo, nombre, descripcion, formulario_sri, frecuencia, requiere_ats, es_retencion, prioridad) VALUES
    ('IVA_MENSUAL', 'Declaración de IVA Mensual', 'Declaración mensual del Impuesto al Valor Agregado', '104', 'mensual', true, false, 'alta'),
    ('RET_FUENTE', 'Retenciones en la Fuente', 'Declaración de retenciones de impuesto a la renta', '103', 'mensual', false, true, 'alta'),
    ('ATS', 'Anexo Transaccional Simplificado', 'Reporte mensual de transacciones', 'ATS', 'mensual', false, false, 'media'),
    ('RENTA_ANUAL', 'Impuesto a la Renta Anual', 'Declaración anual de impuesto a la renta (sociedades)', '101', 'anual', false, false, 'alta'),
    ('RENTA_PN', 'Impuesto a la Renta Personas Naturales', 'Declaración anual de renta para personas naturales', '102', 'anual', false, false, 'alta'),
    ('GASTOS_PERSONALES', 'Proyección Gastos Personales', 'Proyección de gastos personales deducibles', 'GPP', 'semestral', false, false, 'media'),
    ('IVA_SEMESTRAL', 'Declaración IVA Semestral', 'Para contribuyentes con régimen semestral', '104S', 'semestral', true, false, 'alta'),
    ('RDEP', 'Anexo RDEP', 'Anexo de retenciones en la fuente bajo relación de dependencia', 'RDEP', 'anual', false, true, 'media')
ON CONFLICT (codigo) DO NOTHING;

-- =====================================================
-- 2. TABLA DE VENCIMIENTOS POR DÍGITO
-- =====================================================
CREATE TABLE IF NOT EXISTS vencimientos_por_digito (
    id SERIAL PRIMARY KEY,
    noveno_digito INTEGER NOT NULL CHECK (noveno_digito BETWEEN 0 AND 9),
    tipo_obligacion_id INTEGER REFERENCES tipos_obligacion_tributaria(id),
    dia_limite INTEGER NOT NULL CHECK (dia_limite BETWEEN 1 AND 31),
    mes_relativo INTEGER DEFAULT 1, -- 0 = mismo mes, 1 = mes siguiente, etc.
    UNIQUE (noveno_digito, tipo_obligacion_id)
);

-- Insertar vencimientos estándar para obligaciones mensuales
-- (Se ejecutan en el mes siguiente al periodo declarado)
INSERT INTO vencimientos_por_digito (noveno_digito, tipo_obligacion_id, dia_limite, mes_relativo)
SELECT
    d.digito,
    t.id,
    CASE d.digito
        WHEN 1 THEN 10
        WHEN 2 THEN 12
        WHEN 3 THEN 14
        WHEN 4 THEN 16
        WHEN 5 THEN 18
        WHEN 6 THEN 20
        WHEN 7 THEN 22
        WHEN 8 THEN 24
        WHEN 9 THEN 26
        WHEN 0 THEN 28
    END as dia_limite,
    1 as mes_relativo
FROM (SELECT generate_series(0, 9) as digito) d
CROSS JOIN tipos_obligacion_tributaria t
WHERE t.frecuencia = 'mensual'
ON CONFLICT DO NOTHING;

-- =====================================================
-- 3. TABLA DE OBLIGACIONES DEL CONTRIBUYENTE
-- =====================================================
CREATE TABLE IF NOT EXISTS obligaciones_tributarias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_obligacion_id INTEGER REFERENCES tipos_obligacion_tributaria(id),
    periodo_anio INTEGER NOT NULL,
    periodo_mes INTEGER CHECK (periodo_mes BETWEEN 1 AND 12),
    fecha_vencimiento DATE NOT NULL,
    fecha_cumplimiento TIMESTAMPTZ,
    estado VARCHAR(20) DEFAULT 'pendiente', -- pendiente, cumplida, vencida, exonerada
    numero_formulario VARCHAR(50), -- Número del comprobante del SRI
    observaciones TEXT,
    monto_declarado DECIMAL(14,2),
    monto_pagado DECIMAL(14,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_obligaciones_periodo ON obligaciones_tributarias(periodo_anio, periodo_mes);
CREATE INDEX IF NOT EXISTS idx_obligaciones_vencimiento ON obligaciones_tributarias(fecha_vencimiento);
CREATE INDEX IF NOT EXISTS idx_obligaciones_estado ON obligaciones_tributarias(estado);

-- =====================================================
-- 4. FUNCIÓN: Calcular fecha de vencimiento
-- =====================================================
CREATE OR REPLACE FUNCTION calcular_fecha_vencimiento(
    p_ruc VARCHAR(13),
    p_tipo_obligacion VARCHAR(20),
    p_anio INTEGER,
    p_mes INTEGER
) RETURNS DATE AS $$
DECLARE
    v_noveno_digito INTEGER;
    v_dia_limite INTEGER;
    v_mes_relativo INTEGER;
    v_fecha_vencimiento DATE;
    v_ultimo_dia INTEGER;
BEGIN
    -- Extraer noveno dígito del RUC
    v_noveno_digito := CAST(SUBSTRING(p_ruc, 9, 1) AS INTEGER);

    -- Obtener día límite y mes relativo
    SELECT
        vd.dia_limite,
        vd.mes_relativo
    INTO v_dia_limite, v_mes_relativo
    FROM vencimientos_por_digito vd
    JOIN tipos_obligacion_tributaria t ON vd.tipo_obligacion_id = t.id
    WHERE vd.noveno_digito = v_noveno_digito
    AND t.codigo = p_tipo_obligacion;

    -- Si no hay configuración específica, usar valores por defecto
    IF v_dia_limite IS NULL THEN
        v_dia_limite := CASE v_noveno_digito
            WHEN 1 THEN 10 WHEN 2 THEN 12 WHEN 3 THEN 14
            WHEN 4 THEN 16 WHEN 5 THEN 18 WHEN 6 THEN 20
            WHEN 7 THEN 22 WHEN 8 THEN 24 WHEN 9 THEN 26
            ELSE 28
        END;
        v_mes_relativo := 1;
    END IF;

    -- Calcular mes de vencimiento
    v_fecha_vencimiento := (DATE_TRUNC('month', MAKE_DATE(p_anio, p_mes, 1))
                           + (v_mes_relativo || ' months')::INTERVAL)::DATE;

    -- Ajustar día considerando el último día del mes
    v_ultimo_dia := DATE_PART('day',
        (DATE_TRUNC('month', v_fecha_vencimiento) + INTERVAL '1 month - 1 day')::DATE
    );

    v_fecha_vencimiento := MAKE_DATE(
        EXTRACT(YEAR FROM v_fecha_vencimiento)::INTEGER,
        EXTRACT(MONTH FROM v_fecha_vencimiento)::INTEGER,
        LEAST(v_dia_limite, v_ultimo_dia)
    );

    -- Ajustar si cae en fin de semana (pasar al siguiente día hábil)
    IF EXTRACT(DOW FROM v_fecha_vencimiento) = 6 THEN -- Sábado
        v_fecha_vencimiento := v_fecha_vencimiento + INTERVAL '2 days';
    ELSIF EXTRACT(DOW FROM v_fecha_vencimiento) = 0 THEN -- Domingo
        v_fecha_vencimiento := v_fecha_vencimiento + INTERVAL '1 day';
    END IF;

    RETURN v_fecha_vencimiento;
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 5. FUNCIÓN: Obtener próximas obligaciones
-- =====================================================
CREATE OR REPLACE FUNCTION obtener_proximas_obligaciones(
    p_ruc VARCHAR(13),
    p_dias_adelante INTEGER DEFAULT 60
) RETURNS TABLE (
    tipo_codigo VARCHAR(20),
    tipo_nombre VARCHAR(100),
    formulario VARCHAR(20),
    periodo_anio INTEGER,
    periodo_mes INTEGER,
    fecha_vencimiento DATE,
    dias_restantes INTEGER,
    estado VARCHAR(20),
    prioridad VARCHAR(10),
    alerta BOOLEAN
) AS $$
DECLARE
    v_hoy DATE := CURRENT_DATE;
    v_fecha_limite DATE := v_hoy + p_dias_adelante;
BEGIN
    RETURN QUERY
    WITH periodos AS (
        -- Generar periodos desde hace 2 meses hasta 3 meses adelante
        SELECT
            EXTRACT(YEAR FROM d)::INTEGER as anio,
            EXTRACT(MONTH FROM d)::INTEGER as mes
        FROM generate_series(
            DATE_TRUNC('month', v_hoy - INTERVAL '2 months'),
            DATE_TRUNC('month', v_hoy + INTERVAL '3 months'),
            '1 month'
        ) d
    ),
    obligaciones_calculadas AS (
        SELECT
            t.codigo as tipo_codigo,
            t.nombre as tipo_nombre,
            t.formulario_sri as formulario,
            p.anio as periodo_anio,
            p.mes as periodo_mes,
            calcular_fecha_vencimiento(p_ruc, t.codigo, p.anio, p.mes) as fecha_vencimiento,
            t.prioridad,
            COALESCE(o.estado, 'pendiente') as estado,
            o.id as obligacion_id
        FROM tipos_obligacion_tributaria t
        CROSS JOIN periodos p
        LEFT JOIN obligaciones_tributarias o ON
            o.tipo_obligacion_id = t.id
            AND o.periodo_anio = p.anio
            AND o.periodo_mes = p.mes
        WHERE t.activo = true
        AND t.frecuencia = 'mensual'
    )
    SELECT
        oc.tipo_codigo,
        oc.tipo_nombre,
        oc.formulario,
        oc.periodo_anio,
        oc.periodo_mes,
        oc.fecha_vencimiento,
        (oc.fecha_vencimiento - v_hoy)::INTEGER as dias_restantes,
        oc.estado,
        oc.prioridad,
        (oc.fecha_vencimiento - v_hoy) <= 5 AND oc.estado = 'pendiente' as alerta
    FROM obligaciones_calculadas oc
    WHERE oc.fecha_vencimiento >= v_hoy - INTERVAL '30 days'
    AND oc.fecha_vencimiento <= v_fecha_limite
    AND oc.estado != 'cumplida'
    ORDER BY oc.fecha_vencimiento, oc.prioridad;
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 6. FUNCIÓN: Registrar cumplimiento de obligación
-- =====================================================
CREATE OR REPLACE FUNCTION registrar_cumplimiento_obligacion(
    p_tipo_codigo VARCHAR(20),
    p_anio INTEGER,
    p_mes INTEGER,
    p_numero_formulario VARCHAR(50) DEFAULT NULL,
    p_monto_declarado DECIMAL(14,2) DEFAULT NULL,
    p_monto_pagado DECIMAL(14,2) DEFAULT NULL,
    p_observaciones TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_tipo_id INTEGER;
    v_obligacion_id UUID;
    v_ruc VARCHAR(13);
BEGIN
    -- Obtener RUC de la empresa
    SELECT sri_ruc INTO v_ruc FROM company_info LIMIT 1;
    IF v_ruc IS NULL THEN
        v_ruc := '0000000000001'; -- Default si no hay config
    END IF;

    -- Obtener tipo de obligación
    SELECT id INTO v_tipo_id FROM tipos_obligacion_tributaria WHERE codigo = p_tipo_codigo;
    IF v_tipo_id IS NULL THEN
        RAISE EXCEPTION 'Tipo de obligación no encontrado: %', p_tipo_codigo;
    END IF;

    -- Insertar o actualizar obligación
    INSERT INTO obligaciones_tributarias (
        tipo_obligacion_id,
        periodo_anio,
        periodo_mes,
        fecha_vencimiento,
        fecha_cumplimiento,
        estado,
        numero_formulario,
        monto_declarado,
        monto_pagado,
        observaciones
    ) VALUES (
        v_tipo_id,
        p_anio,
        p_mes,
        calcular_fecha_vencimiento(v_ruc, p_tipo_codigo, p_anio, p_mes),
        NOW(),
        'cumplida',
        p_numero_formulario,
        p_monto_declarado,
        p_monto_pagado,
        p_observaciones
    )
    ON CONFLICT (id) DO UPDATE SET
        fecha_cumplimiento = NOW(),
        estado = 'cumplida',
        numero_formulario = COALESCE(EXCLUDED.numero_formulario, obligaciones_tributarias.numero_formulario),
        monto_declarado = COALESCE(EXCLUDED.monto_declarado, obligaciones_tributarias.monto_declarado),
        monto_pagado = COALESCE(EXCLUDED.monto_pagado, obligaciones_tributarias.monto_pagado),
        observaciones = COALESCE(EXCLUDED.observaciones, obligaciones_tributarias.observaciones),
        updated_at = NOW()
    RETURNING id INTO v_obligacion_id;

    RETURN v_obligacion_id;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 7. VISTA: Resumen de obligaciones pendientes
-- =====================================================
CREATE OR REPLACE VIEW v_obligaciones_pendientes AS
SELECT
    t.codigo as tipo_codigo,
    t.nombre as tipo_nombre,
    t.formulario_sri as formulario,
    t.prioridad,
    o.periodo_anio,
    o.periodo_mes,
    o.fecha_vencimiento,
    (o.fecha_vencimiento - CURRENT_DATE) as dias_restantes,
    CASE
        WHEN o.fecha_vencimiento < CURRENT_DATE THEN 'vencida'
        WHEN o.fecha_vencimiento - CURRENT_DATE <= 5 THEN 'urgente'
        WHEN o.fecha_vencimiento - CURRENT_DATE <= 15 THEN 'proxima'
        ELSE 'normal'
    END as urgencia,
    o.estado
FROM obligaciones_tributarias o
JOIN tipos_obligacion_tributaria t ON o.tipo_obligacion_id = t.id
WHERE o.estado = 'pendiente'
ORDER BY o.fecha_vencimiento;

-- =====================================================
-- 8. TRIGGER: Actualizar estado de vencidas
-- =====================================================
CREATE OR REPLACE FUNCTION actualizar_estado_vencidas() RETURNS TRIGGER AS $$
BEGIN
    -- Marcar como vencidas las obligaciones pasadas sin cumplir
    UPDATE obligaciones_tributarias
    SET estado = 'vencida', updated_at = NOW()
    WHERE estado = 'pendiente'
    AND fecha_vencimiento < CURRENT_DATE;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Este trigger se puede ejecutar diariamente con pg_cron si está disponible
-- O ser llamado manualmente/desde la aplicación

-- =====================================================
-- 9. FUNCIÓN: Widget para dashboard
-- =====================================================
CREATE OR REPLACE FUNCTION get_calendario_widget(
    p_ruc VARCHAR(13)
) RETURNS JSON AS $$
DECLARE
    v_result JSON;
BEGIN
    SELECT json_build_object(
        'proximas_obligaciones', (
            SELECT json_agg(row_to_json(t))
            FROM (
                SELECT * FROM obtener_proximas_obligaciones(p_ruc, 30)
                ORDER BY fecha_vencimiento
                LIMIT 5
            ) t
        ),
        'alertas', (
            SELECT COUNT(*)
            FROM obtener_proximas_obligaciones(p_ruc, 30)
            WHERE alerta = true
        ),
        'vencidas', (
            SELECT COUNT(*)
            FROM obligaciones_tributarias
            WHERE estado = 'vencida'
        ),
        'resumen_mes_actual', (
            SELECT json_build_object(
                'total_pendientes', COUNT(*) FILTER (WHERE estado = 'pendiente'),
                'total_cumplidas', COUNT(*) FILTER (WHERE estado = 'cumplida'),
                'total_vencidas', COUNT(*) FILTER (WHERE estado = 'vencida')
            )
            FROM obligaciones_tributarias
            WHERE periodo_anio = EXTRACT(YEAR FROM CURRENT_DATE)
            AND periodo_mes = EXTRACT(MONTH FROM CURRENT_DATE)
        )
    ) INTO v_result;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 10. COMENTARIOS
-- =====================================================
COMMENT ON TABLE tipos_obligacion_tributaria IS 'Catálogo de tipos de obligaciones tributarias del SRI';
COMMENT ON TABLE vencimientos_por_digito IS 'Configuración de fechas de vencimiento por noveno dígito del RUC';
COMMENT ON TABLE obligaciones_tributarias IS 'Registro de obligaciones tributarias del contribuyente';
COMMENT ON FUNCTION calcular_fecha_vencimiento IS 'Calcula la fecha de vencimiento de una obligación según el RUC';
COMMENT ON FUNCTION obtener_proximas_obligaciones IS 'Obtiene las próximas obligaciones con alertas';
COMMENT ON FUNCTION get_calendario_widget IS 'Datos para el widget de calendario en dashboard';
