"""
ECUCONDOR - Modelos de Honorarios
Modelos para gestión de honorarios profesionales (IESS código 109).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class EstadoPago(str, Enum):
    """Estados de un pago de honorarios."""
    PENDIENTE = "pendiente"
    APROBADO = "aprobado"
    PAGADO = "pagado"
    ANULADO = "anulado"


class TipoCuenta(str, Enum):
    """Tipos de cuenta bancaria."""
    CORRIENTE = "corriente"
    AHORROS = "ahorros"


class Administrador(BaseModel):
    """
    Administrador de la empresa.

    Representa a una persona que recibe honorarios profesionales
    bajo el código IESS 109 (sin relación de dependencia).
    """

    id: UUID | None = None

    # Identificación
    tipo_identificacion: str = Field(..., pattern=r"^(04|05|06|07|08)$")
    identificacion: str = Field(..., min_length=10, max_length=13)
    nombres: str = Field(..., min_length=1, max_length=100)
    apellidos: str = Field(..., min_length=1, max_length=100)
    razon_social: str = Field(..., min_length=1, max_length=300)

    # Contacto
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None

    # IESS
    numero_iess: str | None = None
    codigo_actividad: str = "109"  # Honorarios profesionales

    # Bancario
    banco: str | None = None
    numero_cuenta: str | None = None
    tipo_cuenta: TipoCuenta | None = None

    # Estado
    activo: bool = True
    fecha_inicio: date | None = None
    fecha_fin: date | None = None

    # Auditoría
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_db_dict(self) -> dict[str, Any]:
        """Convierte a diccionario para base de datos."""
        return {
            "tipo_identificacion": self.tipo_identificacion,
            "identificacion": self.identificacion,
            "nombres": self.nombres,
            "apellidos": self.apellidos,
            "razon_social": self.razon_social,
            "email": self.email,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "numero_iess": self.numero_iess,
            "codigo_actividad": self.codigo_actividad,
            "banco": self.banco,
            "numero_cuenta": self.numero_cuenta,
            "tipo_cuenta": self.tipo_cuenta.value if self.tipo_cuenta else None,
            "activo": self.activo,
            "fecha_inicio": self.fecha_inicio.isoformat() if self.fecha_inicio else None,
            "fecha_fin": self.fecha_fin.isoformat() if self.fecha_fin else None,
        }


class CalculoIESS(BaseModel):
    """Resultado del cálculo de aportes IESS código 109."""

    honorario_bruto: Decimal

    # Porcentajes
    porcentaje_aporte_patronal: Decimal = Decimal("0.1215")  # 12.15%
    porcentaje_aporte_personal: Decimal = Decimal("0.0945")  # 9.45%

    # Montos calculados
    aporte_patronal: Decimal = Decimal("0")
    aporte_personal: Decimal = Decimal("0")
    total_iess: Decimal = Decimal("0")

    @model_validator(mode="after")
    def calcular_aportes(self):
        """Calcula los aportes IESS."""
        self.aporte_patronal = (
            self.honorario_bruto * self.porcentaje_aporte_patronal
        ).quantize(Decimal("0.01"))

        self.aporte_personal = (
            self.honorario_bruto * self.porcentaje_aporte_personal
        ).quantize(Decimal("0.01"))

        self.total_iess = self.aporte_patronal + self.aporte_personal

        return self


class CalculoRetencion(BaseModel):
    """Resultado del cálculo de retención en la fuente."""

    base_imponible: Decimal
    porcentaje_retencion: Decimal = Decimal("0.08")  # 8%
    base_minima: Decimal = Decimal("0")

    retencion: Decimal = Decimal("0")
    aplica_retencion: bool = True

    @model_validator(mode="after")
    def calcular_retencion(self):
        """Calcula la retención."""
        if self.base_imponible >= self.base_minima:
            self.retencion = (
                self.base_imponible * self.porcentaje_retencion
            ).quantize(Decimal("0.01"))
            self.aplica_retencion = True
        else:
            self.retencion = Decimal("0")
            self.aplica_retencion = False

        return self


class CalculoHonorario(BaseModel):
    """
    Cálculo completo de honorario.

    Incluye IESS y retención en la fuente.
    """

    honorario_bruto: Decimal

    # IESS
    calculo_iess: CalculoIESS

    # Retención
    calculo_retencion: CalculoRetencion

    # Neto a pagar
    neto_pagar: Decimal = Decimal("0")

    @model_validator(mode="after")
    def calcular_neto(self):
        """Calcula el neto a pagar."""
        # Neto = Bruto - Aporte Personal - Retención
        self.neto_pagar = (
            self.honorario_bruto
            - self.calculo_iess.aporte_personal
            - self.calculo_retencion.retencion
        )
        return self

    @property
    def total_descuentos(self) -> Decimal:
        """Total de descuentos al empleado."""
        return self.calculo_iess.aporte_personal + self.calculo_retencion.retencion

    @property
    def costo_empresa(self) -> Decimal:
        """Costo total para la empresa."""
        # Honorario bruto + Aporte patronal
        return self.honorario_bruto + self.calculo_iess.aporte_patronal


class PagoHonorario(BaseModel):
    """
    Pago de honorario al administrador.

    Representa el pago mensual con todos los cálculos.
    """

    id: UUID | None = None

    # Relaciones
    administrador_id: UUID
    administrador: Administrador | None = None

    # Período
    anio: int = Field(..., ge=2020, le=2100)
    mes: int = Field(..., ge=1, le=12)
    periodo: str = Field(..., pattern=r"^\d{4}-\d{2}$")  # "2025-01"

    # Montos
    honorario_bruto: Decimal

    # IESS
    aporte_patronal: Decimal = Decimal("0")
    aporte_personal: Decimal = Decimal("0")
    total_iess: Decimal = Decimal("0")

    # Retención
    base_imponible_renta: Decimal = Decimal("0")
    retencion_renta: Decimal = Decimal("0")
    porcentaje_retencion: Decimal = Decimal("0")

    # Neto
    neto_pagar: Decimal = Decimal("0")

    # Estado
    estado: EstadoPago = EstadoPago.PENDIENTE

    # Pago
    fecha_pago: datetime | None = None
    referencia_pago: str | None = None
    asiento_id: UUID | None = None

    # Comprobantes
    comprobante_retencion_id: UUID | None = None

    # Observaciones
    notas: str | None = None

    # Auditoría
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_calculo(
        cls,
        administrador_id: UUID,
        anio: int,
        mes: int,
        calculo: CalculoHonorario,
    ) -> "PagoHonorario":
        """Crea un PagoHonorario desde un CalculoHonorario."""
        periodo = f"{anio:04d}-{mes:02d}"

        return cls(
            administrador_id=administrador_id,
            anio=anio,
            mes=mes,
            periodo=periodo,
            honorario_bruto=calculo.honorario_bruto,
            aporte_patronal=calculo.calculo_iess.aporte_patronal,
            aporte_personal=calculo.calculo_iess.aporte_personal,
            total_iess=calculo.calculo_iess.total_iess,
            base_imponible_renta=calculo.calculo_retencion.base_imponible,
            retencion_renta=calculo.calculo_retencion.retencion,
            porcentaje_retencion=calculo.calculo_retencion.porcentaje_retencion,
            neto_pagar=calculo.neto_pagar,
        )

    def to_db_dict(self) -> dict[str, Any]:
        """Convierte a diccionario para base de datos."""
        return {
            "administrador_id": str(self.administrador_id),
            "anio": self.anio,
            "mes": self.mes,
            "periodo": self.periodo,
            "honorario_bruto": float(self.honorario_bruto),
            "aporte_patronal": float(self.aporte_patronal),
            "aporte_personal": float(self.aporte_personal),
            "total_iess": float(self.total_iess),
            "base_imponible_renta": float(self.base_imponible_renta),
            "retencion_renta": float(self.retencion_renta),
            "porcentaje_retencion": float(self.porcentaje_retencion),
            "neto_pagar": float(self.neto_pagar),
            "estado": self.estado.value,
            "notas": self.notas,
        }


class ResumenAnual(BaseModel):
    """Resumen anual de honorarios de un administrador."""

    administrador_id: UUID
    razon_social: str
    identificacion: str
    anio: int

    total_pagos: int = 0
    total_honorarios: Decimal = Decimal("0")
    total_aporte_patronal: Decimal = Decimal("0")
    total_aporte_personal: Decimal = Decimal("0")
    total_iess: Decimal = Decimal("0")
    total_retencion: Decimal = Decimal("0")
    total_neto: Decimal = Decimal("0")


class ParametrosIESS(BaseModel):
    """Parámetros IESS para un código de actividad."""

    id: UUID | None = None
    codigo_actividad: str = "109"
    vigencia_desde: date
    vigencia_hasta: date | None = None

    porcentaje_aporte_patronal: Decimal = Decimal("0.1215")
    porcentaje_aporte_personal: Decimal = Decimal("0.0945")

    salario_basico_unificado: Decimal | None = None
    tope_maximo_aportacion: Decimal | None = None

    activo: bool = True


class ParametrosRetencion(BaseModel):
    """Parámetros de retención en la fuente."""

    id: UUID | None = None
    anio: int
    tipo_servicio: str = "honorarios_profesionales"

    porcentaje_retencion: Decimal = Decimal("0.08")
    base_minima: Decimal = Decimal("0")

    # Tabla progresiva (si aplica)
    fraccion_basica: Decimal | None = None
    exceso_hasta: Decimal | None = None
    impuesto_fraccion_basica: Decimal | None = None
    porcentaje_excedente: Decimal | None = None

    activo: bool = True
