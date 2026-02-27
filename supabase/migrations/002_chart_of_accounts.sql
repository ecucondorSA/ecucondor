-- =====================================================
-- ECUCONDOR: MIGRACIÓN 002 - CATÁLOGO DE CUENTAS NIIF
-- Plan de Cuentas según Superintendencia de Compañías Ecuador
-- =====================================================

-- =====================================================
-- TABLA: cuentas_contables
-- =====================================================
CREATE TABLE IF NOT EXISTS cuentas_contables (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo VARCHAR(20) NOT NULL UNIQUE,
    nombre VARCHAR(300) NOT NULL,
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('activo', 'pasivo', 'patrimonio', 'ingreso', 'gasto')),
    subtipo VARCHAR(50),
    cuenta_padre_id UUID REFERENCES cuentas_contables(id),
    nivel INTEGER NOT NULL DEFAULT 1,
    permite_movimiento BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    descripcion TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE cuentas_contables IS 'Catálogo de cuentas contables NIIF Ecuador';

-- Índices
CREATE INDEX IF NOT EXISTS idx_cuentas_codigo ON cuentas_contables(codigo);
CREATE INDEX IF NOT EXISTS idx_cuentas_tipo ON cuentas_contables(tipo);
CREATE INDEX IF NOT EXISTS idx_cuentas_padre ON cuentas_contables(cuenta_padre_id);
CREATE INDEX IF NOT EXISTS idx_cuentas_nivel ON cuentas_contables(nivel);

-- =====================================================
-- INSERTAR CATÁLOGO DE CUENTAS PRINCIPALES
-- =====================================================

-- ===== 1. ACTIVOS =====
INSERT INTO cuentas_contables (codigo, nombre, tipo, nivel, permite_movimiento) VALUES
-- Nivel 1
('1', 'ACTIVO', 'activo', 1, FALSE),

-- Nivel 2 - Activo Corriente
('1.1', 'ACTIVO CORRIENTE', 'activo', 2, FALSE),

-- Nivel 3 - Efectivo y Equivalentes
('1.1.1', 'EFECTIVO Y EQUIVALENTES DE EFECTIVO', 'activo', 3, FALSE),
('1.1.1.01', 'Caja', 'activo', 4, TRUE),
('1.1.1.02', 'Bancos', 'activo', 4, TRUE),
('1.1.1.03', 'Inversiones Temporales', 'activo', 4, TRUE),

-- Nivel 3 - Cuentas por Cobrar
('1.1.2', 'CUENTAS Y DOCUMENTOS POR COBRAR', 'activo', 3, FALSE),
('1.1.2.01', 'Cuentas por Cobrar Clientes', 'activo', 4, TRUE),
('1.1.2.02', 'Documentos por Cobrar', 'activo', 4, TRUE),
('1.1.2.03', 'Provisión Cuentas Incobrables', 'activo', 4, TRUE),

-- Nivel 3 - Activos por Impuestos
('1.1.3', 'ACTIVOS POR IMPUESTOS CORRIENTES', 'activo', 3, FALSE),
('1.1.3.01', 'IVA en Compras (Crédito Tributario)', 'activo', 4, TRUE),
('1.1.3.02', 'Retenciones de IVA que le han sido efectuadas', 'activo', 4, TRUE),
('1.1.3.03', 'Retenciones de IR que le han sido efectuadas', 'activo', 4, TRUE),
('1.1.3.04', 'Anticipo Impuesto a la Renta', 'activo', 4, TRUE),

-- Nivel 3 - Otros Activos Corrientes
('1.1.9', 'OTROS ACTIVOS CORRIENTES', 'activo', 3, FALSE),
('1.1.9.01', 'Pagos Anticipados', 'activo', 4, TRUE),
('1.1.9.02', 'Anticipo a Proveedores', 'activo', 4, TRUE),

