-- =====================================================
-- ECUCONDOR: MIGRACIÓN 003 - COMPROBANTES ELECTRÓNICOS SRI
-- Sistema de Facturación Electrónica Ecuador
-- =====================================================

-- =====================================================
-- TIPO ENUM: Estados de comprobante
-- =====================================================
DO $$ BEGIN
    CREATE TYPE comprobante_estado AS ENUM (
        'draft',           -- Borrador
        'pending',         -- Pendiente de envío
        'sent',            -- Enviado al SRI
        'received',        -- Recibido por SRI (PPR)
        'authorized',      -- Autorizado (AUT)
        'rejected',        -- Rechazado (NAT)
        'cancelled',       -- Anulado
        'error'            -- Error de sistema
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =====================================================
-- TABLA: comprobantes_electronicos
-- =====================================================
CREATE TABLE IF NOT EXISTS comprobantes_electronicos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identificación del comprobante
    tipo_comprobante VARCHAR(2) NOT NULL,
    establecimiento VARCHAR(3) NOT NULL,
    punto_emision VARCHAR(3) NOT NULL,
    secuencial VARCHAR(9) NOT NULL,
    clave_acceso VARCHAR(49) UNIQUE,
    numero_autorizacion VARCHAR(49),

    -- Fechas
    fecha_emision DATE NOT NULL,
    fecha_autorizacion TIMESTAMPTZ,

    -- Cliente
    cliente_id UUID REFERENCES clientes(id),
    cliente_tipo_id VARCHAR(2) NOT NULL,
    cliente_identificacion VARCHAR(20) NOT NULL,
    cliente_razon_social VARCHAR(300) NOT NULL,
    cliente_direccion TEXT,
    cliente_email VARCHAR(300),
    cliente_telefono VARCHAR(20),

    -- Montos
    subtotal_sin_impuestos NUMERIC(14, 2) NOT NULL DEFAULT 0,
    subtotal_12 NUMERIC(14, 2) NOT NULL DEFAULT 0,
    subtotal_15 NUMERIC(14, 2) NOT NULL DEFAULT 0,
    subtotal_0 NUMERIC(14, 2) NOT NULL DEFAULT 0,
    subtotal_no_objeto NUMERIC(14, 2) NOT NULL DEFAULT 0,
    subtotal_exento NUMERIC(14, 2) NOT NULL DEFAULT 0,
    total_descuento NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ice NUMERIC(14, 2) NOT NULL DEFAULT 0,
    iva NUMERIC(14, 2) NOT NULL DEFAULT 0,
    propina NUMERIC(14, 2) NOT NULL DEFAULT 0,
    importe_total NUMERIC(14, 2) NOT NULL,

    -- Estado y procesamiento
    estado comprobante_estado NOT NULL DEFAULT 'draft',
    xml_sin_firmar TEXT,
    xml_firmado TEXT,
    xml_autorizado TEXT,
    pdf_ride BYTEA,

    -- Respuestas del SRI
    mensajes_sri JSONB,
    intentos_envio INTEGER DEFAULT 0,
    ultimo_intento_at TIMESTAMPTZ,

    -- Referencia a documento modificado (para NC/ND)
    comprobante_modificado_id UUID REFERENCES comprobantes_electronicos(id),
    motivo_modificacion TEXT,

    -- Metadata y auditoría
    info_adicional JSONB,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraint de unicidad
    UNIQUE(tipo_comprobante, establecimiento, punto_emision, secuencial)
);

COMMENT ON TABLE comprobantes_electronicos IS 'Comprobantes electrónicos emitidos al SRI';
COMMENT ON COLUMN comprobantes_electronicos.tipo_comprobante IS '01=Factura, 04=NotaCredito, 05=NotaDebito, 06=GuiaRemision, 07=Retencion';
COMMENT ON COLUMN comprobantes_electronicos.clave_acceso IS 'Clave de acceso de 49 dígitos generada con algoritmo Módulo 11';
COMMENT ON COLUMN comprobantes_electronicos.estado IS 'Estado del ciclo de vida del comprobante';

