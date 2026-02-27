"""
ECUCONDOR - Constantes del Sistema
Valores fijos que no dependen de configuración.
"""

from enum import Enum


# ===== TIPOS DE COMPROBANTE SRI =====
class TipoComprobante(str, Enum):
    """Códigos de tipo de comprobante electrónico del SRI."""

    FACTURA = "01"
    LIQUIDACION_COMPRA = "03"
    NOTA_CREDITO = "04"
    NOTA_DEBITO = "05"
    GUIA_REMISION = "06"
    RETENCION = "07"


# ===== TIPOS DE IDENTIFICACIÓN =====
class TipoIdentificacion(str, Enum):
    """Códigos de tipo de identificación del SRI."""

    RUC = "04"
    CEDULA = "05"
    PASAPORTE = "06"
    CONSUMIDOR_FINAL = "07"
    EXTERIOR = "08"


# ===== FORMAS DE PAGO =====
class FormaPago(str, Enum):
    """Códigos de forma de pago del SRI."""

    SIN_SISTEMA_FINANCIERO = "01"
    COMPENSACION = "15"
    TARJETA_DEBITO = "16"
    DINERO_ELECTRONICO = "17"
    TARJETA_PREPAGO = "18"
    TARJETA_CREDITO = "19"
    OTROS = "20"
    ENDOSO_TITULOS = "21"


# ===== CÓDIGOS DE IMPUESTO =====
class CodigoImpuesto(str, Enum):
    """Códigos de impuesto del SRI."""

    IVA = "2"
    ICE = "3"
    IRBPNR = "5"  # Impuesto Redimible Botellas Plásticas


# ===== CÓDIGOS DE PORCENTAJE IVA =====
class CodigoPorcentajeIVA(str, Enum):
    """Códigos de porcentaje IVA del SRI."""

    IVA_0 = "0"
    IVA_12 = "2"
    IVA_14 = "3"
    IVA_15 = "4"
    NO_OBJETO = "6"
    EXENTO = "7"
    IVA_5 = "5"
    IVA_8 = "8"


# Mapeo de código a porcentaje
PORCENTAJE_IVA_MAP = {
    CodigoPorcentajeIVA.IVA_0: 0.0,
    CodigoPorcentajeIVA.IVA_5: 5.0,
    CodigoPorcentajeIVA.IVA_8: 8.0,
    CodigoPorcentajeIVA.IVA_12: 12.0,
    CodigoPorcentajeIVA.IVA_14: 14.0,
    CodigoPorcentajeIVA.IVA_15: 15.0,
    CodigoPorcentajeIVA.NO_OBJETO: 0.0,
    CodigoPorcentajeIVA.EXENTO: 0.0,
}


# ===== ESTADOS DE COMPROBANTE =====
class EstadoComprobante(str, Enum):
    """Estados del ciclo de vida de un comprobante electrónico."""

    DRAFT = "draft"           # Borrador
    PENDING = "pending"       # Pendiente de envío
    SENT = "sent"             # Enviado al SRI
    RECEIVED = "received"     # Recibido por SRI (PPR)
    AUTHORIZED = "authorized" # Autorizado (AUT)
    REJECTED = "rejected"     # Rechazado (NAT)
    CANCELLED = "cancelled"   # Anulado
    ERROR = "error"           # Error de sistema


# ===== CATEGORÍAS DE GASTO =====
class CategoriaGasto(str, Enum):
    """Categorías de gasto para el ledger contable."""

    OPERATIONAL = "OPERATIONAL"       # Gastos operacionales deducibles
    ADMIN_FEE = "ADMIN_FEE"           # Honorarios administrador
    NON_DEDUCTIBLE = "NON_DEDUCTIBLE" # No deducibles
    PERSONAL = "PERSONAL"             # Gastos personales (Muralla China)


# ===== MCC BLOQUEADOS (Muralla China) =====
# Merchant Category Codes que se marcan automáticamente como NON_DEDUCTIBLE
MCC_BLOQUEADOS = {
    "5812": "Restaurantes",
    "5813": "Bares y Tabernas",
    "5814": "Fast Food",
    "5411": "Supermercados",
    "5912": "Farmacias",
    "5941": "Artículos Deportivos",
    "5942": "Librerías",
    "5943": "Papelerías",
    "5944": "Joyerías",
    "5945": "Jugueterías",
    "5946": "Cámaras y Fotografía",
    "5947": "Regalos y Souvenirs",
    "5948": "Artículos de Cuero",
    "5949": "Telas y Costura",
    "5735": "Discos y Música",
    "5815": "Streaming Digital",
    "5816": "Juegos Digitales",
    "5817": "Aplicaciones Digitales",
    "5818": "Suscripciones Digitales",
    "7832": "Cines",
    "7841": "Video Rental",
    "7911": "Salones de Baile",
    "7922": "Teatros",
    "7929": "Entretenimiento",
    "7932": "Billar",
    "7933": "Boliche",
    "7941": "Clubes Deportivos",
    "7991": "Turismo",
    "7992": "Golf",
    "7993": "Videojuegos",
    "7994": "Arcades",
    "7995": "Casinos",
    "7996": "Parques de Diversiones",
    "7997": "Clubes Recreativos",
    "7998": "Acuarios y Zoológicos",
    "7999": "Recreación Miscelánea",
}


