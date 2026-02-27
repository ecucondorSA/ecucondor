"""
ECUCONDOR - Honorarios del Administrador
Gestión de honorarios profesionales IESS código 109.
"""

from src.honorarios.models import (
    Administrador,
    CalculoHonorario,
    CalculoIESS,
    CalculoRetencion,
    EstadoPago,
    PagoHonorario,
    ResumenAnual,
)
from src.honorarios.calculator import (
    HonorarioCalculator,
    calcular_honorario_rapido,
    get_calculator,
)
from src.honorarios.service import (
    HonorariosService,
    get_honorarios_service,
)

__all__ = [
    # Modelos
    "Administrador",
    "CalculoHonorario",
    "CalculoIESS",
    "CalculoRetencion",
    "EstadoPago",
    "PagoHonorario",
    "ResumenAnual",
    # Servicios
    "HonorarioCalculator",
    "HonorariosService",
    # Factory functions
    "get_calculator",
    "get_honorarios_service",
    # Utilidades
    "calcular_honorario_rapido",
]
