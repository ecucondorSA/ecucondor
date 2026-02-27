-- =====================================================
-- MIGRACIÓN 008: CATÁLOGO DE PROVEEDORES
-- Sistema Contable Ecucondor
-- =====================================================

-- Tabla principal de proveedores
CREATE TABLE IF NOT EXISTS proveedores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    tipo_identificacion VARCHAR(2) NOT NULL DEFAULT '04',  -- 04=RUC, 05=Cedula, 06=Pasaporte
    identificacion VARCHAR(13) NOT NULL,
    razon_social VARCHAR(300) NOT NULL,
    nombre_comercial VARCHAR(300),

    -- Contacto
    direccion TEXT,
    email VARCHAR(100),
    telefono VARCHAR(20),

    -- Datos tributarios
    obligado_contabilidad BOOLEAN DEFAULT false,
    agente_retencion BOOLEAN DEFAULT false,
    contribuyente_especial VARCHAR(10),
    regimen_microempresas BOOLEAN DEFAULT false,
    rimpe BOOLEAN DEFAULT false,

    -- Retenciones por defecto
    porcentaje_retencion_renta_default DECIMAL(5,2) DEFAULT 1.00,  -- 1% por defecto
    porcentaje_retencion_iva_default DECIMAL(5,2) DEFAULT 30.00,   -- 30% del IVA

    -- Cuenta contable de gasto por defecto
    cuenta_gasto_default VARCHAR(20) REFERENCES cuentas_contables(codigo),

    -- Clasificación
    categoria VARCHAR(50),  -- servicios, bienes, financiero, etc.
    notas TEXT,

    -- Estado
    activo BOOLEAN DEFAULT true,

    -- Auditoría
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    created_by UUID,

    -- Constraints
    CONSTRAINT proveedores_tipo_id_check CHECK (tipo_identificacion IN ('04', '05', '06', '07', '08')),
    CONSTRAINT proveedores_identificacion_unique UNIQUE (tipo_identificacion, identificacion)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_proveedores_identificacion ON proveedores(identificacion);
CREATE INDEX IF NOT EXISTS idx_proveedores_razon_social ON proveedores(razon_social);
CREATE INDEX IF NOT EXISTS idx_proveedores_activo ON proveedores(activo);
CREATE INDEX IF NOT EXISTS idx_proveedores_categoria ON proveedores(categoria);

-- Trigger para actualizar updated_at
CREATE OR REPLACE FUNCTION update_proveedores_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_proveedores_updated_at ON proveedores;
CREATE TRIGGER trigger_proveedores_updated_at
    BEFORE UPDATE ON proveedores
    FOR EACH ROW
    EXECUTE FUNCTION update_proveedores_updated_at();

-- Comentarios
COMMENT ON TABLE proveedores IS 'Catálogo de proveedores para el módulo de compras';
COMMENT ON COLUMN proveedores.tipo_identificacion IS '04=RUC, 05=Cédula, 06=Pasaporte, 07=Consumidor Final, 08=Exterior';
COMMENT ON COLUMN proveedores.porcentaje_retencion_renta_default IS 'Porcentaje de retención IR por defecto al registrar compras';
COMMENT ON COLUMN proveedores.porcentaje_retencion_iva_default IS 'Porcentaje de retención IVA por defecto (sobre el IVA total)';
COMMENT ON COLUMN proveedores.cuenta_gasto_default IS 'Cuenta de gasto por defecto al registrar compras de este proveedor';

-- Datos iniciales de ejemplo (proveedores comunes)
INSERT INTO proveedores (tipo_identificacion, identificacion, razon_social, categoria, porcentaje_retencion_renta_default, notas)
VALUES
    ('04', '1790016919001', 'CORPORACION NACIONAL DE TELECOMUNICACIONES CNT EP', 'servicios', 2.00, 'Servicios de telecomunicaciones'),
    ('04', '1791251237001', 'EMPRESA ELECTRICA QUITO S.A.', 'servicios', 2.00, 'Servicios eléctricos'),
    ('04', '0992339411001', 'OTECEL S.A. (MOVISTAR)', 'servicios', 2.00, 'Telefonía móvil'),
    ('04', '1792060346001', 'CONECEL S.A. (CLARO)', 'servicios', 2.00, 'Telefonía móvil'),
    ('04', '1790010937001', 'BANCO PICHINCHA C.A.', 'financiero', 0.00, 'Servicios bancarios - No objeto IVA'),
    ('04', '1790053881001', 'PRODUBANCO S.A.', 'financiero', 0.00, 'Servicios bancarios - No objeto IVA'),
    ('04', '0990049459001', 'BANCO GUAYAQUIL S.A.', 'financiero', 0.00, 'Servicios bancarios - No objeto IVA')
ON CONFLICT (tipo_identificacion, identificacion) DO NOTHING;

