"""
ECUCONDOR - Repositorio de Facturas
Operaciones de base de datos para comprobantes electrónicos.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.db.supabase import SupabaseClient, get_supabase_client
from src.sri.models import EstadoComprobante, TipoComprobante

logger = structlog.get_logger(__name__)


class InvoiceRepository:
    """
    Repositorio para operaciones con comprobantes electrónicos.

    Abstrae las operaciones de base de datos relacionadas con facturas,
    notas de crédito, retenciones y otros comprobantes.
    """

    def __init__(self, db: SupabaseClient | None = None):
        """
        Inicializa el repositorio.

        Args:
            db: Cliente de Supabase. Si es None, se obtiene del factory.
        """
        self.db = db or get_supabase_client()

    async def siguiente_secuencial(
        self,
        tipo_comprobante: str,
        establecimiento: str,
        punto_emision: str,
    ) -> int:
        """
        Obtiene el siguiente secuencial para un tipo/establecimiento/punto.

        Returns:
            Siguiente número secuencial disponible
        """
        result = await self.db.select(
            "comprobantes_electronicos",
            columns="secuencial",
            filters={
                "tipo_comprobante": tipo_comprobante,
                "establecimiento": establecimiento,
                "punto_emision": punto_emision,
            },
            order="-secuencial",
            limit=1,
        )

        if result["data"]:
            ultimo = int(result["data"][0]["secuencial"])
            return ultimo + 1
        return 1

    async def crear_comprobante(
        self,
        tipo_comprobante: str,
        establecimiento: str,
        punto_emision: str,
        secuencial: int,
        clave_acceso: str,
        fecha_emision: date,
        cliente_tipo_id: str,
        cliente_identificacion: str,
        cliente_razon_social: str,
        importe_total: Decimal,
        cliente_id: UUID | None = None,
        cliente_direccion: str | None = None,
        cliente_email: str | None = None,
        subtotal_sin_impuestos: Decimal = Decimal("0"),
        subtotal_15: Decimal = Decimal("0"),
        subtotal_0: Decimal = Decimal("0"),
        iva: Decimal = Decimal("0"),
        total_descuento: Decimal = Decimal("0"),
        estado: EstadoComprobante = EstadoComprobante.DRAFT,
        xml_sin_firmar: str | None = None,
        xml_firmado: str | None = None,
        info_adicional: dict | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """
        Crea un nuevo comprobante electrónico en la base de datos.

        Args:
            tipo_comprobante: Código del tipo (01, 04, 07)
            establecimiento: Código de establecimiento
            punto_emision: Código de punto de emisión
            secuencial: Número secuencial
            clave_acceso: Clave de acceso de 49 dígitos
            fecha_emision: Fecha de emisión
            cliente_tipo_id: Tipo de identificación del cliente
            cliente_identificacion: Número de identificación
            cliente_razon_social: Razón social del cliente
            importe_total: Total del comprobante
            cliente_id: UUID del cliente (opcional)
            cliente_direccion: Dirección del cliente
            cliente_email: Email del cliente
            subtotal_sin_impuestos: Subtotal antes de impuestos
            subtotal_15: Subtotal con IVA 15%
            subtotal_0: Subtotal con IVA 0%
            iva: Valor del IVA
            total_descuento: Total de descuentos
            estado: Estado inicial del comprobante
            xml_sin_firmar: XML sin firma
            xml_firmado: XML firmado
            info_adicional: Información adicional JSON
            created_by: Usuario que crea el comprobante

        Returns:
            Comprobante creado
        """
        data = {
            "tipo_comprobante": tipo_comprobante,
            "establecimiento": establecimiento,
            "punto_emision": punto_emision,
            "secuencial": str(secuencial).zfill(9),
            "clave_acceso": clave_acceso,
            "fecha_emision": fecha_emision.isoformat(),
            "cliente_tipo_id": cliente_tipo_id,
            "cliente_identificacion": cliente_identificacion,
            "cliente_razon_social": cliente_razon_social,
            "importe_total": float(importe_total),
            "subtotal_sin_impuestos": float(subtotal_sin_impuestos),
            "subtotal_15": float(subtotal_15),
            "subtotal_0": float(subtotal_0),
            "iva": float(iva),
            "total_descuento": float(total_descuento),
            "estado": estado.value,
        }

        if cliente_id:
            data["cliente_id"] = str(cliente_id)
        if cliente_direccion:
            data["cliente_direccion"] = cliente_direccion
        if cliente_email:
            data["cliente_email"] = cliente_email
        if xml_sin_firmar:
            data["xml_sin_firmar"] = xml_sin_firmar
        if xml_firmado:
            data["xml_firmado"] = xml_firmado
        if info_adicional:
            data["info_adicional"] = info_adicional
        if created_by:
            data["created_by"] = created_by

        result = await self.db.insert("comprobantes_electronicos", data)

        logger.info(
            "Comprobante creado",
            tipo=tipo_comprobante,
            numero=f"{establecimiento}-{punto_emision}-{str(secuencial).zfill(9)}",
            clave_acceso=clave_acceso[:20] + "...",
        )

        return result["data"][0] if result["data"] else {}

    async def agregar_detalles(
        self,
        comprobante_id: str,
        detalles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Agrega líneas de detalle a un comprobante.

        Args:
            comprobante_id: UUID del comprobante
            detalles: Lista de detalles a agregar

        Returns:
            Detalles insertados
        """
        items = []
        for i, detalle in enumerate(detalles):
            items.append({
                "comprobante_id": comprobante_id,
                "codigo_principal": detalle.get("codigo"),
                "descripcion": detalle["descripcion"],
                "cantidad": float(detalle["cantidad"]),
                "precio_unitario": float(detalle["precio_unitario"]),
                "descuento": float(detalle.get("descuento", 0)),
                "precio_total_sin_impuesto": float(detalle["precio_total_sin_impuesto"]),
                "impuestos": detalle.get("impuestos", []),
                "orden": i,
            })

        result = await self.db.insert("comprobante_detalles", items)
        return result

    async def agregar_pagos(
        self,
        comprobante_id: str,
        pagos: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Agrega formas de pago a un comprobante.

        Args:
            comprobante_id: UUID del comprobante
            pagos: Lista de pagos

        Returns:
            Pagos insertados
        """
        items = []
        for pago in pagos:
            items.append({
                "comprobante_id": comprobante_id,
                "forma_pago": pago["forma_pago"],
                "total": float(pago["total"]),
                "plazo": pago.get("plazo"),
                "unidad_tiempo": pago.get("unidad_tiempo"),
            })

        result = await self.db.insert("comprobante_pagos", items)
        return result

    async def obtener_por_id(self, comprobante_id: str) -> dict[str, Any] | None:
        """
        Obtiene un comprobante por su ID.

        Args:
            comprobante_id: UUID del comprobante

        Returns:
            Comprobante o None si no existe
        """
        result = await self.db.select(
            "comprobantes_electronicos",
            filters={"id": comprobante_id}
        )
        return result["data"][0] if result["data"] else None

    async def obtener_por_clave_acceso(self, clave_acceso: str) -> dict[str, Any] | None:
        """
        Obtiene un comprobante por su clave de acceso.

        Args:
            clave_acceso: Clave de acceso de 49 dígitos

        Returns:
            Comprobante o None si no existe
        """
        result = await self.db.select(
            "comprobantes_electronicos",
            filters={"clave_acceso": clave_acceso}
        )
        return result["data"][0] if result["data"] else None

    async def obtener_detalles(self, comprobante_id: str) -> list[dict[str, Any]]:
        """
        Obtiene los detalles de un comprobante.

        Args:
            comprobante_id: UUID del comprobante

        Returns:
            Lista de detalles
        """
        result = await self.db.select(
            "comprobante_detalles",
            filters={"comprobante_id": comprobante_id},
            order="orden"
        )
        return result["data"] or []

    async def obtener_pagos(self, comprobante_id: str) -> list[dict[str, Any]]:
        """
        Obtiene las formas de pago de un comprobante.

        Args:
            comprobante_id: UUID del comprobante

        Returns:
            Lista de pagos
        """
        result = await self.db.select(
            "comprobante_pagos",
            filters={"comprobante_id": comprobante_id}
        )
        return result["data"] or []

    async def actualizar_estado(
        self,
        comprobante_id: str,
        estado: EstadoComprobante,
        numero_autorizacion: str | None = None,
        fecha_autorizacion: datetime | None = None,
        xml_autorizado: str | None = None,
        mensajes_sri: list[dict] | None = None,
        intentos_envio: int | None = None,
    ) -> dict[str, Any]:
        """
        Actualiza el estado de un comprobante.

        Args:
            comprobante_id: UUID del comprobante
            estado: Nuevo estado
            numero_autorizacion: Número de autorización del SRI
            fecha_autorizacion: Fecha de autorización
            xml_autorizado: XML autorizado por el SRI
            mensajes_sri: Mensajes de respuesta del SRI
            intentos_envio: Número de intentos de envío

        Returns:
            Comprobante actualizado
        """
        data: dict[str, Any] = {"estado": estado.value}

        if numero_autorizacion:
            data["numero_autorizacion"] = numero_autorizacion
        if fecha_autorizacion:
            data["fecha_autorizacion"] = fecha_autorizacion.isoformat()
        if xml_autorizado:
            data["xml_autorizado"] = xml_autorizado
        if mensajes_sri is not None:
            data["mensajes_sri"] = mensajes_sri
        if intentos_envio is not None:
            data["intentos_envio"] = intentos_envio
            data["ultimo_intento_at"] = datetime.utcnow().isoformat()

        result = await self.db.update(
            "comprobantes_electronicos",
            data,
            {"id": comprobante_id}
        )

        logger.info(
            "Estado de comprobante actualizado",
            id=comprobante_id,
            estado=estado.value,
        )

        return result["data"][0] if result["data"] else {}

    async def guardar_pdf(
        self,
        comprobante_id: str,
        pdf_bytes: bytes,
    ) -> dict[str, Any]:
        """
        Guarda el PDF del RIDE de un comprobante.

        Args:
            comprobante_id: UUID del comprobante
            pdf_bytes: Bytes del PDF

        Returns:
            Comprobante actualizado
        """
        # Supabase acepta bytes como bytea
        result = await self.db.update(
            "comprobantes_electronicos",
            {"pdf_ride": pdf_bytes.hex()},  # Convertir a hex para transmisión
            {"id": comprobante_id}
        )
        return result["data"][0] if result["data"] else {}

    async def listar_comprobantes(
        self,
        tipo_comprobante: str | None = None,
        estado: EstadoComprobante | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        cliente_identificacion: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Lista comprobantes con filtros opcionales.

        Args:
            tipo_comprobante: Filtrar por tipo
            estado: Filtrar por estado
            fecha_desde: Fecha de inicio
            fecha_hasta: Fecha de fin
            cliente_identificacion: Filtrar por cliente
            limit: Máximo de registros
            offset: Offset para paginación

        Returns:
            Lista de comprobantes y count
        """
        filters: dict[str, Any] = {}

        if tipo_comprobante:
            filters["tipo_comprobante"] = tipo_comprobante
        if estado:
            filters["estado"] = estado.value
        if cliente_identificacion:
            filters["cliente_identificacion"] = cliente_identificacion
        if fecha_desde:
            filters["fecha_emision"] = {"gte": fecha_desde.isoformat()}
        if fecha_hasta:
            if "fecha_emision" in filters:
                # Si ya hay filtro de fecha, combinamos
                pass  # TODO: Implementar filtros compuestos
            else:
                filters["fecha_emision"] = {"lte": fecha_hasta.isoformat()}

        result = await self.db.select(
            "comprobantes_electronicos",
            columns="id, tipo_comprobante, establecimiento, punto_emision, secuencial, "
                    "clave_acceso, fecha_emision, cliente_razon_social, cliente_identificacion, "
                    "importe_total, estado, numero_autorizacion, fecha_autorizacion",
            filters=filters,
            order="-fecha_emision",
            limit=limit,
            offset=offset,
        )

        return result

    async def obtener_pendientes(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Obtiene comprobantes pendientes de autorización.

        Útil para procesos de reintento automático.

        Args:
            limit: Máximo de registros

        Returns:
            Lista de comprobantes pendientes
        """
        result = await self.db.select(
            "comprobantes_electronicos",
            filters={"estado": {"in": ["pending", "sent", "received", "error"]}},
            order="fecha_emision",
            limit=limit,
        )
        return result["data"] or []


def get_invoice_repository() -> InvoiceRepository:
    """Factory function para el repositorio de facturas."""
    return InvoiceRepository()
