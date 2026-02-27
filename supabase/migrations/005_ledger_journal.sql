-- =====================================================
-- ECUCONDOR - Migración 005: Ledger Contable
-- Sistema de contabilidad de partida doble
-- =====================================================

-- =====================================================
-- TABLA: periodos_contables
-- Períodos contables (mensuales)
-- =====================================================

CREATE TABLE IF NOT EXISTS periodos_contables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    anio INTEGER NOT NULL,
    mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre VARCHAR(50) NOT NULL,  -- "Enero 2025"

    -- Fechas
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'abierto'
        CHECK (estado IN ('abierto', 'cerrado', 'ajuste')),
    fecha_cierre TIMESTAMPTZ,
    cerrado_por UUID,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(anio, mes)
);

COMMENT ON TABLE periodos_contables IS 'Períodos contables mensuales';

-- =====================================================
-- TABLA: asientos_contables
-- Libro diario - cabecera de asientos
-- =====================================================

CREATE TABLE IF NOT EXISTS asientos_contables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    numero_asiento SERIAL,
    fecha DATE NOT NULL,
    periodo_id UUID REFERENCES periodos_contables(id),

    -- Descripción
    concepto VARCHAR(500) NOT NULL,
    referencia VARCHAR(100),  -- Número de documento, factura, etc.

    -- Tipo de asiento
    tipo VARCHAR(30) NOT NULL DEFAULT 'normal'
        CHECK (tipo IN (
            'normal',           -- Asiento regular
            'apertura',         -- Asiento de apertura
            'cierre',           -- Asiento de cierre
            'ajuste',           -- Asiento de ajuste
            'reclasificacion',  -- Reclasificación
            'automatico'        -- Generado automáticamente
        )),

    -- Origen (trazabilidad)
    origen_tipo VARCHAR(30),  -- 'factura', 'transaccion', 'manual', etc.
    origen_id UUID,           -- ID del documento origen

    -- Totales (para verificación rápida)
    total_debe DECIMAL(14, 2) NOT NULL DEFAULT 0,
    total_haber DECIMAL(14, 2) NOT NULL DEFAULT 0,

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'borrador'
        CHECK (estado IN ('borrador', 'contabilizado', 'anulado')),

    -- Anulación
    anulado_at TIMESTAMPTZ,
    anulado_por UUID,
    motivo_anulacion TEXT,
    asiento_reverso_id UUID REFERENCES asientos_contables(id),

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    updated_by UUID,

    -- Verificación de cuadre
    CONSTRAINT chk_asiento_cuadrado CHECK (
        estado = 'borrador' OR total_debe = total_haber
    )
);

CREATE INDEX idx_asientos_fecha ON asientos_contables(fecha);
CREATE INDEX idx_asientos_periodo ON asientos_contables(periodo_id);
CREATE INDEX idx_asientos_numero ON asientos_contables(numero_asiento);
CREATE INDEX idx_asientos_origen ON asientos_contables(origen_tipo, origen_id);
CREATE INDEX idx_asientos_estado ON asientos_contables(estado);

COMMENT ON TABLE asientos_contables IS 'Libro diario - cabecera de asientos contables';
COMMENT ON COLUMN asientos_contables.origen_tipo IS 'Tipo de documento origen: factura, transaccion, manual';
COMMENT ON COLUMN asientos_contables.origen_id IS 'UUID del documento que originó el asiento';

-- =====================================================
-- TABLA: movimientos_contables
-- Líneas de detalle de asientos (debe/haber)
-- =====================================================

CREATE TABLE IF NOT EXISTS movimientos_contables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Relación con asiento
    asiento_id UUID NOT NULL REFERENCES asientos_contables(id) ON DELETE CASCADE,

    -- Cuenta contable
    cuenta_codigo VARCHAR(20) NOT NULL REFERENCES cuentas_contables(codigo),

    -- Montos (solo uno debe tener valor > 0)
    debe DECIMAL(14, 2) NOT NULL DEFAULT 0 CHECK (debe >= 0),
    haber DECIMAL(14, 2) NOT NULL DEFAULT 0 CHECK (haber >= 0),

    -- Descripción del movimiento
    concepto VARCHAR(300),

    -- Centro de costo (futuro)
    centro_costo VARCHAR(20),

    -- Referencia adicional
    referencia VARCHAR(100),

    -- Orden dentro del asiento
    orden INTEGER NOT NULL DEFAULT 0,

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Un movimiento debe tener debe O haber, no ambos
    CONSTRAINT chk_debe_o_haber CHECK (
        (debe > 0 AND haber = 0) OR (debe = 0 AND haber > 0)
    )
);

