-- =====================================================
-- ECUCONDOR - Migración 004: Transacciones Bancarias
-- Tablas para el ingestor financiero
-- =====================================================

-- =====================================================
-- TABLA: transacciones_bancarias
-- Almacena movimientos importados de extractos bancarios
-- =====================================================

CREATE TABLE IF NOT EXISTS transacciones_bancarias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación única (para deduplicación)
    hash_unico VARCHAR(16) NOT NULL UNIQUE,

    -- Origen
    banco VARCHAR(20) NOT NULL,
    cuenta_bancaria VARCHAR(30) NOT NULL,
    archivo_origen VARCHAR(255),
    linea_origen INTEGER,

    -- Datos de la transacción
    fecha DATE NOT NULL,
    fecha_valor DATE,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('credito', 'debito')),
    origen VARCHAR(30) NOT NULL DEFAULT 'otro',

    -- Montos
    monto DECIMAL(12, 2) NOT NULL CHECK (monto >= 0),
    saldo DECIMAL(14, 2),

    -- Descripción
    descripcion_original TEXT NOT NULL,
    descripcion_normalizada TEXT,
    referencia VARCHAR(100),
    numero_documento VARCHAR(100),

    -- Contraparte
    contraparte_nombre VARCHAR(300),
    contraparte_identificacion VARCHAR(13),
    contraparte_banco VARCHAR(50),
    contraparte_cuenta VARCHAR(30),

    -- Estado y conciliación
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'conciliada', 'duplicada', 'descartada', 'error')),
    comprobante_id UUID REFERENCES comprobantes_electronicos(id),
    asiento_id UUID,  -- Referencia futura a asientos contables

    -- Categorización automática
    categoria_sugerida VARCHAR(50),
    cuenta_contable_sugerida VARCHAR(20),
    confianza_categoria DECIMAL(3, 2) CHECK (confianza_categoria BETWEEN 0 AND 1),

    -- Metadatos
    datos_originales JSONB,
    notas TEXT,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_by UUID
);

-- Índices para búsquedas frecuentes
CREATE INDEX idx_transacciones_fecha ON transacciones_bancarias(fecha);
CREATE INDEX idx_transacciones_banco_cuenta ON transacciones_bancarias(banco, cuenta_bancaria);
CREATE INDEX idx_transacciones_estado ON transacciones_bancarias(estado);
CREATE INDEX idx_transacciones_comprobante ON transacciones_bancarias(comprobante_id);
CREATE INDEX idx_transacciones_hash ON transacciones_bancarias(hash_unico);
CREATE INDEX idx_transacciones_monto ON transacciones_bancarias(monto);
CREATE INDEX idx_transacciones_contraparte ON transacciones_bancarias(contraparte_identificacion);

-- Índice para búsqueda full-text en descripciones
CREATE INDEX idx_transacciones_descripcion_gin ON transacciones_bancarias
    USING GIN (to_tsvector('spanish', descripcion_original));

-- Comentarios
COMMENT ON TABLE transacciones_bancarias IS 'Movimientos bancarios importados de extractos CSV/Excel';
COMMENT ON COLUMN transacciones_bancarias.hash_unico IS 'Hash SHA-256 truncado para deduplicación';
COMMENT ON COLUMN transacciones_bancarias.origen IS 'Tipo de origen: transferencia, deposito, retiro, cheque, etc.';
COMMENT ON COLUMN transacciones_bancarias.confianza_categoria IS 'Nivel de confianza de la categorización automática (0-1)';

-- =====================================================
-- TABLA: cuentas_bancarias
-- Registro de cuentas bancarias de la empresa
-- =====================================================