-- =====================================================
-- TABLA DE FACTURAS RECIBIDAS (COMPRAS)
-- =====================================================

CREATE TABLE IF NOT EXISTS facturas_recibidas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Proveedor (puede ser referencia o datos directos)
    proveedor_id UUID REFERENCES proveedores(id),
    proveedor_tipo_id VARCHAR(2) NOT NULL,
    proveedor_identificacion VARCHAR(13) NOT NULL,
    proveedor_razon_social VARCHAR(300) NOT NULL,

    -- Documento
    tipo_comprobante VARCHAR(2) NOT NULL DEFAULT '01',  -- 01=Factura, 03=Liquidación
    establecimiento VARCHAR(3) NOT NULL,
    punto_emision VARCHAR(3) NOT NULL,
    secuencial VARCHAR(9) NOT NULL,
    clave_acceso VARCHAR(49),
    numero_autorizacion VARCHAR(49),
    fecha_emision DATE NOT NULL,
    fecha_autorizacion TIMESTAMPTZ,

    -- Montos con desglose de IVA
    subtotal_sin_impuestos DECIMAL(14,2) NOT NULL DEFAULT 0,
    subtotal_15 DECIMAL(14,2) DEFAULT 0,         -- Base gravada 15%
    subtotal_0 DECIMAL(14,2) DEFAULT 0,          -- Base 0%
    subtotal_no_objeto DECIMAL(14,2) DEFAULT 0,  -- No objeto de IVA
    subtotal_exento DECIMAL(14,2) DEFAULT 0,     -- Exento de IVA
    total_descuento DECIMAL(14,2) DEFAULT 0,
    iva DECIMAL(14,2) DEFAULT 0,
    total DECIMAL(14,2) NOT NULL,

    -- Tipo de gasto y crédito tributario
    tipo_gasto VARCHAR(30) DEFAULT 'operacional',  -- operacional, administrativo, financiero, activo_fijo
    genera_credito_tributario BOOLEAN DEFAULT true,
    porcentaje_credito DECIMAL(5,2) DEFAULT 100.00,  -- % del IVA que genera crédito
    cuenta_gasto VARCHAR(20) REFERENCES cuentas_contables(codigo),

    -- Retenciones aplicadas
    aplica_retencion_renta BOOLEAN DEFAULT true,
    porcentaje_retencion_renta DECIMAL(5,2) DEFAULT 1.00,
    retencion_renta DECIMAL(14,2) DEFAULT 0,

    aplica_retencion_iva BOOLEAN DEFAULT false,
    porcentaje_retencion_iva DECIMAL(5,2) DEFAULT 30.00,
    retencion_iva DECIMAL(14,2) DEFAULT 0,

    -- Valor neto a pagar
    valor_a_pagar DECIMAL(14,2) GENERATED ALWAYS AS (total - retencion_renta - retencion_iva) STORED,

    -- Estado
    estado VARCHAR(20) DEFAULT 'pendiente',  -- pendiente, contabilizada, pagada, anulada
    fecha_pago DATE,
    referencia_pago VARCHAR(100),

    -- Contabilización
    asiento_id UUID REFERENCES asientos_contables(id),
    comprobante_retencion_id UUID,  -- Referencia al comprobante de retención generado

    -- Documentos adjuntos
    xml_original TEXT,
    pdf_ride BYTEA,

    -- Metadata
    concepto TEXT,
    notas TEXT,
    info_adicional JSONB,

    -- Auditoría
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    created_by UUID,

    -- Constraints
    CONSTRAINT facturas_recibidas_tipo_check CHECK (tipo_comprobante IN ('01', '03', '04', '05')),
    CONSTRAINT facturas_recibidas_estado_check CHECK (estado IN ('pendiente', 'contabilizada', 'pagada', 'anulada')),
    CONSTRAINT facturas_recibidas_documento_unique UNIQUE (proveedor_identificacion, tipo_comprobante, establecimiento, punto_emision, secuencial)
);

