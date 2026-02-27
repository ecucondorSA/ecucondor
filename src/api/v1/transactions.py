"""
ECUCONDOR - API de Transacciones Bancarias
Endpoints para importación y gestión de transacciones bancarias.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from src.db.repositories.transactions import get_transaction_repository
from src.ingestor import (
    BancoEcuador,
    Deduplicator,
    EstadoTransaccion,
    Reconciler,
    TipoTransaccion,
    TransactionNormalizer,
)
from src.ingestor.parsers.base import get_parser

logger = structlog.get_logger(__name__)

router = APIRouter()


# ===== SCHEMAS =====


class ImportarExtractoRequest(BaseModel):
    """Request para importar extracto (sin archivo)."""

    banco: BancoEcuador
    cuenta_bancaria: str = Field(..., min_length=5, max_length=30)
    encoding: str | None = None
    delimiter: str | None = None


class TransaccionResponse(BaseModel):
    """Response de transacción."""

    id: str
    hash_unico: str
    banco: str
    cuenta_bancaria: str
    fecha: str
    tipo: str
    origen: str
    monto: float
    saldo: float | None
    descripcion: str
    contraparte_nombre: str | None
    contraparte_identificacion: str | None
    estado: str
    categoria_sugerida: str | None
    confianza_categoria: float | None
    comprobante_id: str | None


class ResultadoImportacionResponse(BaseModel):
    """Response de importación."""

    archivo: str
    banco: str
    cuenta: str
    total_lineas: int
    transacciones_nuevas: int
    transacciones_duplicadas: int
    transacciones_error: int
    monto_total_creditos: float
    monto_total_debitos: float
    errores: list[str]
    advertencias: list[str]


class ConciliarRequest(BaseModel):
    """Request para conciliar transacción."""

    comprobante_id: str


class CandidatoConciliacion(BaseModel):
    """Candidato de conciliación."""

    comprobante_id: str
    numero_comprobante: str
    fecha_emision: str
    monto_total: float
    cliente_nombre: str
    cliente_identificacion: str
    score: float
    razones: list[str]


class SugerenciaConciliacionResponse(BaseModel):
    """Response con sugerencias de conciliación."""

    transaccion_id: str
    candidatos: list[CandidatoConciliacion]


# ===== ENDPOINTS =====


@router.post(
    "/importar",
    response_model=ResultadoImportacionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Importar extracto bancario",
    description="""
    Importa un archivo de extracto bancario (CSV o Excel).

    Bancos soportados:
    - pichincha: Banco Pichincha
    - produbanco: Banco Produbanco

    El sistema:
    1. Parsea el archivo según el formato del banco
    2. Normaliza las descripciones
    3. Detecta y filtra duplicados
    4. Sugiere categorías contables
    5. Guarda las transacciones nuevas
    """,
)
async def importar_extracto(
    archivo: UploadFile = File(..., description="Archivo CSV o Excel del extracto"),
    banco: BancoEcuador = Form(..., description="Banco de origen"),
    cuenta_bancaria: str = Form(..., description="Número de cuenta"),
    encoding: str | None = Form(None, description="Codificación del archivo"),
    delimiter: str | None = Form(None, description="Delimitador CSV"),
):
    """Importa un archivo de extracto bancario."""
    logger.info(
        "Iniciando importación de extracto",
        archivo=archivo.filename,
        banco=banco.value,
        cuenta=cuenta_bancaria,
    )

    try:
        # Leer contenido del archivo
        content = await archivo.read()

        # Obtener parser apropiado
        parser = get_parser(banco, cuenta_bancaria)

        # Parsear archivo
        resultado = parser.parse_bytes(
            content,
            archivo.filename or "extracto.csv",
            encoding=encoding,
            delimiter=delimiter,
        )

        if not resultado.transacciones:
            return ResultadoImportacionResponse(
                archivo=resultado.archivo,
                banco=resultado.banco.value,
                cuenta=resultado.cuenta,
                total_lineas=resultado.total_lineas,
                transacciones_nuevas=0,
                transacciones_duplicadas=resultado.transacciones_duplicadas,
                transacciones_error=resultado.transacciones_error,
                monto_total_creditos=float(resultado.monto_total_creditos),
                monto_total_debitos=float(resultado.monto_total_debitos),
                errores=resultado.errores,
                advertencias=resultado.advertencias,
            )

        # Normalizar transacciones
        normalizer = TransactionNormalizer()
        transacciones = normalizer.normalizar_lote(resultado.transacciones)

        # Deduplicar contra base de datos
        repo = get_transaction_repository()
        hashes = [tx.hash_unico for tx in transacciones]
        hashes_existentes = await repo.obtener_hashes_existentes(hashes)

        deduplicator = Deduplicator()
        resultado_dedup = deduplicator.deduplicar_contra_db(
            transacciones, hashes_existentes
        )

        # Guardar transacciones nuevas
        if resultado_dedup.transacciones_unicas:
            await repo.crear_lote(resultado_dedup.transacciones_unicas)

        # Registrar importación
        await repo.registrar_importacion(
            nombre_archivo=archivo.filename or "extracto.csv",
            banco=banco,
            cuenta_bancaria=cuenta_bancaria,
            total_lineas=resultado.total_lineas,
            transacciones_nuevas=len(resultado_dedup.transacciones_unicas),
            transacciones_duplicadas=len(resultado_dedup.transacciones_duplicadas),
            transacciones_error=resultado.transacciones_error,
            monto_creditos=resultado.monto_total_creditos,
            monto_debitos=resultado.monto_total_debitos,
            errores=resultado.errores,
            advertencias=resultado.advertencias,
        )

        logger.info(
            "Importación completada",
            nuevas=len(resultado_dedup.transacciones_unicas),
            duplicadas=len(resultado_dedup.transacciones_duplicadas),
        )

        return ResultadoImportacionResponse(
            archivo=resultado.archivo,
            banco=resultado.banco.value,
            cuenta=resultado.cuenta,
            total_lineas=resultado.total_lineas,
            transacciones_nuevas=len(resultado_dedup.transacciones_unicas),
            transacciones_duplicadas=len(resultado_dedup.transacciones_duplicadas),
            transacciones_error=resultado.transacciones_error,
            monto_total_creditos=float(resultado.monto_total_creditos),
            monto_total_debitos=float(resultado.monto_total_debitos),
            errores=resultado.errores,
            advertencias=resultado.advertencias,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Error importando extracto", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando archivo: {str(e)}",
        )


@router.get(
    "/",
    summary="Listar transacciones",
    description="Lista transacciones bancarias con filtros opcionales.",
)
async def listar_transacciones(
    banco: BancoEcuador | None = Query(None, description="Filtrar por banco"),
    cuenta: str | None = Query(None, description="Filtrar por cuenta"),
    tipo: TipoTransaccion | None = Query(None, description="Filtrar por tipo"),
    estado: EstadoTransaccion | None = Query(None, description="Filtrar por estado"),
    fecha_desde: date | None = Query(None, description="Fecha inicio"),
    fecha_hasta: date | None = Query(None, description="Fecha fin"),
    solo_pendientes: bool = Query(False, description="Solo sin conciliar"),
    limit: int = Query(50, ge=1, le=200, description="Límite"),
    offset: int = Query(0, ge=0, description="Offset"),
) -> dict[str, Any]:
    """Lista transacciones con filtros."""
    repo = get_transaction_repository()

    resultado = await repo.listar_transacciones(
        banco=banco,
        cuenta_bancaria=cuenta,
        tipo=tipo,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        solo_sin_conciliar=solo_pendientes,
        limit=limit,
        offset=offset,
    )

    return {
        "transacciones": resultado["data"],
        "total": resultado["count"],
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/{transaccion_id}",
    summary="Obtener transacción",
    description="Obtiene los detalles de una transacción específica.",
)
async def obtener_transaccion(transaccion_id: str) -> dict[str, Any]:
    """Obtiene una transacción por ID."""
    repo = get_transaction_repository()
    transaccion = await repo.obtener_por_id(transaccion_id)

    if not transaccion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transacción no encontrada",
        )

    return transaccion


@router.get(
    "/{transaccion_id}/candidatos",
    summary="Obtener candidatos de conciliación",
    description="Obtiene comprobantes candidatos para conciliar con esta transacción.",
)
async def obtener_candidatos_conciliacion(
    transaccion_id: str,
    tolerancia_monto: float = Query(0.01, description="Tolerancia en monto"),
    tolerancia_dias: int = Query(7, ge=1, le=30, description="Tolerancia en días"),
) -> SugerenciaConciliacionResponse:
    """Obtiene candidatos de conciliación para una transacción."""
    repo = get_transaction_repository()

    # Obtener transacción
    transaccion = await repo.obtener_por_id(transaccion_id)
    if not transaccion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transacción no encontrada",
        )

    # Buscar candidatos
    candidatos = await repo.obtener_candidatos_conciliacion(
        monto=Decimal(str(transaccion["monto"])),
        fecha=date.fromisoformat(transaccion["fecha"]),
        identificacion=transaccion.get("contraparte_identificacion"),
        tolerancia_monto=Decimal(str(tolerancia_monto)),
        tolerancia_dias=tolerancia_dias,
    )

    return SugerenciaConciliacionResponse(
        transaccion_id=transaccion_id,
        candidatos=[
            CandidatoConciliacion(
                comprobante_id=c["id"],
                numero_comprobante=f"{c['establecimiento']}-{c['punto_emision']}-{c['secuencial']}",
                fecha_emision=c["fecha_emision"],
                monto_total=float(c["importe_total"]),
                cliente_nombre=c["cliente_razon_social"],
                cliente_identificacion=c["cliente_identificacion"],
                score=1.0 - (float(c["diff_monto"]) + float(c["diff_dias"]) * 0.1),
                razones=[
                    f"Diferencia monto: ${c['diff_monto']:.2f}",
                    f"Diferencia días: {c['diff_dias']}",
                ],
            )
            for c in candidatos
        ],
    )


@router.post(
    "/{transaccion_id}/conciliar",
    summary="Conciliar transacción",
    description="Concilia una transacción con un comprobante específico.",
)
async def conciliar_transaccion(
    transaccion_id: str,
    request: ConciliarRequest,
) -> dict[str, Any]:
    """Concilia una transacción con un comprobante."""
    repo = get_transaction_repository()

    # Verificar que la transacción existe
    transaccion = await repo.obtener_por_id(transaccion_id)
    if not transaccion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transacción no encontrada",
        )

    # Verificar que no está ya conciliada
    if transaccion["estado"] == "conciliada":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La transacción ya está conciliada",
        )

    # Conciliar
    resultado = await repo.conciliar(transaccion_id, request.comprobante_id)

    logger.info(
        "Transacción conciliada",
        transaccion_id=transaccion_id,
        comprobante_id=request.comprobante_id,
    )

    return resultado


@router.post(
    "/{transaccion_id}/descartar",
    summary="Descartar transacción",
    description="Marca una transacción como descartada.",
)
async def descartar_transaccion(
    transaccion_id: str,
    notas: str | None = Query(None, description="Razón del descarte"),
) -> dict[str, Any]:
    """Descarta una transacción."""
    repo = get_transaction_repository()

    resultado = await repo.actualizar_estado(
        transaccion_id,
        EstadoTransaccion.DESCARTADA,
        notas=notas,
    )

    if not resultado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transacción no encontrada",
        )

    return resultado


@router.get(
    "/resumen/mensual",
    summary="Resumen mensual",
    description="Obtiene resumen mensual de transacciones por banco y cuenta.",
)
async def resumen_mensual(
    banco: BancoEcuador | None = Query(None, description="Filtrar por banco"),
    cuenta: str | None = Query(None, description="Filtrar por cuenta"),
) -> list[dict[str, Any]]:
    """Obtiene resumen mensual de transacciones."""
    repo = get_transaction_repository()
    return await repo.obtener_resumen_mensual(banco, cuenta)


@router.get(
    "/pendientes/lista",
    summary="Listar pendientes",
    description="Lista transacciones pendientes de conciliación ordenadas por monto.",
)
async def listar_pendientes(
    banco: BancoEcuador | None = Query(None, description="Filtrar por banco"),
    limit: int = Query(100, ge=1, le=500, description="Límite"),
) -> list[dict[str, Any]]:
    """Lista transacciones pendientes de conciliación."""
    repo = get_transaction_repository()
    return await repo.obtener_pendientes(banco, limit)