CREATE TABLE IF NOT EXISTS cuentas_bancarias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    banco VARCHAR(20) NOT NULL,
    numero_cuenta VARCHAR(30) NOT NULL,
    tipo_cuenta VARCHAR(20) NOT NULL CHECK (tipo_cuenta IN ('corriente', 'ahorros')),

    -- Descripción
    alias VARCHAR(100),
    moneda CHAR(3) NOT NULL DEFAULT 'USD',

    -- Estado
    activa BOOLEAN NOT NULL DEFAULT true,
    es_principal BOOLEAN NOT NULL DEFAULT false,

    -- Contabilidad
    cuenta_contable VARCHAR(20) REFERENCES cuentas_contables(codigo),

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(banco, numero_cuenta)
);

COMMENT ON TABLE cuentas_bancarias IS 'Cuentas bancarias de la empresa para conciliación';

-- =====================================================
-- TABLA: importaciones_extractos
-- Log de importaciones de extractos bancarios
-- =====================================================

CREATE TABLE IF NOT EXISTS importaciones_extractos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Archivo
    nombre_archivo VARCHAR(255) NOT NULL,
    tamano_bytes INTEGER,
    checksum_md5 VARCHAR(32),

    -- Origen
    banco VARCHAR(20) NOT NULL,
    cuenta_bancaria VARCHAR(30) NOT NULL,

    -- Resultados
    total_lineas INTEGER NOT NULL DEFAULT 0,
    transacciones_nuevas INTEGER NOT NULL DEFAULT 0,
    transacciones_duplicadas INTEGER NOT NULL DEFAULT 0,
    transacciones_error INTEGER NOT NULL DEFAULT 0,

    -- Montos
    monto_total_creditos DECIMAL(14, 2) NOT NULL DEFAULT 0,
    monto_total_debitos DECIMAL(14, 2) NOT NULL DEFAULT 0,

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'procesando'
        CHECK (estado IN ('procesando', 'completado', 'error', 'parcial')),
    errores JSONB,
    advertencias JSONB,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX idx_importaciones_fecha ON importaciones_extractos(created_at);
CREATE INDEX idx_importaciones_banco ON importaciones_extractos(banco, cuenta_bancaria);

COMMENT ON TABLE importaciones_extractos IS 'Log de importaciones de extractos bancarios';

-- =====================================================
-- TABLA: reglas_categorizacion
-- Reglas personalizables para categorización automática
-- =====================================================

CREATE TABLE IF NOT EXISTS reglas_categorizacion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,

    -- Condiciones (patron regex)
    patron_descripcion VARCHAR(500),
    tipo_transaccion VARCHAR(10) CHECK (tipo_transaccion IN ('credito', 'debito')),
    monto_minimo DECIMAL(12, 2),
    monto_maximo DECIMAL(12, 2),

    -- Resultado
    categoria VARCHAR(50) NOT NULL,
    cuenta_contable VARCHAR(20) REFERENCES cuentas_contables(codigo),
    confianza DECIMAL(3, 2) NOT NULL DEFAULT 0.8 CHECK (confianza BETWEEN 0 AND 1),

    -- Prioridad y estado
    prioridad INTEGER NOT NULL DEFAULT 100,
    activa BOOLEAN NOT NULL DEFAULT true,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reglas_activas ON reglas_categorizacion(activa, prioridad);

COMMENT ON TABLE reglas_categorizacion IS 'Reglas personalizables para categorización automática de transacciones';

-- =====================================================
-- VISTA: v_transacciones_pendientes
-- Transacciones pendientes de conciliación
-- =====================================================

CREATE OR REPLACE VIEW v_transacciones_pendientes AS
SELECT
    t.id,
    t.fecha,
    t.banco,
    t.cuenta_bancaria,
    t.tipo,
    t.origen,
    t.monto,
    t.descripcion_normalizada,
    t.contraparte_nombre,
    t.contraparte_identificacion,
    t.categoria_sugerida,
    t.cuenta_contable_sugerida,
    t.confianza_categoria,
    t.created_at
FROM transacciones_bancarias t
WHERE t.estado = 'pendiente'
ORDER BY t.fecha DESC, t.monto DESC;