-- Nivel 2 - Activo No Corriente
('1.2', 'ACTIVO NO CORRIENTE', 'activo', 2, FALSE),
('1.2.1', 'PROPIEDAD, PLANTA Y EQUIPO', 'activo', 3, FALSE),
('1.2.1.01', 'Equipos de Computación', 'activo', 4, TRUE),
('1.2.1.02', 'Muebles y Enseres', 'activo', 4, TRUE),
('1.2.1.03', 'Depreciación Acumulada', 'activo', 4, TRUE),

('1.2.2', 'ACTIVOS INTANGIBLES', 'activo', 3, FALSE),
('1.2.2.01', 'Software', 'activo', 4, TRUE),
('1.2.2.02', 'Amortización Acumulada', 'activo', 4, TRUE)

ON CONFLICT (codigo) DO NOTHING;

-- ===== 2. PASIVOS =====
INSERT INTO cuentas_contables (codigo, nombre, tipo, nivel, permite_movimiento) VALUES
-- Nivel 1
('2', 'PASIVO', 'pasivo', 1, FALSE),

-- Nivel 2 - Pasivo Corriente
('2.1', 'PASIVO CORRIENTE', 'pasivo', 2, FALSE),

-- Nivel 3 - Cuentas por Pagar
('2.1.1', 'CUENTAS Y DOCUMENTOS POR PAGAR', 'pasivo', 3, FALSE),
('2.1.1.01', 'Cuentas por Pagar Proveedores', 'pasivo', 4, TRUE),
('2.1.1.02', 'Documentos por Pagar', 'pasivo', 4, TRUE),

-- Nivel 3 - Obligaciones Laborales
('2.1.2', 'OBLIGACIONES CON EMPLEADOS', 'pasivo', 3, FALSE),
('2.1.2.01', 'Obligaciones con el IESS', 'pasivo', 4, TRUE),
('2.1.2.02', 'Honorarios de Administración por Pagar', 'pasivo', 4, TRUE),
('2.1.2.03', 'Préstamos IESS por Pagar', 'pasivo', 4, TRUE),

-- Nivel 3 - Obligaciones Tributarias
('2.1.3', 'OBLIGACIONES CON LA ADMINISTRACIÓN TRIBUTARIA', 'pasivo', 3, FALSE),
('2.1.3.01', 'IVA en Ventas', 'pasivo', 4, TRUE),
('2.1.3.02', 'Retenciones de IVA por Pagar', 'pasivo', 4, TRUE),
('2.1.3.03', 'Retenciones de IR por Pagar', 'pasivo', 4, TRUE),
('2.1.3.04', 'Impuesto a la Renta por Pagar', 'pasivo', 4, TRUE),

-- Nivel 3 - Otras Obligaciones
('2.1.4', 'OTRAS OBLIGACIONES CORRIENTES', 'pasivo', 3, FALSE),
('2.1.4.01', 'Anticipo de Clientes', 'pasivo', 4, TRUE),

-- Nivel 3 - Fondos de Terceros (CRÍTICO PARA MODELO COMISIONISTA)
('2.1.5', 'FONDOS DE TERCEROS EN CUSTODIA', 'pasivo', 3, FALSE),
('2.1.5.01', 'Depósitos de Clientes (Fondos de Terceros)', 'pasivo', 4, TRUE),
('2.1.5.02', 'Pagos Pendientes a Contrapartes', 'pasivo', 4, TRUE),

-- Nivel 2 - Pasivo No Corriente
('2.2', 'PASIVO NO CORRIENTE', 'pasivo', 2, FALSE),
('2.2.1', 'OBLIGACIONES A LARGO PLAZO', 'pasivo', 3, FALSE),
('2.2.1.01', 'Préstamos Bancarios LP', 'pasivo', 4, TRUE)

ON CONFLICT (codigo) DO NOTHING;

-- ===== 3. PATRIMONIO =====
INSERT INTO cuentas_contables (codigo, nombre, tipo, nivel, permite_movimiento) VALUES
-- Nivel 1
('3', 'PATRIMONIO', 'patrimonio', 1, FALSE),