-- Índices para búsqueda eficiente
CREATE INDEX IF NOT EXISTS idx_comprobantes_estado ON comprobantes_electronicos(estado);
CREATE INDEX IF NOT EXISTS idx_comprobantes_clave ON comprobantes_electronicos(clave_acceso);
CREATE INDEX IF NOT EXISTS idx_comprobantes_fecha ON comprobantes_electronicos(fecha_emision);
CREATE INDEX IF NOT EXISTS idx_comprobantes_cliente ON comprobantes_electronicos(cliente_identificacion);
CREATE INDEX IF NOT EXISTS idx_comprobantes_tipo ON comprobantes_electronicos(tipo_comprobante);
CREATE INDEX IF NOT EXISTS idx_comprobantes_cliente_id ON comprobantes_electronicos(cliente_id);

-- =====================================================
-- TABLA: comprobante_detalles (Items de factura)
-- =====================================================
CREATE TABLE IF NOT EXISTS comprobante_detalles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comprobante_id UUID NOT NULL REFERENCES comprobantes_electronicos(id) ON DELETE CASCADE,

    -- Códigos del producto/servicio
    codigo_principal VARCHAR(25),
    codigo_auxiliar VARCHAR(25),

    -- Descripción y cantidades
    descripcion VARCHAR(300) NOT NULL,
    cantidad NUMERIC(14, 6) NOT NULL,
    precio_unitario NUMERIC(14, 6) NOT NULL,
    descuento NUMERIC(14, 2) NOT NULL DEFAULT 0,
    precio_total_sin_impuesto NUMERIC(14, 2) NOT NULL,

    -- Impuestos del detalle (array de objetos JSON)
    impuestos JSONB NOT NULL DEFAULT '[]',

    -- Información adicional del detalle
    detalles_adicionales JSONB,

    -- Orden de aparición en el comprobante
    orden INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE comprobante_detalles IS 'Líneas de detalle de cada comprobante';
COMMENT ON COLUMN comprobante_detalles.impuestos IS 'Array JSON con código, código porcentaje, tarifa, base imponible, valor';

CREATE INDEX IF NOT EXISTS idx_detalles_comprobante ON comprobante_detalles(comprobante_id);

-- =====================================================
-- TABLA: comprobante_pagos (Formas de pago)
-- =====================================================
CREATE TABLE IF NOT EXISTS comprobante_pagos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comprobante_id UUID NOT NULL REFERENCES comprobantes_electronicos(id) ON DELETE CASCADE,

    forma_pago VARCHAR(2) NOT NULL,
    total NUMERIC(14, 2) NOT NULL,
    plazo INTEGER,
    unidad_tiempo VARCHAR(20),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE comprobante_pagos IS 'Formas de pago de cada comprobante';
COMMENT ON COLUMN comprobante_pagos.forma_pago IS '01=SinSistemaFinanciero, 16=TarjetaDebito, 19=TarjetaCredito, 20=Otros';

CREATE INDEX IF NOT EXISTS idx_pagos_comprobante ON comprobante_pagos(comprobante_id);

-- =====================================================
-- TABLA: comprobante_retenciones (Para comprobantes de retención)
-- =====================================================
CREATE TABLE IF NOT EXISTS comprobante_retenciones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comprobante_id UUID NOT NULL REFERENCES comprobantes_electronicos(id) ON DELETE CASCADE,

    -- Documento sustento
    tipo_documento_sustento VARCHAR(2) NOT NULL,
    numero_documento_sustento VARCHAR(17) NOT NULL,
    fecha_emision_sustento DATE NOT NULL,

    -- Retención
    codigo_retencion VARCHAR(3) NOT NULL,
    tipo_retencion VARCHAR(20) NOT NULL, -- 'IR' o 'IVA'
    base_imponible NUMERIC(14, 2) NOT NULL,
    porcentaje_retencion NUMERIC(5, 2) NOT NULL,
    valor_retenido NUMERIC(14, 2) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE comprobante_retenciones IS 'Detalles de retención para comprobantes tipo 07';

