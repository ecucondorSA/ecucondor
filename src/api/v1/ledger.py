"""
ECUCONDOR - API del Ledger Contable
Endpoints para gestión contable y consultas.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.ledger import (
    EstadoAsiento,
    JournalService,
    PostingService,
    TipoAsiento,
    calcular_split_rapido,
    get_comision_service,
    get_journal_service,
    get_posting_service,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ===== SCHEMAS =====


class MovimientoRequest(BaseModel):
    """Movimiento de un asiento."""

    cuenta: str = Field(..., description="Código de cuenta contable")
    debe: float = Field(default=0, ge=0, description="Monto al debe")
    haber: float = Field(default=0, ge=0, description="Monto al haber")
    concepto: str | None = Field(None, description="Concepto del movimiento")


class CrearAsientoRequest(BaseModel):
    """Request para crear asiento."""

    fecha: date
    concepto: str = Field(..., min_length=1, max_length=500)
    referencia: str | None = None
    movimientos: list[MovimientoRequest] = Field(..., min_length=2)
    tipo: str = "normal"
    auto_contabilizar: bool = True


class AsientoSimpleRequest(BaseModel):
    """Request para asiento simple (1 debe, 1 haber)."""

    fecha: date
    concepto: str = Field(..., min_length=1)
    cuenta_debe: str
    cuenta_haber: str
    monto: float = Field(..., gt=0)
    referencia: str | None = None


class AnularAsientoRequest(BaseModel):
    """Request para anular asiento."""

    motivo: str = Field(..., min_length=5)


class ContabilizarTransaccionRequest(BaseModel):
    """Request para contabilizar transacción."""

    transaccion_id: str
    cuenta_contable: str | None = None
    es_ingreso_alquiler: bool = False


class ProcesarCobroRequest(BaseModel):
    """Request para procesar cobro con split."""

    monto: float = Field(..., gt=0)
    fecha: date
    concepto: str
    transaccion_id: str | None = None
    comprobante_id: str | None = None
    propietario_id: str | None = None
    vehiculo_id: str | None = None
    incluye_iva: bool = False


class RegistrarPagoRequest(BaseModel):
    """Request para registrar pago a propietario."""

    split_id: str
    fecha_pago: date
    referencia_pago: str


class FacturaRecibidaRequest(BaseModel):
    """Request para contabilizar factura de proveedor."""

    fecha: date
    proveedor: str
    numero_factura: str
    subtotal: float = Field(..., gt=0)
    iva: float = Field(default=0, ge=0)
    cuenta_gasto: str
    retencion_renta: float = Field(default=0, ge=0)
    retencion_iva: float = Field(default=0, ge=0)


class AsientoResponse(BaseModel):
    """Response de asiento."""

    id: str
    numero_asiento: int | None
    fecha: str
    concepto: str
    tipo: str
    total_debe: float
    total_haber: float
    estado: str
    movimientos: list[dict[str, Any]]


class SplitResponse(BaseModel):
    """Response de split de comisión."""

    monto_bruto: float
    porcentaje_comision: float
    monto_comision: float
    monto_propietario: float


# ===== ENDPOINTS DE ASIENTOS =====


@router.post(
    "/asientos",
    status_code=status.HTTP_201_CREATED,
    summary="Crear asiento contable",
    description="Crea un nuevo asiento con múltiples movimientos.",
)
async def crear_asiento(request: CrearAsientoRequest) -> dict[str, Any]:
    """Crea un asiento contable."""
    journal = get_journal_service()

    try:
        movimientos = [
            {
                "cuenta": m.cuenta,
                "debe": Decimal(str(m.debe)),
                "haber": Decimal(str(m.haber)),
                "concepto": m.concepto,
            }
            for m in request.movimientos
        ]

        asiento = await journal.crear_asiento(
            fecha=request.fecha,
            concepto=request.concepto,
            movimientos=movimientos,
            tipo=TipoAsiento(request.tipo),
            referencia=request.referencia,
            auto_contabilizar=request.auto_contabilizar,
        )

        return {
            "id": str(asiento.id),
            "numero_asiento": asiento.numero_asiento,
            "fecha": asiento.fecha.isoformat(),
            "concepto": asiento.concepto,
            "total_debe": float(asiento.total_debe),
            "total_haber": float(asiento.total_haber),
            "estado": asiento.estado.value,
            "esta_cuadrado": asiento.esta_cuadrado,
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/asientos/simple",
    status_code=status.HTTP_201_CREATED,
    summary="Crear asiento simple",
    description="Crea un asiento con un movimiento al debe y otro al haber.",
)
async def crear_asiento_simple(request: AsientoSimpleRequest) -> dict[str, Any]:
    """Crea un asiento simple."""
    journal = get_journal_service()

    try:
        asiento = await journal.crear_asiento_simple(
            fecha=request.fecha,
            concepto=request.concepto,
            cuenta_debe=request.cuenta_debe,
            cuenta_haber=request.cuenta_haber,
            monto=Decimal(str(request.monto)),
            referencia=request.referencia,
            auto_contabilizar=True,
        )

        return {
            "id": str(asiento.id),
            "numero_asiento": asiento.numero_asiento,
            "fecha": asiento.fecha.isoformat(),
            "concepto": asiento.concepto,
            "total": float(asiento.total_debe),
            "estado": asiento.estado.value,
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/asientos/{asiento_id}",
    summary="Obtener asiento",
    description="Obtiene un asiento con sus movimientos.",
)
async def obtener_asiento(asiento_id: str) -> dict[str, Any]:
    """Obtiene un asiento por ID."""
    from uuid import UUID

    journal = get_journal_service()
    asiento = await journal.obtener_por_id(UUID(asiento_id))

    if not asiento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asiento no encontrado",
        )

    return {
        "id": str(asiento.id),
        "numero_asiento": asiento.numero_asiento,
        "fecha": asiento.fecha.isoformat(),
        "concepto": asiento.concepto,
        "tipo": asiento.tipo.value,
        "referencia": asiento.referencia,
        "total_debe": float(asiento.total_debe),
        "total_haber": float(asiento.total_haber),
        "estado": asiento.estado.value,
        "movimientos": [
            {
                "cuenta": m.cuenta_codigo,
                "debe": float(m.debe),
                "haber": float(m.haber),
                "concepto": m.concepto,
            }
            for m in asiento.movimientos
        ],
    }


@router.post(
    "/asientos/{asiento_id}/contabilizar",
    summary="Contabilizar asiento",
    description="Contabiliza un asiento en borrador.",
)
async def contabilizar_asiento(asiento_id: str) -> dict[str, Any]:
    """Contabiliza un asiento."""
    from uuid import UUID

    journal = get_journal_service()

    try:
        asiento = await journal.contabilizar(UUID(asiento_id))
        return {
            "id": str(asiento.id),
            "estado": asiento.estado.value,
            "mensaje": "Asiento contabilizado exitosamente",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/asientos/{asiento_id}/anular",
    summary="Anular asiento",
    description="Anula un asiento creando un asiento de reverso.",
)
async def anular_asiento(
    asiento_id: str,
    request: AnularAsientoRequest,
) -> dict[str, Any]:
    """Anula un asiento."""
    from uuid import UUID

    journal = get_journal_service()

    try:
        reverso = await journal.anular(UUID(asiento_id), request.motivo)
        return {
            "asiento_anulado": asiento_id,
            "asiento_reverso": str(reverso.id),
            "mensaje": "Asiento anulado exitosamente",
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/libro-diario",
    summary="Libro diario",
    description="Lista asientos del libro diario.",
)
async def listar_libro_diario(
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
    tipo: str | None = Query(None),
    estado: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Lista asientos del libro diario."""
    journal = get_journal_service()

    result = await journal.listar_libro_diario(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo=TipoAsiento(tipo) if tipo else None,
        estado=EstadoAsiento(estado) if estado else None,
        limit=limit,
        offset=offset,
    )

    return {
        "asientos": result["data"],
        "total": result["count"],
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/libro-mayor/{cuenta}",
    summary="Libro mayor",
    description="Obtiene el libro mayor de una cuenta.",
)
async def obtener_libro_mayor(
    cuenta: str,
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
) -> list[dict[str, Any]]:
    """Obtiene libro mayor de una cuenta."""
    journal = get_journal_service()
    return await journal.obtener_libro_mayor(cuenta, fecha_desde, fecha_hasta)


