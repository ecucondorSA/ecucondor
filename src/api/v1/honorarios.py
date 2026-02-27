"""
ECUCONDOR - API de Honorarios
Endpoints para gestión de honorarios del administrador (IESS código 109).
"""

from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.honorarios import (
    EstadoPago,
    HonorarioCalculator,
    HonorariosService,
    calcular_honorario_rapido,
    get_calculator,
    get_honorarios_service,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ===== SCHEMAS =====


class CrearAdministradorRequest(BaseModel):
    """Request para crear administrador."""

    tipo_identificacion: str = Field(..., pattern=r"^(04|05|06|07|08)$")
    identificacion: str = Field(..., min_length=10, max_length=13)
    nombres: str
    apellidos: str
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    numero_iess: str | None = None
    banco: str | None = None
    numero_cuenta: str | None = None
    tipo_cuenta: str | None = None


class CrearPagoRequest(BaseModel):
    """Request para crear pago de honorarios."""

    administrador_id: str
    anio: int = Field(..., ge=2020, le=2100)
    mes: int = Field(..., ge=1, le=12)
    honorario_bruto: float = Field(..., gt=0)
    auto_contabilizar: bool = True


class RegistrarPagoRequest(BaseModel):
    """Request para registrar pago efectivo."""

    fecha_pago: date
    referencia_pago: str
    auto_contabilizar: bool = True


class CalculoResponse(BaseModel):
    """Response de cálculo de honorario."""

    honorario_bruto: float
    aporte_patronal: float
    porcentaje_aporte_patronal: float
    aporte_personal: float
    porcentaje_aporte_personal: float
    total_iess: float
    retencion_renta: float
    porcentaje_retencion: float
    neto_pagar: float
    total_descuentos: float
    costo_empresa: float


# ===== ENDPOINTS DE ADMINISTRADORES =====


@router.post(
    "/administradores",
    status_code=status.HTTP_201_CREATED,
    summary="Crear administrador",
    description="Registra un nuevo administrador para pagos de honorarios.",
)
async def crear_administrador(request: CrearAdministradorRequest) -> dict[str, Any]:
    """Crea un administrador."""
    service = get_honorarios_service()

    try:
        admin = await service.crear_administrador(
            tipo_identificacion=request.tipo_identificacion,
            identificacion=request.identificacion,
            nombres=request.nombres,
            apellidos=request.apellidos,
            email=request.email,
            telefono=request.telefono,
            direccion=request.direccion,
            numero_iess=request.numero_iess,
            banco=request.banco,
            numero_cuenta=request.numero_cuenta,
            tipo_cuenta=request.tipo_cuenta,
        )

        return {
            "id": str(admin.id),
            "identificacion": admin.identificacion,
            "razon_social": admin.razon_social,
            "activo": admin.activo,
        }

    except Exception as e:
        logger.error("Error creando administrador", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/administradores",
    summary="Listar administradores",
    description="Lista todos los administradores registrados.",
)
async def listar_administradores(
    activo: bool | None = Query(None, description="Filtrar por estado"),
) -> list[dict[str, Any]]:
    """Lista administradores."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    filters = {}
    if activo is not None:
        filters["activo"] = activo

    result = await db.select(
        "administradores",
        columns="id, identificacion, razon_social, email, telefono, "
                "numero_iess, activo, created_at",
        filters=filters,
        order="razon_social",
    )

    return result["data"] or []


@router.get(
    "/administradores/{admin_id}",
    summary="Obtener administrador",
    description="Obtiene los datos de un administrador.",
)
async def obtener_administrador(admin_id: str) -> dict[str, Any]:
    """Obtiene un administrador."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()
    result = await db.select(
        "administradores",
        filters={"id": admin_id}
    )

    if not result["data"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Administrador no encontrado",
        )

    return result["data"][0]


# ===== ENDPOINTS DE CÁLCULO =====


@router.get(
    "/calcular",
    summary="Calcular honorario",
    description="Calcula honorario con IESS y retención en la fuente.",
)
async def calcular_honorario(
    monto: float = Query(..., gt=0, description="Monto bruto del honorario"),
    anio: int | None = Query(None, description="Año fiscal para retención"),
) -> CalculoResponse:
    """Calcula un honorario."""
    calculo = await calcular_honorario_rapido(
        Decimal(str(monto)),
        date(anio or date.today().year, 1, 1) if anio else None,
    )

    return CalculoResponse(
        honorario_bruto=float(calculo.honorario_bruto),
        aporte_patronal=float(calculo.calculo_iess.aporte_patronal),
        porcentaje_aporte_patronal=float(calculo.calculo_iess.porcentaje_aporte_patronal),
        aporte_personal=float(calculo.calculo_iess.aporte_personal),
        porcentaje_aporte_personal=float(calculo.calculo_iess.porcentaje_aporte_personal),
        total_iess=float(calculo.calculo_iess.total_iess),
        retencion_renta=float(calculo.calculo_retencion.retencion),
        porcentaje_retencion=float(calculo.calculo_retencion.porcentaje_retencion),
        neto_pagar=float(calculo.neto_pagar),
        total_descuentos=float(calculo.total_descuentos),
        costo_empresa=float(calculo.costo_empresa),
    )


# ===== ENDPOINTS DE PAGOS =====


@router.post(
    "/pagos",
    status_code=status.HTTP_201_CREATED,
    summary="Crear pago de honorarios",
    description="Crea un pago de honorarios con cálculo automático de IESS y retención.",
)
async def crear_pago(request: CrearPagoRequest) -> dict[str, Any]:
    """Crea un pago de honorarios."""
    from uuid import UUID

    service = get_honorarios_service()

    try:
        pago, asiento = await service.crear_pago(
            administrador_id=UUID(request.administrador_id),
            anio=request.anio,
            mes=request.mes,
            honorario_bruto=Decimal(str(request.honorario_bruto)),
            auto_contabilizar=request.auto_contabilizar,
        )

        return {
            "id": str(pago.id),
            "periodo": pago.periodo,
            "honorario_bruto": float(pago.honorario_bruto),
            "aporte_patronal": float(pago.aporte_patronal),
            "aporte_personal": float(pago.aporte_personal),
            "total_iess": float(pago.total_iess),
            "retencion_renta": float(pago.retencion_renta),
            "neto_pagar": float(pago.neto_pagar),
            "estado": pago.estado.value,
            "asiento_id": str(asiento.id) if asiento else None,
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/pagos",
    summary="Listar pagos",
    description="Lista pagos de honorarios con filtros.",
)
async def listar_pagos(
    administrador_id: str | None = Query(None),
    anio: int | None = Query(None),
    mes: int | None = Query(None),
    estado: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Lista pagos de honorarios."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    filters: dict[str, Any] = {}
    if administrador_id:
        filters["administrador_id"] = administrador_id
    if anio:
        filters["anio"] = anio
    if mes:
        filters["mes"] = mes
    if estado:
        filters["estado"] = estado

    result = await db.select(
        "pagos_honorarios",
        columns="id, periodo, honorario_bruto, aporte_patronal, aporte_personal, "
                "total_iess, retencion_renta, neto_pagar, estado, created_at",
        filters=filters,
        order="-periodo",
        limit=limit,
    )

    return result["data"] or []


@router.get(
    "/pagos/{pago_id}",
    summary="Obtener pago",
    description="Obtiene los detalles de un pago de honorarios.",
)
async def obtener_pago(pago_id: str) -> dict[str, Any]:
    """Obtiene un pago de honorarios."""
    from uuid import UUID

    service = get_honorarios_service()

    try:
        pago = await service.obtener_pago(UUID(pago_id))

        return {
            "id": str(pago.id),
            "administrador_id": str(pago.administrador_id),
            "periodo": pago.periodo,
            "anio": pago.anio,
            "mes": pago.mes,
            "honorario_bruto": float(pago.honorario_bruto),
            "aporte_patronal": float(pago.aporte_patronal),
            "aporte_personal": float(pago.aporte_personal),
            "total_iess": float(pago.total_iess),
            "base_imponible_renta": float(pago.base_imponible_renta),
            "retencion_renta": float(pago.retencion_renta),
            "porcentaje_retencion": float(pago.porcentaje_retencion),
            "neto_pagar": float(pago.neto_pagar),
            "estado": pago.estado.value,
            "fecha_pago": pago.fecha_pago.isoformat() if pago.fecha_pago else None,
            "referencia_pago": pago.referencia_pago,
            "asiento_id": str(pago.asiento_id) if pago.asiento_id else None,
            "notas": pago.notas,
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/pagos/{pago_id}/aprobar",
    summary="Aprobar pago",
    description="Aprueba un pago de honorarios pendiente.",
)
async def aprobar_pago(pago_id: str) -> dict[str, Any]:
    """Aprueba un pago."""
    from uuid import UUID

    service = get_honorarios_service()

    try:
        pago = await service.aprobar_pago(UUID(pago_id))

        return {
            "id": str(pago.id),
            "estado": pago.estado.value,
            "mensaje": "Pago aprobado exitosamente",
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/pagos/{pago_id}/registrar-pago",
    summary="Registrar pago efectivo",
    description="Registra el pago efectivo de un honorario aprobado.",
)
async def registrar_pago_efectivo(
    pago_id: str,
    request: RegistrarPagoRequest,
) -> dict[str, Any]:
    """Registra el pago efectivo."""
    from uuid import UUID

    service = get_honorarios_service()

    try:
        pago, asiento = await service.registrar_pago(
            pago_id=UUID(pago_id),
            fecha_pago=request.fecha_pago,
            referencia_pago=request.referencia_pago,
            auto_contabilizar=request.auto_contabilizar,
        )

        return {
            "id": str(pago.id),
            "estado": pago.estado.value,
            "neto_pagado": float(pago.neto_pagar),
            "referencia": pago.referencia_pago,
            "asiento_pago_id": str(asiento.id) if asiento else None,
            "mensaje": "Pago registrado exitosamente",
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/pagos/pendientes/lista",
    summary="Pagos pendientes",
    description="Lista pagos pendientes de aprobación o pago.",
)
async def listar_pagos_pendientes(
    administrador_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Lista pagos pendientes."""
    from uuid import UUID

    service = get_honorarios_service()

    pagos = await service.listar_pagos_pendientes(
        administrador_id=UUID(administrador_id) if administrador_id else None,
    )

    return [
        {
            "id": str(p.id),
            "periodo": p.periodo,
            "honorario_bruto": float(p.honorario_bruto),
            "neto_pagar": float(p.neto_pagar),
            "estado": p.estado.value,
        }
        for p in pagos
    ]


# ===== ENDPOINTS DE REPORTES =====


@router.get(
    "/reportes/resumen-anual/{admin_id}",
    summary="Resumen anual",
    description="Obtiene el resumen anual de honorarios de un administrador.",
)
async def resumen_anual(
    admin_id: str,
    anio: int = Query(..., ge=2020, le=2100),
) -> dict[str, Any]:
    """Obtiene resumen anual."""
    from uuid import UUID

    service = get_honorarios_service()

    try:
        resumen = await service.obtener_resumen_anual(
            administrador_id=UUID(admin_id),
            anio=anio,
        )

        return {
            "administrador_id": str(resumen.administrador_id),
            "razon_social": resumen.razon_social,
            "identificacion": resumen.identificacion,
            "anio": resumen.anio,
            "total_pagos": resumen.total_pagos,
            "total_honorarios": float(resumen.total_honorarios),
            "total_aporte_patronal": float(resumen.total_aporte_patronal),
            "total_aporte_personal": float(resumen.total_aporte_personal),
            "total_iess": float(resumen.total_iess),
            "total_retencion": float(resumen.total_retencion),
            "total_neto": float(resumen.total_neto),
        }

    except Exception as e:
        logger.error("Error obteniendo resumen", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/reportes/pendientes-iess",
    summary="Reporte IESS pendiente",
    description="Obtiene el total de aportes IESS pendientes de pago.",
)
async def reporte_iess_pendiente() -> dict[str, Any]:
    """Reporte de IESS pendiente."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    result = await db.select(
        "pagos_honorarios",
        columns="SUM(total_iess) as total, COUNT(*) as cantidad",
        filters={"estado": {"in": ["pendiente", "aprobado"]}},
    )

    data = result["data"][0] if result["data"] else {}

    return {
        "total_iess_pendiente": float(data.get("total", 0) or 0),
        "cantidad_pagos": data.get("cantidad", 0) or 0,
    }
