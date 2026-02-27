"""
ECUCONDOR - API de Servicios SRI
Endpoints para calendario tributario, retenciones, validaciones y consultas.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.config.settings import get_settings
from src.db.supabase import get_supabase_client
from src.sri.tax_calendar import TaxCalendar
from src.sri.services.retenciones import ServicioRetenciones
from src.sri.services.ruc_validator import ServicioRUC
from src.sri.services.comprobante_validator import ServicioComprobantesSRI, EstadoAutorizacion
from src.sri.services.sincronizacion import ServicioSincronizacionSRI

router = APIRouter()


class RegistrarCumplimientoRequest(BaseModel):
    """Request para registrar cumplimiento de obligación."""
    tipo_codigo: str
    anio: int
    mes: int
    numero_formulario: Optional[str] = None
    monto_declarado: Optional[float] = None
    monto_pagado: Optional[float] = None


# =====================================================
# CALENDARIO TRIBUTARIO
# =====================================================

@router.get("/calendario/proximas")
async def obtener_proximas_obligaciones(
    dias_adelante: int = Query(default=60, ge=1, le=365)
) -> dict[str, Any]:
    """
    Obtiene las próximas obligaciones tributarias.

    Args:
        dias_adelante: Número de días hacia adelante para consultar (1-365)

    Returns:
        Lista de obligaciones próximas con sus fechas de vencimiento
    """
    settings = get_settings()
    supabase = get_supabase_client()

    calendar = TaxCalendar(settings.sri_ruc, supabase)
    obligaciones = calendar.get_upcoming_obligations(dias_adelante)

    # Separar por urgencia
    urgentes = [o for o in obligaciones if o.get('alerta', False)]
    proximas = [o for o in obligaciones if not o.get('alerta', False)]

    return {
        "ruc": settings.sri_ruc,
        "fecha_consulta": str(date.today()),
        "dias_consultados": dias_adelante,
        "total_obligaciones": len(obligaciones),
        "alertas": len(urgentes),
        "urgentes": urgentes,
        "proximas": proximas
    }


@router.get("/calendario/widget")
async def obtener_widget_calendario() -> dict[str, Any]:
    """
    Obtiene datos para el widget del calendario en el dashboard.

    Returns:
        Datos resumidos para mostrar en el widget
    """
    settings = get_settings()
    supabase = get_supabase_client()

    calendar = TaxCalendar(settings.sri_ruc, supabase)
    widget_data = calendar.get_calendar_widget_data()

    return {
        "ruc": settings.sri_ruc,
        "empresa": settings.sri_razon_social,
        **widget_data
    }


@router.get("/calendario/mes/{anio}/{mes}")
async def obtener_obligaciones_mes(
    anio: int,
    mes: int
) -> dict[str, Any]:
    """
    Obtiene las obligaciones para un mes específico.

    Args:
        anio: Año del periodo
        mes: Mes del periodo (1-12)

    Returns:
        Obligaciones del mes con fechas de vencimiento
    """
    settings = get_settings()
    calendar = TaxCalendar(settings.sri_ruc)

    obligaciones = calendar.get_obligations(anio, mes)

    return {
        "ruc": settings.sri_ruc,
        "periodo": {
            "anio": anio,
            "mes": mes,
            "nombre_mes": calendar._get_month_name(mes)
        },
        "obligaciones": obligaciones
    }


@router.post("/calendario/cumplimiento")
async def registrar_cumplimiento(
    request: RegistrarCumplimientoRequest
) -> dict[str, Any]:
    """
    Registra el cumplimiento de una obligación tributaria.

    Args:
        request: Datos del cumplimiento

    Returns:
        Confirmación del registro
    """
    settings = get_settings()
    supabase = get_supabase_client()

    calendar = TaxCalendar(settings.sri_ruc, supabase)

    success = calendar.mark_obligation_completed(
        tipo_codigo=request.tipo_codigo,
        anio=request.anio,
        mes=request.mes,
        numero_formulario=request.numero_formulario,
        monto_declarado=request.monto_declarado,
        monto_pagado=request.monto_pagado
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Error al registrar el cumplimiento"
        )

    return {
        "success": True,
        "mensaje": f"Obligación {request.tipo_codigo} del período {request.mes}/{request.anio} marcada como cumplida",
        "tipo_codigo": request.tipo_codigo,
        "periodo": f"{request.mes}/{request.anio}"
    }


@router.get("/calendario/vencimientos-por-digito")
async def obtener_vencimientos_por_digito() -> dict[str, Any]:
    """
    Obtiene la tabla de días de vencimiento por noveno dígito del RUC.

    Returns:
        Mapeo de dígitos a días de vencimiento
    """
    return {
        "tabla_vencimientos": TaxCalendar.DEADLINE_MAPPING,
        "descripcion": "Día máximo de pago según el noveno dígito del RUC",
        "nota": "Las obligaciones mensuales se declaran el mes siguiente al periodo declarado"
    }


# =====================================================
# RETENCIONES IR E IVA
# =====================================================

class CalcularRetencionesRequest(BaseModel):
    """Request para calcular retenciones."""
    subtotal: float
    iva: float
    codigo_ir: str
    tipo_agente: str = "SOCIEDAD"
    tipo_proveedor: str = "SOCIEDAD"
    tipo_transaccion: str = "SERVICIOS"


@router.get("/retenciones/ir")
async def obtener_conceptos_ir() -> dict[str, Any]:
    """
    Obtiene la lista de conceptos de retención de Impuesto a la Renta.

    Returns:
        Lista de códigos SRI con concepto y porcentaje
    """
    supabase = get_supabase_client()
    servicio = ServicioRetenciones(supabase)
    conceptos = servicio.obtener_conceptos_ir()

    return {
        "conceptos": conceptos,
        "total": len(conceptos),
        "actualizacion": "2025-01-01"
    }


@router.get("/retenciones/iva")
async def obtener_conceptos_iva() -> dict[str, Any]:
    """
    Obtiene la lista de conceptos de retención de IVA.

    Returns:
        Lista de códigos SRI con concepto y porcentaje
    """
    supabase = get_supabase_client()
    servicio = ServicioRetenciones(supabase)
    conceptos = servicio.obtener_conceptos_iva()

    return {
        "conceptos": conceptos,
        "total": len(conceptos),
        "actualizacion": "2025-01-01",
        "resolucion": "NAC-DGERCGC24-00000008"
    }


@router.get("/retenciones/tipos-contribuyente")
async def obtener_tipos_contribuyente() -> dict[str, Any]:
    """
    Obtiene los tipos de contribuyente disponibles.

    Returns:
        Diccionario con códigos y nombres
    """
    servicio = ServicioRetenciones()
    return {
        "tipos": servicio.obtener_tipos_contribuyente(),
        "tipos_transaccion": servicio.obtener_tipos_transaccion()
    }


@router.post("/retenciones/calcular")
async def calcular_retenciones(request: CalcularRetencionesRequest) -> dict[str, Any]:
    """
    Calcula las retenciones IR e IVA para una compra.

    Args:
        request: Datos de la compra

    Returns:
        Retenciones calculadas con códigos, porcentajes y valores
    """
    supabase = get_supabase_client()
    servicio = ServicioRetenciones(supabase)

    resultado = servicio.calcular_retenciones(
        subtotal=Decimal(str(request.subtotal)),
        iva=Decimal(str(request.iva)),
        codigo_ir=request.codigo_ir,
        tipo_agente=request.tipo_agente,
        tipo_proveedor=request.tipo_proveedor,
        tipo_transaccion=request.tipo_transaccion
    )

    return {
        "retencion_ir": {
            "codigo": resultado.ir.codigo,
            "concepto": resultado.ir.concepto,
            "porcentaje": float(resultado.ir.porcentaje),
            "base": float(resultado.ir.base),
            "valor": float(resultado.ir.valor)
        },
        "retencion_iva": {
            "codigo": resultado.iva.codigo,
            "concepto": resultado.iva.concepto,
            "porcentaje": float(resultado.iva.porcentaje),
            "base": float(resultado.iva.base),
            "valor": float(resultado.iva.valor)
        },
        "total_retenciones": float(resultado.total_retenciones),
        "valor_a_pagar": float(resultado.valor_a_pagar),
        "subtotal": request.subtotal,
        "iva": request.iva,
        "total_factura": request.subtotal + request.iva
    }


@router.get("/retenciones/sugerir")
async def sugerir_retencion(descripcion: str = Query(..., min_length=3)) -> dict[str, Any]:
    """
    Sugiere códigos de retención IR basándose en la descripción del gasto.

    Args:
        descripcion: Descripción del gasto o servicio (mínimo 3 caracteres)

    Returns:
        Lista de sugerencias ordenadas por confianza
    """
    supabase = get_supabase_client()
    servicio = ServicioRetenciones(supabase)
    sugerencias = servicio.sugerir_retencion_ir(descripcion)

    return {
        "descripcion": descripcion,
        "sugerencias": sugerencias,
        "nota": "Seleccione el código que mejor se ajuste al tipo de gasto"
    }


# =====================================================
# VALIDACIÓN DE RUC
# =====================================================

@router.get("/ruc/validar/{ruc}")
async def validar_formato_ruc(ruc: str) -> dict[str, Any]:
    """
    Valida el formato de un RUC (sin consultar al SRI).

    Args:
        ruc: Número de RUC a validar (13 dígitos)

    Returns:
        Resultado de la validación con detalles
    """
    servicio = ServicioRUC()
    es_valido, mensaje = servicio.validar_formato_ruc(ruc)

    return {
        "ruc": ruc,
        "es_valido": es_valido,
        "mensaje": mensaje,
        "tipo_contribuyente_probable": servicio.obtener_tipo_contribuyente_codigo(ruc) if es_valido else None,
        "noveno_digito": int(ruc[8]) if len(ruc) >= 9 and ruc.isdigit() else None,
        "dia_vencimiento": TaxCalendar.DEADLINE_MAPPING.get(int(ruc[8]), 28) if len(ruc) >= 9 and ruc.isdigit() else None
    }


@router.get("/ruc/{ruc}")
async def consultar_ruc(
    ruc: str,
    usar_cache: bool = Query(default=True, description="Usar cache de consultas anteriores")
) -> dict[str, Any]:
    """
    Consulta información completa de un RUC.
    Intenta obtener datos del SRI y los cachea.

    Args:
        ruc: Número de RUC a consultar (13 dígitos)
        usar_cache: Si debe usar cache de consultas anteriores

    Returns:
        Información del contribuyente
    """
    supabase = get_supabase_client()
    servicio = ServicioRUC(supabase)

    # Validar formato primero
    es_valido, mensaje = servicio.validar_formato_ruc(ruc)
    if not es_valido:
        raise HTTPException(status_code=400, detail=mensaje)

    # Consultar información
    info = await servicio.consultar_ruc(ruc, usar_cache=usar_cache)

    if not info:
        raise HTTPException(
            status_code=404,
            detail="No se pudo obtener información del RUC"
        )

    return {
        "ruc": info.ruc,
        "razon_social": info.razon_social,
        "nombre_comercial": info.nombre_comercial,
        "estado": info.estado,
        "tipo_contribuyente": info.tipo_contribuyente,
        "obligado_contabilidad": info.obligado_contabilidad,
        "actividad_economica": info.actividad_economica,
        "direccion": info.direccion,
        "es_contribuyente_especial": info.es_contribuyente_especial,
        "es_exportador": info.es_exportador,
        "agente_retencion": info.agente_retencion,
        "fecha_consulta": info.fecha_consulta.isoformat(),
        "tipo_para_retenciones": servicio.determinar_tipo_retencion(info),
        "dia_vencimiento": TaxCalendar.DEADLINE_MAPPING.get(int(ruc[8]), 28)
    }


# =====================================================
# VALIDACIÓN DE COMPROBANTES ELECTRÓNICOS
# =====================================================

@router.get("/comprobante/info/{clave_acceso}")
async def obtener_info_clave(clave_acceso: str) -> dict[str, Any]:
    """
    Extrae información de una clave de acceso sin consultar al SRI.

    Args:
        clave_acceso: Clave de acceso del comprobante (49 dígitos)

    Returns:
        Información extraída de la clave
    """
    servicio = ServicioComprobantesSRI()

    # Validar formato
    es_valida, mensaje = servicio.validar_clave_acceso(clave_acceso)
    if not es_valida:
        raise HTTPException(status_code=400, detail=mensaje)

    # Extraer datos
    datos = servicio.extraer_datos_clave(clave_acceso)

    return {
        "clave_acceso": clave_acceso,
        "es_valida": True,
        **datos
    }


@router.get("/comprobante/validar/{clave_acceso}")
async def validar_comprobante(
    clave_acceso: str,
    ambiente: str = Query(default="PRODUCCION", description="Ambiente del SRI (PRODUCCION o PRUEBAS)")
) -> dict[str, Any]:
    """
    Valida un comprobante electrónico con el SRI.
    Consulta el Web Service del SRI para verificar el estado de autorización.

    Args:
        clave_acceso: Clave de acceso del comprobante (49 dígitos)
        ambiente: Ambiente del SRI a consultar

    Returns:
        Estado de autorización y detalles del comprobante
    """
    supabase = get_supabase_client()
    servicio = ServicioComprobantesSRI(supabase, ambiente=ambiente)

    # Validar formato primero
    es_valida, mensaje = servicio.validar_clave_acceso(clave_acceso)
    if not es_valida:
        raise HTTPException(status_code=400, detail=mensaje)

    # Consultar al SRI
    resultado = await servicio.validar_comprobante(clave_acceso)

    # Guardar resultado si está autorizado
    if resultado.estado == EstadoAutorizacion.AUTORIZADO:
        await servicio.guardar_validacion(resultado)

    return {
        "clave_acceso": resultado.clave_acceso,
        "estado": resultado.estado.value,
        "autorizado": resultado.estado == EstadoAutorizacion.AUTORIZADO,
        "numero_autorizacion": resultado.numero_autorizacion,
        "fecha_autorizacion": resultado.fecha_autorizacion.isoformat() if resultado.fecha_autorizacion else None,
        "ambiente": resultado.ambiente,
        "tipo_comprobante": resultado.tipo_comprobante,
        "ruc_emisor": resultado.ruc_emisor,
        "fecha_emision": resultado.fecha_emision,
        "mensajes": resultado.mensajes,
        "validado_en": resultado.validado_en.isoformat(),
        "tiene_xml": resultado.comprobante_xml is not None
    }


@router.post("/comprobante/validar-lote")
async def validar_comprobantes_lote(
    claves_acceso: list[str],
    ambiente: str = Query(default="PRODUCCION")
) -> dict[str, Any]:
    """
    Valida múltiples comprobantes electrónicos con el SRI.

    Args:
        claves_acceso: Lista de claves de acceso a validar (máximo 10)
        ambiente: Ambiente del SRI

    Returns:
        Resultados de validación para cada comprobante
    """
    if len(claves_acceso) > 10:
        raise HTTPException(
            status_code=400,
            detail="Máximo 10 claves de acceso por lote"
        )

    supabase = get_supabase_client()
    servicio = ServicioComprobantesSRI(supabase, ambiente=ambiente)

    resultados = []
    autorizados = 0
    errores = 0

    for clave in claves_acceso:
        resultado = await servicio.validar_comprobante(clave)
        resultados.append({
            "clave_acceso": resultado.clave_acceso,
            "estado": resultado.estado.value,
            "autorizado": resultado.estado == EstadoAutorizacion.AUTORIZADO,
            "tipo_comprobante": resultado.tipo_comprobante,
            "ruc_emisor": resultado.ruc_emisor
        })

        if resultado.estado == EstadoAutorizacion.AUTORIZADO:
            autorizados += 1
            await servicio.guardar_validacion(resultado)
        elif resultado.estado == EstadoAutorizacion.ERROR:
            errores += 1

    return {
        "total_procesados": len(claves_acceso),
        "autorizados": autorizados,
        "no_autorizados": len(claves_acceso) - autorizados - errores,
        "errores": errores,
        "resultados": resultados
    }


# =====================================================
# SINCRONIZACIÓN DE COMPROBANTES
# =====================================================

class ImportarXMLRequest(BaseModel):
    """Request para importar un XML de factura."""
    xml_content: str


class AprobarFacturaRequest(BaseModel):
    """Request para aprobar una factura pendiente."""
    proveedor_id: Optional[str] = None
    categoria_gasto: Optional[str] = None
    codigo_retencion_ir: Optional[str] = None
    codigo_retencion_iva: Optional[str] = None
    notas: Optional[str] = None


class RechazarFacturaRequest(BaseModel):
    """Request para rechazar una factura."""
    motivo: str


@router.get("/sincronizacion/pendientes")
async def obtener_facturas_pendientes(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
) -> dict[str, Any]:
    """
    Obtiene la lista de facturas recibidas pendientes de revisión.

    Args:
        limit: Número máximo de facturas a retornar
        offset: Desplazamiento para paginación

    Returns:
        Lista de facturas pendientes con su información
    """
    supabase = get_supabase_client()
    servicio = ServicioSincronizacionSRI(supabase)

    facturas = await servicio.obtener_facturas_pendientes(limit=limit, offset=offset)

    # Obtener total para paginación
    total = len(facturas)
    if total == limit:
        # Puede haber más, consultar count
        try:
            result = supabase.table('facturas_recibidas').select(
                'id', count='exact'
            ).eq('estado', 'pendiente').execute()
            total = result.count or total
        except:
            pass

    return {
        "facturas": facturas,
        "total": total,
        "limit": limit,
        "offset": offset,
        "tiene_mas": len(facturas) == limit
    }


@router.post("/sincronizacion/importar-xml")
async def importar_factura_xml(request: ImportarXMLRequest) -> dict[str, Any]:
    """
    Importa una factura electrónica desde su contenido XML.

    Args:
        request: Contenido XML de la factura

    Returns:
        Datos de la factura importada
    """
    supabase = get_supabase_client()
    servicio = ServicioSincronizacionSRI(supabase)

    factura = await servicio.importar_xml(request.xml_content)

    if not factura:
        raise HTTPException(
            status_code=400,
            detail="No se pudo procesar el XML de la factura"
        )

    return {
        "success": True,
        "mensaje": "Factura importada correctamente",
        "factura": {
            "clave_acceso": factura.clave_acceso,
            "numero": factura.numero_factura,
            "ruc_emisor": factura.ruc_emisor,
            "razon_social": factura.razon_social_emisor,
            "fecha_emision": factura.fecha_emision,
            "subtotal": float(factura.subtotal),
            "iva": float(factura.iva),
            "total": float(factura.total)
        }
    }


@router.post("/sincronizacion/aprobar/{clave_acceso}")
async def aprobar_factura(
    clave_acceso: str,
    request: AprobarFacturaRequest
) -> dict[str, Any]:
    """
    Aprueba una factura pendiente para su contabilización.

    Args:
        clave_acceso: Clave de acceso de la factura
        request: Datos adicionales para la aprobación

    Returns:
        Confirmación de la aprobación
    """
    supabase = get_supabase_client()
    servicio = ServicioSincronizacionSRI(supabase)

    success = await servicio.aprobar_factura(
        clave_acceso=clave_acceso,
        proveedor_id=request.proveedor_id,
        categoria_gasto=request.categoria_gasto,
        codigo_retencion_ir=request.codigo_retencion_ir,
        codigo_retencion_iva=request.codigo_retencion_iva,
        notas=request.notas
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Factura no encontrada o ya procesada"
        )

    return {
        "success": True,
        "mensaje": "Factura aprobada correctamente",
        "clave_acceso": clave_acceso,
        "estado": "aprobada"
    }


@router.post("/sincronizacion/rechazar/{clave_acceso}")
async def rechazar_factura(
    clave_acceso: str,
    request: RechazarFacturaRequest
) -> dict[str, Any]:
    """
    Rechaza una factura pendiente.

    Args:
        clave_acceso: Clave de acceso de la factura
        request: Motivo del rechazo

    Returns:
        Confirmación del rechazo
    """
    supabase = get_supabase_client()
    servicio = ServicioSincronizacionSRI(supabase)

    success = await servicio.rechazar_factura(
        clave_acceso=clave_acceso,
        motivo=request.motivo
    )

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Factura no encontrada o ya procesada"
        )

    return {
        "success": True,
        "mensaje": "Factura rechazada",
        "clave_acceso": clave_acceso,
        "estado": "rechazada",
        "motivo": request.motivo
    }


@router.get("/sincronizacion/resumen")
async def obtener_resumen_sincronizacion() -> dict[str, Any]:
    """
    Obtiene un resumen del estado de sincronización de facturas.

    Returns:
        Contadores por estado y últimas fechas
    """
    supabase = get_supabase_client()

    try:
        # Contadores por estado
        pendientes = supabase.table('facturas_recibidas').select(
            'id', count='exact'
        ).eq('estado', 'pendiente').execute()

        aprobadas = supabase.table('facturas_recibidas').select(
            'id', count='exact'
        ).eq('estado', 'aprobada').execute()

        rechazadas = supabase.table('facturas_recibidas').select(
            'id', count='exact'
        ).eq('estado', 'rechazada').execute()

        # Última sincronización
        ultima = supabase.table('facturas_recibidas').select(
            'created_at'
        ).order('created_at', desc=True).limit(1).execute()

        return {
            "contadores": {
                "pendientes": pendientes.count or 0,
                "aprobadas": aprobadas.count or 0,
                "rechazadas": rechazadas.count or 0,
                "total": (pendientes.count or 0) + (aprobadas.count or 0) + (rechazadas.count or 0)
            },
            "ultima_sincronizacion": ultima.data[0]['created_at'] if ultima.data else None,
            "fecha_consulta": str(date.today())
        }
    except Exception as e:
        return {
            "contadores": {
                "pendientes": 0,
                "aprobadas": 0,
                "rechazadas": 0,
                "total": 0
            },
            "ultima_sincronizacion": None,
            "fecha_consulta": str(date.today()),
            "error": str(e)
        }
