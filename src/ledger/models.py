"""
ECUCONDOR - Modelos del Ledger Contable
Define las estructuras para asientos contables y movimientos.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class TipoAsiento(str, Enum):
    """Tipos de asiento contable."""
    NORMAL = "normal"
    APERTURA = "apertura"
    CIERRE = "cierre"
    AJUSTE = "ajuste"
    RECLASIFICACION = "reclasificacion"
    AUTOMATICO = "automatico"


class EstadoAsiento(str, Enum):
    """Estados de un asiento contable."""
    BORRADOR = "borrador"
    CONTABILIZADO = "contabilizado"
    ANULADO = "anulado"


class OrigenAsiento(str, Enum):
    """Origen/fuente del asiento."""
    FACTURA = "factura"
    TRANSACCION = "transaccion"
    COMISION = "comision"
    MANUAL = "manual"
    CIERRE = "cierre"
    ANULACION = "anulacion"


class NaturalezaCuenta(str, Enum):
    """Naturaleza de la cuenta contable."""
    DEUDORA = "deudora"    # Activos, Gastos
    ACREEDORA = "acreedora"  # Pasivos, Patrimonio, Ingresos


class MovimientoContable(BaseModel):
    """
    Línea de detalle de un asiento contable.

    Representa un movimiento individual en una cuenta,
    ya sea al debe o al haber.
    """

    id: UUID | None = None
    asiento_id: UUID | None = None

    # Cuenta
    cuenta_codigo: str = Field(..., min_length=1, max_length=20)
    cuenta_nombre: str | None = None  # Para display

    # Montos (solo uno debe tener valor > 0)
    debe: Decimal = Field(default=Decimal("0"), ge=0)
    haber: Decimal = Field(default=Decimal("0"), ge=0)

    # Detalle
    concepto: str | None = None
    centro_costo: str | None = None
    referencia: str | None = None

    # Orden
    orden: int = 0

    @model_validator(mode="after")
    def validar_debe_o_haber(self):
        """Valida que solo debe o haber tenga valor."""
        if self.debe > 0 and self.haber > 0:
            raise ValueError("Un movimiento debe tener debe O haber, no ambos")
        if self.debe == 0 and self.haber == 0:
            raise ValueError("Un movimiento debe tener debe o haber con valor > 0")
        return self

    @property
    def es_debe(self) -> bool:
        """Indica si es movimiento al debe."""
        return self.debe > 0

    @property
    def es_haber(self) -> bool:
        """Indica si es movimiento al haber."""
        return self.haber > 0

    @property
    def monto(self) -> Decimal:
        """Retorna el monto del movimiento."""
        return self.debe if self.debe > 0 else self.haber

    def to_db_dict(self) -> dict[str, Any]:
        """Convierte a diccionario para base de datos."""
        return {
            "cuenta_codigo": self.cuenta_codigo,
            "debe": float(self.debe),
            "haber": float(self.haber),
            "concepto": self.concepto,
            "centro_costo": self.centro_costo,
            "referencia": self.referencia,
            "orden": self.orden,
        }


class AsientoContable(BaseModel):
    """
    Asiento contable (cabecera).

    Representa un asiento en el libro diario con sus movimientos.
    Debe cumplir la ecuación: Total Debe = Total Haber
    """

    id: UUID | None = None
    numero_asiento: int | None = None

    # Datos principales
    fecha: date
    concepto: str = Field(..., min_length=1, max_length=500)
    referencia: str | None = None

    # Tipo y origen
    tipo: TipoAsiento = TipoAsiento.NORMAL
    origen_tipo: OrigenAsiento | None = None
    origen_id: UUID | None = None

    # Movimientos
    movimientos: list[MovimientoContable] = Field(default_factory=list)

    # Totales (calculados)
    total_debe: Decimal = Decimal("0")
    total_haber: Decimal = Decimal("0")

    # Estado
    estado: EstadoAsiento = EstadoAsiento.BORRADOR
    periodo_id: UUID | None = None

    # Anulación
    anulado_at: datetime | None = None
    motivo_anulacion: str | None = None
    asiento_reverso_id: UUID | None = None

    # Auditoría
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None

    @model_validator(mode="after")
    def calcular_totales(self):
        """Calcula totales de debe y haber."""
        self.total_debe = sum(m.debe for m in self.movimientos)
        self.total_haber = sum(m.haber for m in self.movimientos)
        return self

    @property
    def esta_cuadrado(self) -> bool:
        """Verifica si el asiento cuadra (debe = haber)."""
        return self.total_debe == self.total_haber

    @property
    def diferencia(self) -> Decimal:
        """Calcula la diferencia entre debe y haber."""
        return self.total_debe - self.total_haber

    def agregar_debe(
        self,
        cuenta: str,
        monto: Decimal,
        concepto: str | None = None,
    ) -> "AsientoContable":
        """Agrega un movimiento al debe."""
        self.movimientos.append(MovimientoContable(
            cuenta_codigo=cuenta,
            debe=monto,
            haber=Decimal("0"),
            concepto=concepto,
            orden=len(self.movimientos),
        ))
        self.total_debe += monto
        return self

    def agregar_haber(
        self,
        cuenta: str,
        monto: Decimal,
        concepto: str | None = None,
    ) -> "AsientoContable":
        """Agrega un movimiento al haber."""
        self.movimientos.append(MovimientoContable(
            cuenta_codigo=cuenta,
            debe=Decimal("0"),
            haber=monto,
            concepto=concepto,
            orden=len(self.movimientos),
        ))
        self.total_haber += monto
        return self

    def validar(self) -> list[str]:
        """
        Valida el asiento completo.

        Returns:
            Lista de errores (vacía si es válido)
        """
        errores: list[str] = []

        if not self.movimientos:
            errores.append("El asiento no tiene movimientos")

        if len(self.movimientos) < 2:
            errores.append("El asiento debe tener al menos 2 movimientos")

        if not self.esta_cuadrado:
            errores.append(
                f"El asiento no cuadra: Debe={self.total_debe} "
                f"Haber={self.total_haber} Diferencia={self.diferencia}"
            )

        return errores

    def to_db_dict(self) -> dict[str, Any]:
        """Convierte cabecera a diccionario para base de datos."""
        data = {
            "fecha": self.fecha.isoformat(),
            "concepto": self.concepto,
            "tipo": self.tipo.value,
            "total_debe": float(self.total_debe),
            "total_haber": float(self.total_haber),
            "estado": self.estado.value,
        }

        if self.referencia:
            data["referencia"] = self.referencia
        if self.origen_tipo:
            data["origen_tipo"] = self.origen_tipo.value
        if self.origen_id:
            data["origen_id"] = str(self.origen_id)
        if self.created_by:
            data["created_by"] = str(self.created_by)

        return data


class PeriodoContable(BaseModel):
    """Período contable (mes)."""

    id: UUID | None = None
    anio: int
    mes: int = Field(..., ge=1, le=12)
    nombre: str

    fecha_inicio: date
    fecha_fin: date

    estado: str = "abierto"  # abierto, cerrado, ajuste
    fecha_cierre: datetime | None = None

    @property
    def esta_abierto(self) -> bool:
        """Indica si el período está abierto."""
        return self.estado == "abierto"


class SaldoCuenta(BaseModel):
    """Saldo de una cuenta en un período."""

    cuenta_codigo: str
    cuenta_nombre: str | None = None
    periodo_id: UUID | None = None

    saldo_inicial: Decimal = Decimal("0")
    total_debe: Decimal = Decimal("0")
    total_haber: Decimal = Decimal("0")
    saldo_final: Decimal = Decimal("0")

    cantidad_movimientos: int = 0


class BalanceComprobacion(BaseModel):
    """Balance de comprobación."""

    fecha_corte: date
    periodo: str | None = None

    cuentas: list[SaldoCuenta] = Field(default_factory=list)

    total_debe: Decimal = Decimal("0")
    total_haber: Decimal = Decimal("0")

    @property
    def esta_cuadrado(self) -> bool:
        """Verifica si el balance cuadra."""
        return self.total_debe == self.total_haber


class ComisionSplit(BaseModel):
    """
    Registro de split de comisión.

    Para el modelo de negocio de alquiler:
    - 1.5% es ingreso (comisión)
    - 98.5% es pasivo (a pagar al propietario)
    """

    id: UUID | None = None

    # Origen
    transaccion_id: UUID | None = None
    comprobante_id: UUID | None = None

    # Montos
    monto_bruto: Decimal
    porcentaje_comision: Decimal = Decimal("0.015")  # 1.5%

    monto_comision: Decimal = Decimal("0")
    monto_propietario: Decimal = Decimal("0")

    # Contabilización
    asiento_id: UUID | None = None

    # Propietario
    propietario_id: UUID | None = None
    vehiculo_id: UUID | None = None

    # Estado
    estado: str = "pendiente"  # pendiente, contabilizado, pagado, anulado

    # Pago
    fecha_pago: datetime | None = None
    referencia_pago: str | None = None

    @model_validator(mode="after")
    def calcular_montos(self):
        """Calcula los montos de comisión y propietario."""
        if self.monto_comision == Decimal("0"):
            self.monto_comision = (
                self.monto_bruto * self.porcentaje_comision
            ).quantize(Decimal("0.01"))
        if self.monto_propietario == Decimal("0"):
            self.monto_propietario = self.monto_bruto - self.monto_comision
        return self

    def to_db_dict(self) -> dict[str, Any]:
        """Convierte a diccionario para base de datos."""
        data = {
            "monto_bruto": float(self.monto_bruto),
            "porcentaje_comision": float(self.porcentaje_comision),
            "monto_comision": float(self.monto_comision),
            "monto_propietario": float(self.monto_propietario),
            "estado": self.estado,
        }

        if self.transaccion_id:
            data["transaccion_id"] = str(self.transaccion_id)
        if self.comprobante_id:
            data["comprobante_id"] = str(self.comprobante_id)
        if self.asiento_id:
            data["asiento_id"] = str(self.asiento_id)
        if self.propietario_id:
            data["propietario_id"] = str(self.propietario_id)
        if self.vehiculo_id:
            data["vehiculo_id"] = str(self.vehiculo_id)

        return data
