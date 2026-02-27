-- ECUCONDOR - Tabla para tracking de emails de Produbanco procesados
-- Permite deduplicación y auditoría del daemon de auto-facturación P2P

CREATE TABLE IF NOT EXISTS gmail_facturas_procesadas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gmail_message_id VARCHAR(100) UNIQUE NOT NULL,
    deposito_monto DECIMAL(12,2) NOT NULL,
    deposito_remitente VARCHAR(300),
    deposito_fecha DATE,
    comprobante_id UUID REFERENCES comprobantes_electronicos(id),
    estado VARCHAR(20) NOT NULL DEFAULT 'procesado',
    error_detalle TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gmail_facturas_msg
    ON gmail_facturas_procesadas(gmail_message_id);

CREATE INDEX IF NOT EXISTS idx_gmail_facturas_fecha
    ON gmail_facturas_procesadas(deposito_fecha);
