"""
ECUCONDOR - Repositorio de Transacciones Bancarias
Operaciones de base de datos para transacciones bancarias.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from src.db.supabase import SupabaseClient, get_supabase_client
from src.ingestor.models import (
    BancoEcuador,
    EstadoTransaccion,
    TipoTransaccion,
    TransaccionBancaria,
)

logger = structlog.get_logger(__name__)


class TransactionRepository:
    """
    Repositorio para operaciones con transacciones bancarias.

    Abstrae las operaciones de base de datos relacionadas con
    transacciones importadas de extractos bancarios.
    """

    def __init__(self, db: SupabaseClient | None = None):
        """
        Inicializa el repositorio.

        Args:
            db: Cliente de Supabase. Si es None, se obtiene del factory.
        """
        self.db = db or get_supabase_client()

    async def crear_transaccion(
        self,
        transaccion: TransaccionBancaria,
    ) -> dict[str, Any]:
        """
        Crea una nueva transacción en la base de datos.

        Args:
            transaccion: Transacción a crear

        Returns:
            Transacción creada
        """
        data = transaccion.to_db_dict()
        result = await self.db.insert("transacciones_bancarias", data)

        logger.info(
            "Transacción creada",
            hash=transaccion.hash_unico,
            monto=float(transaccion.monto),
            tipo=transaccion.tipo.value,
        )

        return result["data"][0] if result["data"] else {}

    async def crear_lote(
        self,
        transacciones: list[TransaccionBancaria],
    ) -> dict[str, Any]:
        """
        Crea múltiples transacciones en lote.

        Args:
            transacciones: Lista de transacciones

        Returns:
            Resultado de la inserción
        """
        if not transacciones:
            return {"data": [], "count": 0}

        data = [tx.to_db_dict() for tx in transacciones]
        result = await self.db.insert("transacciones_bancarias", data)

        logger.info(
            "Lote de transacciones creado",
            cantidad=len(transacciones),
        )

        return result

    async def obtener_por_id(self, transaccion_id: str) -> dict[str, Any] | None:
        """
        Obtiene una transacción por su ID.

        Args:
            transaccion_id: UUID de la transacción

        Returns:
            Transacción o None
        """
        result = await self.db.select(
            "transacciones_bancarias",
            filters={"id": transaccion_id}
        )
        return result["data"][0] if result["data"] else None

    async def obtener_por_hash(self, hash_unico: str) -> dict[str, Any] | None:
        """
        Obtiene una transacción por su hash único.

        Args:
            hash_unico: Hash de 16 caracteres

        Returns:
            Transacción o None
        """
        result = await self.db.select(
            "transacciones_bancarias",
            filters={"hash_unico": hash_unico}
        )
        return result["data"][0] if result["data"] else None

    async def obtener_hashes_existentes(
        self,
        hashes: list[str],
    ) -> set[str]:
        """
        Obtiene los hashes que ya existen en la base de datos.

        Útil para deduplicación masiva.

        Args:
            hashes: Lista de hashes a verificar

        Returns:
            Set de hashes existentes
        """
        if not hashes:
            return set()

        # Usar función RPC para eficiencia
        result = await self.db.rpc(
            "buscar_hashes_existentes",
            {"p_hashes": hashes}
        )

        return {row["hash_unico"] for row in result} if result else set()

    async def actualizar_estado(
        self,
        transaccion_id: str,
        estado: EstadoTransaccion,
        comprobante_id: str | None = None,
        asiento_id: str | None = None,
        notas: str | None = None,
    ) -> dict[str, Any]:
        """
        Actualiza el estado de una transacción.

        Args:
            transaccion_id: UUID de la transacción
            estado: Nuevo estado
            comprobante_id: ID del comprobante conciliado
            asiento_id: ID del asiento contable
            notas: Notas adicionales

        Returns:
            Transacción actualizada
        """
        data: dict[str, Any] = {"estado": estado.value}

        if comprobante_id:
            data["comprobante_id"] = comprobante_id
        if asiento_id:
            data["asiento_id"] = asiento_id
        if notas:
            data["notas"] = notas

        result = await self.db.update(
            "transacciones_bancarias",
            data,
            {"id": transaccion_id}
        )

        logger.info(
            "Estado de transacción actualizado",
            id=transaccion_id,
            estado=estado.value,
        )

        return result["data"][0] if result["data"] else {}

    async def conciliar(
        self,
        transaccion_id: str,
        comprobante_id: str,
    ) -> dict[str, Any]:
        """
        Marca una transacción como conciliada con un comprobante.

        Args:
            transaccion_id: UUID de la transacción
            comprobante_id: UUID del comprobante

        Returns:
            Transacción actualizada
        """
        return await self.actualizar_estado(
            transaccion_id,
            EstadoTransaccion.CONCILIADA,
            comprobante_id=comprobante_id,
        )

    async def listar_transacciones(
        self,
        banco: BancoEcuador | None = None,
        cuenta_bancaria: str | None = None,
        tipo: TipoTransaccion | None = None,
        estado: EstadoTransaccion | None = None,
        fecha_desde: date | None = None,
        fecha_hasta: date | None = None,
        monto_minimo: Decimal | None = None,
        monto_maximo: Decimal | None = None,
        solo_sin_conciliar: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Lista transacciones con filtros.

        Args:
            banco: Filtrar por banco
            cuenta_bancaria: Filtrar por cuenta
            tipo: Filtrar por tipo (crédito/débito)
            estado: Filtrar por estado
            fecha_desde: Fecha inicio
            fecha_hasta: Fecha fin
            monto_minimo: Monto mínimo
            monto_maximo: Monto máximo
            solo_sin_conciliar: Solo pendientes
            limit: Límite de registros
            offset: Offset para paginación

        Returns:
            Lista de transacciones
        """
        filters: dict[str, Any] = {}

        if banco:
            filters["banco"] = banco.value
        if cuenta_bancaria:
            filters["cuenta_bancaria"] = cuenta_bancaria
        if tipo:
            filters["tipo"] = tipo.value
        if estado:
            filters["estado"] = estado.value
        if solo_sin_conciliar:
            filters["estado"] = "pendiente"
        if fecha_desde:
            filters["fecha"] = {"gte": fecha_desde.isoformat()}
        if fecha_hasta:
            if "fecha" in filters:
                # Combinar filtros de fecha
                pass
            else:
                filters["fecha"] = {"lte": fecha_hasta.isoformat()}

        columns = (
            "id, hash_unico, banco, cuenta_bancaria, fecha, tipo, origen, "
            "monto, saldo, descripcion_normalizada, descripcion_original, "
            "referencia, contraparte_nombre, contraparte_identificacion, "
            "estado, comprobante_id, categoria_sugerida, confianza_categoria, "
            "created_at"
        )

        result = await self.db.select(
            "transacciones_bancarias",
            columns=columns,
            filters=filters,
            order="-fecha",
            limit=limit,
            offset=offset,
        )

        return result

    async def obtener_pendientes(
        self,
        banco: BancoEcuador | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Obtiene transacciones pendientes de conciliación.

        Args:
            banco: Filtrar por banco
            limit: Máximo de registros

        Returns:
            Lista de transacciones pendientes
        """
        filters: dict[str, Any] = {"estado": "pendiente"}
        if banco:
            filters["banco"] = banco.value

        result = await self.db.select(
            "transacciones_bancarias",
            filters=filters,
            order="-monto",
            limit=limit,
        )
        return result["data"] or []

    async def obtener_candidatos_conciliacion(
        self,
        monto: Decimal,
        fecha: date,
        identificacion: str | None = None,
        tolerancia_monto: Decimal = Decimal("0.01"),
        tolerancia_dias: int = 7,
    ) -> list[dict[str, Any]]:
        """
        Obtiene comprobantes candidatos para conciliación.

        Args:
            monto: Monto de la transacción
            fecha: Fecha de la transacción
            identificacion: Identificación de la contraparte
            tolerancia_monto: Tolerancia en monto
            tolerancia_dias: Tolerancia en días

        Returns:
            Lista de comprobantes candidatos
        """
        result = await self.db.rpc(
            "obtener_candidatos_conciliacion",
            {
                "p_monto": float(monto),
                "p_fecha": fecha.isoformat(),
                "p_identificacion": identificacion,
                "p_tolerancia_monto": float(tolerancia_monto),
                "p_tolerancia_dias": tolerancia_dias,
            }
        )
        return result or []

    async def obtener_resumen_mensual(
        self,
        banco: BancoEcuador | None = None,
        cuenta: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Obtiene resumen mensual de transacciones.

        Args:
            banco: Filtrar por banco
            cuenta: Filtrar por cuenta

        Returns:
            Resumen mensual
        """
        result = await self.db.select(
            "v_resumen_banco_mes",
            filters={
                **({"banco": banco.value} if banco else {}),
                **({"cuenta_bancaria": cuenta} if cuenta else {}),
            },
            limit=24,  # Últimos 2 años
        )
        return result["data"] or []

    async def registrar_importacion(
        self,
        nombre_archivo: str,
        banco: BancoEcuador,
        cuenta_bancaria: str,
        total_lineas: int,
        transacciones_nuevas: int,
        transacciones_duplicadas: int,
        transacciones_error: int,
        monto_creditos: Decimal,
        monto_debitos: Decimal,
        errores: list[str] | None = None,
        advertencias: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Registra una importación de extracto.

        Args:
            nombre_archivo: Nombre del archivo
            banco: Banco
            cuenta_bancaria: Cuenta
            total_lineas: Total de líneas procesadas
            transacciones_nuevas: Transacciones nuevas
            transacciones_duplicadas: Duplicados detectados
            transacciones_error: Errores
            monto_creditos: Total créditos
            monto_debitos: Total débitos
            errores: Lista de errores
            advertencias: Lista de advertencias

        Returns:
            Registro de importación
        """
        estado = "completado"
        if transacciones_error > 0:
            estado = "parcial"
        if transacciones_nuevas == 0 and transacciones_error > 0:
            estado = "error"

        data = {
            "nombre_archivo": nombre_archivo,
            "banco": banco.value,
            "cuenta_bancaria": cuenta_bancaria,
            "total_lineas": total_lineas,
            "transacciones_nuevas": transacciones_nuevas,
            "transacciones_duplicadas": transacciones_duplicadas,
            "transacciones_error": transacciones_error,
            "monto_total_creditos": float(monto_creditos),
            "monto_total_debitos": float(monto_debitos),
            "estado": estado,
            "errores": errores,
            "advertencias": advertencias,
        }

        result = await self.db.insert("importaciones_extractos", data)
        return result["data"][0] if result["data"] else {}


def get_transaction_repository() -> TransactionRepository:
    """Factory function para el repositorio de transacciones."""
    return TransactionRepository()
