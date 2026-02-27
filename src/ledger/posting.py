"""
ECUCONDOR - Servicio de Contabilización Automática
Genera asientos contables desde transacciones y facturas.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.db.supabase import SupabaseClient, get_supabase_client
from src.ledger.journal import JournalService
from src.ledger.models import AsientoContable, OrigenAsiento, TipoAsiento
from src.ledger.split_comision import ComisionSplitService

logger = structlog.get_logger(__name__)


# Cuentas contables predefinidas
CUENTAS = {
    # Activos
    "bancos": "1.1.03",
    "cuentas_por_cobrar": "1.1.04",
    "iva_pagado": "1.1.05",
    "inventario": "1.1.06",

    # Pasivos
    "cuentas_por_pagar": "2.1.01",
    "iva_cobrado": "2.1.04",
    "impuestos_por_pagar": "2.1.05",
    "iess_por_pagar": "2.1.06",
    "retenciones_por_pagar": "2.1.07",
    "pasivo_propietarios": "2.1.09",

    # Ingresos
    "ingresos_servicios": "4.1.01",
    "ingresos_comision": "4.1.01",
    "otros_ingresos": "4.1.09",

    # Gastos operacionales
    "gasto_arriendos": "5.2.01",
    "gasto_servicios_basicos": "5.2.03",
    "gasto_combustible": "5.2.05",
    "gasto_mantenimiento": "5.2.06",
    "gasto_seguros": "5.2.07",
    "gasto_honorarios": "5.2.08",

    # Gastos financieros
    "gastos_bancarios": "5.3.02",
    "gastos_impuestos": "5.3.03",
}


class PostingService:
    """
    Servicio de contabilización automática.

    Responsabilidades:
    - Generar asientos desde transacciones bancarias
    - Generar asientos desde facturas emitidas
    - Generar asientos desde facturas recibidas
    - Aplicar reglas de categorización
    """

    def __init__(
        self,
        db: SupabaseClient | None = None,
        journal: JournalService | None = None,
        comision: ComisionSplitService | None = None,
    ):
        """
        Inicializa el servicio.

        Args:
            db: Cliente de Supabase
            journal: Servicio de libro diario
            comision: Servicio de split de comisión
        """
        self.db = db or get_supabase_client()
        self.journal = journal or JournalService(self.db)
        self.comision = comision or ComisionSplitService(self.db, self.journal)

    async def contabilizar_transaccion(
        self,
        transaccion_id: UUID,
        cuenta_contable: str | None = None,
        es_ingreso_alquiler: bool = False,
    ) -> AsientoContable:
        """
        Genera asiento contable desde una transacción bancaria.

        Args:
            transaccion_id: ID de la transacción
            cuenta_contable: Cuenta contable a usar (override)
            es_ingreso_alquiler: Si True, aplica split de comisión

        Returns:
            Asiento contable generado

        Raises:
            ValueError: Si la transacción no existe o ya tiene asiento
        """
        # Obtener transacción
        result = await self.db.select(
            "transacciones_bancarias",
            filters={"id": str(transaccion_id)}
        )

        if not result["data"]:
            raise ValueError(f"Transacción no encontrada: {transaccion_id}")

        tx = result["data"][0]

        if tx.get("asiento_id"):
            raise ValueError("La transacción ya tiene un asiento contable")

        monto = Decimal(str(tx["monto"]))
        fecha = date.fromisoformat(tx["fecha"])
        concepto = tx.get("descripcion_normalizada") or tx["descripcion_original"]

        # Si es ingreso de alquiler, usar split de comisión
        if es_ingreso_alquiler and tx["tipo"] == "credito":
            split, asiento = await self.comision.procesar_cobro(
                monto_bruto=monto,
                fecha=fecha,
                concepto=concepto,
                transaccion_id=transaccion_id,
            )

            # Actualizar transacción con asiento
            await self.db.update(
                "transacciones_bancarias",
                {"asiento_id": str(asiento.id)},
                {"id": str(transaccion_id)}
            )

            return asiento

        # Contabilización estándar
        cuenta = cuenta_contable or tx.get("cuenta_contable_sugerida")

        if not cuenta:
            # Usar cuenta por defecto según tipo
            if tx["tipo"] == "credito":
                cuenta = CUENTAS["otros_ingresos"]
            else:
                cuenta = self._determinar_cuenta_gasto(tx)

        # Crear asiento
        if tx["tipo"] == "credito":
            # Ingreso: Debe Bancos, Haber Ingreso
            asiento = await self.journal.crear_asiento_simple(
                fecha=fecha,
                concepto=concepto,
                cuenta_debe=CUENTAS["bancos"],
                cuenta_haber=cuenta,
                monto=monto,
                origen_tipo=OrigenAsiento.TRANSACCION,
                origen_id=transaccion_id,
                auto_contabilizar=True,
            )
        else:
            # Gasto: Debe Gasto, Haber Bancos
            asiento = await self.journal.crear_asiento_simple(
                fecha=fecha,
                concepto=concepto,
                cuenta_debe=cuenta,
                cuenta_haber=CUENTAS["bancos"],
                monto=monto,
                origen_tipo=OrigenAsiento.TRANSACCION,
                origen_id=transaccion_id,
                auto_contabilizar=True,
            )

        # Actualizar transacción
        await self.db.update(
            "transacciones_bancarias",
            {"asiento_id": str(asiento.id)},
            {"id": str(transaccion_id)}
        )

        logger.info(
            "Transacción contabilizada",
            transaccion_id=str(transaccion_id),
            asiento_id=str(asiento.id),
            monto=float(monto),
        )

        return asiento

    async def contabilizar_factura_emitida(
        self,
        comprobante_id: UUID,
        aplicar_split: bool = True,
    ) -> AsientoContable:
        """
        Genera asiento contable desde una factura emitida.

        Si aplicar_split=True:
        - Debe: Cuentas por cobrar
        - Haber: Ingresos por comisión (1.5%)
        - Haber: Pasivo propietario (98.5%)
        - Haber: IVA cobrado (si aplica)

        Si aplicar_split=False:
        - Debe: Cuentas por cobrar
        - Haber: Ingresos por servicios
        - Haber: IVA cobrado (si aplica)

        Args:
            comprobante_id: ID del comprobante electrónico
            aplicar_split: Si True, aplica split de comisión

        Returns:
            Asiento generado
        """
        # Obtener comprobante
        result = await self.db.select(
            "comprobantes_electronicos",
            filters={"id": str(comprobante_id)}
        )

        if not result["data"]:
            raise ValueError(f"Comprobante no encontrado: {comprobante_id}")

        comp = result["data"][0]

        if comp["tipo_comprobante"] != "01":
            raise ValueError("Solo se pueden contabilizar facturas (tipo 01)")

        fecha = date.fromisoformat(comp["fecha_emision"])
        total = Decimal(str(comp["importe_total"]))
        subtotal = Decimal(str(comp.get("subtotal_sin_impuestos", total)))
        iva = Decimal(str(comp.get("iva", 0)))
        numero = f"{comp['establecimiento']}-{comp['punto_emision']}-{comp['secuencial']}"
        cliente = comp.get("cliente_razon_social", "")

        concepto = f"Factura {numero} - {cliente}"

        if aplicar_split:
            # Split de comisión
            split, asiento = await self.comision.procesar_cobro(
                monto_bruto=total,
                fecha=fecha,
                concepto=concepto,
                comprobante_id=comprobante_id,
                incluye_iva=iva > 0,
            )
            return asiento

        # Contabilización estándar (sin split)
        movimientos = []

        # Debe: Cuentas por cobrar
        movimientos.append({
            "cuenta": CUENTAS["cuentas_por_cobrar"],
            "debe": total,
            "haber": Decimal("0"),
            "concepto": f"Factura {numero}",
        })

        # Haber: Ingresos
        if iva > 0:
            movimientos.append({
                "cuenta": CUENTAS["ingresos_servicios"],
                "debe": Decimal("0"),
                "haber": subtotal,
                "concepto": "Servicios de alquiler",
            })
            movimientos.append({
                "cuenta": CUENTAS["iva_cobrado"],
                "debe": Decimal("0"),
                "haber": iva,
                "concepto": "IVA en ventas",
            })
        else:
            movimientos.append({
                "cuenta": CUENTAS["ingresos_servicios"],
                "debe": Decimal("0"),
                "haber": total,
                "concepto": "Servicios de alquiler",
            })

        asiento = await self.journal.crear_asiento(
            fecha=fecha,
            concepto=concepto,
            movimientos=movimientos,
            tipo=TipoAsiento.AUTOMATICO,
            origen_tipo=OrigenAsiento.FACTURA,
            origen_id=comprobante_id,
            referencia=numero,
            auto_contabilizar=True,
        )

        logger.info(
            "Factura emitida contabilizada",
            comprobante_id=str(comprobante_id),
            asiento_id=str(asiento.id),
        )

        return asiento

    async def contabilizar_factura_recibida(
        self,
        fecha: date,
        proveedor: str,
        numero_factura: str,
        subtotal: Decimal,
        iva: Decimal,
        cuenta_gasto: str,
        retencion_renta: Decimal = Decimal("0"),
        retencion_iva: Decimal = Decimal("0"),
    ) -> AsientoContable:
        """
        Genera asiento contable desde una factura de proveedor.

        Asiento:
        - Debe: Gasto (subtotal)
        - Debe: IVA pagado
        - Haber: Cuentas por pagar (total - retenciones)
        - Haber: Retenciones por pagar (si aplica)

        Args:
            fecha: Fecha de la factura
            proveedor: Nombre del proveedor
            numero_factura: Número de factura
            subtotal: Subtotal sin IVA
            iva: Valor del IVA
            cuenta_gasto: Cuenta de gasto a afectar
            retencion_renta: Retención en la fuente
            retencion_iva: Retención de IVA

        Returns:
            Asiento generado
        """
        total = subtotal + iva
        total_a_pagar = total - retencion_renta - retencion_iva

        movimientos = []

        # Debe: Gasto
        movimientos.append({
            "cuenta": cuenta_gasto,
            "debe": subtotal,
            "haber": Decimal("0"),
            "concepto": f"Factura {proveedor}",
        })

        # Debe: IVA pagado (si hay)
        if iva > 0:
            movimientos.append({
                "cuenta": CUENTAS["iva_pagado"],
                "debe": iva,
                "haber": Decimal("0"),
                "concepto": "IVA en compras",
            })

        # Haber: Cuentas por pagar
        movimientos.append({
            "cuenta": CUENTAS["cuentas_por_pagar"],
            "debe": Decimal("0"),
            "haber": total_a_pagar,
            "concepto": f"Por pagar a {proveedor}",
        })

        # Haber: Retenciones (si hay)
        if retencion_renta > 0:
            movimientos.append({
                "cuenta": CUENTAS["retenciones_por_pagar"],
                "debe": Decimal("0"),
                "haber": retencion_renta,
                "concepto": "Retención fuente renta",
            })

        if retencion_iva > 0:
            movimientos.append({
                "cuenta": CUENTAS["retenciones_por_pagar"],
                "debe": Decimal("0"),
                "haber": retencion_iva,
                "concepto": "Retención IVA",
            })

        asiento = await self.journal.crear_asiento(
            fecha=fecha,
            concepto=f"Factura proveedor: {proveedor} - {numero_factura}",
            movimientos=movimientos,
            tipo=TipoAsiento.NORMAL,
            referencia=numero_factura,
            auto_contabilizar=True,
        )

        logger.info(
            "Factura recibida contabilizada",
            proveedor=proveedor,
            numero=numero_factura,
            asiento_id=str(asiento.id),
        )

        return asiento

    async def contabilizar_pago(
        self,
        fecha: date,
        concepto: str,
        monto: Decimal,
        cuenta_gasto: str,
        referencia: str | None = None,
    ) -> AsientoContable:
        """
        Contabiliza un pago simple.

        Asiento:
        - Debe: Cuenta de gasto
        - Haber: Bancos

        Args:
            fecha: Fecha del pago
            concepto: Descripción
            monto: Monto del pago
            cuenta_gasto: Cuenta de gasto
            referencia: Referencia del pago

        Returns:
            Asiento generado
        """
        return await self.journal.crear_asiento_simple(
            fecha=fecha,
            concepto=concepto,
            cuenta_debe=cuenta_gasto,
            cuenta_haber=CUENTAS["bancos"],
            monto=monto,
            referencia=referencia,
            auto_contabilizar=True,
        )

    async def contabilizar_cobro(
        self,
        fecha: date,
        concepto: str,
        monto: Decimal,
        cuenta_ingreso: str,
        referencia: str | None = None,
    ) -> AsientoContable:
        """
        Contabiliza un cobro simple.

        Asiento:
        - Debe: Bancos
        - Haber: Cuenta de ingreso

        Args:
            fecha: Fecha del cobro
            concepto: Descripción
            monto: Monto del cobro
            cuenta_ingreso: Cuenta de ingreso
            referencia: Referencia

        Returns:
            Asiento generado
        """
        return await self.journal.crear_asiento_simple(
            fecha=fecha,
            concepto=concepto,
            cuenta_debe=CUENTAS["bancos"],
            cuenta_haber=cuenta_ingreso,
            monto=monto,
            referencia=referencia,
            auto_contabilizar=True,
        )

    def _determinar_cuenta_gasto(self, transaccion: dict) -> str:
        """
        Determina la cuenta de gasto según la categoría de la transacción.

        Args:
            transaccion: Datos de la transacción

        Returns:
            Código de cuenta contable
        """
        categoria = transaccion.get("categoria_sugerida", "")

        mapeo = {
            "gasto_combustible": CUENTAS["gasto_combustible"],
            "gasto_mantenimiento": CUENTAS["gasto_mantenimiento"],
            "gasto_seguro": CUENTAS["gasto_seguros"],
            "gasto_arriendo": CUENTAS["gasto_arriendos"],
            "gasto_servicios": CUENTAS["gasto_servicios_basicos"],
            "gasto_bancario": CUENTAS["gastos_bancarios"],
            "gasto_honorarios": CUENTAS["gasto_honorarios"],
            "impuesto_isd": CUENTAS["gastos_impuestos"],
            "impuesto_gmt": CUENTAS["gastos_impuestos"],
            "pago_impuesto_sri": CUENTAS["impuestos_por_pagar"],
            "pago_iess": CUENTAS["iess_por_pagar"],
        }

        return mapeo.get(categoria, CUENTAS["cuentas_por_pagar"])


def get_posting_service() -> PostingService:
    """Factory function para el servicio de posting."""
    return PostingService()
