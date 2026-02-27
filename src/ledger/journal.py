"""
ECUCONDOR - Servicio de Libro Diario
Gestiona la creación y contabilización de asientos contables.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.db.supabase import SupabaseClient, get_supabase_client
from src.ledger.models import (
    AsientoContable,
    EstadoAsiento,
    MovimientoContable,
    OrigenAsiento,
    TipoAsiento,
)

logger = structlog.get_logger(__name__)


class JournalService:
    """
    Servicio para gestión de asientos contables.

    Responsabilidades:
    - Crear asientos con validación de partida doble
    - Contabilizar asientos (guardar en libro mayor)
    - Anular asientos
    - Consultar libro diario
    """

    def __init__(self, db: SupabaseClient | None = None):
        """
        Inicializa el servicio.

        Args:
            db: Cliente de Supabase
        """
        self.db = db or get_supabase_client()

    async def crear_asiento(
        self,
        fecha: date,
        concepto: str,
        movimientos: list[dict[str, Any]],
        *,
        tipo: TipoAsiento = TipoAsiento.NORMAL,
        referencia: str | None = None,
        origen_tipo: OrigenAsiento | None = None,
        origen_id: UUID | None = None,
        auto_contabilizar: bool = False,
        created_by: UUID | None = None,
    ) -> AsientoContable:
        """
        Crea un nuevo asiento contable.

        Args:
            fecha: Fecha del asiento
            concepto: Descripción del asiento
            movimientos: Lista de movimientos [{cuenta, debe, haber, concepto?}]
            tipo: Tipo de asiento
            referencia: Referencia externa
            origen_tipo: Tipo de documento origen
            origen_id: ID del documento origen
            auto_contabilizar: Si True, contabiliza automáticamente
            created_by: Usuario que crea

        Returns:
            Asiento creado

        Raises:
            ValueError: Si el asiento no cuadra o no tiene movimientos
        """
        # Construir objeto de asiento
        asiento = AsientoContable(
            fecha=fecha,
            concepto=concepto,
            tipo=tipo,
            referencia=referencia,
            origen_tipo=origen_tipo,
            origen_id=origen_id,
            created_by=created_by,
        )

        # Agregar movimientos
        for i, mov in enumerate(movimientos):
            debe = Decimal(str(mov.get("debe", 0)))
            haber = Decimal(str(mov.get("haber", 0)))

            if debe > 0 or haber > 0:
                asiento.movimientos.append(MovimientoContable(
                    cuenta_codigo=mov["cuenta"],
                    debe=debe,
                    haber=haber,
                    concepto=mov.get("concepto"),
                    referencia=mov.get("referencia"),
                    orden=i,
                ))

        # Recalcular totales
        asiento = asiento.model_copy()  # Trigger validator

        # Validar
        errores = asiento.validar()
        if errores:
            raise ValueError(f"Asiento inválido: {'; '.join(errores)}")

        # Guardar en base de datos
        asiento = await self._guardar_asiento(asiento)

        logger.info(
            "Asiento creado",
            id=str(asiento.id),
            numero=asiento.numero_asiento,
            fecha=fecha.isoformat(),
            total=float(asiento.total_debe),
        )

        # Contabilizar si se solicita
        if auto_contabilizar:
            asiento = await self.contabilizar(asiento.id)

        return asiento

    async def crear_asiento_simple(
        self,
        fecha: date,
        concepto: str,
        cuenta_debe: str,
        cuenta_haber: str,
        monto: Decimal,
        *,
        referencia: str | None = None,
        origen_tipo: OrigenAsiento | None = None,
        origen_id: UUID | None = None,
        auto_contabilizar: bool = True,
    ) -> AsientoContable:
        """
        Crea un asiento simple con un debe y un haber.

        Args:
            fecha: Fecha del asiento
            concepto: Descripción
            cuenta_debe: Código de cuenta al debe
            cuenta_haber: Código de cuenta al haber
            monto: Monto del movimiento
            referencia: Referencia externa
            origen_tipo: Tipo de documento origen
            origen_id: ID del documento origen
            auto_contabilizar: Si True, contabiliza automáticamente

        Returns:
            Asiento creado
        """
        return await self.crear_asiento(
            fecha=fecha,
            concepto=concepto,
            movimientos=[
                {"cuenta": cuenta_debe, "debe": monto, "haber": Decimal("0")},
                {"cuenta": cuenta_haber, "debe": Decimal("0"), "haber": monto},
            ],
            referencia=referencia,
            origen_tipo=origen_tipo,
            origen_id=origen_id,
            auto_contabilizar=auto_contabilizar,
        )

    async def contabilizar(self, asiento_id: UUID) -> AsientoContable:
        """
        Contabiliza un asiento (lo guarda definitivamente).

        Utiliza la función SQL `contabilizar_asiento` que:
        - Verifica que el asiento cuadre
        - Crea el período si no existe
        - Actualiza saldos de cuentas

        Args:
            asiento_id: ID del asiento a contabilizar

        Returns:
            Asiento contabilizado

        Raises:
            ValueError: Si el asiento no puede ser contabilizado
        """
        try:
            result = await self.db.rpc(
                "contabilizar_asiento",
                {"p_asiento_id": str(asiento_id)}
            )

            if not result:
                raise ValueError("Error al contabilizar asiento")

            # Obtener asiento actualizado
            asiento = await self.obtener_por_id(asiento_id)

            logger.info(
                "Asiento contabilizado",
                id=str(asiento_id),
                numero=asiento.numero_asiento if asiento else None,
            )

            return asiento

        except Exception as e:
            logger.error("Error contabilizando asiento", error=str(e))
            raise ValueError(f"Error al contabilizar: {str(e)}")

    async def anular(
        self,
        asiento_id: UUID,
        motivo: str,
        usuario_id: UUID | None = None,
    ) -> AsientoContable:
        """
        Anula un asiento creando un asiento de reverso.

        Args:
            asiento_id: ID del asiento a anular
            motivo: Motivo de la anulación
            usuario_id: Usuario que anula

        Returns:
            Asiento de reverso creado

        Raises:
            ValueError: Si el asiento no puede ser anulado
        """
        try:
            result = await self.db.rpc(
                "anular_asiento",
                {
                    "p_asiento_id": str(asiento_id),
                    "p_motivo": motivo,
                    "p_usuario_id": str(usuario_id) if usuario_id else None,
                }
            )

            if not result:
                raise ValueError("Error al anular asiento")

            # Obtener asiento de reverso
            reverso = await self.obtener_por_id(UUID(result))

            logger.info(
                "Asiento anulado",
                id=str(asiento_id),
                reverso_id=result,
                motivo=motivo,
            )

            return reverso

        except Exception as e:
            logger.error("Error anulando asiento", error=str(e))
            raise ValueError(f"Error al anular: {str(e)}")

    async def obtener_por_id(self, asiento_id: UUID) -> AsientoContable | None:
        """
        Obtiene un asiento por su ID con sus movimientos.

        Args:
            asiento_id: ID del asiento

        Returns:
            Asiento con movimientos o None
        """
        # Obtener cabecera
        result = await self.db.select(
            "asientos_contables",
            filters={"id": str(asiento_id)}
        )

        if not result["data"]:
            return None

        data = result["data"][0]

        # Obtener movimientos
        mov_result = await self.db.select(
            "movimientos_contables",
            filters={"asiento_id": str(asiento_id)},
            order="orden"
        )

        movimientos = [
            MovimientoContable(
                id=UUID(m["id"]),
                asiento_id=UUID(m["asiento_id"]),
                cuenta_codigo=m["cuenta_codigo"],
                debe=Decimal(str(m["debe"])),
                haber=Decimal(str(m["haber"])),
                concepto=m.get("concepto"),
                centro_costo=m.get("centro_costo"),
                referencia=m.get("referencia"),
                orden=m["orden"],
            )
            for m in (mov_result["data"] or [])
        ]

        return AsientoContable(
            id=UUID(data["id"]),
            numero_asiento=data.get("numero_asiento"),
            fecha=date.fromisoformat(data["fecha"]),
            concepto=data["concepto"],
            tipo=TipoAsiento(data["tipo"]),
            referencia=data.get("referencia"),
            origen_tipo=OrigenAsiento(data["origen_tipo"]) if data.get("origen_tipo") else None,
            origen_id=UUID(data["origen_id"]) if data.get("origen_id") else None,
            movimientos=movimientos,
            total_debe=Decimal(str(data["total_debe"])),
            total_haber=Decimal(str(data["total_haber"])),
            estado=EstadoAsiento(data["estado"]),
            periodo_id=UUID(data["periodo_id"]) if data.get("periodo_id") else None,
        )

    async def listar_libro_diario(
        self,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        tipo: TipoAsiento | None = None,
        estado: EstadoAsiento | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Lista asientos del libro diario.

        Args:
            fecha_desde: Fecha inicio
            fecha_hasta: Fecha fin
            tipo: Filtrar por tipo
            estado: Filtrar por estado
            limit: Límite de registros
            offset: Offset para paginación

        Returns:
            Lista de asientos con movimientos
        """
        filters: dict[str, Any] = {}

        if tipo:
            filters["tipo"] = tipo.value
        if estado:
            filters["estado"] = estado.value
        if fecha_desde:
            filters["fecha"] = {"gte": fecha_desde.isoformat()}
        if fecha_hasta:
            if "fecha" in filters:
                pass  # TODO: Combinar filtros
            else:
                filters["fecha"] = {"lte": fecha_hasta.isoformat()}

        result = await self.db.select(
            "asientos_contables",
            columns="id, numero_asiento, fecha, concepto, tipo, referencia, "
                    "total_debe, total_haber, estado, created_at",
            filters=filters,
            order="-fecha,-numero_asiento",
            limit=limit,
            offset=offset,
        )

        return result

    async def obtener_libro_mayor(
        self,
        cuenta_codigo: str,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
    ) -> list[dict[str, Any]]:
        """
        Obtiene el libro mayor de una cuenta.

        Args:
            cuenta_codigo: Código de la cuenta
            fecha_desde: Fecha inicio
            fecha_hasta: Fecha fin

        Returns:
            Movimientos de la cuenta con saldo acumulado
        """
        # Usar la vista v_libro_mayor
        filters: dict[str, Any] = {"cuenta_codigo": cuenta_codigo}

        result = await self.db.select(
            "v_libro_mayor",
            filters=filters,
            order="fecha,numero_asiento",
            limit=1000,
        )

        return result["data"] or []

    async def _guardar_asiento(self, asiento: AsientoContable) -> AsientoContable:
        """
        Guarda un asiento y sus movimientos en la base de datos.

        Args:
            asiento: Asiento a guardar

        Returns:
            Asiento con ID asignado
        """
        # Insertar cabecera
        data = asiento.to_db_dict()
        result = await self.db.insert("asientos_contables", data)

        if not result["data"]:
            raise ValueError("Error al guardar asiento")

        asiento_db = result["data"][0]
        asiento.id = UUID(asiento_db["id"])
        asiento.numero_asiento = asiento_db.get("numero_asiento")

        # Insertar movimientos
        if asiento.movimientos:
            movimientos_data = [
                {**m.to_db_dict(), "asiento_id": str(asiento.id)}
                for m in asiento.movimientos
            ]
            await self.db.insert("movimientos_contables", movimientos_data)

        return asiento


def get_journal_service() -> JournalService:
    """Factory function para el servicio de libro diario."""
    return JournalService()
