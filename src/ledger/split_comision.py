"""
ECUCONDOR - Servicio de Split de Comisión
Implementa la lógica de negocio del modelo de alquiler de vehículos.

Modelo de negocio:
- La empresa cobra por alquiler de vehículos
- Del total cobrado, 1.5% es comisión (ingreso)
- El 98.5% restante es un pasivo (a pagar al propietario del vehículo)

Contabilización:
- Debe: 1.1.03 Bancos (total recibido)
- Haber: 4.1.01 Ingresos por servicios (1.5% comisión)
- Haber: 2.1.09 Cuentas por pagar propietarios (98.5%)
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import structlog

from src.config.settings import get_settings
from src.db.supabase import SupabaseClient, get_supabase_client
from src.ledger.journal import JournalService
from src.ledger.models import (
    AsientoContable,
    ComisionSplit,
    OrigenAsiento,
    TipoAsiento,
)

logger = structlog.get_logger(__name__)


# Cuentas contables para el split de comisión
CUENTA_BANCOS = "1.1.03"
CUENTA_INGRESO_COMISION = "4.1.01"
CUENTA_PASIVO_PROPIETARIO = "2.1.09"
CUENTA_IVA_COBRADO = "2.1.04"  # IVA en ventas

# Para gastos relacionados
CUENTA_IVA_PAGADO = "1.1.05"  # IVA en compras


class ComisionSplitService:
    """
    Servicio para gestión de splits de comisión.

    Responsabilidades:
    - Calcular el split de comisión (1.5% / 98.5%)
    - Generar asientos contables automáticos
    - Registrar y consultar comisiones
    - Gestionar pagos a propietarios
    """

    def __init__(
        self,
        db: SupabaseClient | None = None,
        journal: JournalService | None = None,
    ):
        """
        Inicializa el servicio.

        Args:
            db: Cliente de Supabase
            journal: Servicio de libro diario
        """
        self.db = db or get_supabase_client()
        self.journal = journal or JournalService(self.db)

        settings = get_settings()
        self.porcentaje_comision = Decimal(str(settings.comision_porcentaje))
        self.porcentaje_iva = Decimal(str(settings.iva_porcentaje))

    def calcular_split(
        self,
        monto_bruto: Decimal,
        porcentaje_comision: Decimal | None = None,
    ) -> ComisionSplit:
        """
        Calcula el split de comisión para un monto.

        Args:
            monto_bruto: Monto total recibido
            porcentaje_comision: Porcentaje de comisión (default: 1.5%)

        Returns:
            ComisionSplit con montos calculados
        """
        pct = porcentaje_comision or self.porcentaje_comision

        # Calcular comisión (redondeado a 2 decimales)
        monto_comision = (monto_bruto * pct).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # El resto va al propietario
        monto_propietario = monto_bruto - monto_comision

        return ComisionSplit(
            monto_bruto=monto_bruto,
            porcentaje_comision=pct,
            monto_comision=monto_comision,
            monto_propietario=monto_propietario,
        )

    async def procesar_cobro(
        self,
        monto_bruto: Decimal,
        fecha: date,
        concepto: str,
        *,
        transaccion_id: UUID | None = None,
        comprobante_id: UUID | None = None,
        propietario_id: UUID | None = None,
        vehiculo_id: UUID | None = None,
        incluye_iva: bool = False,
        auto_contabilizar: bool = True,
    ) -> tuple[ComisionSplit, AsientoContable]:
        """
        Procesa un cobro y genera el split de comisión.

        Este es el método principal que:
        1. Calcula el split de comisión
        2. Crea el asiento contable
        3. Registra el split en la base de datos

        Args:
            monto_bruto: Monto total cobrado
            fecha: Fecha del cobro
            concepto: Descripción del cobro
            transaccion_id: ID de la transacción bancaria (si aplica)
            comprobante_id: ID del comprobante electrónico (si aplica)
            propietario_id: ID del propietario del vehículo
            vehiculo_id: ID del vehículo
            incluye_iva: Si True, desglosa el IVA de la comisión
            auto_contabilizar: Si True, contabiliza automáticamente

        Returns:
            Tupla (ComisionSplit, AsientoContable)
        """
        # Calcular split
        split = self.calcular_split(monto_bruto)
        split.transaccion_id = transaccion_id
        split.comprobante_id = comprobante_id
        split.propietario_id = propietario_id
        split.vehiculo_id = vehiculo_id

        # Preparar movimientos contables
        movimientos = self._generar_movimientos_cobro(
            split, concepto, incluye_iva
        )

        # Crear asiento
        asiento = await self.journal.crear_asiento(
            fecha=fecha,
            concepto=f"Split comisión: {concepto}",
            movimientos=movimientos,
            tipo=TipoAsiento.AUTOMATICO,
            origen_tipo=OrigenAsiento.COMISION,
            origen_id=transaccion_id or comprobante_id,
            auto_contabilizar=auto_contabilizar,
        )

        # Guardar split
        split.asiento_id = asiento.id
        split.estado = "contabilizado" if auto_contabilizar else "pendiente"
        split = await self._guardar_split(split)

        logger.info(
            "Cobro procesado con split de comisión",
            monto_bruto=float(monto_bruto),
            comision=float(split.monto_comision),
            propietario=float(split.monto_propietario),
            asiento_id=str(asiento.id),
        )

        return split, asiento

    def _generar_movimientos_cobro(
        self,
        split: ComisionSplit,
        concepto: str,
        incluye_iva: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Genera los movimientos contables para un cobro.

        Asiento tipo:
        - Debe: Bancos (total)
        - Haber: Ingresos por comisión (1.5%)
        - Haber: Pasivo propietario (98.5%)

        Si incluye_iva (para facturación propia):
        - Debe: Bancos (total)
        - Haber: Ingresos por comisión (base)
        - Haber: IVA cobrado
        - Haber: Pasivo propietario

        Args:
            split: Split de comisión calculado
            concepto: Concepto del asiento
            incluye_iva: Si desglosa IVA

        Returns:
            Lista de movimientos para el asiento
        """
        movimientos = []

        # Debe: Bancos (total recibido)
        movimientos.append({
            "cuenta": CUENTA_BANCOS,
            "debe": split.monto_bruto,
            "haber": Decimal("0"),
            "concepto": f"Cobro {concepto}",
        })

        if incluye_iva:
            # Calcular base e IVA de la comisión
            # comision_con_iva = base * (1 + iva%)
            # base = comision_con_iva / (1 + iva%)
            divisor = Decimal("1") + self.porcentaje_iva
            base_comision = (split.monto_comision / divisor).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            iva_comision = split.monto_comision - base_comision

            # Haber: Ingreso comisión (base)
            movimientos.append({
                "cuenta": CUENTA_INGRESO_COMISION,
                "debe": Decimal("0"),
                "haber": base_comision,
                "concepto": f"Comisión {split.porcentaje_comision * 100}% (base)",
            })

            # Haber: IVA cobrado
            movimientos.append({
                "cuenta": CUENTA_IVA_COBRADO,
                "debe": Decimal("0"),
                "haber": iva_comision,
                "concepto": f"IVA sobre comisión",
            })
        else:
            # Sin desglose de IVA
            # Haber: Ingreso comisión (total)
            movimientos.append({
                "cuenta": CUENTA_INGRESO_COMISION,
                "debe": Decimal("0"),
                "haber": split.monto_comision,
                "concepto": f"Comisión {split.porcentaje_comision * 100}%",
            })

        # Haber: Pasivo propietario
        movimientos.append({
            "cuenta": CUENTA_PASIVO_PROPIETARIO,
            "debe": Decimal("0"),
            "haber": split.monto_propietario,
            "concepto": f"Por pagar a propietario ({(1 - split.porcentaje_comision) * 100}%)",
        })

        return movimientos

    async def registrar_pago_propietario(
        self,
        split_id: UUID,
        fecha_pago: date,
        referencia_pago: str,
        *,
        auto_contabilizar: bool = True,
    ) -> tuple[ComisionSplit, AsientoContable]:
        """
        Registra el pago al propietario del vehículo.

        Asiento:
        - Debe: Cuentas por pagar propietarios
        - Haber: Bancos

        Args:
            split_id: ID del split de comisión
            fecha_pago: Fecha del pago
            referencia_pago: Referencia de transferencia/cheque
            auto_contabilizar: Si True, contabiliza automáticamente

        Returns:
            Tupla (ComisionSplit actualizado, Asiento del pago)
        """
        # Obtener split
        split = await self.obtener_por_id(split_id)
        if not split:
            raise ValueError(f"Split no encontrado: {split_id}")

        if split.estado == "pagado":
            raise ValueError("El split ya fue pagado")

        # Crear asiento de pago
        asiento = await self.journal.crear_asiento_simple(
            fecha=fecha_pago,
            concepto=f"Pago a propietario - Ref: {referencia_pago}",
            cuenta_debe=CUENTA_PASIVO_PROPIETARIO,
            cuenta_haber=CUENTA_BANCOS,
            monto=split.monto_propietario,
            referencia=referencia_pago,
            origen_tipo=OrigenAsiento.COMISION,
            origen_id=split_id,
            auto_contabilizar=auto_contabilizar,
        )

        # Actualizar split
        from datetime import datetime
        await self.db.update(
            "comisiones_split",
            {
                "estado": "pagado",
                "fecha_pago": datetime.now().isoformat(),
                "referencia_pago": referencia_pago,
            },
            {"id": str(split_id)}
        )

        split.estado = "pagado"
        split.referencia_pago = referencia_pago

        logger.info(
            "Pago a propietario registrado",
            split_id=str(split_id),
            monto=float(split.monto_propietario),
            referencia=referencia_pago,
        )

        return split, asiento

    async def obtener_por_id(self, split_id: UUID) -> ComisionSplit | None:
        """
        Obtiene un split por su ID.

        Args:
            split_id: ID del split

        Returns:
            ComisionSplit o None
        """
        result = await self.db.select(
            "comisiones_split",
            filters={"id": str(split_id)}
        )

        if not result["data"]:
            return None

        data = result["data"][0]
        return self._from_db(data)

    async def listar_pendientes_pago(
        self,
        propietario_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ComisionSplit]:
        """
        Lista splits pendientes de pago a propietarios.

        Args:
            propietario_id: Filtrar por propietario
            limit: Límite de registros

        Returns:
            Lista de splits pendientes
        """
        filters: dict[str, Any] = {"estado": "contabilizado"}
        if propietario_id:
            filters["propietario_id"] = str(propietario_id)

        result = await self.db.select(
            "comisiones_split",
            filters=filters,
            order="-created_at",
            limit=limit,
        )

        return [self._from_db(d) for d in (result["data"] or [])]

    async def obtener_resumen_propietario(
        self,
        propietario_id: UUID,
    ) -> dict[str, Any]:
        """
        Obtiene resumen de comisiones para un propietario.

        Args:
            propietario_id: ID del propietario

        Returns:
            Resumen con totales
        """
        result = await self.db.select(
            "comisiones_split",
            filters={"propietario_id": str(propietario_id)}
        )

        splits = [self._from_db(d) for d in (result["data"] or [])]

        total_bruto = sum(s.monto_bruto for s in splits)
        total_comision = sum(s.monto_comision for s in splits)
        total_propietario = sum(s.monto_propietario for s in splits)
        total_pagado = sum(
            s.monto_propietario for s in splits if s.estado == "pagado"
        )
        total_pendiente = total_propietario - total_pagado

        return {
            "propietario_id": str(propietario_id),
            "cantidad_operaciones": len(splits),
            "total_bruto": float(total_bruto),
            "total_comision": float(total_comision),
            "total_propietario": float(total_propietario),
            "total_pagado": float(total_pagado),
            "total_pendiente": float(total_pendiente),
        }

    async def _guardar_split(self, split: ComisionSplit) -> ComisionSplit:
        """Guarda un split en la base de datos."""
        data = split.to_db_dict()
        result = await self.db.insert("comisiones_split", data)

        if result["data"]:
            split.id = UUID(result["data"][0]["id"])

        return split

    def _from_db(self, data: dict[str, Any]) -> ComisionSplit:
        """Construye ComisionSplit desde datos de DB."""
        return ComisionSplit(
            id=UUID(data["id"]),
            transaccion_id=UUID(data["transaccion_id"]) if data.get("transaccion_id") else None,
            comprobante_id=UUID(data["comprobante_id"]) if data.get("comprobante_id") else None,
            monto_bruto=Decimal(str(data["monto_bruto"])),
            porcentaje_comision=Decimal(str(data["porcentaje_comision"])),
            monto_comision=Decimal(str(data["monto_comision"])),
            monto_propietario=Decimal(str(data["monto_propietario"])),
            asiento_id=UUID(data["asiento_id"]) if data.get("asiento_id") else None,
            propietario_id=UUID(data["propietario_id"]) if data.get("propietario_id") else None,
            vehiculo_id=UUID(data["vehiculo_id"]) if data.get("vehiculo_id") else None,
            estado=data["estado"],
            referencia_pago=data.get("referencia_pago"),
        )


def get_comision_service() -> ComisionSplitService:
    """Factory function para el servicio de comisiones."""
    return ComisionSplitService()


# ============================================
# FUNCIONES DE CONVENIENCIA
# ============================================


async def procesar_cobro_simple(
    monto: Decimal,
    fecha: date,
    concepto: str,
) -> tuple[ComisionSplit, AsientoContable]:
    """
    Procesa un cobro simple con split de comisión.

    Args:
        monto: Monto cobrado
        fecha: Fecha del cobro
        concepto: Descripción

    Returns:
        Tupla (split, asiento)
    """
    service = get_comision_service()
    return await service.procesar_cobro(
        monto_bruto=monto,
        fecha=fecha,
        concepto=concepto,
    )


def calcular_split_rapido(monto: Decimal) -> dict[str, Decimal]:
    """
    Calcula el split de comisión de forma rápida.

    Args:
        monto: Monto total

    Returns:
        Diccionario con montos
    """
    service = ComisionSplitService()
    split = service.calcular_split(monto)

    return {
        "total": split.monto_bruto,
        "comision": split.monto_comision,
        "propietario": split.monto_propietario,
        "porcentaje": split.porcentaje_comision,
    }