COMMENT ON VIEW v_transacciones_pendientes IS 'Transacciones pendientes de conciliación';

-- =====================================================
-- VISTA: v_resumen_banco_mes
-- Resumen mensual por banco
-- =====================================================

CREATE OR REPLACE VIEW v_resumen_banco_mes AS
SELECT
    banco,
    cuenta_bancaria,
    DATE_TRUNC('month', fecha) AS mes,
    COUNT(*) AS total_transacciones,
    COUNT(*) FILTER (WHERE tipo = 'credito') AS total_creditos,
    COUNT(*) FILTER (WHERE tipo = 'debito') AS total_debitos,
    COALESCE(SUM(monto) FILTER (WHERE tipo = 'credito'), 0) AS monto_creditos,
    COALESCE(SUM(monto) FILTER (WHERE tipo = 'debito'), 0) AS monto_debitos,
    COUNT(*) FILTER (WHERE estado = 'conciliada') AS conciliadas,
    COUNT(*) FILTER (WHERE estado = 'pendiente') AS pendientes
FROM transacciones_bancarias
WHERE estado NOT IN ('duplicada', 'descartada')
GROUP BY banco, cuenta_bancaria, DATE_TRUNC('month', fecha)
ORDER BY mes DESC, banco, cuenta_bancaria;

COMMENT ON VIEW v_resumen_banco_mes IS 'Resumen mensual de transacciones por banco y cuenta';

-- =====================================================
-- FUNCIÓN: buscar_hashes_existentes
-- Busca hashes existentes para deduplicación
-- =====================================================

CREATE OR REPLACE FUNCTION buscar_hashes_existentes(
    p_hashes TEXT[]
)
RETURNS TABLE (hash_unico VARCHAR(16))
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT t.hash_unico
    FROM transacciones_bancarias t
    WHERE t.hash_unico = ANY(p_hashes);
END;
$$;

COMMENT ON FUNCTION buscar_hashes_existentes IS 'Busca hashes existentes para deduplicación masiva';

-- =====================================================
-- FUNCIÓN: obtener_candidatos_conciliacion
-- Obtiene comprobantes candidatos para conciliar
-- =====================================================

