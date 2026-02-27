-- =====================================================
-- MIGRACIÓN 013: Tablas de Retenciones Actualizadas 2025
-- =====================================================
-- Basado en resoluciones SRI vigentes:
-- - NAC-DGERCGC24-00000008 (Retenciones IVA)
-- - Tabla oficial SRI de porcentajes IR
-- =====================================================

-- =====================================================
-- 1. CATÁLOGO DE TIPOS DE CONTRIBUYENTE
-- =====================================================
CREATE TABLE IF NOT EXISTS tipos_contribuyente (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(20) UNIQUE NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    es_especial BOOLEAN DEFAULT false,
    obligado_contabilidad BOOLEAN DEFAULT false,
    aplica_retenciones BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO tipos_contribuyente (codigo, nombre, descripcion, es_especial, obligado_contabilidad) VALUES
    ('ESPECIAL', 'Contribuyente Especial', 'Designado por el SRI como contribuyente especial', true, true),
    ('SOCIEDAD', 'Sociedad', 'Persona jurídica (compañía, asociación, etc.)', false, true),
    ('PN_OBLIG', 'Persona Natural Obligada a Llevar Contabilidad', 'Persona natural con obligación contable', false, true),
    ('PN_NO_OBLIG', 'Persona Natural No Obligada a Llevar Contabilidad', 'Persona natural sin obligación contable', false, false),
    ('RISE', 'RISE', 'Régimen Impositivo Simplificado', false, false),
    ('RIMPE_EMP', 'RIMPE Emprendedor', 'Régimen para emprendedores', false, false),
    ('RIMPE_NEG', 'RIMPE Negocio Popular', 'Régimen negocio popular', false, false),
    ('EXPORTADOR', 'Exportador Habitual', 'Exportador designado por el SRI', false, true)
ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre;

-- =====================================================
-- 2. CATÁLOGO DE CONCEPTOS DE RETENCIÓN IR
-- =====================================================
CREATE TABLE IF NOT EXISTS conceptos_retencion_ir (
    id SERIAL PRIMARY KEY,
    codigo_sri VARCHAR(10) UNIQUE NOT NULL,
    concepto VARCHAR(200) NOT NULL,
    porcentaje DECIMAL(5,2) NOT NULL,
    base_legal TEXT,
    aplica_desde DATE DEFAULT '2025-01-01',
    aplica_hasta DATE,
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de retenciones IR 2025 según SRI
INSERT INTO conceptos_retencion_ir (codigo_sri, concepto, porcentaje, base_legal) VALUES
    -- Honorarios y servicios profesionales
    ('303', 'Honorarios profesionales y dietas', 10.00, 'Art. 92 RLRTI'),
    ('304', 'Servicios predomina el intelecto no relacionados con título profesional', 8.00, 'Art. 92 RLRTI'),
    ('304A', 'Comisiones y demás pagos por servicios predomina el intelecto', 8.00, 'Art. 92 RLRTI'),
    ('304B', 'Pagos a notarios y registradores', 8.00, 'Art. 92 RLRTI'),
    ('304C', 'Pagos a deportistas, artistas y otros por espectáculos públicos', 8.00, 'Art. 92 RLRTI'),
    ('304D', 'Pagos por pensiones jubilares', 8.00, 'Art. 92 RLRTI'),
    ('304E', 'Pagos por pagos realizados a entidades del sector público', 0.00, 'Art. 92 RLRTI'),

    -- Servicios
    ('307', 'Servicios donde predomina la mano de obra', 2.00, 'Art. 92 RLRTI'),
    ('308', 'Servicios entre sociedades', 2.00, 'Art. 92 RLRTI'),
    ('309', 'Servicios publicidad y comunicación', 1.75, 'Art. 92 RLRTI'),
    ('310', 'Servicio de transporte privado de pasajeros o carga', 1.00, 'Art. 92 RLRTI'),
    ('311', 'Pagos por través de LdC a PN no obligadas a llevar contabilidad', 2.00, 'Art. 92 RLRTI'),

    -- Arrendamientos
    ('312', 'Transferencia de bienes muebles', 1.00, 'Art. 92 RLRTI'),
    ('319', 'Arrendamiento mercantil local', 1.00, 'Art. 92 RLRTI'),
    ('320', 'Arrendamiento bienes inmuebles', 8.00, 'Art. 92 RLRTI'),

    -- Seguros y reaseguros
    ('322', 'Seguros y reaseguros (primas y cesiones)', 1.75, 'Art. 92 RLRTI'),

    -- Compras
    ('332', 'Pagos bienes no producidos en el país', 1.75, 'Art. 92 RLRTI'),
    ('332B', 'Compras de bienes de origen agrícola, pecuario, acuícola, etc.', 1.00, 'Art. 92 RLRTI'),
    ('332C', 'Compras de bienes inmuebles', 0.00, 'Art. 92 RLRTI'),

    -- Otros
    ('340', 'Otras retenciones aplicables 1%', 1.00, 'Art. 92 RLRTI'),
    ('341', 'Otras retenciones aplicables 2%', 2.00, 'Art. 92 RLRTI'),
    ('342', 'Otras retenciones aplicables 8%', 8.00, 'Art. 92 RLRTI'),
    ('343', 'Otras retenciones aplicables 25%', 25.00, 'Art. 92 RLRTI'),

    -- Rendimientos financieros
    ('323', 'Rendimientos financieros pagados a PN o sociedades', 2.00, 'Art. 92 RLRTI'),
    ('323A', 'Rendimientos financieros: depósitos en instituciones financieras', 2.00, 'Art. 92 RLRTI'),
    ('323B', 'Rendimientos financieros: inversiones en títulos valores', 2.00, 'Art. 92 RLRTI'),

    -- Sin retención
    ('332A', 'Compras a contribuyentes RISE', 0.00, 'Art. 92 RLRTI'),
    ('344', 'Pagos que no constituyen renta gravada', 0.00, 'Art. 92 RLRTI')
ON CONFLICT (codigo_sri) DO UPDATE SET
    concepto = EXCLUDED.concepto,
    porcentaje = EXCLUDED.porcentaje;

-- =====================================================
-- 3. CATÁLOGO DE CONCEPTOS DE RETENCIÓN IVA
-- =====================================================
CREATE TABLE IF NOT EXISTS conceptos_retencion_iva (
    id SERIAL PRIMARY KEY,
    codigo_sri VARCHAR(10) UNIQUE NOT NULL,
    concepto VARCHAR(200) NOT NULL,
    porcentaje DECIMAL(5,2) NOT NULL,
    aplica_bienes BOOLEAN DEFAULT false,
    aplica_servicios BOOLEAN DEFAULT false,
    base_legal TEXT,
    aplica_desde DATE DEFAULT '2025-01-01',
    aplica_hasta DATE,
    activo BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de retenciones IVA 2025 según Resolución NAC-DGERCGC24-00000008
INSERT INTO conceptos_retencion_iva (codigo_sri, concepto, porcentaje, aplica_bienes, aplica_servicios, base_legal) VALUES
    -- Retenciones estándar
    ('721', 'Retención 10% IVA', 10.00, true, false, 'NAC-DGERCGC24-00000008'),
    ('723', 'Retención 20% IVA', 20.00, false, true, 'NAC-DGERCGC24-00000008'),
    ('725', 'Retención 30% IVA', 30.00, false, true, 'NAC-DGERCGC24-00000008'),
    ('727', 'Retención 70% IVA', 70.00, false, true, 'NAC-DGERCGC24-00000008'),
    ('729', 'Retención 100% IVA', 100.00, true, true, 'NAC-DGERCGC24-00000008'),

    -- Sin retención
    ('731', 'No aplica retención IVA', 0.00, true, true, 'NAC-DGERCGC24-00000008')
ON CONFLICT (codigo_sri) DO UPDATE SET
    concepto = EXCLUDED.concepto,
    porcentaje = EXCLUDED.porcentaje;

-- =====================================================
-- 4. MATRIZ DE RETENCIONES IVA POR TIPO DE TRANSACCIÓN
-- =====================================================
CREATE TABLE IF NOT EXISTS matriz_retenciones_iva (
    id SERIAL PRIMARY KEY,
    agente_retencion VARCHAR(50) NOT NULL,  -- tipo de contribuyente del agente
    sujeto_retenido VARCHAR(50) NOT NULL,   -- tipo de contribuyente del sujeto
    tipo_transaccion VARCHAR(50) NOT NULL,  -- bienes, servicios, profesionales, etc.
    codigo_retencion VARCHAR(10) REFERENCES conceptos_retencion_iva(codigo_sri),
    porcentaje DECIMAL(5,2) NOT NULL,
    observaciones TEXT,
    activo BOOLEAN DEFAULT true,
    UNIQUE (agente_retencion, sujeto_retenido, tipo_transaccion)
);

-- Matriz simplificada de retenciones IVA 2025
INSERT INTO matriz_retenciones_iva (agente_retencion, sujeto_retenido, tipo_transaccion, codigo_retencion, porcentaje, observaciones) VALUES
    -- Contribuyente Especial comprando a Sociedades
    ('ESPECIAL', 'SOCIEDAD', 'BIENES', '721', 10.00, 'CE compra bienes a sociedad'),
    ('ESPECIAL', 'SOCIEDAD', 'SERVICIOS', '723', 20.00, 'CE contrata servicios de sociedad'),

    -- Contribuyente Especial comprando a PN Obligada
    ('ESPECIAL', 'PN_OBLIG', 'BIENES', '721', 10.00, 'CE compra bienes a PN obligada'),
    ('ESPECIAL', 'PN_OBLIG', 'SERVICIOS', '723', 20.00, 'CE contrata servicios de PN obligada'),

    -- Contribuyente Especial comprando a PN No Obligada
    ('ESPECIAL', 'PN_NO_OBLIG', 'BIENES', '721', 10.00, 'CE compra bienes a PN no obligada'),
    ('ESPECIAL', 'PN_NO_OBLIG', 'SERVICIOS', '729', 100.00, 'CE contrata servicios de PN no obligada'),
    ('ESPECIAL', 'PN_NO_OBLIG', 'PROFESIONALES', '729', 100.00, 'CE contrata honorarios profesionales'),

    -- Sociedad comprando a Sociedad
    ('SOCIEDAD', 'SOCIEDAD', 'BIENES', '731', 0.00, 'Sociedad compra bienes a sociedad - sin retención'),
    ('SOCIEDAD', 'SOCIEDAD', 'SERVICIOS', '731', 0.00, 'Sociedad contrata servicios de sociedad - sin retención'),

    -- Sociedad comprando a PN No Obligada
    ('SOCIEDAD', 'PN_NO_OBLIG', 'BIENES', '721', 10.00, 'Sociedad compra bienes a PN no obligada'),
    ('SOCIEDAD', 'PN_NO_OBLIG', 'SERVICIOS', '729', 100.00, 'Sociedad contrata servicios de PN no obligada'),
    ('SOCIEDAD', 'PN_NO_OBLIG', 'PROFESIONALES', '729', 100.00, 'Sociedad contrata honorarios profesionales'),

    -- Casos especiales
    ('ESPECIAL', 'EXPORTADOR', 'BIENES', '731', 0.00, 'Exportadores tienen régimen especial'),
    ('SOCIEDAD', 'RISE', 'BIENES', '731', 0.00, 'RISE no genera retención'),
    ('SOCIEDAD', 'RISE', 'SERVICIOS', '731', 0.00, 'RISE no genera retención'),

    -- Construcción
    ('ESPECIAL', 'SOCIEDAD', 'CONSTRUCCION', '725', 30.00, 'Servicios de construcción'),
    ('ESPECIAL', 'PN_OBLIG', 'CONSTRUCCION', '725', 30.00, 'Servicios de construcción'),

    -- Liquidación de compras
    ('SOCIEDAD', 'PN_NO_OBLIG', 'LIQ_COMPRAS', '729', 100.00, 'Liquidación de compras siempre 100%'),
    ('ESPECIAL', 'PN_NO_OBLIG', 'LIQ_COMPRAS', '729', 100.00, 'Liquidación de compras siempre 100%'),

    -- Arrendamiento
    ('SOCIEDAD', 'PN_NO_OBLIG', 'ARRIENDO', '729', 100.00, 'Arrendamiento a persona natural'),
    ('ESPECIAL', 'PN_NO_OBLIG', 'ARRIENDO', '729', 100.00, 'Arrendamiento a persona natural')
ON CONFLICT (agente_retencion, sujeto_retenido, tipo_transaccion) DO UPDATE SET
    codigo_retencion = EXCLUDED.codigo_retencion,
    porcentaje = EXCLUDED.porcentaje;

-- =====================================================
-- 5. FUNCIÓN: Obtener porcentaje de retención IR
-- =====================================================
CREATE OR REPLACE FUNCTION obtener_retencion_ir(
    p_codigo_concepto VARCHAR(10)
) RETURNS DECIMAL(5,2) AS $$
DECLARE
    v_porcentaje DECIMAL(5,2);
BEGIN
    SELECT porcentaje INTO v_porcentaje
    FROM conceptos_retencion_ir
    WHERE codigo_sri = p_codigo_concepto
    AND activo = true
    AND (aplica_hasta IS NULL OR aplica_hasta >= CURRENT_DATE);

    RETURN COALESCE(v_porcentaje, 0);
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 6. FUNCIÓN: Obtener porcentaje de retención IVA
-- =====================================================
CREATE OR REPLACE FUNCTION obtener_retencion_iva(
    p_tipo_agente VARCHAR(50),
    p_tipo_sujeto VARCHAR(50),
    p_tipo_transaccion VARCHAR(50)
) RETURNS TABLE (
    codigo_retencion VARCHAR(10),
    porcentaje DECIMAL(5,2),
    concepto VARCHAR(200)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.codigo_retencion,
        m.porcentaje,
        c.concepto
    FROM matriz_retenciones_iva m
    JOIN conceptos_retencion_iva c ON m.codigo_retencion = c.codigo_sri
    WHERE m.agente_retencion = p_tipo_agente
    AND m.sujeto_retenido = p_tipo_sujeto
    AND m.tipo_transaccion = p_tipo_transaccion
    AND m.activo = true
    AND c.activo = true;

    -- Si no hay resultado específico, devolver sin retención
    IF NOT FOUND THEN
        RETURN QUERY
        SELECT '731'::VARCHAR(10), 0.00::DECIMAL(5,2), 'No aplica retención IVA'::VARCHAR(200);
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 7. FUNCIÓN: Calcular retenciones para una compra
-- =====================================================
CREATE OR REPLACE FUNCTION calcular_retenciones_compra(
    p_tipo_agente VARCHAR(50),       -- Tipo de contribuyente del comprador
    p_tipo_proveedor VARCHAR(50),    -- Tipo de contribuyente del proveedor
    p_tipo_transaccion VARCHAR(50),  -- bienes, servicios, profesionales, etc.
    p_codigo_ir VARCHAR(10),         -- Código de concepto IR
    p_subtotal DECIMAL(14,2),        -- Subtotal de la factura (sin IVA)
    p_iva DECIMAL(14,2)              -- Valor del IVA
) RETURNS TABLE (
    retencion_ir_codigo VARCHAR(10),
    retencion_ir_porcentaje DECIMAL(5,2),
    retencion_ir_base DECIMAL(14,2),
    retencion_ir_valor DECIMAL(14,2),
    retencion_iva_codigo VARCHAR(10),
    retencion_iva_porcentaje DECIMAL(5,2),
    retencion_iva_base DECIMAL(14,2),
    retencion_iva_valor DECIMAL(14,2),
    total_retenciones DECIMAL(14,2)
) AS $$
DECLARE
    v_ir_porcentaje DECIMAL(5,2);
    v_iva_porcentaje DECIMAL(5,2);
    v_iva_codigo VARCHAR(10);
    v_ir_valor DECIMAL(14,2);
    v_iva_valor DECIMAL(14,2);
BEGIN
    -- Obtener porcentaje de retención IR
    v_ir_porcentaje := obtener_retencion_ir(p_codigo_ir);
    v_ir_valor := ROUND(p_subtotal * v_ir_porcentaje / 100, 2);

    -- Obtener porcentaje de retención IVA
    SELECT m.codigo_retencion, m.porcentaje
    INTO v_iva_codigo, v_iva_porcentaje
    FROM matriz_retenciones_iva m
    WHERE m.agente_retencion = p_tipo_agente
    AND m.sujeto_retenido = p_tipo_proveedor
    AND m.tipo_transaccion = p_tipo_transaccion
    AND m.activo = true
    LIMIT 1;

    v_iva_codigo := COALESCE(v_iva_codigo, '731');
    v_iva_porcentaje := COALESCE(v_iva_porcentaje, 0);
    v_iva_valor := ROUND(p_iva * v_iva_porcentaje / 100, 2);

    RETURN QUERY
    SELECT
        p_codigo_ir,
        v_ir_porcentaje,
        p_subtotal,
        v_ir_valor,
        v_iva_codigo,
        v_iva_porcentaje,
        p_iva,
        v_iva_valor,
        v_ir_valor + v_iva_valor;
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 8. VISTA: Resumen de porcentajes de retención
-- =====================================================
CREATE OR REPLACE VIEW v_resumen_retenciones AS
SELECT
    'IR' as tipo,
    codigo_sri as codigo,
    concepto,
    porcentaje,
    activo
FROM conceptos_retencion_ir
WHERE activo = true
UNION ALL
SELECT
    'IVA' as tipo,
    codigo_sri as codigo,
    concepto,
    porcentaje,
    activo
FROM conceptos_retencion_iva
WHERE activo = true
ORDER BY tipo, codigo;

-- =====================================================
-- 9. FUNCIÓN: Sugerir retención según descripción
-- =====================================================
CREATE OR REPLACE FUNCTION sugerir_retencion_ir(
    p_descripcion TEXT
) RETURNS TABLE (
    codigo_sri VARCHAR(10),
    concepto VARCHAR(200),
    porcentaje DECIMAL(5,2),
    confianza DECIMAL(3,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.codigo_sri,
        c.concepto,
        c.porcentaje,
        CASE
            -- Honorarios profesionales
            WHEN p_descripcion ~* 'honorario|profesional|abogad|contador|doctor|médic|ingenier|arquitect' THEN 0.95
            -- Servicios con predominio de mano de obra
            WHEN p_descripcion ~* 'limpieza|mantenimiento|jardin|seguridad|vigilancia' THEN 0.90
            -- Transporte
            WHEN p_descripcion ~* 'transport|flete|encomienda|courier' THEN 0.90
            -- Arrendamiento
            WHEN p_descripcion ~* 'arriendo|alquiler|arrendamiento' THEN 0.85
            -- Publicidad
            WHEN p_descripcion ~* 'publicidad|marketing|anuncio|propaganda' THEN 0.85
            -- Seguros
            WHEN p_descripcion ~* 'seguro|póliza|prima' THEN 0.80
            ELSE 0.50
        END::DECIMAL(3,2) as confianza
    FROM conceptos_retencion_ir c
    WHERE c.activo = true
    AND (
        (p_descripcion ~* 'honorario|profesional|abogad|contador|doctor|médic|ingenier|arquitect' AND c.codigo_sri = '303')
        OR (p_descripcion ~* 'limpieza|mantenimiento|jardin|seguridad|vigilancia' AND c.codigo_sri = '307')
        OR (p_descripcion ~* 'transport|flete|encomienda|courier' AND c.codigo_sri = '310')
        OR (p_descripcion ~* 'arriendo|alquiler|arrendamiento' AND c.codigo_sri = '320')
        OR (p_descripcion ~* 'publicidad|marketing|anuncio|propaganda' AND c.codigo_sri = '309')
        OR (p_descripcion ~* 'seguro|póliza|prima' AND c.codigo_sri = '322')
        OR (p_descripcion ~* 'servicio' AND c.codigo_sri = '308')
        OR (p_descripcion ~* 'compra|material|suministro|producto' AND c.codigo_sri = '312')
    )
    ORDER BY confianza DESC
    LIMIT 3;
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- 10. COMENTARIOS
-- =====================================================
COMMENT ON TABLE conceptos_retencion_ir IS 'Catálogo de conceptos de retención de Impuesto a la Renta según SRI';
COMMENT ON TABLE conceptos_retencion_iva IS 'Catálogo de conceptos de retención de IVA según SRI';
COMMENT ON TABLE matriz_retenciones_iva IS 'Matriz de retenciones IVA según tipo de agente, sujeto y transacción';
COMMENT ON FUNCTION calcular_retenciones_compra IS 'Calcula retenciones IR e IVA para una compra';
COMMENT ON FUNCTION sugerir_retencion_ir IS 'Sugiere código de retención IR basándose en la descripción';
