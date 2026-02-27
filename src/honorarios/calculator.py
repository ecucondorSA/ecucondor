"""
ECUCONDOR - Calculador de Honorarios
Calcula aportes IESS código 109 y retención en la fuente.
"""

from datetime import date
from decimal import Decimal

import structlog

from src.db.supabase import SupabaseClient, get_supabase_client
from src.honorarios.models import (
    CalculoHonorario,
    CalculoIESS,
    CalculoRetencion,
)

logger = structlog.get_logger(__name__)


# Valores por defecto (Ecuador 2025)
PORCENTAJE_APORTE_PATRONAL_DEFAULT = Decimal("0.1215")  # 12.15%
PORCENTAJE_APORTE_PERSONAL_DEFAULT = Decimal("0.0945")   # 9.45%
PORCENTAJE_RETENCION_DEFAULT = Decimal("0.08")           # 8%


class HonorarioCalculator:
    """
    Calculador de honorarios profesionales IESS código 109.

    Responsabilidades:
    - Calcular aportes IESS (patronal + personal)
    - Calcular retención en la fuente
    - Calcular neto a pagar
    """

    def __init__(self, db: SupabaseClient | None = None):
        """
        Inicializa el calculador.

        Args:
            db: Cliente de Supabase
        """
        self.db = db or get_supabase_client()

    async def calcular(
        self,
        honorario_bruto: Decimal,
        fecha: date = None,
        anio: int | None = None,
    ) -> CalculoHonorario:
        """
        Calcula el honorario completo con IESS y retención.

        Args:
            honorario_bruto: Monto bruto del honorario
            fecha: Fecha del cálculo (para obtener parámetros vigentes)
            anio: Año fiscal (para retención)

        Returns:
            CalculoHonorario con todos los valores
        """
        if fecha is None:
            fecha = date.today()
        if anio is None:
            anio = fecha.year

        # Calcular IESS
        calculo_iess = await self.calcular_iess(honorario_bruto, fecha)

        # Calcular retención (base = honorario bruto)
        calculo_retencion = await self.calcular_retencion(honorario_bruto, anio)

        # Crear cálculo completo
        calculo = CalculoHonorario(
            honorario_bruto=honorario_bruto,
            calculo_iess=calculo_iess,
            calculo_retencion=calculo_retencion,
        )

        logger.debug(
            "Honorario calculado",
            bruto=float(honorario_bruto),
            neto=float(calculo.neto_pagar),
            iess=float(calculo.calculo_iess.total_iess),
            retencion=float(calculo.calculo_retencion.retencion),
        )

        return calculo

    async def calcular_iess(
        self,
        honorario_bruto: Decimal,
        fecha: date | None = None,
    ) -> CalculoIESS:
        """
        Calcula aportes IESS código 109.

        Args:
            honorario_bruto: Monto bruto
            fecha: Fecha para obtener parámetros vigentes

        Returns:
            CalculoIESS con aportes calculados
        """
        if fecha is None:
            fecha = date.today()

        # Obtener parámetros desde la base de datos
        parametros = await self._obtener_parametros_iess(fecha)

        pct_patronal = parametros.get(
            "porcentaje_aporte_patronal",
            PORCENTAJE_APORTE_PATRONAL_DEFAULT
        )
        pct_personal = parametros.get(
            "porcentaje_aporte_personal",
            PORCENTAJE_APORTE_PERSONAL_DEFAULT
        )

        # Crear cálculo
        calculo = CalculoIESS(
            honorario_bruto=honorario_bruto,
            porcentaje_aporte_patronal=Decimal(str(pct_patronal)),
            porcentaje_aporte_personal=Decimal(str(pct_personal)),
        )

        return calculo

    async def calcular_retencion(
        self,
        base_imponible: Decimal,
        anio: int | None = None,
    ) -> CalculoRetencion:
        """
        Calcula retención en la fuente para honorarios.

        Args:
            base_imponible: Base imponible para retención
            anio: Año fiscal

        Returns:
            CalculoRetencion con valores calculados
        """
        if anio is None:
            anio = date.today().year

        # Obtener parámetros desde la base de datos
        parametros = await self._obtener_parametros_retencion(anio)

        porcentaje = parametros.get(
            "porcentaje_retencion",
            PORCENTAJE_RETENCION_DEFAULT
        )
        base_minima = parametros.get("base_minima", Decimal("0"))

        # Crear cálculo
        calculo = CalculoRetencion(
            base_imponible=base_imponible,
            porcentaje_retencion=Decimal(str(porcentaje)),
            base_minima=Decimal(str(base_minima)),
        )

        return calculo

    async def calcular_usando_funcion_sql(
        self,
        honorario_bruto: Decimal,
        fecha: date | None = None,
    ) -> CalculoIESS:
        """
        Calcula IESS usando la función SQL calcular_iess_109.

        Args:
            honorario_bruto: Monto bruto
            fecha: Fecha de cálculo

        Returns:
            CalculoIESS
        """
        if fecha is None:
            fecha = date.today()

        result = await self.db.rpc(
            "calcular_iess_109",
            {
                "p_honorario_bruto": float(honorario_bruto),
                "p_fecha": fecha.isoformat(),
            }
        )

        if not result:
            # Usar valores por defecto
            return CalculoIESS(honorario_bruto=honorario_bruto)

        data = result[0] if isinstance(result, list) else result

        return CalculoIESS(
            honorario_bruto=honorario_bruto,
            aporte_patronal=Decimal(str(data["aporte_patronal"])),
            aporte_personal=Decimal(str(data["aporte_personal"])),
            total_iess=Decimal(str(data["total_iess"])),
        )

    async def _obtener_parametros_iess(self, fecha: date) -> dict:
        """
        Obtiene parámetros IESS vigentes a una fecha.

        Args:
            fecha: Fecha de consulta

        Returns:
            Diccionario con parámetros
        """
        result = await self.db.select(
            "parametros_iess",
            columns="porcentaje_aporte_patronal, porcentaje_aporte_personal",
            filters={
                "codigo_actividad": "109",
                "activo": True,
            },
            order="-vigencia_desde",
            limit=1,
        )

        if result["data"]:
            return result["data"][0]

        # Retornar valores por defecto
        return {
            "porcentaje_aporte_patronal": float(PORCENTAJE_APORTE_PATRONAL_DEFAULT),
            "porcentaje_aporte_personal": float(PORCENTAJE_APORTE_PERSONAL_DEFAULT),
        }

    async def _obtener_parametros_retencion(self, anio: int) -> dict:
        """
        Obtiene parámetros de retención para un año.

        Args:
            anio: Año fiscal

        Returns:
            Diccionario con parámetros
        """
        result = await self.db.select(
            "parametros_retencion_renta",
            columns="porcentaje_retencion, base_minima",
            filters={
                "anio": anio,
                "tipo_servicio": "honorarios_profesionales",
                "activo": True,
            },
            order="-created_at",
            limit=1,
        )

        if result["data"]:
            return result["data"][0]

        # Retornar valores por defecto
        return {
            "porcentaje_retencion": float(PORCENTAJE_RETENCION_DEFAULT),
            "base_minima": 0.0,
        }


def get_calculator() -> HonorarioCalculator:
    """Factory function para el calculador."""
    return HonorarioCalculator()


# Función de conveniencia
async def calcular_honorario_rapido(
    monto: Decimal,
    fecha: date | None = None,
) -> CalculoHonorario:
    """
    Calcula un honorario de forma rápida.

    Args:
        monto: Monto bruto del honorario
        fecha: Fecha de cálculo

    Returns:
        CalculoHonorario completo
    """
    calculator = get_calculator()
    return await calculator.calcular(monto, fecha)