# ===== VERSIONES DE ESQUEMA SRI =====
SCHEMA_VERSIONS = {
    TipoComprobante.FACTURA: "2.1.0",
    TipoComprobante.NOTA_CREDITO: "1.1.0",
    TipoComprobante.NOTA_DEBITO: "1.0.0",
    TipoComprobante.RETENCION: "2.0.0",
    TipoComprobante.GUIA_REMISION: "1.1.0",
    TipoComprobante.LIQUIDACION_COMPRA: "1.1.0",
}


# ===== CÓDIGOS DE RETENCIÓN =====
# Los más comunes para servicios
RETENCIONES_FUENTE = {
    "303": ("Honorarios profesionales", 10.0),
    "304": ("Servicios predomina intelecto", 8.0),
    "307": ("Servicios predomina mano obra", 2.0),
    "308": ("Servicios entre sociedades", 2.0),
    "309": ("Servicios publicidad", 1.0),
    "310": ("Transporte privado", 1.0),
    "312": ("Transferencia bienes muebles", 1.0),
    "320": ("Arrendamiento bienes inmuebles", 8.0),
    "322": ("Seguros y reaseguros", 1.0),
    "323": ("Rendimientos financieros", 2.0),
    "332": ("Pagos al exterior", 25.0),
    "340": ("Otras retenciones aplicables 1%", 1.0),
    "341": ("Otras retenciones aplicables 2%", 2.0),
    "342": ("Otras retenciones aplicables 8%", 8.0),
}


RETENCIONES_IVA = {
    "1": ("10% del IVA", 10.0),
    "2": ("20% del IVA", 20.0),
    "3": ("30% del IVA", 30.0),
    "4": ("50% del IVA", 50.0),
    "5": ("70% del IVA", 70.0),
    "6": ("100% del IVA", 100.0),
    "7": ("No procede retención", 0.0),
    "8": ("Retención presuntiva del 10%", 10.0),
}


# ===== CUENTAS CONTABLES PRINCIPALES (NIIF Ecuador) =====
# Códigos según Plan de Cuentas SuperCias
CUENTAS_PRINCIPALES = {
    # Activos
    "1.1.1.01": "Caja",
    "1.1.1.02": "Bancos",
    "1.1.2.01": "Cuentas por Cobrar Clientes",
    "1.1.3.01": "IVA en Compras (Crédito Tributario)",
    "1.1.3.02": "Retenciones de IVA que le han sido efectuadas",
    "1.1.3.03": "Retenciones de IR que le han sido efectuadas",

    # Pasivos
    "2.1.1.01": "Cuentas por Pagar Proveedores",
    "2.1.2.01": "Obligaciones con el IESS",
    "2.1.3.01": "IVA en Ventas",
    "2.1.3.02": "Retenciones de IVA por Pagar",
    "2.1.3.03": "Retenciones de IR por Pagar",
    "2.1.4.01": "Impuesto a la Renta por Pagar",
    "2.1.5.01": "Depósitos de Clientes (Fondos de Terceros)",

    # Patrimonio
    "3.1.1.01": "Capital Suscrito",
    "3.2.1.01": "Reserva Legal",
    "3.3.1.01": "Resultados del Ejercicio",
    "3.3.2.01": "Resultados Acumulados",

    # Ingresos
    "4.1.1.01": "Ingresos por Servicios de Comisión",
    "4.1.1.02": "Ingresos por Honorarios",
    "4.2.1.01": "Otros Ingresos",

    # Gastos
    "5.1.1.01": "Honorarios de Administración",
    "5.1.1.02": "Aportes al IESS",
    "5.1.2.01": "Servicios Básicos",
    "5.1.2.02": "Servicios Profesionales",
    "5.1.2.03": "Comisiones Bancarias",
    "5.1.2.04": "Comisiones Pasarela de Pago",
    "5.1.3.01": "Depreciación",
    "5.1.4.01": "Gastos No Deducibles",
}
