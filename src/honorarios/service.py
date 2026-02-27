"""
ECUCONDOR - Servicio de Honorarios
Gestiona pagos de honorarios al administrador (IESS código 109).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.db.supabase import SupabaseClient, get_supabase_client
from src.honorarios.calculator import HonorarioCalculator
from src.honorarios.models import (
    Administrador,
    CalculoHonorario,
    EstadoPago,
    PagoHonorario,
    ResumenAnual,
)
from src.ledger.journal import JournalService
from src.ledger.models import AsientoContable, OrigenAsiento

logger = structlog.get_logger(__name__)


# Cuentas contables para honorarios
CUENTA_GASTOS_HONORARIOS = "5.2.08"
CUENTA_IESS_PATRONAL_POR_PAGAR = "2.1.06"
CUENTA_IESS_PERSONAL_POR_PAGAR = "2.1.06"
CUENTA_RETENCION_POR_PAGAR = "2.1.07"
CUENTA_BANCOS = "1.1.03"
CUENTA_HONORARIOS_POR_PAGAR = "2.1.01"


class HonorariosService:
    """
    Servicio para gestión de honorarios del administrador.

    Responsabilidades:
    - Registrar administradores
    - Calcular y registrar pagos de honorarios
    - Generar asientos contables
    - Generar reportes anuales
    """

    def __init__(
        self,
        db: SupabaseClient | None = None,
        calculator: HonorarioCalculator | None = None,
        journal: JournalService | None = None,
    ):
        """
        Inicializa el servicio.

        Args:
            db: Cliente de Supabase
            calculator: Calculador de honorarios
            journal: Servicio de libro diario
        """
        self.db = db or get_supabase_client()
        self.calculator = calculator or HonorarioCalculator(self.db)
        self.journal = journal or JournalService(self.db)

    async def crear_administrador(
        self,
        tipo_identificacion: str,
        identificacion: str,
        nombres: str,
        apellidos: str,
        **kwargs,
    ) -> Administrador:
        """
        Crea un nuevo administrador.

        Args:
            tipo_identificacion: Tipo de identificación
            identificacion: Número de identificación
            nombres: Nombres
            apellidos: Apellidos
            **kwargs: Campos adicionales

        Returns:
            Administrador creado
        """
        admin = Administrador(
            tipo_identificacion=tipo_identificacion,
            identificacion=identificacion,
            nombres=nombres,
            apellidos=apellidos,
            razon_social=f"{nombres} {apellidos}",
            **kwargs,
        )

        data = admin.to_db_dict()
        result = await self.db.insert("administradores", data)

        if result["data"]:
            admin.id = UUID(result["data"][0]["id"])

        logger.info(
            "Administrador creado",
            id=str(admin.id),
            identificacion=identificacion,
            nombre=admin.razon_social,
        )

        return admin

    async def crear_pago(
        self,
        administrador_id: UUID,
        anio: int,
        mes: int,
        honorario_bruto: Decimal,
        *,
        auto_contabilizar: bool = True,
    ) -> tuple[PagoHonorario, AsientoContable | None]:
        """
        Crea un pago de honorarios.

        Este es el método principal que:
        1. Calcula IESS y retención
        2. Crea el registro de pago
        3. Genera el asiento contable

        Args:
            administrador_id: ID del administrador
            anio: Año del pago
            mes: Mes del pago
            honorario_bruto: Monto bruto del honorario
            auto_contabilizar: Si True, genera asiento automático

        Returns:
            Tupla (PagoHonorario, AsientoContable)

        Raises:
            ValueError: Si ya existe un pago para ese período
        """
        # Verificar que no exista pago para el período
        periodo = f"{anio:04d}-{mes:02d}"
        existente = await self._obtener_pago_por_periodo(administrador_id, periodo)
        if existente:
            raise ValueError(f"Ya existe un pago para el período {periodo}")

        # Calcular honorario
        fecha_calculo = date(anio, mes, 1)
        calculo = await self.calculator.calcular(honorario_bruto, fecha_calculo, anio)

        # Crear pago
        pago = PagoHonorario.from_calculo(
            administrador_id=administrador_id,
            anio=anio,
            mes=mes,
            calculo=calculo,
        )

        # Guardar en base de datos
        data = pago.to_db_dict()
        result = await self.db.insert("pagos_honorarios", data)

        if result["data"]:
            pago.id = UUID(result["data"][0]["id"])

        logger.info(
            "Pago de honorarios creado",
            id=str(pago.id),
            periodo=periodo,
            bruto=float(honorario_bruto),
            neto=float(pago.neto_pagar),
        )

        # Generar asiento contable si se solicita
        asiento = None
        if auto_contabilizar:
            asiento = await self._generar_asiento_provision(pago, fecha_calculo)
            await self.db.update(
                "pagos_honorarios",
                {"asiento_id": str(asiento.id)},
                {"id": str(pago.id)}
            )
            pago.asiento_id = asiento.id

        return pago, asiento

    async def aprobar_pago(
        self,
        pago_id: UUID,
        usuario_id: UUID | None = None,
    ) -> PagoHonorario:
        """
        Aprueba un pago de honorarios.

        Args:
            pago_id: ID del pago
            usuario_id: ID del usuario que aprueba

        Returns:
            Pago actualizado
        """
        await self.db.update(
            "pagos_honorarios",
            {
                "estado": EstadoPago.APROBADO.value,
                "approved_by": str(usuario_id) if usuario_id else None,
            },
            {"id": str(pago_id)}
        )

        pago = await self.obtener_pago(pago_id)
        logger.info("Pago de honorarios aprobado", id=str(pago_id))

        return pago

    async def registrar_pago(
        self,
        pago_id: UUID,
        fecha_pago: date,
        referencia_pago: str,
        *,
        auto_contabilizar: bool = True,
    ) -> tuple[PagoHonorario, AsientoContable | None]:
        """
        Registra el pago efectivo de un honorario.

        Args:
            pago_id: ID del pago
            fecha_pago: Fecha del pago
            referencia_pago: Referencia de transferencia/cheque
            auto_contabilizar: Si True, genera asiento de pago

        Returns:
            Tupla (PagoHonorario, AsientoContable de pago)
        """
        pago = await self.obtener_pago(pago_id)

        if pago.estado == EstadoPago.PAGADO:
            raise ValueError("El pago ya fue registrado")

        # Actualizar pago
        await self.db.update(
            "pagos_honorarios",
            {
                "estado": EstadoPago.PAGADO.value,
                "fecha_pago": datetime.now().isoformat(),
                "referencia_pago": referencia_pago,
            },
            {"id": str(pago_id)}
        )

        pago.estado = EstadoPago.PAGADO
        pago.referencia_pago = referencia_pago

        # Generar asiento de pago
        asiento = None
        if auto_contabilizar:
            asiento = await self._generar_asiento_pago(pago, fecha_pago, referencia_pago)

        logger.info(
            "Pago de honorarios registrado",
            id=str(pago_id),
            monto=float(pago.neto_pagar),
            referencia=referencia_pago,
        )

        return pago, asiento

    async def obtener_pago(self, pago_id: UUID) -> PagoHonorario:
        """Obtiene un pago por ID."""
        result = await self.db.select(
            "pagos_honorarios",
            filters={"id": str(pago_id)}
        )

        if not result["data"]:
            raise ValueError(f"Pago no encontrado: {pago_id}")

        return self._from_db(result["data"][0])

    async def listar_pagos_pendientes(
        self,
        administrador_id: UUID | None = None,
    ) -> list[PagoHonorario]:
        """Lista pagos pendientes de aprobación o pago."""
        filters: dict[str, Any] = {
            "estado": {"in": ["pendiente", "aprobado"]}
        }
        if administrador_id:
            filters["administrador_id"] = str(administrador_id)

        result = await self.db.select(
            "pagos_honorarios",
            filters=filters,
            order="-periodo",
        )

        return [self._from_db(d) for d in (result["data"] or [])]

    async def obtener_resumen_anual(
        self,
        administrador_id: UUID,
        anio: int,
    ) -> ResumenAnual:
        """
        Obtiene resumen anual de honorarios.

        Args:
            administrador_id: ID del administrador
            anio: Año a consultar

        Returns:
            ResumenAnual con totales
        """
        result = await self.db.select(
            "v_resumen_honorarios_anual",
            filters={
                "administrador_id": str(administrador_id),
                "anio": anio,
            }
        )

        if not result["data"]:
            # Obtener datos del administrador
            admin_result = await self.db.select(
                "administradores",
                columns="razon_social, identificacion",
                filters={"id": str(administrador_id)}
            )
            admin = admin_result["data"][0] if admin_result["data"] else {}

            return ResumenAnual(
                administrador_id=administrador_id,
                razon_social=admin.get("razon_social", ""),
                identificacion=admin.get("identificacion", ""),
                anio=anio,
            )

        data = result["data"][0]
        return ResumenAnual(
            administrador_id=UUID(data["administrador_id"]),
            razon_social=data["razon_social"],
            identificacion=data["identificacion"],
            anio=data["anio"],
            total_pagos=data["total_pagos"],
            total_honorarios=Decimal(str(data["total_honorarios"])),
            total_aporte_patronal=Decimal(str(data["total_aporte_patronal"])),
            total_aporte_personal=Decimal(str(data["total_aporte_personal"])),
            total_iess=Decimal(str(data["total_iess"])),
            total_retencion=Decimal(str(data["total_retencion"])),
            total_neto=Decimal(str(data["total_neto"])),
        )

    async def _generar_asiento_provision(
        self,
        pago: PagoHonorario,
        fecha: date,
    ) -> AsientoContable:
        """
        Genera asiento de provisión del honorario.

        Asiento:
        - Debe: Gastos de honorarios (bruto)
        - Debe: Aporte patronal IESS (gasto)
        - Haber: Honorarios por pagar (neto)
        - Haber: IESS por pagar (aporte personal + patronal)
        - Haber: Retenciones por pagar
        """
        movimientos = []

        # Debe: Gasto honorarios (bruto)
        movimientos.append({
            "cuenta": CUENTA_GASTOS_HONORARIOS,
            "debe": pago.honorario_bruto,
            "haber": Decimal("0"),
            "concepto": "Honorarios profesionales",
        })

        # Debe: Aporte patronal (es gasto de la empresa)
        movimientos.append({
            "cuenta": CUENTA_GASTOS_HONORARIOS,
            "debe": pago.aporte_patronal,
            "haber": Decimal("0"),
            "concepto": "Aporte patronal IESS 12.15%",
        })

        # Haber: Por pagar al administrador (neto)
        movimientos.append({
            "cuenta": CUENTA_HONORARIOS_POR_PAGAR,
            "debe": Decimal("0"),
            "haber": pago.neto_pagar,
            "concepto": f"Por pagar administrador {pago.periodo}",
        })

        # Haber: IESS por pagar (personal + patronal)
        if pago.total_iess > 0:
            movimientos.append({
                "cuenta": CUENTA_IESS_PATRONAL_POR_PAGAR,
                "debe": Decimal("0"),
                "haber": pago.total_iess,
                "concepto": "IESS por pagar (código 109)",
            })

        # Haber: Retención por pagar
        if pago.retencion_renta > 0:
            movimientos.append({
                "cuenta": CUENTA_RETENCION_POR_PAGAR,
                "debe": Decimal("0"),
                "haber": pago.retencion_renta,
                "concepto": f"Retención fuente {pago.porcentaje_retencion * 100}%",
            })

        # Crear asiento
        asiento = await self.journal.crear_asiento(
            fecha=fecha,
            concepto=f"Provisión honorarios {pago.periodo}",
            movimientos=movimientos,
            referencia=pago.periodo,
            origen_tipo=OrigenAsiento.MANUAL,
            origen_id=pago.id,
            auto_contabilizar=True,
        )

        return asiento

    async def _generar_asiento_pago(
        self,
        pago: PagoHonorario,
        fecha_pago: date,
        referencia: str,
    ) -> AsientoContable:
        """
        Genera asiento del pago efectivo.

        Asiento:
        - Debe: Honorarios por pagar
        - Haber: Bancos
        """
        asiento = await self.journal.crear_asiento_simple(
            fecha=fecha_pago,
            concepto=f"Pago honorarios {pago.periodo} - Ref: {referencia}",
            cuenta_debe=CUENTA_HONORARIOS_POR_PAGAR,
            cuenta_haber=CUENTA_BANCOS,
            monto=pago.neto_pagar,
            referencia=referencia,
            origen_tipo=OrigenAsiento.MANUAL,
            origen_id=pago.id,
            auto_contabilizar=True,
        )

        return asiento

    async def _obtener_pago_por_periodo(
        self,
        administrador_id: UUID,
        periodo: str,
    ) -> PagoHonorario | None:
        """Busca un pago por período."""
        result = await self.db.select(
            "pagos_honorarios",
            filters={
                "administrador_id": str(administrador_id),
                "periodo": periodo,
            }
        )

        if result["data"]:
            return self._from_db(result["data"][0])
        return None

    def _from_db(self, data: dict[str, Any]) -> PagoHonorario:
        """Construye PagoHonorario desde datos de DB."""
        return PagoHonorario(
            id=UUID(data["id"]),
            administrador_id=UUID(data["administrador_id"]),
            anio=data["anio"],
            mes=data["mes"],
            periodo=data["periodo"],
            honorario_bruto=Decimal(str(data["honorario_bruto"])),
            aporte_patronal=Decimal(str(data["aporte_patronal"])),
            aporte_personal=Decimal(str(data["aporte_personal"])),
            total_iess=Decimal(str(data["total_iess"])),
            base_imponible_renta=Decimal(str(data["base_imponible_renta"])),
            retencion_renta=Decimal(str(data["retencion_renta"])),
            porcentaje_retencion=Decimal(str(data["porcentaje_retencion"])),
            neto_pagar=Decimal(str(data["neto_pagar"])),
            estado=EstadoPago(data["estado"]),
            referencia_pago=data.get("referencia_pago"),
            asiento_id=UUID(data["asiento_id"]) if data.get("asiento_id") else None,
            notas=data.get("notas"),
        )


def get_honorarios_service() -> HonorariosService:
    """Factory function para el servicio de honorarios."""
    return HonorariosService()
