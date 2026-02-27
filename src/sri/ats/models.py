"""
ECUCONDOR - Modelos de datos para ATS (Anexo Transaccional Simplificado)
Basado en la Ficha Técnica ATS del SRI Ecuador.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from decimal import Decimal
from enum import Enum


class TipoIdentificacionATS(str, Enum):
    """Tipos de identificación válidos para ATS."""
    RUC = "04"
    CEDULA = "05"
    PASAPORTE = "06"
    CONSUMIDOR_FINAL = "07"
    EXTERIOR = "08"


class TipoComprobanteATS(str, Enum):
    """
    Tipos de comprobante para el ATS.
    Nota: Los códigos son diferentes a los de facturación electrónica.
    """
    # Comprobantes físicos
    FACTURA = "01"
    NOTA_VENTA = "02"
    LIQUIDACION_COMPRA = "03"
    NOTA_CREDITO = "04"
    NOTA_DEBITO = "05"
    GUIA_REMISION = "06"
    COMPROBANTE_RETENCION = "07"

    # Comprobantes electrónicos
    FACTURA_ELECTRONICA = "18"
    NOTA_CREDITO_ELECTRONICA = "41"
    NOTA_DEBITO_ELECTRONICA = "42"
    LIQUIDACION_COMPRA_ELECTRONICA = "43"
    GUIA_REMISION_ELECTRONICA = "44"
    COMPROBANTE_RETENCION_ELECTRONICO = "45"


class FormaPagoATS(str, Enum):
    """Formas de pago para ATS."""
    SIN_SISTEMA_FINANCIERO = "01"
    CHEQUE_PROPIO = "02"
    CHEQUE_CERTIFICADO = "03"
    CHEQUE_GERENCIA = "04"
    CHEQUE_EXTRANJERO = "05"
    DEBITO_CUENTA = "06"
    TRANSFERENCIA_OTRO_BANCO = "07"
    TRANSFERENCIA_MISMO_BANCO = "08"
    TARJETA_CREDITO_NACIONAL = "09"
    TARJETA_CREDITO_INTERNACIONAL = "10"
    GIRO = "11"
    DEPOSITO_CUENTA_CORRIENTE = "12"
    DEPOSITO_CUENTA_AHORROS = "13"
    ENDOSO_TITULOS = "14"
    COMPENSACION_DEUDAS = "15"
    TARJETA_DEBITO = "16"
    DINERO_ELECTRONICO_BCE = "17"
    TARJETA_PREPAGO = "18"
    TARJETA_CREDITO = "19"
    OTROS_SISTEMA_FINANCIERO = "20"
    ENDOSO_TITULOS_CREDITO = "21"


class DetalleVenta(BaseModel):
    """
    Detalle de venta para el módulo de ventas del ATS.
    Cada registro agrupa las ventas a un mismo cliente con mismo tipo de comprobante.
    """
    tipo_id_cliente: TipoIdentificacionATS = Field(
        ...,
        description="Tipo de identificación del cliente"
    )
    id_cliente: str = Field(
        ...,
        max_length=20,
        description="Número de identificación del cliente"
    )
    parte_relacionada: str = Field(
        default="NO",
        description="SI si es parte relacionada, NO si no lo es"
    )
    tipo_comprobante: TipoComprobanteATS = Field(
        ...,
        description="Tipo de comprobante emitido"
    )
    tipo_emision: str = Field(
        default="E",
        description="E=Electrónico, F=Físico"
    )
    numero_comprobantes: int = Field(
        default=1,
        ge=1,
        description="Cantidad de comprobantes emitidos al cliente"
    )
    base_no_grava_iva: Decimal = Field(
        default=Decimal("0.00"),
        description="Base no objeto de IVA"
    )
    base_imponible_0: Decimal = Field(
        default=Decimal("0.00"),
        description="Base imponible IVA 0%"
    )
    base_imponible_15: Decimal = Field(
        default=Decimal("0.00"),
        description="Base imponible IVA 15%"
    )
    monto_iva: Decimal = Field(
        default=Decimal("0.00"),
        description="Valor total del IVA"
    )
    monto_ice: Decimal = Field(
        default=Decimal("0.00"),
        description="Valor total del ICE"
    )
    valor_ret_iva: Decimal = Field(
        default=Decimal("0.00"),
        description="Retención de IVA recibida del cliente"
    )
    valor_ret_renta: Decimal = Field(
        default=Decimal("0.00"),
        description="Retención de IR recibida del cliente"
    )
    formas_pago: List[str] = Field(
        default=["20"],
        description="Lista de códigos de forma de pago"
    )

    class Config:
        use_enum_values = True


class SustentoTributario(str, Enum):
    """Códigos de sustento tributario."""
    CREDITO_TRIBUTARIO_IVA_RENTA = "01"
    COSTO_GASTO_NO_CREDITO_IVA = "02"
    ACTIVO_FIJO_CREDITO_IVA = "03"
    ACTIVO_FIJO_NO_CREDITO_IVA = "04"
    LIQUIDACION_GASTOS_VIAJE = "05"
    INVENTARIO_CREDITO_IVA = "06"
    INVENTARIO_NO_CREDITO_IVA = "07"
    VALOR_PAGADO_REEMBOLSO = "08"
    REEMBOLSO_MEDIARIOS = "09"
    CONTRATOS_CONSTRUCCION = "10"


class PagoExterior(BaseModel):
    """Detalle de pago al exterior."""
    pago_loc_ext: str = Field(
        default="01",
        description="01: Local, 02: Exterior"
    )
    tipo_regim: Optional[str] = Field(
        default=None,
        description="Tipo de régimen fiscal (si es exterior)"
    )
    pais_efec_pago: Optional[str] = Field(
        default=None,
        description="Código del país al que se efectúa el pago"
    )
    aplic_conv_dob_trib: str = Field(
        default="NO",
        description="Aplica convenio de doble tributación (SI/NO)"
    )
    pag_ext_suj_ret_nor_leg: str = Field(
        default="NO",
        description="Pago al exterior sujeto a retención (SI/NO)"
    )


class DetalleCompra(BaseModel):
    """
    Detalle de compras para el módulo de compras del ATS.
    """
    cod_sustento: SustentoTributario = Field(
        ...,
        description="Código de sustento tributario"
    )
    tp_id_prov: TipoIdentificacionATS = Field(
        ...,
        description="Tipo de identificación del proveedor"
    )
    id_prov: str = Field(
        ...,
        max_length=13,
        description="Número de identificación del proveedor"
    )
    tipo_comprobante: TipoComprobanteATS = Field(
        ...,
        description="Tipo de comprobante"
    )
    tipo_prov: Optional[str] = Field(
        default=None,
        description="Tipo de proveedor (01: Persona Natural, 02: Sociedad)"
    )
    deno_prov: Optional[str] = Field(
        default=None,
        description="Nombre o Razón Social del proveedor (opcional)"
    )
    parte_relacionada: str = Field(
        default="NO",
        description="SI/NO"
    )
    fecha_registro: str = Field(
        ...,
        description="Fecha de registro contable (dd/mm/aaaa)"
    )
    establecimiento: str = Field(
        ...,
        min_length=3,
        max_length=3
    )
    punto_emision: str = Field(
        ...,
        min_length=3,
        max_length=3
    )
    secuencial: str = Field(
        ...,
        min_length=9,
        max_length=9
    )
    fecha_emision: str = Field(
        ...,
        description="Fecha de emisión del comprobante (dd/mm/aaaa)"
    )
    autorizacion: str = Field(
        ...,
        max_length=49
    )
    base_no_grava_iva: Decimal = Field(default=Decimal("0.00"))
    base_imponible_0: Decimal = Field(default=Decimal("0.00"))
    base_imponible_15: Decimal = Field(default=Decimal("0.00"))
    base_exenta: Decimal = Field(default=Decimal("0.00"))
    monto_iva: Decimal = Field(default=Decimal("0.00"))
    monto_ice: Decimal = Field(default=Decimal("0.00"))
    
    # Retenciones
    val_ret_bien_10: Decimal = Field(default=Decimal("0.00"))
    val_ret_serv_20: Decimal = Field(default=Decimal("0.00"))
    valor_ret_bienes: Decimal = Field(default=Decimal("0.00"))
    val_ret_serv_50: Decimal = Field(default=Decimal("0.00"))
    valor_ret_servicios: Decimal = Field(default=Decimal("0.00"))
    val_ret_serv_100: Decimal = Field(default=Decimal("0.00"))
    
    # Totales
    tot_bases_impobst_reemb: Decimal = Field(default=Decimal("0.00"))
    
    # Pago exterior
    pago_exterior: PagoExterior = Field(
        default_factory=PagoExterior,
        description="Datos de pago al exterior"
    )
    
    formas_pago: List[str] = Field(
        default=["01"],
        description="Códigos de forma de pago"
    )

    class Config:
        use_enum_values = True


class DetalleAnulado(BaseModel):
    """
    Detalle de comprobante anulado para el módulo de anulados del ATS.
    """
    tipo_comprobante: TipoComprobanteATS = Field(
        ...,
        description="Tipo de comprobante anulado"
    )
    establecimiento: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Código del establecimiento (3 dígitos)"
    )
    punto_emision: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Código del punto de emisión (3 dígitos)"
    )
    secuencial_inicio: str = Field(
        ...,
        min_length=9,
        max_length=9,
        description="Secuencial inicial del rango anulado"
    )
    secuencial_fin: str = Field(
        ...,
        min_length=9,
        max_length=9,
        description="Secuencial final del rango anulado"
    )
    autorizacion: str = Field(
        ...,
        max_length=49,
        description="Clave de acceso o número de autorización"
    )

    class Config:
        use_enum_values = True


class VentaEstablecimiento(BaseModel):
    """Resumen de ventas por establecimiento."""
    cod_estab: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Código del establecimiento"
    )
    ventas_estab: Decimal = Field(
        default=Decimal("0.00"),
        description="Total de ventas del establecimiento"
    )
    iva_comp: Decimal = Field(
        default=Decimal("0.00"),
        description="IVA de comprobantes de venta"
    )


class ATS(BaseModel):
    """
    Modelo principal del Anexo Transaccional Simplificado.
    Representa el archivo XML completo que se envía al SRI.
    """
    # Identificación del informante
    tipo_id_informante: str = Field(
        default="R",
        description="R=RUC, C=Cédula"
    )
    id_informante: str = Field(
        ...,
        min_length=13,
        max_length=13,
        description="RUC del contribuyente (13 dígitos)"
    )
    razon_social: str = Field(
        ...,
        max_length=300,
        description="Razón social del contribuyente"
    )

    # Período
    anio: int = Field(
        ...,
        ge=2020,
        le=2100,
        description="Año del período"
    )
    mes: int = Field(
        ...,
        ge=1,
        le=12,
        description="Mes del período (1-12)"
    )

    # Establecimientos
    num_estab_ruc: str = Field(
        default="001",
        description="Número de establecimientos con actividad"
    )

    # Código operativo (obligatorio para SRI)
    codigo_operativo: str = Field(
        default="IVA",
        description="Código operativo del anexo (IVA)"
    )

    # Datos de ventas
    ventas: List[DetalleVenta] = Field(
        default=[],
        description="Lista de detalles de ventas"
    )

    # Datos de compras
    compras: List[DetalleCompra] = Field(
        default=[],
        description="Lista de detalles de compras"
    )

    # Datos de anulados
    anulados: List[DetalleAnulado] = Field(
        default=[],
        description="Lista de comprobantes anulados"
    )

    # Ventas por establecimiento (calculado)
    ventas_establecimiento: Optional[List[VentaEstablecimiento]] = Field(
        default=None,
        description="Resumen de ventas por establecimiento"
    )

    def calcular_total_ventas(self) -> Decimal:
        """Calcula el total de ventas del período."""
        total = Decimal("0.00")
        for v in self.ventas:
            total += (
                v.base_no_grava_iva +
                v.base_imponible_0 +
                v.base_imponible_15 +
                v.monto_iva +
                v.monto_ice
            )
        return total

    def calcular_base_gravada_total(self) -> Decimal:
        """Calcula el total de base gravada IVA 15%."""
        return sum(v.base_imponible_15 for v in self.ventas)

    def calcular_iva_total(self) -> Decimal:
        """Calcula el IVA total del período."""
        return sum(v.monto_iva for v in self.ventas)

    def calcular_total_compras(self) -> Decimal:
        """Calcula el total de compras."""
        return sum(
            c.base_no_grava_iva +
            c.base_imponible_0 +
            c.base_imponible_15 +
            c.base_exenta +
            c.monto_iva +
            c.monto_ice
            for c in self.compras
        )
