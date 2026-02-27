-- =====================================================
-- ECUCONDOR: MIGRACIÓN 001 - SCHEMA INICIAL
-- Sistema de Contabilidad Automatizada para SAS Ecuador
-- =====================================================

-- Extensiones necesarias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =====================================================
-- TABLA: company_info (Información de la SAS)
-- =====================================================
CREATE TABLE IF NOT EXISTS company_info (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ruc VARCHAR(13) NOT NULL UNIQUE,
    razon_social VARCHAR(300) NOT NULL,
    nombre_comercial VARCHAR(300),
    direccion_matriz TEXT NOT NULL,
    obligado_contabilidad BOOLEAN NOT NULL DEFAULT TRUE,
    contribuyente_especial VARCHAR(10),
    agente_retencion VARCHAR(10),
    regimen_microempresas BOOLEAN DEFAULT FALSE,
    rimpe BOOLEAN DEFAULT FALSE,
    ambiente_sri VARCHAR(1) NOT NULL DEFAULT '1' CHECK (ambiente_sri IN ('1', '2')),
    tipo_emision VARCHAR(1) NOT NULL DEFAULT '1',
    email_notificacion VARCHAR(300),
    telefono VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE company_info IS 'Información de la empresa SAS para facturación electrónica';
COMMENT ON COLUMN company_info.ambiente_sri IS '1=Pruebas (celcer.sri.gob.ec), 2=Producción (cel.sri.gob.ec)';
COMMENT ON COLUMN company_info.tipo_emision IS '1=Emisión Normal';

-- =====================================================
-- TABLA: establecimientos
-- =====================================================
CREATE TABLE IF NOT EXISTS establecimientos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES company_info(id) ON DELETE CASCADE,
    codigo VARCHAR(3) NOT NULL,
    direccion TEXT NOT NULL,
    nombre_comercial VARCHAR(300),
    is_matriz BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, codigo)
);

COMMENT ON TABLE establecimientos IS 'Establecimientos de la empresa (001, 002, etc.)';

-- =====================================================
-- TABLA: puntos_emision
-- =====================================================
CREATE TABLE IF NOT EXISTS puntos_emision (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    establecimiento_id UUID NOT NULL REFERENCES establecimientos(id) ON DELETE CASCADE,
    codigo VARCHAR(3) NOT NULL,
    descripcion VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(establecimiento_id, codigo)
);

COMMENT ON TABLE puntos_emision IS 'Puntos de emisión dentro de cada establecimiento';

-- =====================================================
-- TABLA: secuenciales
-- =====================================================
CREATE TABLE IF NOT EXISTS secuenciales (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    punto_emision_id UUID NOT NULL REFERENCES puntos_emision(id) ON DELETE CASCADE,
    tipo_comprobante VARCHAR(2) NOT NULL,
    ultimo_secuencial INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(punto_emision_id, tipo_comprobante)
);

COMMENT ON TABLE secuenciales IS 'Control de secuenciales por tipo de comprobante';
COMMENT ON COLUMN secuenciales.tipo_comprobante IS '01=Factura, 04=NotaCredito, 05=NotaDebito, 06=GuiaRemision, 07=Retencion';

-- =====================================================
-- TABLA: clientes
-- =====================================================
CREATE TABLE IF NOT EXISTS clientes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tipo_identificacion VARCHAR(2) NOT NULL,
    identificacion VARCHAR(20) NOT NULL,
    razon_social VARCHAR(300) NOT NULL,
    direccion TEXT,
    email VARCHAR(300),
    telefono VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    -- UAFE tracking
    requiere_resu BOOLEAN DEFAULT FALSE,
    notas TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tipo_identificacion, identificacion)
);

COMMENT ON TABLE clientes IS 'Clientes para facturación';
COMMENT ON COLUMN clientes.tipo_identificacion IS '04=RUC, 05=Cedula, 06=Pasaporte, 07=ConsumidorFinal, 08=Exterior';
COMMENT ON COLUMN clientes.requiere_resu IS 'TRUE si el cliente supera umbral UAFE en algún mes';

-- Índices para búsqueda rápida
CREATE INDEX IF NOT EXISTS idx_clientes_identificacion ON clientes(identificacion);
CREATE INDEX IF NOT EXISTS idx_clientes_razon_social ON clientes(razon_social);

-- =====================================================
-- FUNCIÓN: Actualizar timestamp automáticamente
-- =====================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers para updated_at
CREATE TRIGGER update_company_info_updated_at
    BEFORE UPDATE ON company_info
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_clientes_updated_at
    BEFORE UPDATE ON clientes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_secuenciales_updated_at
    BEFORE UPDATE ON secuenciales
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- FUNCIÓN: Obtener siguiente secuencial
-- =====================================================
CREATE OR REPLACE FUNCTION get_next_secuencial(
    p_punto_emision_id UUID,
    p_tipo_comprobante VARCHAR(2)
)
RETURNS INTEGER AS $$
DECLARE
    v_secuencial INTEGER;
BEGIN
    -- Insertar si no existe, actualizar si existe
    INSERT INTO secuenciales (punto_emision_id, tipo_comprobante, ultimo_secuencial)
    VALUES (p_punto_emision_id, p_tipo_comprobante, 1)
    ON CONFLICT (punto_emision_id, tipo_comprobante)
    DO UPDATE SET
        ultimo_secuencial = secuenciales.ultimo_secuencial + 1,
        updated_at = NOW()
    RETURNING ultimo_secuencial INTO v_secuencial;

    RETURN v_secuencial;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_next_secuencial IS 'Obtiene el siguiente número secuencial atómicamente';