CREATE OR REPLACE FUNCTION obtener_candidatos_conciliacion(
    p_monto DECIMAL(12, 2),
    p_fecha DATE,
    p_identificacion VARCHAR(13) DEFAULT NULL,
    p_tolerancia_monto DECIMAL(12, 2) DEFAULT 0.01,
    p_tolerancia_dias INTEGER DEFAULT 7
)
RETURNS TABLE (
    id UUID,
    tipo_comprobante VARCHAR(2),
    establecimiento VARCHAR(3),
    punto_emision VARCHAR(3),
    secuencial VARCHAR(9),
    clave_acceso VARCHAR(49),
    fecha_emision DATE,
    cliente_razon_social VARCHAR(300),
    cliente_identificacion VARCHAR(13),
    importe_total DECIMAL(12, 2),
    estado VARCHAR(20),
    diff_monto DECIMAL(12, 2),
    diff_dias INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.tipo_comprobante,
        c.establecimiento,
        c.punto_emision,
        c.secuencial,
        c.clave_acceso,
        c.fecha_emision,
        c.cliente_razon_social,
        c.cliente_identificacion,
        c.importe_total,
        c.estado,
        ABS(c.importe_total - p_monto) AS diff_monto,
        ABS(c.fecha_emision - p_fecha) AS diff_dias
    FROM comprobantes_electronicos c
    WHERE
        c.tipo_comprobante = '01'  -- Solo facturas
        AND c.estado = 'authorized'  -- Solo autorizadas
        AND ABS(c.importe_total - p_monto) <= p_tolerancia_monto
        AND ABS(c.fecha_emision - p_fecha) <= p_tolerancia_dias
        AND (p_identificacion IS NULL OR c.cliente_identificacion = p_identificacion)
        AND NOT EXISTS (
            -- Excluir ya conciliadas
            SELECT 1 FROM transacciones_bancarias t
            WHERE t.comprobante_id = c.id AND t.estado = 'conciliada'
        )
    ORDER BY
        diff_monto ASC,
        diff_dias ASC
    LIMIT 10;
END;
$$;

COMMENT ON FUNCTION obtener_candidatos_conciliacion IS 'Obtiene comprobantes candidatos para conciliación automática';

-- =====================================================
-- TRIGGER: actualizar_updated_at
-- Actualiza timestamp de modificación
-- =====================================================

CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_updated_at_transacciones
    BEFORE UPDATE ON transacciones_bancarias
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_cuentas_bancarias
    BEFORE UPDATE ON cuentas_bancarias
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_reglas_categorizacion
    BEFORE UPDATE ON reglas_categorizacion
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

-- =====================================================
-- DATOS INICIALES: Reglas de categorización
-- =====================================================

INSERT INTO reglas_categorizacion (nombre, patron_descripcion, tipo_transaccion, categoria, cuenta_contable, confianza, prioridad)
VALUES
    -- Ingresos
    ('Pago DataFast', 'datafast|medianet', 'credito', 'ingreso_tarjeta', '4.1.01', 0.95, 10),
    ('Transferencia recibida', 'transf.*recib|ach.*entran|spi.*entrada', 'credito', 'transferencia_entrada', '1.1.03', 0.70, 50),

    -- Gastos operacionales
    ('Combustible', 'gasolina|combustible|petroecuador|primax|mobil|shell', 'debito', 'gasto_combustible', '5.2.05', 0.95, 10),
    ('Mantenimiento vehículos', 'taller|mecanica|repuesto|llanta|lubricante', 'debito', 'gasto_mantenimiento', '5.2.06', 0.90, 20),
    ('Seguros', 'seguro|aseguradora|poliza|prima', 'debito', 'gasto_seguro', '5.2.07', 0.90, 20),

    -- Gastos administrativos
    ('Servicios básicos', 'luz|agua|telefono|internet|cnt|claro|movistar', 'debito', 'gasto_servicios', '5.2.03', 0.90, 30),
    ('Comisiones bancarias', 'comision|costo.*mensual|mantenimiento.*cuenta', 'debito', 'gasto_bancario', '5.3.02', 0.95, 10),

    -- Impuestos
    ('ISD', 'isd|impuesto.*salida.*divisas', 'debito', 'impuesto_isd', '5.3.03', 0.95, 10),
    ('GMT', 'gmt|gravamen.*movimiento', 'debito', 'impuesto_gmt', '5.3.03', 0.95, 10),
    ('Pago SRI', 'sri|servicio.*rentas|formulario', 'debito', 'pago_impuesto_sri', '2.1.05', 0.90, 20),

    -- Nómina
    ('Pago IESS', 'iess|seguro.*social|aporte.*patronal', 'debito', 'pago_iess', '2.1.06', 0.95, 10)
ON CONFLICT DO NOTHING;

-- =====================================================
-- RLS: Row Level Security
-- =====================================================

ALTER TABLE transacciones_bancarias ENABLE ROW LEVEL SECURITY;
ALTER TABLE cuentas_bancarias ENABLE ROW LEVEL SECURITY;
ALTER TABLE importaciones_extractos ENABLE ROW LEVEL SECURITY;
ALTER TABLE reglas_categorizacion ENABLE ROW LEVEL SECURITY;

-- Políticas permisivas para service role
CREATE POLICY "Service role full access transacciones"
    ON transacciones_bancarias FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service role full access cuentas_bancarias"
    ON cuentas_bancarias FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service role full access importaciones"
    ON importaciones_extractos FOR ALL
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service role full access reglas"
    ON reglas_categorizacion FOR ALL
    USING (true)
    WITH CHECK (true);