-- Nivel 2 - Capital
('3.1', 'CAPITAL', 'patrimonio', 2, FALSE),
('3.1.1', 'CAPITAL SOCIAL', 'patrimonio', 3, FALSE),
('3.1.1.01', 'Capital Suscrito y Pagado', 'patrimonio', 4, TRUE),
('3.1.1.02', 'Aportes Futuras Capitalizaciones', 'patrimonio', 4, TRUE),

-- Nivel 2 - Reservas
('3.2', 'RESERVAS', 'patrimonio', 2, FALSE),
('3.2.1', 'RESERVAS DE CAPITAL', 'patrimonio', 3, FALSE),
('3.2.1.01', 'Reserva Legal', 'patrimonio', 4, TRUE),
('3.2.1.02', 'Reserva Estatutaria', 'patrimonio', 4, TRUE),

-- Nivel 2 - Resultados
('3.3', 'RESULTADOS', 'patrimonio', 2, FALSE),
('3.3.1', 'RESULTADOS DEL EJERCICIO', 'patrimonio', 3, FALSE),
('3.3.1.01', 'Utilidad del Ejercicio', 'patrimonio', 4, TRUE),
('3.3.1.02', 'Pérdida del Ejercicio', 'patrimonio', 4, TRUE),
('3.3.2', 'RESULTADOS ACUMULADOS', 'patrimonio', 3, FALSE),
('3.3.2.01', 'Utilidades Acumuladas', 'patrimonio', 4, TRUE),
('3.3.2.02', 'Pérdidas Acumuladas', 'patrimonio', 4, TRUE)

ON CONFLICT (codigo) DO NOTHING;

-- ===== 4. INGRESOS =====
INSERT INTO cuentas_contables (codigo, nombre, tipo, nivel, permite_movimiento) VALUES
-- Nivel 1
('4', 'INGRESOS', 'ingreso', 1, FALSE),

-- Nivel 2 - Ingresos Operacionales
('4.1', 'INGRESOS OPERACIONALES', 'ingreso', 2, FALSE),
('4.1.1', 'INGRESOS POR SERVICIOS', 'ingreso', 3, FALSE),
('4.1.1.01', 'Ingresos por Comisión de Intermediación', 'ingreso', 4, TRUE),
('4.1.1.02', 'Ingresos por Honorarios Profesionales', 'ingreso', 4, TRUE),
('4.1.1.03', 'Ingresos por Servicios de Consultoría', 'ingreso', 4, TRUE),

-- Nivel 2 - Otros Ingresos
('4.2', 'OTROS INGRESOS', 'ingreso', 2, FALSE),
('4.2.1', 'INGRESOS NO OPERACIONALES', 'ingreso', 3, FALSE),
('4.2.1.01', 'Intereses Ganados', 'ingreso', 4, TRUE),
('4.2.1.02', 'Otros Ingresos', 'ingreso', 4, TRUE)

ON CONFLICT (codigo) DO NOTHING;

-- ===== 5. GASTOS =====
INSERT INTO cuentas_contables (codigo, nombre, tipo, nivel, permite_movimiento) VALUES
-- Nivel 1
('5', 'GASTOS', 'gasto', 1, FALSE),

-- Nivel 2 - Gastos Operacionales
('5.1', 'GASTOS OPERACIONALES', 'gasto', 2, FALSE),

-- Nivel 3 - Gastos de Personal (Honorarios Administrador)
('5.1.1', 'GASTOS DE ADMINISTRACIÓN', 'gasto', 3, FALSE),
('5.1.1.01', 'Honorarios de Administración', 'gasto', 4, TRUE),
('5.1.1.02', 'Aportes al IESS (Parte Patronal)', 'gasto', 4, TRUE),

