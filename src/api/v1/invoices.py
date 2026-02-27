"""
ECUCONDOR - Endpoints de Facturación Electrónica
API REST para emisión y consulta de comprobantes electrónicos.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.db.repositories.invoices import InvoiceRepository, get_invoice_repository
from src.sri.access_key import generar_clave_acceso
from src.sri.client import SRIClient, get_sri_client
from src.sri.models import (
    CrearFacturaRequest,
    CrearFacturaResponse,
    EstadoComprobante,
    FormaPago,
    TipoComprobante,
    TipoIdentificacion,
)
from src.sri.ride_generator import RIDEGenerator
from src.sri.signer_sri import XAdESSigner, CertificateError, SigningError
from src.sri.xml_builder import crear_factura_xml

logger = structlog.get_logger(__name__)

router = APIRouter()


# ===== MODELOS DE RESPUESTA =====

class ComprobanteResumen(BaseModel):
    """Resumen de un comprobante para listados."""
    id: str
    tipo_comprobante: str
    numero: str
    clave_acceso: str
    fecha_emision: str
    cliente_razon_social: str
    cliente_identificacion: str
    importe_total: float
    estado: str
    numero_autorizacion: str | None = None


class ComprobanteDetalle(BaseModel):
    """Detalle completo de un comprobante."""
    id: str
    tipo_comprobante: str
    numero: str
    clave_acceso: str
    fecha_emision: str
    fecha_autorizacion: str | None
    numero_autorizacion: str | None
    estado: str
    emisor: dict[str, Any]
    cliente: dict[str, Any]
    detalles: list[dict[str, Any]]
    totales: dict[str, Any]
    pagos: list[dict[str, Any]]
    info_adicional: dict[str, Any] | None
    mensajes_sri: list[dict[str, Any]] | None


class ListaComprobantesResponse(BaseModel):
    """Respuesta de listado de comprobantes."""
    data: list[ComprobanteResumen]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    """Respuesta de error."""
    error: str
    message: str
    details: dict[str, Any] | None = None


# ===== DEPENDENCIAS =====

def get_signer(settings: Settings = Depends(get_settings)) -> XAdESSigner:
    """Obtiene el firmador XAdES."""
    try:
        return XAdESSigner(settings.sri_cert_path, settings.sri_cert_password)
    except CertificateError as e:
        logger.error("Error al cargar certificado", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Error de configuración: certificado no disponible"
        )


# ===== ENDPOINTS =====

@router.post(
    "/facturas",
    response_model=CrearFacturaResponse,
    status_code=201,
    summary="Crear y emitir una factura",
    description="Crea una nueva factura, la firma digitalmente y la envía al SRI.",
)
async def crear_factura(
    request: CrearFacturaRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    repo: InvoiceRepository = Depends(get_invoice_repository),
    signer: XAdESSigner = Depends(get_signer),
    sri_client: SRIClient = Depends(get_sri_client),
) -> CrearFacturaResponse:
    """
    Crea y emite una factura electrónica.

    El proceso incluye:
    1. Obtener siguiente secuencial
    2. Generar clave de acceso
    3. Construir XML
    4. Firmar con XAdES-BES
    5. Enviar al SRI (si enviar_sri=true)
    6. Guardar en base de datos
    7. Generar PDF RIDE (en background)
    """
    try:
        # Obtener siguiente secuencial automáticamente
        secuencial = await repo.siguiente_secuencial(
            tipo_comprobante=TipoComprobante.FACTURA.value,
            establecimiento=settings.sri_establecimiento,
            punto_emision=settings.sri_punto_emision,
        )

        # Generar clave de acceso
        clave_acceso = generar_clave_acceso(
            fecha_emision=date.today(),
            tipo_comprobante=TipoComprobante.FACTURA,
            ruc=settings.sri_ruc,
            ambiente=settings.sri_ambiente,
            establecimiento=settings.sri_establecimiento,
            punto_emision=settings.sri_punto_emision,
            secuencial=secuencial,
        )

        # Preparar items para el XML
        items_xml = [
            {
                "codigo": item.codigo,
                "descripcion": item.descripcion,
                "cantidad": item.cantidad,
                "precio_unitario": item.precio_unitario,
                "descuento": item.descuento,
                "aplica_iva": item.aplica_iva,
                "porcentaje_iva": item.porcentaje_iva,
            }
            for item in request.items
        ]

        # Construir XML
        xml_sin_firmar = crear_factura_xml(
            ruc=settings.sri_ruc,
            razon_social=settings.sri_razon_social,
            direccion_matriz=settings.sri_direccion_matriz,
            ambiente=settings.sri_ambiente,
            establecimiento=settings.sri_establecimiento,
            punto_emision=settings.sri_punto_emision,
            secuencial=secuencial,
            clave_acceso=clave_acceso,
            nombre_comercial=settings.sri_nombre_comercial,
            fecha_emision=date.today(),
            cliente_tipo_id=request.cliente.tipo_identificacion,
            cliente_identificacion=request.cliente.identificacion,
            cliente_razon_social=request.cliente.razon_social,
            cliente_direccion=request.cliente.direccion,
            cliente_email=request.cliente.email,
            obligado_contabilidad=settings.sri_obligado_contabilidad,
            items=items_xml,
            forma_pago=request.forma_pago,
            info_adicional=request.info_adicional,
        )

        # Firmar XML
        xml_firmado = signer.sign(xml_sin_firmar)

        # Calcular totales
        subtotal = sum(
            (item.cantidad * item.precio_unitario) - item.descuento
            for item in request.items
        )
        iva = sum(
            ((item.cantidad * item.precio_unitario) - item.descuento) * (item.porcentaje_iva / 100)
            for item in request.items
            if item.aplica_iva
        )
        importe_total = subtotal + iva

        # Guardar en base de datos
        comprobante = await repo.crear_comprobante(
            tipo_comprobante=TipoComprobante.FACTURA.value,
            establecimiento=settings.sri_establecimiento,
            punto_emision=settings.sri_punto_emision,
            secuencial=secuencial,
            clave_acceso=clave_acceso,
            fecha_emision=date.today(),
            cliente_tipo_id=request.cliente.tipo_identificacion.value,
            cliente_identificacion=request.cliente.identificacion,
            cliente_razon_social=request.cliente.razon_social,
            cliente_direccion=request.cliente.direccion,
            cliente_email=request.cliente.email,
            subtotal_sin_impuestos=Decimal(str(subtotal)),
            subtotal_15=Decimal(str(subtotal)) if any(i.aplica_iva for i in request.items) else Decimal("0"),
            iva=Decimal(str(iva)),
            importe_total=Decimal(str(importe_total)),
            estado=EstadoComprobante.PENDING if request.enviar_sri else EstadoComprobante.DRAFT,
            xml_sin_firmar=xml_sin_firmar,
            xml_firmado=xml_firmado,
            info_adicional=request.info_adicional,
        )

        # Agregar detalles
        detalles_db = [
            {
                "codigo": item.codigo,
                "descripcion": item.descripcion,
                "cantidad": float(item.cantidad),
                "precio_unitario": float(item.precio_unitario),
                "descuento": float(item.descuento),
                "precio_total_sin_impuesto": float(
                    (item.cantidad * item.precio_unitario) - item.descuento
                ),
            }
            for item in request.items
        ]
        await repo.agregar_detalles(comprobante["id"], detalles_db)

        # Agregar pago
        await repo.agregar_pagos(comprobante["id"], [{
            "forma_pago": request.forma_pago.value,
            "total": float(importe_total),
        }])

        # Enviar al SRI en background si se solicitó
        if request.enviar_sri:
            background_tasks.add_task(
                _enviar_y_procesar_sri,
                comprobante["id"],
                xml_firmado,
                clave_acceso,
                repo,
                sri_client,
                settings,
            )

        numero = f"{settings.sri_establecimiento}-{settings.sri_punto_emision}-{str(secuencial).zfill(9)}"

        logger.info(
            "Factura creada",
            id=comprobante["id"],
            numero=numero,
            clave_acceso=clave_acceso[:20] + "...",
            importe_total=float(importe_total),
        )

        return CrearFacturaResponse(
            id=comprobante["id"],
            numero=numero,
            clave_acceso=clave_acceso,
            estado=EstadoComprobante.PENDING if request.enviar_sri else EstadoComprobante.DRAFT,
            fecha_emision=date.today(),
            importe_total=Decimal(str(importe_total)),
            mensaje="Factura creada. Procesando envío al SRI..." if request.enviar_sri else "Factura guardada como borrador",
        )

    except SigningError as e:
        logger.error("Error al firmar factura", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error de firma: {e}")

    except Exception as e:
        logger.error("Error al crear factura", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")


async def _enviar_y_procesar_sri(
    comprobante_id: str,
    xml_firmado: str,
    clave_acceso: str,
    repo: InvoiceRepository,
    sri_client: SRIClient,
    settings: Settings,
) -> None:
    """Tarea en background para enviar al SRI y procesar respuesta."""
    try:
        resultado = await sri_client.enviar_y_autorizar(
            xml_firmado=xml_firmado,
            clave_acceso=clave_acceso,
        )

        # Actualizar estado en BD
        await repo.actualizar_estado(
            comprobante_id=comprobante_id,
            estado=resultado["estado"],
            numero_autorizacion=resultado.get("numero_autorizacion"),
            fecha_autorizacion=resultado.get("fecha_autorizacion"),
            xml_autorizado=resultado.get("xml_autorizado"),
            mensajes_sri=resultado.get("mensajes"),
        )

        # Generar PDF si fue autorizado
        if resultado["estado"] == EstadoComprobante.AUTHORIZED:
            try:
                comprobante = await repo.obtener_por_id(comprobante_id)
                detalles = await repo.obtener_detalles(comprobante_id)
                ride = RIDEGenerator()
                pdf_bytes = ride.generar_factura_pdf(
                    comprobante=comprobante,
                    detalles=detalles,
                    emisor={
                        "ruc": settings.sri_ruc,
                        "razon_social": settings.sri_razon_social,
                        "direccion_matriz": settings.sri_direccion_matriz,
                    },
                )
                await repo.guardar_pdf(comprobante_id, pdf_bytes)
                logger.info("PDF RIDE generado", comprobante_id=comprobante_id)
            except Exception as pdf_err:
                logger.error("Error generando PDF RIDE", error=str(pdf_err))

        logger.info(
            "Procesamiento SRI completado",
            comprobante_id=comprobante_id,
            estado=resultado["estado"].value if hasattr(resultado["estado"], 'value') else resultado["estado"],
        )

    except Exception as e:
        logger.error(
            "Error en procesamiento SRI",
            comprobante_id=comprobante_id,
            error=str(e),
        )
        await repo.actualizar_estado(
            comprobante_id=comprobante_id,
            estado=EstadoComprobante.ERROR,
            mensajes_sri=[{"identificador": "ERROR", "mensaje": str(e)}],
        )


@router.get(
    "/facturas",
    response_model=ListaComprobantesResponse,
    summary="Listar facturas",
    description="Obtiene una lista de facturas con filtros opcionales.",
)
async def listar_facturas(
    estado: EstadoComprobante | None = Query(None, description="Filtrar por estado"),
    fecha_desde: date | None = Query(None, description="Fecha de inicio"),
    fecha_hasta: date | None = Query(None, description="Fecha de fin"),
    cliente: str | None = Query(None, description="Identificación del cliente"),
    limit: int = Query(50, ge=1, le=100, description="Máximo de registros"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    repo: InvoiceRepository = Depends(get_invoice_repository),
) -> ListaComprobantesResponse:
    """Lista facturas con paginación y filtros."""
    result = await repo.listar_comprobantes(
        tipo_comprobante=TipoComprobante.FACTURA.value,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cliente_identificacion=cliente,
        limit=limit,
        offset=offset,
    )

    comprobantes = [
        ComprobanteResumen(
            id=c["id"],
            tipo_comprobante=c["tipo_comprobante"],
            numero=f"{c['establecimiento']}-{c['punto_emision']}-{c['secuencial']}",
            clave_acceso=c["clave_acceso"],
            fecha_emision=c["fecha_emision"],
            cliente_razon_social=c["cliente_razon_social"],
            cliente_identificacion=c["cliente_identificacion"],
            importe_total=c["importe_total"],
            estado=c["estado"],
            numero_autorizacion=c.get("numero_autorizacion"),
        )
        for c in result["data"]
    ]

    return ListaComprobantesResponse(
        data=comprobantes,
        total=result["count"],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/facturas/{factura_id}",
    response_model=ComprobanteDetalle,
    summary="Obtener factura",
    description="Obtiene el detalle completo de una factura.",
)
async def obtener_factura(
    factura_id: str,
    settings: Settings = Depends(get_settings),
    repo: InvoiceRepository = Depends(get_invoice_repository),
) -> ComprobanteDetalle:
    """Obtiene el detalle de una factura por ID."""
    comprobante = await repo.obtener_por_id(factura_id)

    if not comprobante:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    detalles = await repo.obtener_detalles(factura_id)
    pagos = await repo.obtener_pagos(factura_id)

    return ComprobanteDetalle(
        id=comprobante["id"],
        tipo_comprobante=comprobante["tipo_comprobante"],
        numero=f"{comprobante['establecimiento']}-{comprobante['punto_emision']}-{comprobante['secuencial']}",
        clave_acceso=comprobante["clave_acceso"],
        fecha_emision=comprobante["fecha_emision"],
        fecha_autorizacion=comprobante.get("fecha_autorizacion"),
        numero_autorizacion=comprobante.get("numero_autorizacion"),
        estado=comprobante["estado"],
        emisor={
            "ruc": settings.sri_ruc,
            "razon_social": settings.sri_razon_social,
            "direccion_matriz": settings.sri_direccion_matriz,
        },
        cliente={
            "tipo_identificacion": comprobante["cliente_tipo_id"],
            "identificacion": comprobante["cliente_identificacion"],
            "razon_social": comprobante["cliente_razon_social"],
            "direccion": comprobante.get("cliente_direccion"),
            "email": comprobante.get("cliente_email"),
        },
        detalles=detalles,
        totales={
            "subtotal_sin_impuestos": comprobante.get("subtotal_sin_impuestos", 0),
            "subtotal_15": comprobante.get("subtotal_15", 0),
            "subtotal_0": comprobante.get("subtotal_0", 0),
            "iva": comprobante.get("iva", 0),
            "importe_total": comprobante["importe_total"],
        },
        pagos=pagos,
        info_adicional=comprobante.get("info_adicional"),
        mensajes_sri=comprobante.get("mensajes_sri"),
    )


@router.get(
    "/facturas/{factura_id}/pdf",
    summary="Descargar PDF RIDE",
    description="Descarga el PDF del RIDE de una factura.",
)
async def descargar_pdf(
    factura_id: str,
    repo: InvoiceRepository = Depends(get_invoice_repository),
):
    """Descarga el PDF del RIDE de una factura."""
    from fastapi.responses import Response

    comprobante = await repo.obtener_por_id(factura_id)

    if not comprobante:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if not comprobante.get("pdf_ride"):
        raise HTTPException(status_code=404, detail="PDF no disponible")

    # Convertir hex back a bytes
    pdf_bytes = bytes.fromhex(comprobante["pdf_ride"])

    numero = f"{comprobante['establecimiento']}-{comprobante['punto_emision']}-{comprobante['secuencial']}"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=factura_{numero}.pdf"
        }
    )


@router.post(
    "/facturas/{factura_id}/reenviar",
    summary="Reenviar al SRI",
    description="Reintenta el envío de una factura al SRI.",
)
async def reenviar_factura(
    factura_id: str,
    background_tasks: BackgroundTasks,
    repo: InvoiceRepository = Depends(get_invoice_repository),
    sri_client: SRIClient = Depends(get_sri_client),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Reenvía una factura al SRI."""
    comprobante = await repo.obtener_por_id(factura_id)

    if not comprobante:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if comprobante["estado"] == EstadoComprobante.AUTHORIZED.value:
        raise HTTPException(status_code=400, detail="La factura ya está autorizada")

    if not comprobante.get("xml_firmado"):
        raise HTTPException(status_code=400, detail="No hay XML firmado disponible")

    # Actualizar estado a pendiente
    await repo.actualizar_estado(
        comprobante_id=factura_id,
        estado=EstadoComprobante.PENDING,
        intentos_envio=(comprobante.get("intentos_envio", 0) or 0) + 1,
    )

    # Reenviar en background
    background_tasks.add_task(
        _enviar_y_procesar_sri,
        factura_id,
        comprobante["xml_firmado"],
        comprobante["clave_acceso"],
        repo,
        sri_client,
        settings,
    )

    return {"message": "Reenvío iniciado", "id": factura_id}


@router.get(
    "/facturas/clave/{clave_acceso}",
    response_model=ComprobanteResumen,
    summary="Buscar por clave de acceso",
    description="Busca una factura por su clave de acceso.",
)
async def buscar_por_clave(
    clave_acceso: str,
    repo: InvoiceRepository = Depends(get_invoice_repository),
) -> ComprobanteResumen:
    """Busca una factura por clave de acceso."""
    if len(clave_acceso) != 49:
        raise HTTPException(status_code=400, detail="Clave de acceso inválida")

    comprobante = await repo.obtener_por_clave_acceso(clave_acceso)

    if not comprobante:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    return ComprobanteResumen(
        id=comprobante["id"],
        tipo_comprobante=comprobante["tipo_comprobante"],
        numero=f"{comprobante['establecimiento']}-{comprobante['punto_emision']}-{comprobante['secuencial']}",
        clave_acceso=comprobante["clave_acceso"],
        fecha_emision=comprobante["fecha_emision"],
        cliente_razon_social=comprobante["cliente_razon_social"],
        cliente_identificacion=comprobante["cliente_identificacion"],
        importe_total=comprobante["importe_total"],
        estado=comprobante["estado"],
        numero_autorizacion=comprobante.get("numero_autorizacion"),
    )
