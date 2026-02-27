"""
ECUCONDOR - Cliente Supabase
Gestiona la conexión y operaciones con la base de datos.
"""

from functools import lru_cache
from typing import Any

import structlog
from supabase import Client, create_client

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)


class SupabaseClient:
    """
    Cliente wrapper para Supabase con métodos de conveniencia.

    Proporciona acceso a tablas y funciones RPC de manera tipada.
    """

    def __init__(self, url: str, key: str, service_key: str | None = None):
        """
        Inicializa el cliente Supabase.

        Args:
            url: URL del proyecto Supabase
            key: API Key pública (anon)
            service_key: Service role key para operaciones admin
        """
        self._url = url
        self._key = key
        self._service_key = service_key

        # Cliente público (respeta RLS)
        self._client: Client = create_client(url, key)

        # Cliente admin (bypass RLS) - solo si se proporciona service_key
        self._admin_client: Client | None = None
        if service_key:
            self._admin_client = create_client(url, service_key)

        logger.info("Cliente Supabase inicializado", url=url[:30] + "...")

    @property
    def client(self) -> Client:
        """Cliente público que respeta RLS."""
        return self._client

    @property
    def admin(self) -> Client:
        """Cliente admin que bypasea RLS."""
        if self._admin_client is None:
            raise ValueError("Service key no configurada para operaciones admin")
        return self._admin_client

    # ===== TABLAS =====

    def table(self, name: str) -> Any:
        """Accede a una tabla."""
        return self._client.table(name)

    def admin_table(self, name: str) -> Any:
        """Accede a una tabla con privilegios admin."""
        return self.admin.table(name)

    # ===== MÉTODOS DE CONVENIENCIA =====

    async def insert(
        self,
        table: str,
        data: dict[str, Any] | list[dict[str, Any]],
        returning: str = "representation",
    ) -> dict[str, Any]:
        """
        Inserta uno o más registros.

        Args:
            table: Nombre de la tabla
            data: Datos a insertar
            returning: Tipo de retorno ('minimal', 'representation')

        Returns:
            Datos insertados
        """
        result = self._client.table(table).insert(data).execute()
        return {"data": result.data, "count": len(result.data) if result.data else 0}

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """
        Selecciona registros de una tabla.

        Args:
            table: Nombre de la tabla
            columns: Columnas a seleccionar
            filters: Filtros a aplicar (eq, neq, gt, lt, etc.)
            order: Ordenamiento
            limit: Límite de registros
            offset: Offset para paginación

        Returns:
            Registros encontrados
        """
        query = self._client.table(table).select(columns)

        if filters:
            for key, value in filters.items():
                if isinstance(value, dict):
                    # Filtros complejos: {"column": {"operator": "value"}}
                    for op, val in value.items():
                        if op == "eq":
                            query = query.eq(key, val)
                        elif op == "neq":
                            query = query.neq(key, val)
                        elif op == "gt":
                            query = query.gt(key, val)
                        elif op == "gte":
                            query = query.gte(key, val)
                        elif op == "lt":
                            query = query.lt(key, val)
                        elif op == "lte":
                            query = query.lte(key, val)
                        elif op == "like":
                            query = query.like(key, val)
                        elif op == "ilike":
                            query = query.ilike(key, val)
                        elif op == "in":
                            query = query.in_(key, val)
                else:
                    # Filtro simple: igualdad
                    query = query.eq(key, value)

        if order:
            desc = order.startswith("-")
            column = order.lstrip("-")
            query = query.order(column, desc=desc)

        if limit:
            query = query.limit(limit)

        if offset:
            query = query.offset(offset)

        result = query.execute()
        return {"data": result.data, "count": len(result.data) if result.data else 0}

    async def update(
        self,
        table: str,
        data: dict[str, Any],
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Actualiza registros.

        Args:
            table: Nombre de la tabla
            data: Datos a actualizar
            filters: Filtros para identificar registros

        Returns:
            Registros actualizados
        """
        query = self._client.table(table).update(data)

        for key, value in filters.items():
            query = query.eq(key, value)

        result = query.execute()
        return {"data": result.data, "count": len(result.data) if result.data else 0}

    async def delete(
        self,
        table: str,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Elimina registros.

        Args:
            table: Nombre de la tabla
            filters: Filtros para identificar registros

        Returns:
            Registros eliminados
        """
        query = self._client.table(table).delete()

        for key, value in filters.items():
            query = query.eq(key, value)

        result = query.execute()
        return {"data": result.data, "count": len(result.data) if result.data else 0}

    async def rpc(
        self,
        function: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Llama a una función RPC de Supabase.

        Args:
            function: Nombre de la función
            params: Parámetros de la función

        Returns:
            Resultado de la función
        """
        result = self._client.rpc(function, params or {}).execute()
        return result.data

    async def get_next_secuencial(
        self,
        punto_emision_id: str,
        tipo_comprobante: str,
    ) -> int:
        """
        Obtiene el siguiente número secuencial para un comprobante.

        Utiliza la función RPC `get_next_secuencial` definida en las migraciones.

        Args:
            punto_emision_id: UUID del punto de emisión
            tipo_comprobante: Código del tipo de comprobante (01, 04, 07)

        Returns:
            Siguiente número secuencial
        """
        result = await self.rpc(
            "get_next_secuencial",
            {
                "p_punto_emision_id": punto_emision_id,
                "p_tipo_comprobante": tipo_comprobante,
            }
        )
        return result


@lru_cache
def get_supabase_client() -> SupabaseClient:
    """
    Factory function para obtener el cliente Supabase.

    Cachea la instancia para reutilización.

    Returns:
        Cliente Supabase configurado
    """
    settings = get_settings()
    return SupabaseClient(
        url=settings.supabase_url,
        key=settings.supabase_key,
        service_key=settings.supabase_service_key,
    )


# Alias para compatibilidad
def get_db() -> SupabaseClient:
    """Alias de get_supabase_client para uso como dependencia."""
    return get_supabase_client()
