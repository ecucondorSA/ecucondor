"""
ECUCONDOR - Modelos del Ingestor Financiero
Define las estructuras de datos para transacciones bancarias normalizadas.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TipoTransaccion(str, Enum):
    """Tipos de transacciones bancarias."""
    CREDITO = "credito"  # Dinero que entra
    DEBITO = "debito"    # Dinero que sale


class OrigenTransaccion(str, Enum):
    """Origen/fuente de la transacción."""
    TRANSFERENCIA = "transferencia"
    DEPOSITO = "deposito"
    RETIRO = "retiro"
    CHEQUE = "cheque"
    PAGO_TARJETA = "pago_tarjeta"
    COMISION_BANCARIA = "comision_bancaria"
    INTERES = "interes"
    IMPUESTO = "impuesto"
    OTRO = "otro"


class EstadoTransaccion(str, Enum):
    """Estado de procesamiento de la transacción."""
    PENDIENTE = "pendiente"           # Recién importada
    CONCILIADA = "conciliada"         # Matched con factura/gasto
    DUPLICADA = "duplicada"           # Detectada como duplicado
    DESCARTADA = "descartada"         # Descartada manualmente
    ERROR = "error"                   # Error en procesamiento


class BancoEcuador(str, Enum):
    """Bancos ecuatorianos soportados."""
    PICHINCHA = "pichincha"
    PRODUBANCO = "produbanco"
    GUAYAQUIL = "guayaquil"
    PACIFICO = "pacifico"
    BOLIVARIANO = "bolivariano"
    INTERNACIONAL = "internacional"
    AUSTRO = "austro"
    MACHALA = "machala"
    LOJA = "loja"
    OTRO = "otro"


class TransaccionBancaria(BaseModel):
    """
    Modelo normalizado de transacción bancaria.

    Representa cualquier movimiento bancario de forma estandarizada,
    independiente del formato original del banco.
    """

    # Identificación
    id: UUID | None = None
    hash_unico: str = Field(..., description="Hash para deduplicación")

    # Origen
    banco: BancoEcuador
    cuenta_bancaria: str = Field(..., min_length=5)
    archivo_origen: str | None = None
    linea_origen: int | None = None

    # Datos de la transacción
    fecha: date
    fecha_valor: date | None = None  # Fecha efectiva (puede diferir)
    tipo: TipoTransaccion
    origen: OrigenTransaccion = OrigenTransaccion.OTRO

    # Montos
    monto: Decimal = Field(..., ge=0)
    saldo: Decimal | None = None

    # Descripción y referencias
    descripcion_original: str
    descripcion_normalizada: str | None = None
    referencia: str | None = None
    numero_documento: str | None = None

    # Contraparte (si aplica)
    contraparte_nombre: str | None = None
    contraparte_identificacion: str | None = None
    contraparte_banco: str | None = None
    contraparte_cuenta: str | None = None

    # Estado y conciliación
    estado: EstadoTransaccion = EstadoTransaccion.PENDIENTE
    comprobante_id: UUID | None = None  # Si está conciliada con factura
    asiento_id: UUID | None = None      # Si tiene asiento contable

    # Categorización automática
    categoria_sugerida: str | None = None
    cuenta_contable_sugerida: str | None = None
    confianza_categoria: float | None = Field(None, ge=0, le=1)

    # Metadatos
    datos_originales: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("monto", mode="before")
    @classmethod
    def parse_monto(cls, v):
        """Convierte el monto a Decimal."""
        if isinstance(v, str):
            # Limpiar formato común en Ecuador (1.234,56)
            v = v.replace(".", "").replace(",", ".")
        return Decimal(str(v))

    @field_validator("saldo", mode="before")
    @classmethod
    def parse_saldo(cls, v):
        """Convierte el saldo a Decimal si existe."""
        if v is None:
            return None
        if isinstance(v, str):
            v = v.replace(".", "").replace(",", ".")
        return Decimal(str(v))

    def to_db_dict(self) -> dict[str, Any]:
        """Convierte a diccionario para inserción en base de datos."""
        data = {
            "hash_unico": self.hash_unico,
            "banco": self.banco.value,
            "cuenta_bancaria": self.cuenta_bancaria,
            "archivo_origen": self.archivo_origen,
            "linea_origen": self.linea_origen,
            "fecha": self.fecha.isoformat(),
            "fecha_valor": self.fecha_valor.isoformat() if self.fecha_valor else None,
            "tipo": self.tipo.value,
            "origen": self.origen.value,
            "monto": float(self.monto),
            "saldo": float(self.saldo) if self.saldo else None,
            "descripcion_original": self.descripcion_original,
            "descripcion_normalizada": self.descripcion_normalizada,
            "referencia": self.referencia,
            "numero_documento": self.numero_documento,
            "contraparte_nombre": self.contraparte_nombre,
            "contraparte_identificacion": self.contraparte_identificacion,
            "contraparte_banco": self.contraparte_banco,
            "contraparte_cuenta": self.contraparte_cuenta,
            "estado": self.estado.value,
            "categoria_sugerida": self.categoria_sugerida,
            "cuenta_contable_sugerida": self.cuenta_contable_sugerida,
            "confianza_categoria": self.confianza_categoria,
            "datos_originales": self.datos_originales,
        }

        if self.id:
            data["id"] = str(self.id)
        if self.comprobante_id:
            data["comprobante_id"] = str(self.comprobante_id)
        if self.asiento_id:
            data["asiento_id"] = str(self.asiento_id)

        return data


class ResultadoImportacion(BaseModel):
    """Resultado de una operación de importación de extracto."""

    archivo: str
    banco: BancoEcuador
    cuenta: str

    total_lineas: int = 0
    transacciones_nuevas: int = 0
    transacciones_duplicadas: int = 0
    transacciones_error: int = 0

    monto_total_creditos: Decimal = Decimal("0")
    monto_total_debitos: Decimal = Decimal("0")

    errores: list[str] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)

    transacciones: list[TransaccionBancaria] = Field(default_factory=list)


class FiltrosTransaccion(BaseModel):
    """Filtros para búsqueda de transacciones."""

    banco: BancoEcuador | None = None
    cuenta_bancaria: str | None = None
    tipo: TipoTransaccion | None = None
    estado: EstadoTransaccion | None = None
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    monto_minimo: Decimal | None = None
    monto_maximo: Decimal | None = None
    descripcion: str | None = None
    contraparte: str | None = None
    solo_sin_conciliar: bool = False
