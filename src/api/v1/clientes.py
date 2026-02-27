"""
ECUCONDOR - API de Clientes
Endpoints para gestión de clientes (ventas).
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, EmailStr

from src.db.supabase import get_supabase_client

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/clientes", tags=["Clientes"])


# =====================================================
# MODELOS PYDANTIC
# =====================================================

class ClienteCreate(BaseModel):
    """Crear nuevo cliente."""
    tipo_identificacion: str = Field("04", description="04=RUC, 05=Cedula, 06=Pasaporte, 07=ConsumidorFinal")
    identificacion: str = Field(..., min_length=3, max_length=20)
    razon_social: str = Field(..., min_length=1, max_length=300)
    nombre_comercial: Optional[str] = None
    direccion: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None


class ClienteUpdate(BaseModel):
    """Actualizar cliente."""
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    direccion: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    activo: Optional[bool] = None


class ClienteResponse(BaseModel):
    """Respuesta de cliente."""
    id: UUID
    tipo_identificacion: str
    identificacion: str
    razon_social: str
    nombre_comercial: Optional[str]
    direccion: Optional[str]
    email: Optional[str]
    telefono: Optional[str]
    activo: bool
    requiere_resu: bool


# =====================================================
# ENDPOINTS DE CLIENTES
# =====================================================

@router.get("")
async def listar_clientes(
    activo: Optional[bool] = None,
    buscar: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0
):
    """Lista clientes con filtros opcionales."""
    try:
        supabase = get_supabase_client()
        query = supabase.table('clientes').select('*', count='exact')

        if activo is not None:
            query = query.eq('activo', activo)
        if buscar:
            query = query.or_(f"razon_social.ilike.%{buscar}%,identificacion.ilike.%{buscar}%")

        result = query.order('razon_social').range(offset, offset + limit - 1).execute()

        return {
            "clientes": result.data,
            "total": result.count or len(result.data),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Error listando clientes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buscar")
async def buscar_clientes(q: str, limit: int = 10):
    """Busca clientes por RUC/Cédula o nombre (para autocompletar)."""
    try:
        supabase = get_supabase_client()
        result = supabase.table('clientes').select(
            'id, tipo_identificacion, identificacion, razon_social, nombre_comercial, email'
        ).or_(
            f"razon_social.ilike.%{q}%,identificacion.ilike.%{q}%,nombre_comercial.ilike.%{q}%"
        ).eq('activo', True).limit(limit).execute()

        return {"clientes": result.data}

    except Exception as e:
        logger.error(f"Error buscando clientes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas")
async def estadisticas_clientes():
    """Obtiene estadísticas generales de clientes."""
    try:
        supabase = get_supabase_client()

        # Total clientes
        total = supabase.table('clientes').select('id', count='exact').execute()
        activos = supabase.table('clientes').select('id', count='exact').eq('activo', True).execute()
        requieren_resu = supabase.table('clientes').select('id', count='exact').eq('requiere_resu', True).execute()

        # Clientes por tipo
        por_tipo = supabase.table('clientes').select('tipo_identificacion').execute()
        tipos = {}
        for c in por_tipo.data:
            t = c['tipo_identificacion']
            tipos[t] = tipos.get(t, 0) + 1

        return {
            "total": total.count or 0,
            "activos": activos.count or 0,
            "inactivos": (total.count or 0) - (activos.count or 0),
            "requieren_resu": requieren_resu.count or 0,
            "por_tipo": tipos
        }

    except Exception as e:
        logger.error(f"Error en estadísticas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{cliente_id}")
async def obtener_cliente(cliente_id: str):
    """Obtiene un cliente por ID."""
    try:
        supabase = get_supabase_client()
        result = supabase.table('clientes').select('*').eq('id', cliente_id).single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        # Obtener estadísticas del cliente
        facturas = supabase.table('comprobantes_electronicos').select(
            'id, importe_total, estado'
        ).eq('cliente_id', cliente_id).execute()

        total_ventas = sum(
            float(f['importe_total']) for f in facturas.data
            if f['estado'] == 'authorized'
        )
        total_facturas = len([f for f in facturas.data if f['estado'] == 'authorized'])

        return {
            **result.data,
            "estadisticas": {
                "total_ventas": total_ventas,
                "total_facturas": total_facturas
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo cliente: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/por-identificacion/{identificacion}")
async def obtener_cliente_por_identificacion(identificacion: str):
    """Obtiene un cliente por identificación (RUC/Cédula)."""
    try:
        supabase = get_supabase_client()
        result = supabase.table('clientes').select('*').eq(
            'identificacion', identificacion
        ).single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo cliente: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def crear_cliente(cliente: ClienteCreate):
    """Crea un nuevo cliente."""
    try:
        supabase = get_supabase_client()

        # Verificar si ya existe
        existing = supabase.table('clientes').select('id').eq(
            'identificacion', cliente.identificacion
        ).execute()

        if existing.data:
            raise HTTPException(status_code=400, detail="Ya existe un cliente con esa identificación")

        # Validar RUC si es tipo 04
        if cliente.tipo_identificacion == "04":
            if len(cliente.identificacion) != 13:
                raise HTTPException(status_code=400, detail="RUC debe tener 13 dígitos")
        elif cliente.tipo_identificacion == "05":
            if len(cliente.identificacion) != 10:
                raise HTTPException(status_code=400, detail="Cédula debe tener 10 dígitos")

        result = supabase.table('clientes').insert(
            cliente.model_dump(mode='json')
        ).execute()

        return {"message": "Cliente creado", "cliente": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando cliente: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{cliente_id}")
async def actualizar_cliente(cliente_id: str, cliente: ClienteUpdate):
    """Actualiza un cliente existente."""
    try:
        supabase = get_supabase_client()

        # Verificar que existe
        existing = supabase.table('clientes').select('id').eq('id', cliente_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        # Filtrar campos no nulos
        update_data = {k: v for k, v in cliente.model_dump().items() if v is not None}

        if not update_data:
            raise HTTPException(status_code=400, detail="No hay datos para actualizar")

        result = supabase.table('clientes').update(update_data).eq('id', cliente_id).execute()

        return {"message": "Cliente actualizado", "cliente": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error actualizando cliente: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{cliente_id}")
async def desactivar_cliente(cliente_id: str):
    """Desactiva un cliente (soft delete)."""
    try:
        supabase = get_supabase_client()

        # Verificar que existe
        existing = supabase.table('clientes').select('id').eq('id', cliente_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        result = supabase.table('clientes').update(
            {'activo': False}
        ).eq('id', cliente_id).execute()

        return {"message": "Cliente desactivado", "cliente": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error desactivando cliente: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{cliente_id}/activar")
async def activar_cliente(cliente_id: str):
    """Reactiva un cliente desactivado."""
    try:
        supabase = get_supabase_client()

        result = supabase.table('clientes').update(
            {'activo': True}
        ).eq('id', cliente_id).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        return {"message": "Cliente activado", "cliente": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activando cliente: {e}")
        raise HTTPException(status_code=500, detail=str(e))