-- Nivel 3 - Gastos de Servicios
('5.1.2', 'GASTOS POR SERVICIOS', 'gasto', 3, FALSE),
('5.1.2.01', 'Servicios Básicos (Luz, Agua, Internet)', 'gasto', 4, TRUE),
('5.1.2.02', 'Servicios Profesionales', 'gasto', 4, TRUE),
('5.1.2.03', 'Comisiones Bancarias', 'gasto', 4, TRUE),
('5.1.2.04', 'Comisiones Pasarela de Pago', 'gasto', 4, TRUE),
('5.1.2.05', 'Hosting y Servicios Cloud', 'gasto', 4, TRUE),
('5.1.2.06', 'Licencias de Software', 'gasto', 4, TRUE),
('5.1.2.07', 'Arrendamiento', 'gasto', 4, TRUE),
('5.1.2.08', 'Mantenimiento y Reparaciones', 'gasto', 4, TRUE),

-- Nivel 3 - Depreciación y Amortización
('5.1.3', 'DEPRECIACIONES Y AMORTIZACIONES', 'gasto', 3, FALSE),
('5.1.3.01', 'Depreciación Equipos de Computación', 'gasto', 4, TRUE),
('5.1.3.02', 'Depreciación Muebles y Enseres', 'gasto', 4, TRUE),
('5.1.3.03', 'Amortización Intangibles', 'gasto', 4, TRUE),

-- Nivel 3 - Gastos No Deducibles (Muralla China)
('5.1.4', 'GASTOS NO DEDUCIBLES', 'gasto', 3, FALSE),
('5.1.4.01', 'Gastos Personales No Deducibles', 'gasto', 4, TRUE),
('5.1.4.02', 'Gastos sin Comprobante Válido', 'gasto', 4, TRUE),
('5.1.4.03', 'Multas e Intereses SRI', 'gasto', 4, TRUE),

-- Nivel 2 - Gastos Financieros
('5.2', 'GASTOS FINANCIEROS', 'gasto', 2, FALSE),
('5.2.1', 'COSTOS FINANCIEROS', 'gasto', 3, FALSE),
('5.2.1.01', 'Intereses Pagados', 'gasto', 4, TRUE),
('5.2.1.02', 'Gastos Bancarios', 'gasto', 4, TRUE)

ON CONFLICT (codigo) DO NOTHING;

-- =====================================================
-- FUNCIÓN: Obtener saldo de cuenta
-- =====================================================
CREATE OR REPLACE FUNCTION get_saldo_cuenta(
    p_codigo_cuenta VARCHAR(20),
    p_fecha_inicio DATE DEFAULT NULL,
    p_fecha_fin DATE DEFAULT NULL
)
RETURNS NUMERIC AS $$
DECLARE
    v_tipo VARCHAR(20);
    v_saldo NUMERIC(14, 2);
BEGIN
    -- Obtener tipo de cuenta
    SELECT tipo INTO v_tipo
    FROM cuentas_contables
    WHERE codigo = p_codigo_cuenta;

    -- Calcular saldo según naturaleza de la cuenta
    -- Activos y Gastos: Debe - Haber (saldo deudor)
    -- Pasivos, Patrimonio e Ingresos: Haber - Debe (saldo acreedor)

    SELECT
        CASE
            WHEN v_tipo IN ('activo', 'gasto') THEN
                COALESCE(SUM(al.debe), 0) - COALESCE(SUM(al.haber), 0)
            ELSE
                COALESCE(SUM(al.haber), 0) - COALESCE(SUM(al.debe), 0)
        END INTO v_saldo
    FROM asiento_lineas al
    JOIN asientos_contables ac ON al.asiento_id = ac.id
    JOIN cuentas_contables cc ON al.cuenta_id = cc.id
    WHERE cc.codigo LIKE p_codigo_cuenta || '%'
      AND ac.estado = 'posted'
      AND (p_fecha_inicio IS NULL OR ac.fecha >= p_fecha_inicio)
      AND (p_fecha_fin IS NULL OR ac.fecha <= p_fecha_fin);

    RETURN COALESCE(v_saldo, 0);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_saldo_cuenta IS 'Obtiene el saldo de una cuenta (incluyendo subcuentas) en un rango de fechas';