CREATE INDEX idx_movimientos_asiento ON movimientos_contables(asiento_id);
CREATE INDEX idx_movimientos_cuenta ON movimientos_contables(cuenta_codigo);
CREATE INDEX idx_movimientos_debe ON movimientos_contables(debe) WHERE debe > 0;
CREATE INDEX idx_movimientos_haber ON movimientos_contables(haber) WHERE haber > 0;

COMMENT ON TABLE movimientos_contables IS 'Líneas de detalle de asientos contables';

-- =====================================================
-- TABLA: saldos_cuentas
-- Saldos acumulados por cuenta y período
-- =====================================================

CREATE TABLE IF NOT EXISTS saldos_cuentas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identificación
    cuenta_codigo VARCHAR(20) NOT NULL REFERENCES cuentas_contables(codigo),
    periodo_id UUID NOT NULL REFERENCES periodos_contables(id),

    -- Saldos
    saldo_inicial DECIMAL(14, 2) NOT NULL DEFAULT 0,
    total_debe DECIMAL(14, 2) NOT NULL DEFAULT 0,
    total_haber DECIMAL(14, 2) NOT NULL DEFAULT 0,
    saldo_final DECIMAL(14, 2) NOT NULL DEFAULT 0,

    -- Cantidad de movimientos
    cantidad_movimientos INTEGER NOT NULL DEFAULT 0,

    -- Auditoría
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(cuenta_codigo, periodo_id)
);

CREATE INDEX idx_saldos_cuenta ON saldos_cuentas(cuenta_codigo);
CREATE INDEX idx_saldos_periodo ON saldos_cuentas(periodo_id);

COMMENT ON TABLE saldos_cuentas IS 'Saldos acumulados por cuenta y período contable';

-- =====================================================
-- TABLA: comisiones_split
-- Registro de splits de comisión por transacción
-- =====================================================

CREATE TABLE IF NOT EXISTS comisiones_split (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Origen
    transaccion_id UUID REFERENCES transacciones_bancarias(id),
    comprobante_id UUID REFERENCES comprobantes_electronicos(id),

    -- Montos
    monto_bruto DECIMAL(12, 2) NOT NULL,
    porcentaje_comision DECIMAL(5, 4) NOT NULL DEFAULT 0.015,  -- 1.5%

    monto_comision DECIMAL(12, 2) NOT NULL,      -- 1.5% ingreso
    monto_propietario DECIMAL(12, 2) NOT NULL,   -- 98.5% pasivo

    -- Asiento generado
    asiento_id UUID REFERENCES asientos_contables(id),

    -- Propietario del vehículo (futuro)
    propietario_id UUID,
    vehiculo_id UUID,

    -- Estado
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'contabilizado', 'pagado', 'anulado')),

    -- Pago al propietario
    fecha_pago TIMESTAMPTZ,
    referencia_pago VARCHAR(100),

    -- Auditoría
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_comisiones_transaccion ON comisiones_split(transaccion_id);
CREATE INDEX idx_comisiones_comprobante ON comisiones_split(comprobante_id);
CREATE INDEX idx_comisiones_estado ON comisiones_split(estado);
CREATE INDEX idx_comisiones_propietario ON comisiones_split(propietario_id);

COMMENT ON TABLE comisiones_split IS 'Registro de splits de comisión (1.5% ingreso / 98.5% pasivo)';

-- =====================================================
-- VISTA: v_libro_diario
-- Vista del libro diario con detalles
-- =====================================================

CREATE OR REPLACE VIEW v_libro_diario AS
SELECT
    a.id AS asiento_id,
    a.numero_asiento,
    a.fecha,
    a.concepto AS concepto_asiento,
    a.tipo,
    a.estado,
    a.referencia,
    m.id AS movimiento_id,
    m.cuenta_codigo,
    c.nombre AS cuenta_nombre,
    c.tipo AS cuenta_tipo,
    m.debe,
    m.haber,
    m.concepto AS concepto_movimiento,
    m.orden,
    p.nombre AS periodo