# ===== ENDPOINTS DE COMISIONES =====


@router.get(
    "/split/calcular",
    summary="Calcular split de comisión",
    description="Calcula el split de comisión para un monto.",
)
async def calcular_split(
    monto: float = Query(..., gt=0, description="Monto total"),
) -> SplitResponse:
    """Calcula el split de comisión."""
    result = calcular_split_rapido(Decimal(str(monto)))
    return SplitResponse(
        monto_bruto=float(result["total"]),
        porcentaje_comision=float(result["porcentaje"]),
        monto_comision=float(result["comision"]),
        monto_propietario=float(result["propietario"]),
    )


@router.post(
    "/split/procesar",
    status_code=status.HTTP_201_CREATED,
    summary="Procesar cobro con split",
    description="Procesa un cobro aplicando el split de comisión y genera el asiento.",
)
async def procesar_cobro(request: ProcesarCobroRequest) -> dict[str, Any]:
    """Procesa un cobro con split de comisión."""
    from uuid import UUID

    comision_service = get_comision_service()

    try:
        split, asiento = await comision_service.procesar_cobro(
            monto_bruto=Decimal(str(request.monto)),
            fecha=request.fecha,
            concepto=request.concepto,
            transaccion_id=UUID(request.transaccion_id) if request.transaccion_id else None,
            comprobante_id=UUID(request.comprobante_id) if request.comprobante_id else None,
            propietario_id=UUID(request.propietario_id) if request.propietario_id else None,
            vehiculo_id=UUID(request.vehiculo_id) if request.vehiculo_id else None,
            incluye_iva=request.incluye_iva,
        )

        return {
            "split": {
                "id": str(split.id),
                "monto_bruto": float(split.monto_bruto),
                "monto_comision": float(split.monto_comision),
                "monto_propietario": float(split.monto_propietario),
                "estado": split.estado,
            },
            "asiento": {
                "id": str(asiento.id),
                "numero": asiento.numero_asiento,
            },
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/split/pagar",
    summary="Registrar pago a propietario",
    description="Registra el pago al propietario y genera el asiento correspondiente.",
)
async def registrar_pago_propietario(request: RegistrarPagoRequest) -> dict[str, Any]:
    """Registra pago a propietario."""
    from uuid import UUID

    comision_service = get_comision_service()

    try:
        split, asiento = await comision_service.registrar_pago_propietario(
            split_id=UUID(request.split_id),
            fecha_pago=request.fecha_pago,
            referencia_pago=request.referencia_pago,
        )

        return {
            "split_id": str(split.id),
            "estado": split.estado,
            "monto_pagado": float(split.monto_propietario),
            "asiento_pago_id": str(asiento.id),
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/split/pendientes",
    summary="Splits pendientes de pago",
    description="Lista splits pendientes de pago a propietarios.",
)
async def listar_pendientes_pago(
    propietario_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Lista splits pendientes."""
    from uuid import UUID

    comision_service = get_comision_service()

    splits = await comision_service.listar_pendientes_pago(
        propietario_id=UUID(propietario_id) if propietario_id else None,
        limit=limit,
    )

    return [
        {
            "id": str(s.id),
            "monto_bruto": float(s.monto_bruto),
            "monto_comision": float(s.monto_comision),
            "monto_propietario": float(s.monto_propietario),
            "estado": s.estado,
            "propietario_id": str(s.propietario_id) if s.propietario_id else None,
        }
        for s in splits
    ]


# ===== ENDPOINTS DE CONTABILIZACIÓN AUTOMÁTICA =====


@router.post(
    "/posting/transaccion",
    summary="Contabilizar transacción",
    description="Genera asiento desde una transacción bancaria.",
)
async def contabilizar_transaccion(
    request: ContabilizarTransaccionRequest,
) -> dict[str, Any]:
    """Contabiliza una transacción bancaria."""
    from uuid import UUID

    posting = get_posting_service()

    try:
        asiento = await posting.contabilizar_transaccion(
            transaccion_id=UUID(request.transaccion_id),
            cuenta_contable=request.cuenta_contable,
            es_ingreso_alquiler=request.es_ingreso_alquiler,
        )

        return {
            "transaccion_id": request.transaccion_id,
            "asiento_id": str(asiento.id),
            "numero_asiento": asiento.numero_asiento,
            "total": float(asiento.total_debe),
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/posting/factura-recibida",
    summary="Contabilizar factura de proveedor",
    description="Genera asiento desde una factura de proveedor.",
)
async def contabilizar_factura_recibida(
    request: FacturaRecibidaRequest,
) -> dict[str, Any]:
    """Contabiliza factura de proveedor."""
    posting = get_posting_service()

    try:
        asiento = await posting.contabilizar_factura_recibida(
            fecha=request.fecha,
            proveedor=request.proveedor,
            numero_factura=request.numero_factura,
            subtotal=Decimal(str(request.subtotal)),
            iva=Decimal(str(request.iva)),
            cuenta_gasto=request.cuenta_gasto,
            retencion_renta=Decimal(str(request.retencion_renta)),
            retencion_iva=Decimal(str(request.retencion_iva)),
        )

        return {
            "asiento_id": str(asiento.id),
            "numero_asiento": asiento.numero_asiento,
            "proveedor": request.proveedor,
            "total": float(asiento.total_debe),
        }

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ===== ENDPOINTS DE CONSULTAS =====


@router.get(
    "/balance",
    summary="Balance de comprobación",
    description="Obtiene el balance de comprobación de sumas y saldos.",
)
async def obtener_balance() -> list[dict[str, Any]]:
    """Obtiene balance de comprobación."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()
    result = await db.select("v_balance_comprobacion")
    return result["data"] or []


@router.get(
    "/cuentas/{codigo}/saldo",
    summary="Saldo de cuenta",
    description="Obtiene el saldo actual de una cuenta.",
)
async def obtener_saldo_cuenta(
    codigo: str,
    fecha_hasta: date | None = Query(None),
) -> dict[str, Any]:
    """Obtiene saldo de una cuenta."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    result = await db.rpc(
        "obtener_saldo_cuenta",
        {
            "p_cuenta_codigo": codigo,
            "p_fecha_hasta": fecha_hasta.isoformat() if fecha_hasta else None,
        }
    )

    return {
        "cuenta": codigo,
        "fecha_hasta": (fecha_hasta or date.today()).isoformat(),
        "saldo": float(result) if result else 0,
    }


# ===== ENDPOINTS DE IVA Y CRÉDITO TRIBUTARIO =====


@router.post(
    "/iva/calcular",
    summary="Calcular IVA mensual",
    description="Calcula el resumen de IVA y crédito tributario del mes.",
)
async def calcular_iva_mensual(
    anio: int = Query(..., ge=2020, le=2030),
    mes: int = Query(..., ge=1, le=12),
) -> dict[str, Any]:
    """Calcula el resumen de IVA del mes."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    try:
        # Ejecutar la función de cálculo
        result = await db.rpc(
            "generar_resumen_iva_mensual",
            {"p_anio": anio, "p_mes": mes}
        )

        # Obtener el resumen generado
        resumen = await db.select(
            "resumen_iva_mensual",
            filters={"anio": anio, "mes": mes},
            single=True
        )

        if resumen and resumen.get("data"):
            data = resumen["data"]
            return {
                "periodo": f"{anio}-{mes:02d}",
                "compras": {
                    "gravadas_15": float(data.get("compras_gravadas_15", 0)),
                    "iva_15": float(data.get("iva_compras_15", 0)),
                },
                "credito_tributario": {
                    "mes_anterior": float(data.get("credito_tributario_anterior", 0)),
                    "este_mes": float(data.get("credito_tributario_mes", 0)),
                    "total": float(data.get("credito_tributario_total", 0)),
                },
                "iva_ventas": float(data.get("iva_ventas_15", 0)),
                "iva_a_pagar": float(data.get("iva_a_pagar", 0)),
                "credito_siguiente_mes": float(data.get("credito_siguiente_mes", 0)),
                "estado": data.get("estado"),
            }
        else:
            return {
                "periodo": f"{anio}-{mes:02d}",
                "mensaje": "Resumen calculado pero sin datos",
            }

    except Exception as e:
        logger.error(f"Error calculando IVA: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error calculando IVA: {str(e)}",
        )


@router.get(
    "/iva/resumen",
    summary="Resumen IVA mensual",
    description="Obtiene el resumen de IVA de un período.",
)
async def obtener_resumen_iva(
    anio: int = Query(..., ge=2020, le=2030),
    mes: int = Query(..., ge=1, le=12),
) -> dict[str, Any]:
    """Obtiene el resumen de IVA del mes."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    result = await db.select(
        "v_resumen_iva_declaracion",
        filters={"anio": anio, "mes": mes},
        single=True
    )

    if not result or not result.get("data"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay resumen de IVA para {anio}-{mes:02d}. Ejecute el cálculo primero.",
        )

    return result["data"]


@router.get(
    "/iva/detalle",
    summary="Detalle crédito tributario",
    description="Lista el detalle de documentos que generan crédito tributario.",
)
async def obtener_detalle_credito(
    anio: int = Query(..., ge=2020, le=2030),
    mes: int = Query(..., ge=1, le=12),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Lista detalle de crédito tributario."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    result = await db.select(
        "v_credito_tributario_detalle",
        filters={"anio": anio, "mes": mes},
        limit=limit,
        offset=offset,
    )

    return {
        "periodo": f"{anio}-{mes:02d}",
        "detalle": result.get("data", []),
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/iva/evolucion",
    summary="Evolución crédito tributario",
    description="Muestra la evolución del crédito tributario en el tiempo.",
)
async def obtener_evolucion_credito(
    anio: int = Query(None, ge=2020, le=2030),
) -> list[dict[str, Any]]:
    """Obtiene evolución del crédito tributario."""
    from src.db.supabase import get_supabase_client

    db = get_supabase_client()

    filters = {"anio": anio} if anio else {}
    result = await db.select(
        "v_credito_tributario_acumulado",
        filters=filters,
        order="anio.asc,mes.asc",
    )

    return result.get("data", [])