-- Índices para facturas_recibidas
CREATE INDEX IF NOT EXISTS idx_facturas_recibidas_proveedor ON facturas_recibidas(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_facturas_recibidas_fecha ON facturas_recibidas(fecha_emision);
CREATE INDEX IF NOT EXISTS idx_facturas_recibidas_estado ON facturas_recibidas(estado);
CREATE INDEX IF NOT EXISTS idx_facturas_recibidas_clave_acceso ON facturas_recibidas(clave_acceso);
CREATE INDEX IF NOT EXISTS idx_facturas_recibidas_periodo ON facturas_recibidas(EXTRACT(YEAR FROM fecha_emision), EXTRACT(MONTH FROM fecha_emision));

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_facturas_recibidas_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_facturas_recibidas_updated_at ON facturas_recibidas;
CREATE TRIGGER trigger_facturas_recibidas_updated_at
    BEFORE UPDATE ON facturas_recibidas
    FOR EACH ROW
    EXECUTE FUNCTION update_facturas_recibidas_updated_at();

-- Comentarios
COMMENT ON TABLE facturas_recibidas IS 'Registro de facturas de proveedores (compras)';
COMMENT ON COLUMN facturas_recibidas.subtotal_15 IS 'Base imponible gravada con IVA 15%';
COMMENT ON COLUMN facturas_recibidas.subtotal_0 IS 'Base imponible gravada con IVA 0%';
COMMENT ON COLUMN facturas_recibidas.subtotal_no_objeto IS 'Monto no objeto de IVA (servicios financieros, etc.)';
COMMENT ON COLUMN facturas_recibidas.subtotal_exento IS 'Monto exento de IVA (salud, educación, etc.)';
COMMENT ON COLUMN facturas_recibidas.genera_credito_tributario IS 'Si el IVA de esta compra genera crédito tributario';
COMMENT ON COLUMN facturas_recibidas.porcentaje_credito IS 'Porcentaje del IVA que genera crédito (100% si es 100% relacionado con actividad gravada)';

-- =====================================================
-- TABLA DE DETALLES DE FACTURA RECIBIDA
-- =====================================================

CREATE TABLE IF NOT EXISTS factura_recibida_detalles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id UUID NOT NULL REFERENCES facturas_recibidas(id) ON DELETE CASCADE,

    -- Producto/Servicio
    codigo VARCHAR(50),
    descripcion TEXT NOT NULL,
    cantidad DECIMAL(14,4) NOT NULL DEFAULT 1,
    precio_unitario DECIMAL(14,4) NOT NULL,
    descuento DECIMAL(14,2) DEFAULT 0,
    precio_total DECIMAL(14,2) NOT NULL,

    -- IVA del item
    tipo_iva VARCHAR(20) DEFAULT 'gravado_15',  -- gravado_15, gravado_0, no_objeto, exento
    tarifa_iva DECIMAL(5,2) DEFAULT 15.00,
    valor_iva DECIMAL(14,2) DEFAULT 0,

    -- Orden
    orden INTEGER DEFAULT 0,

    -- Auditoría
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_factura_recibida_detalles_factura ON factura_recibida_detalles(factura_id);

COMMENT ON TABLE factura_recibida_detalles IS 'Líneas de detalle de facturas recibidas';
COMMENT ON COLUMN factura_recibida_detalles.tipo_iva IS 'Clasificación de IVA: gravado_15, gravado_0, no_objeto, exento';

-- =====================================================
-- VISTAS ÚTILES
-- =====================================================

-- Vista de proveedores con estadísticas
CREATE OR REPLACE VIEW v_proveedores_estadisticas AS
SELECT
    p.*,
    COALESCE(COUNT(f.id), 0) as total_facturas,
    COALESCE(SUM(f.total), 0) as total_compras,
    COALESCE(SUM(f.iva), 0) as total_iva_compras,
    MAX(f.fecha_emision) as ultima_compra
FROM proveedores p
LEFT JOIN facturas_recibidas f ON f.proveedor_id = p.id AND f.estado != 'anulada'
GROUP BY p.id;

-- Vista de facturas pendientes de pago
CREATE OR REPLACE VIEW v_facturas_recibidas_pendientes AS
SELECT
    f.*,
    p.razon_social as proveedor_nombre,
    p.categoria as proveedor_categoria,
    CURRENT_DATE - f.fecha_emision as dias_transcurridos
FROM facturas_recibidas f
LEFT JOIN proveedores p ON f.proveedor_id = p.id
WHERE f.estado IN ('pendiente', 'contabilizada')
ORDER BY f.fecha_emision;

-- Vista resumen de compras por mes
CREATE OR REPLACE VIEW v_resumen_compras_mes AS
SELECT
    EXTRACT(YEAR FROM fecha_emision) as anio,
    EXTRACT(MONTH FROM fecha_emision) as mes,
    COUNT(*) as total_facturas,
    SUM(subtotal_sin_impuestos) as total_subtotal,
    SUM(subtotal_15) as total_base_gravada,
    SUM(subtotal_0) as total_base_0,
    SUM(subtotal_no_objeto) as total_no_objeto,
    SUM(subtotal_exento) as total_exento,
    SUM(iva) as total_iva,
    SUM(CASE WHEN genera_credito_tributario THEN iva * porcentaje_credito / 100 ELSE 0 END) as credito_tributario,
    SUM(retencion_renta) as total_retencion_renta,
    SUM(retencion_iva) as total_retencion_iva,
    SUM(total) as total_compras
FROM facturas_recibidas
WHERE estado != 'anulada'
GROUP BY EXTRACT(YEAR FROM fecha_emision), EXTRACT(MONTH FROM fecha_emision)
ORDER BY anio DESC, mes DESC;

-- =====================================================
-- FIN MIGRACIÓN 008
-- =====================================================