CREATE INDEX IF NOT EXISTS idx_retenciones_comprobante ON comprobante_retenciones(comprobante_id);

-- =====================================================
-- TRIGGER: Actualizar timestamp
-- =====================================================
CREATE TRIGGER update_comprobantes_updated_at
    BEFORE UPDATE ON comprobantes_electronicos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- FUNCIÓN: Generar número de comprobante formateado
-- =====================================================
CREATE OR REPLACE FUNCTION format_numero_comprobante(
    p_establecimiento VARCHAR(3),
    p_punto_emision VARCHAR(3),
    p_secuencial INTEGER
)
RETURNS VARCHAR(17) AS $$
BEGIN
    RETURN p_establecimiento || '-' || p_punto_emision || '-' || LPAD(p_secuencial::TEXT, 9, '0');
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- FUNCIÓN: Validar clave de acceso
-- =====================================================
CREATE OR REPLACE FUNCTION validar_clave_acceso(p_clave VARCHAR(49))
RETURNS BOOLEAN AS $$
DECLARE
    v_base VARCHAR(48);
    v_digito_verificador INTEGER;
    v_suma INTEGER := 0;
    v_factor INTEGER;
    v_residuo INTEGER;
    v_resultado INTEGER;
    v_i INTEGER;
BEGIN
    -- Validar longitud
    IF LENGTH(p_clave) != 49 THEN
        RETURN FALSE;
    END IF;

    -- Extraer base (48 dígitos) y dígito verificador
    v_base := SUBSTRING(p_clave FROM 1 FOR 48);
    v_digito_verificador := SUBSTRING(p_clave FROM 49 FOR 1)::INTEGER;

    -- Calcular Módulo 11
    FOR v_i IN REVERSE 48..1 LOOP
        v_factor := ((48 - v_i) % 6) + 2;
        v_suma := v_suma + (SUBSTRING(v_base FROM v_i FOR 1)::INTEGER * v_factor);
    END LOOP;

    v_residuo := v_suma % 11;
    v_resultado := 11 - v_residuo;

    IF v_resultado = 11 THEN
        v_resultado := 0;
    ELSIF v_resultado = 10 THEN
        v_resultado := 1;
    END IF;

    RETURN v_resultado = v_digito_verificador;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION validar_clave_acceso IS 'Valida el dígito verificador de una clave de acceso usando Módulo 11';

-- =====================================================
-- VISTA: Resumen de comprobantes por estado
-- =====================================================
CREATE OR REPLACE VIEW v_comprobantes_resumen AS
SELECT
    tipo_comprobante,
    estado,
    DATE_TRUNC('month', fecha_emision) AS mes,
    COUNT(*) AS cantidad,
    SUM(importe_total) AS total
FROM comprobantes_electronicos
GROUP BY tipo_comprobante, estado, DATE_TRUNC('month', fecha_emision)
ORDER BY mes DESC, tipo_comprobante, estado;

COMMENT ON VIEW v_comprobantes_resumen IS 'Resumen mensual de comprobantes por tipo y estado';

-- =====================================================
-- VISTA: Comprobantes pendientes de autorización
-- =====================================================
CREATE OR REPLACE VIEW v_comprobantes_pendientes AS
SELECT
    id,
    tipo_comprobante,
    establecimiento || '-' || punto_emision || '-' || secuencial AS numero,
    clave_acceso,
    fecha_emision,
    cliente_razon_social,
    importe_total,
    estado,
    intentos_envio,
    ultimo_intento_at,
    mensajes_sri
FROM comprobantes_electronicos
WHERE estado IN ('pending', 'sent', 'received', 'error')
ORDER BY fecha_emision DESC, created_at DESC;

COMMENT ON VIEW v_comprobantes_pendientes IS 'Comprobantes que requieren atención (pendientes, con error, etc.)';