FROM asientos_contables a
JOIN movimientos_contables m ON m.asiento_id = a.id
JOIN cuentas_contables c ON c.codigo = m.cuenta_codigo
LEFT JOIN periodos_contables p ON p.id = a.periodo_id
WHERE a.estado != 'anulado'
ORDER BY a.fecha DESC, a.numero_asiento DESC, m.orden;

COMMENT ON VIEW v_libro_diario IS 'Vista del libro diario con detalle de movimientos';

-- =====================================================
-- VISTA: v_libro_mayor
-- Libro mayor por cuenta
-- =====================================================

CREATE OR REPLACE VIEW v_libro_mayor AS
SELECT
    m.cuenta_codigo,
    c.nombre AS cuenta_nombre,
    c.tipo AS cuenta_tipo,
    a.fecha,
    a.numero_asiento,
    a.concepto,
    m.debe,
    m.haber,
    SUM(m.debe - m.haber) OVER (
        PARTITION BY m.cuenta_codigo
        ORDER BY a.fecha, a.numero_asiento
    ) AS saldo_acumulado,
    a.id AS asiento_id
FROM movimientos_contables m
JOIN asientos_contables a ON a.id = m.asiento_id
JOIN cuentas_contables c ON c.codigo = m.cuenta_codigo
WHERE a.estado = 'contabilizado'
ORDER BY m.cuenta_codigo, a.fecha, a.numero_asiento;

COMMENT ON VIEW v_libro_mayor IS 'Libro mayor con saldo acumulado por cuenta';

-- =====================================================
-- VISTA: v_balance_comprobacion
-- Balance de comprobación por cuenta
-- =====================================================

CREATE OR REPLACE VIEW v_balance_comprobacion AS
SELECT
    c.codigo,
    c.nombre,
    c.tipo,
    c.naturaleza,
    COALESCE(SUM(m.debe), 0) AS total_debe,
    COALESCE(SUM(m.haber), 0) AS total_haber,
    COALESCE(SUM(m.debe), 0) - COALESCE(SUM(m.haber), 0) AS saldo
FROM cuentas_contables c
LEFT JOIN movimientos_contables m ON m.cuenta_codigo = c.codigo
LEFT JOIN asientos_contables a ON a.id = m.asiento_id AND a.estado = 'contabilizado'
WHERE c.es_movimiento = true
GROUP BY c.codigo, c.nombre, c.tipo, c.naturaleza
HAVING COALESCE(SUM(m.debe), 0) != 0 OR COALESCE(SUM(m.haber), 0) != 0
ORDER BY c.codigo;

COMMENT ON VIEW v_balance_comprobacion IS 'Balance de comprobación de sumas y saldos';

-- =====================================================
-- FUNCIÓN: crear_periodo_si_no_existe
-- Crea el período contable si no existe
-- =====================================================

CREATE OR REPLACE FUNCTION crear_periodo_si_no_existe(p_fecha DATE)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_periodo_id UUID;
    v_anio INTEGER;
    v_mes INTEGER;
    v_nombre VARCHAR(50);
    v_meses VARCHAR[] := ARRAY[
        'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
    ];
BEGIN
    v_anio := EXTRACT(YEAR FROM p_fecha);
    v_mes := EXTRACT(MONTH FROM p_fecha);
    v_nombre := v_meses[v_mes] || ' ' || v_anio;

    -- Buscar período existente
    SELECT id INTO v_periodo_id
    FROM periodos_contables
    WHERE anio = v_anio AND mes = v_mes;

    -- Crear si no existe
    IF v_periodo_id IS NULL THEN
        INSERT INTO periodos_contables (anio, mes, nombre, fecha_inicio, fecha_fin)
        VALUES (
            v_anio,
            v_mes,
            v_nombre,
            DATE_TRUNC('month', p_fecha)::DATE,
            (DATE_TRUNC('month', p_fecha) + INTERVAL '1 month' - INTERVAL '1 day')::DATE
        )
        RETURNING id INTO v_periodo_id;
    END IF;

    RETURN v_periodo_id;
