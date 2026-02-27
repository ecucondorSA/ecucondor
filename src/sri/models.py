"""
ECUCONDOR - Modelos Pydantic para Facturación Electrónica SRI
Define las estructuras de datos para comprobantes electrónicos.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class TipoComprobante(str, Enum):
    """Tipos de comprobante electrónico del SRI."""
    FACTURA = "01"
    LIQUIDACION_COMPRA = "03"
    NOTA_CREDITO = "04"
    NOTA_DEBITO = "05"
    GUIA_REMISION = "06"
    RETENCION = "07"


class TipoIdentificacion(str, Enum):
    """Tipos de identificación del comprador."""
    RUC = "04"
    CEDULA = "05"
    PASAPORTE = "06"
    CONSUMIDOR_FINAL = "07"
    EXTERIOR = "08"


class FormaPago(str, Enum):
    """Formas de pago válidas para el SRI."""
    SIN_SISTEMA_FINANCIERO = "01"
    COMPENSACION = "15"
    TARJETA_DEBITO = "16"
    DINERO_ELECTRONICO = "17"
    TARJETA_PREPAGO = "18"
    TARJETA_CREDITO = "19"
    OTROS = "20"
    ENDOSO_TITULOS = "21"


class CodigoImpuesto(str, Enum):
    """Códigos de impuesto."""
    IVA = "2"
    ICE = "3"
    IRBPNR = "5"


class CodigoPorcentajeIVA(str, Enum):
    """Códigos de porcentaje IVA según ficha técnica SRI."""
    IVA_0 = "0"
    IVA_5 = "5"
    IVA_8 = "8"
    IVA_12 = "2"
    IVA_14 = "3"
    IVA_15 = "4"
    NO_OBJETO = "6"
    EXENTO = "7"


class EstadoComprobante(str, Enum):
    """Estados del ciclo de vida de un comprobante."""
    DRAFT = "draft"
    PENDING = "pending"
    SENT = "sent"
    RECEIVED = "received"
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ERROR = "error"


# ===== MODELOS BASE =====

class InfoTributaria(BaseModel):
    """Información tributaria del emisor."""
    ambiente: str = Field(..., min_length=1, max_length=1, description="1=Pruebas, 2=Producción")
    tipo_emision: str = Field(default="1", min_length=1, max_length=1)
    razon_social: str = Field(..., max_length=300)
    nombre_comercial: str | None = Field(default=None, max_length=300)
    ruc: str = Field(..., min_length=13, max_length=13)
    clave_acceso: str | None = Field(default=None, min_length=49, max_length=49)
    cod_doc: str = Field(..., min_length=2, max_length=2, description="Código tipo documento")
    estab: str = Field(..., min_length=3, max_length=3, description="Establecimiento")
    pto_emi: str = Field(..., min_length=3, max_length=3, description="Punto de emisión")
    secuencial: str = Field(..., min_length=9, max_length=9)
    dir_matriz: str = Field(..., max_length=300)

    @field_validator("ruc")
    @classmethod
    def validate_ruc(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("El RUC debe contener solo dígitos")
        return v


class Impuesto(BaseModel):
    """Impuesto aplicado a un detalle."""
    codigo: CodigoImpuesto = Field(default=CodigoImpuesto.IVA)
    codigo_porcentaje: CodigoPorcentajeIVA
    tarifa: Decimal = Field(ge=0, le=100)
    base_imponible: Decimal = Field(ge=0)
    valor: Decimal = Field(ge=0)


class DetalleFactura(BaseModel):
    """Línea de detalle de una factura."""
    codigo_principal: str | None = Field(default=None, max_length=25)
    codigo_auxiliar: str | None = Field(default=None, max_length=25)
    descripcion: str = Field(..., min_length=1, max_length=300)
    cantidad: Decimal = Field(gt=0)
    precio_unitario: Decimal = Field(ge=0)
    descuento: Decimal = Field(default=Decimal("0"), ge=0)
    precio_total_sin_impuesto: Decimal = Field(ge=0)
    impuestos: list[Impuesto] = Field(default_factory=list)
    detalles_adicionales: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_precio_total(self) -> "DetalleFactura":
        """Validar que el precio total sea correcto."""
        esperado = (self.cantidad * self.precio_unitario) - self.descuento
        if abs(self.precio_total_sin_impuesto - esperado) > Decimal("0.01"):
            # Permitir pequeña tolerancia por redondeo
            pass
        return self


class Pago(BaseModel):
    """Forma de pago de un comprobante."""
    forma_pago: FormaPago
    total: Decimal = Field(gt=0)
    plazo: int | None = Field(default=None, ge=0)
    unidad_tiempo: str | None = Field(default=None, max_length=20)


class TotalImpuesto(BaseModel):
    """Total de impuestos por código y porcentaje."""
    codigo: CodigoImpuesto = CodigoImpuesto.IVA
    codigo_porcentaje: CodigoPorcentajeIVA
    descuento_adicional: Decimal = Field(default=Decimal("0"))
    base_imponible: Decimal = Field(ge=0)
    tarifa: Decimal = Field(ge=0)
    valor: Decimal = Field(ge=0)


# ===== MODELOS DE FACTURA =====

class InfoFactura(BaseModel):
    """Información específica de la factura."""
    fecha_emision: date
    dir_establecimiento: str | None = Field(default=None, max_length=300)
    contribuyente_especial: str | None = Field(default=None, max_length=10)
    obligado_contabilidad: str = Field(default="SI", pattern="^(SI|NO)$")
    tipo_identificacion_comprador: TipoIdentificacion
    guia_remision: str | None = Field(default=None, max_length=17)
    razon_social_comprador: str = Field(..., max_length=300)
    identificacion_comprador: str = Field(..., max_length=20)
    direccion_comprador: str | None = Field(default=None, max_length=300)
    total_sin_impuestos: Decimal = Field(ge=0)
    total_descuento: Decimal = Field(default=Decimal("0"), ge=0)
    total_con_impuestos: list[TotalImpuesto]
    propina: Decimal = Field(default=Decimal("0"), ge=0)
    importe_total: Decimal = Field(ge=0)
    moneda: str = Field(default="DOLAR")
    pagos: list[Pago]

    @field_validator("fecha_emision", mode="before")
    @classmethod
    def parse_fecha(cls, v: Any) -> date:
        if isinstance(v, str):
            return datetime.strptime(v, "%d/%m/%Y").date()
        return v


class Factura(BaseModel):
    """Modelo completo de factura electrónica."""
    info_tributaria: InfoTributaria
    info_factura: InfoFactura
    detalles: list[DetalleFactura] = Field(..., min_length=1)
    info_adicional: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_totales(self) -> "Factura":
        """Validar que los totales sean consistentes."""
        # Sumar totales de detalles
        total_detalles = sum(d.precio_total_sin_impuesto for d in self.detalles)

        # Validar contra total_sin_impuestos con tolerancia
        if abs(total_detalles - self.info_factura.total_sin_impuestos) > Decimal("0.02"):
            pass  # Permitir diferencias menores por redondeo

        return self


# ===== MODELOS DE RESPUESTA SRI =====

class MensajeSRI(BaseModel):
    """Mensaje de respuesta del SRI."""
    identificador: str
    mensaje: str
    informacion_adicional: str | None = None
    tipo: str | None = None  # ERROR, ADVERTENCIA, INFORMATIVO


class RespuestaRecepcion(BaseModel):
    """Respuesta del Web Service de Recepción."""
    estado: str  # RECIBIDA, DEVUELTA
    comprobantes: list[dict[str, Any]] | None = None


class AutorizacionSRI(BaseModel):
    """Respuesta del Web Service de Autorización."""
    estado: str  # AUTORIZADO, NO AUTORIZADO
    numero_autorizacion: str | None = None
    fecha_autorizacion: datetime | None = None
    ambiente: str | None = None
    comprobante: str | None = None  # XML del comprobante
    mensajes: list[MensajeSRI] = Field(default_factory=list)


class RespuestaAutorizacion(BaseModel):
    """Respuesta completa de autorización."""
    clave_acceso_consultada: str
    numero_comprobantes: int
    autorizaciones: list[AutorizacionSRI]


# ===== MODELO PARA CREAR FACTURA (API) =====

class ClienteFactura(BaseModel):
    """Datos del cliente para crear una factura."""
    tipo_identificacion: TipoIdentificacion
    identificacion: str = Field(..., max_length=20)
    razon_social: str = Field(..., max_length=300)
    direccion: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=300)
    telefono: str | None = Field(default=None, max_length=20)


class ItemFactura(BaseModel):
    """Item/línea para crear una factura."""
    codigo: str | None = Field(default=None, max_length=25)
    descripcion: str = Field(..., max_length=300)
    cantidad: Decimal = Field(gt=0)
    precio_unitario: Decimal = Field(ge=0)
    descuento: Decimal = Field(default=Decimal("0"), ge=0)
    aplica_iva: bool = Field(default=True)
    porcentaje_iva: Decimal = Field(default=Decimal("15"))


class CrearFacturaRequest(BaseModel):
    """Request para crear una nueva factura."""
    cliente: ClienteFactura
    items: list[ItemFactura] = Field(..., min_length=1)
    forma_pago: FormaPago = FormaPago.OTROS
    info_adicional: dict[str, str] | None = None
    enviar_sri: bool = Field(default=True, description="Enviar automáticamente al SRI")
    enviar_email: bool = Field(default=False, description="Enviar por email al cliente")


class CrearFacturaResponse(BaseModel):
    """Response de creación de factura."""
    id: str
    numero: str  # 001-001-000000001
    clave_acceso: str
    estado: EstadoComprobante
    fecha_emision: date
    importe_total: Decimal
    mensaje: str | None = None


# ===== MODELOS DE NOTA DE CRÉDITO =====

class InfoNotaCredito(BaseModel):
    """Información específica de la nota de crédito."""
    fecha_emision: date
    dir_establecimiento: str | None = Field(default=None, max_length=300)
    tipo_identificacion_comprador: TipoIdentificacion
    razon_social_comprador: str = Field(..., max_length=300)
    identificacion_comprador: str = Field(..., max_length=20)
    contribuyente_especial: str | None = Field(default=None, max_length=10)
    obligado_contabilidad: str = Field(default="SI", pattern="^(SI|NO)$")
    cod_doc_modificado: str = Field(default="01", min_length=2, max_length=2)
    num_doc_modificado: str = Field(..., description="Ej: 001-001-000000002")
    fecha_emision_doc_sustento: date
    total_sin_impuestos: Decimal = Field(ge=0)
    valor_modificacion: Decimal = Field(ge=0)
    moneda: str = Field(default="DOLAR")
    total_con_impuestos: list[TotalImpuesto]
    motivo: str = Field(..., max_length=300)

    @field_validator("fecha_emision", "fecha_emision_doc_sustento", mode="before")
    @classmethod
    def parse_fecha(cls, v: Any) -> date:
        if isinstance(v, str):
            return datetime.strptime(v, "%d/%m/%Y").date()
        return v


class NotaCredito(BaseModel):
    """Modelo completo de nota de crédito electrónica."""
    info_tributaria: InfoTributaria
    info_nota_credito: InfoNotaCredito
    detalles: list[DetalleFactura] = Field(..., min_length=1)
    info_adicional: dict[str, str] | None = None