END;
$$;

COMMENT ON FUNCTION crear_periodo_si_no_existe IS 'Crea el período contable del mes si no existe';

-- =====================================================
-- FUNCIÓN: contabilizar_asiento
-- Contabiliza un asiento y actualiza saldos
-- =====================================================

CREATE OR REPLACE FUNCTION contabilizar_asiento(p_asiento_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_asiento RECORD;
    v_total_debe DECIMAL(14, 2);
    v_total_haber DECIMAL(14, 2);
    v_periodo_id UUID;
BEGIN
    -- Obtener asiento
    SELECT * INTO v_asiento
    FROM asientos_contables
    WHERE id = p_asiento_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Asiento no encontrado: %', p_asiento_id;
    END IF;

    IF v_asiento.estado != 'borrador' THEN
        RAISE EXCEPTION 'El asiento no está en estado borrador';
    END IF;

    -- Calcular totales
    SELECT
        COALESCE(SUM(debe), 0),
        COALESCE(SUM(haber), 0)
    INTO v_total_debe, v_total_haber
    FROM movimientos_contables
    WHERE asiento_id = p_asiento_id;

    -- Verificar cuadre
    IF v_total_debe != v_total_haber THEN
        RAISE EXCEPTION 'El asiento no cuadra: Debe=% Haber=%', v_total_debe, v_total_haber;
    END IF;

    IF v_total_debe = 0 THEN
        RAISE EXCEPTION 'El asiento no tiene movimientos';
    END IF;

    -- Obtener o crear período
    v_periodo_id := crear_periodo_si_no_existe(v_asiento.fecha);

    -- Actualizar asiento
    UPDATE asientos_contables
    SET
        estado = 'contabilizado',
        periodo_id = v_periodo_id,
        total_debe = v_total_debe,
        total_haber = v_total_haber,
        updated_at = NOW()
    WHERE id = p_asiento_id;

    -- Actualizar saldos de cuentas
    INSERT INTO saldos_cuentas (cuenta_codigo, periodo_id, total_debe, total_haber, cantidad_movimientos)
    SELECT
        m.cuenta_codigo,
        v_periodo_id,
        SUM(m.debe),
        SUM(m.haber),
        COUNT(*)
    FROM movimientos_contables m
    WHERE m.asiento_id = p_asiento_id
    GROUP BY m.cuenta_codigo
    ON CONFLICT (cuenta_codigo, periodo_id) DO UPDATE SET
        total_debe = saldos_cuentas.total_debe + EXCLUDED.total_debe,
        total_haber = saldos_cuentas.total_haber + EXCLUDED.total_haber,
        cantidad_movimientos = saldos_cuentas.cantidad_movimientos + EXCLUDED.cantidad_movimientos,
        saldo_final = saldos_cuentas.saldo_inicial +
            (saldos_cuentas.total_debe + EXCLUDED.total_debe) -
            (saldos_cuentas.total_haber + EXCLUDED.total_haber),
        updated_at = NOW();

    RETURN TRUE;
END;
$$;

COMMENT ON FUNCTION contabilizar_asiento IS 'Contabiliza un asiento verificando cuadre y actualizando saldos';

-- =====================================================
-- FUNCIÓN: anular_asiento
-- Anula un asiento creando un asiento de reverso
-- =====================================================

CREATE OR REPLACE FUNCTION anular_asiento(
    p_asiento_id UUID,
    p_motivo TEXT,
    p_usuario_id UUID DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_asiento RECORD;
    v_nuevo_asiento_id UUID;
BEGIN
    -- Obtener asiento original
    SELECT * INTO v_asiento
    FROM asientos_contables
    WHERE id = p_asiento_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Asiento no encontrado: %', p_asiento_id;
    END IF;

    IF v_asiento.estado = 'anulado' THEN
        RAISE EXCEPTION 'El asiento ya está anulado';
    END IF;

    -- Crear asiento de reverso
    INSERT INTO asientos_contables (
        fecha, concepto, tipo, referencia,
        origen_tipo, origen_id, estado, created_by
    )
    VALUES (
        CURRENT_DATE,
        'ANULACIÓN: ' || v_asiento.concepto,
        'ajuste',
        'REV-' || v_asiento.numero_asiento,
        'anulacion',
        p_asiento_id,
        'borrador',
        p_usuario_id
    )
    RETURNING id INTO v_nuevo_asiento_id;

    -- Copiar movimientos invertidos
    INSERT INTO movimientos_contables (
        asiento_id, cuenta_codigo, debe, haber, concepto, orden
    )
    SELECT
        v_nuevo_asiento_id,
        cuenta_codigo,
        haber,  -- Invertido
        debe,   -- Invertido
        'Reverso: ' || COALESCE(concepto, ''),
        orden
    FROM movimientos_contables
    WHERE asiento_id = p_asiento_id;

    -- Contabilizar asiento de reverso
    PERFORM contabilizar_asiento(v_nuevo_asiento_id);

    -- Marcar asiento original como anulado
    UPDATE asientos_contables
    SET
        estado = 'anulado',
        anulado_at = NOW(),
        anulado_por = p_usuario_id,
        motivo_anulacion = p_motivo,
        asiento_reverso_id = v_nuevo_asiento_id,
        updated_at = NOW()
    WHERE id = p_asiento_id;

    RETURN v_nuevo_asiento_id;
END;
$$;

COMMENT ON FUNCTION anular_asiento IS 'Anula un asiento creando asiento de reverso';

-- =====================================================
-- FUNCIÓN: obtener_saldo_cuenta
-- Obtiene el saldo actual de una cuenta
-- =====================================================

CREATE OR REPLACE FUNCTION obtener_saldo_cuenta(
    p_cuenta_codigo VARCHAR(20),
    p_fecha_hasta DATE DEFAULT CURRENT_DATE
)
RETURNS DECIMAL(14, 2)
LANGUAGE plpgsql
AS $$
DECLARE
    v_saldo DECIMAL(14, 2);
    v_cuenta RECORD;
BEGIN
    -- Obtener información de la cuenta
    SELECT * INTO v_cuenta
    FROM cuentas_contables
    WHERE codigo = p_cuenta_codigo;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    -- Calcular saldo según movimientos
    SELECT COALESCE(SUM(m.debe - m.haber), 0)
    INTO v_saldo
    FROM movimientos_contables m
    JOIN asientos_contables a ON a.id = m.asiento_id
    WHERE m.cuenta_codigo = p_cuenta_codigo
      AND a.estado = 'contabilizado'
      AND a.fecha <= p_fecha_hasta;

    -- Ajustar según naturaleza de la cuenta
    -- Cuentas de naturaleza acreedora tienen saldo positivo al haber
    IF v_cuenta.naturaleza = 'acreedora' THEN
        v_saldo := -v_saldo;
    END IF;

    RETURN v_saldo;
END;
$$;

COMMENT ON FUNCTION obtener_saldo_cuenta IS 'Obtiene el saldo actual de una cuenta a una fecha';

-- =====================================================
-- TRIGGERS
-- =====================================================

CREATE TRIGGER set_updated_at_asientos
    BEFORE UPDATE ON asientos_contables
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_periodos
    BEFORE UPDATE ON periodos_contables
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at_comisiones
    BEFORE UPDATE ON comisiones_split
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_updated_at();

-- =====================================================
-- RLS: Row Level Security
-- =====================================================

ALTER TABLE periodos_contables ENABLE ROW LEVEL SECURITY;
ALTER TABLE asientos_contables ENABLE ROW LEVEL SECURITY;
ALTER TABLE movimientos_contables ENABLE ROW LEVEL SECURITY;
ALTER TABLE saldos_cuentas ENABLE ROW LEVEL SECURITY;
ALTER TABLE comisiones_split ENABLE ROW LEVEL SECURITY;

-- Políticas permisivas para service role
CREATE POLICY "Service role full access periodos"
    ON periodos_contables FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access asientos"
    ON asientos_contables FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access movimientos"
    ON movimientos_contables FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access saldos"
    ON saldos_cuentas FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access comisiones"
    ON comisiones_split FOR ALL USING (true) WITH CHECK (true);

-- =====================================================
-- DATOS INICIALES: Período actual
-- =====================================================

SELECT crear_periodo_si_no_existe(CURRENT_DATE);
