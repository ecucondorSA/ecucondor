"""
ECUCONDOR - Dashboard Routes
Endpoints para el dashboard web.
"""

import calendar
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from src.config.settings import get_settings
from src.db.supabase import get_supabase_client
from src.ledger.reportes import GeneradorReportes
from src.sri.tax_calendar import TaxCalendar
from src.sri.iva import CalculadorIVA
from src.sri.services.sincronizacion import ServicioSincronizacionSRI
from src.sri.services.retenciones import ServicioRetenciones
from src.reports import ExportadorPDF, ExportadorExcel

logger = structlog.get_logger(__name__)

router = APIRouter()

# Configurar templates
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def get_supabase():
    """Obtiene cliente Supabase."""
    return get_supabase_client()


def format_currency(value: float | Decimal) -> str:
    """Formatea valor como moneda."""
    return f"${float(value):,.2f}"


def get_dashboard_data(anio: int, mes: int) -> dict[str, Any]:
    """Obtiene todos los datos para el dashboard."""
    settings = get_settings()
    supabase = get_supabase()
    generador = GeneradorReportes(supabase)
    calculador = CalculadorIVA(supabase)

    # Fechas del periodo
    fecha_inicio = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = date(anio, mes, ultimo_dia)

    # Información de empresa
    empresa_info = supabase.table('company_info').select('*').limit(1).execute()
    empresa = empresa_info.data[0] if empresa_info.data else {}

    # Balance General
    balance = generador.generar_balance_general(
        fecha_corte=fecha_fin,
        empresa=empresa.get('razon_social', settings.sri_razon_social)
    )

    # Estado de Resultados
    estado_resultados = generador.generar_estado_resultados(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        empresa=empresa.get('razon_social', settings.sri_razon_social)
    )

    # Datos IVA
    datos_iva = calculador.calcular_periodo(
        anio=anio,
        mes=mes,
        ruc=settings.sri_ruc,
        razon_social=settings.sri_razon_social
    )

    # Clientes
    try:
        clientes_res = supabase.table('clientes').select('*', count='exact').limit(1).execute()
        total_clientes = clientes_res.count
    except Exception:
        total_clientes = 0

    # Transacciones bancarias del mes
    tx_mes = supabase.table('transacciones_bancarias').select(
        '*'
    ).gte('fecha', str(fecha_inicio)).lte('fecha', str(fecha_fin)).order('fecha', desc=True).execute()

    # Calcular totales reales de transacciones
    total_creditos = sum(
        float(t['monto']) for t in tx_mes.data if t['tipo'] == 'credito'
    )
    total_debitos = sum(
        float(t['monto']) for t in tx_mes.data if t['tipo'] == 'debito'
    )

    # Ultimas transacciones para la tabla
    ultimas_transacciones = tx_mes.data[:10]

    # Asientos contables recientes
    asientos_res = supabase.table('asientos_contables').select(
        '*'
    ).order('created_at', desc=True).limit(5).execute()
    ultimos_asientos = asientos_res.data

    # ========== MOVIMIENTOS BANCARIOS DEL MES ==========
    # Obtener movimientos de la cuenta bancaria (1.1.1.07)
    mov_bancarios = supabase.table('movimientos_contables').select(
        'debe, haber, concepto, asientos_contables!inner(fecha, estado)'
    ).eq('cuenta_codigo', '1.1.1.07').gte(
        'asientos_contables.fecha', str(fecha_inicio)
    ).lte(
        'asientos_contables.fecha', str(fecha_fin)
    ).neq('asientos_contables.estado', 'anulado').execute()

    # Calcular totales: Debe = entradas, Haber = salidas
    banco_entradas = sum(float(m['debe']) for m in (mov_bancarios.data or []))
    banco_salidas = sum(float(m['haber']) for m in (mov_bancarios.data or []))
    banco_neto = banco_entradas - banco_salidas

    # Facturas del mes
    facturas = supabase.table('comprobantes_electronicos').select(
        'estado', 'importe_total'
    ).eq('tipo_comprobante', '01').gte(
        'fecha_emision', str(fecha_inicio)
    ).lte('fecha_emision', str(fecha_fin)).execute()

    facturas_autorizadas = sum(1 for f in facturas.data if f['estado'] == 'authorized')
    facturas_anuladas = sum(1 for f in facturas.data if f['estado'] == 'cancelled')
    total_facturado = sum(
        float(f['importe_total']) for f in facturas.data if f['estado'] == 'authorized'
    )

    # Obligaciones tributarias usando TaxCalendar mejorado
    hoy = date.today()
    tax_calendar = TaxCalendar(settings.sri_ruc, supabase)

    # Obtener próximas obligaciones (30 días adelante)
    proximas_obligaciones = tax_calendar.get_upcoming_obligations(30)

    # Convertir formato para compatibilidad con template existente
    obligaciones = []
    for ob in proximas_obligaciones:
        fecha_venc = date.fromisoformat(ob['vencimiento']) if isinstance(ob['vencimiento'], str) else ob['vencimiento']
        obligaciones.append({
            'nombre': ob['nombre'],
            'monto': float(datos_iva.iva_a_pagar) if 'IVA' in ob['nombre'] else 0,
            'fecha_limite': fecha_venc,
            'vencida': fecha_venc < hoy,
            'tipo': ob.get('tipo', 'otro').lower(),
            'formulario': ob.get('formulario'),
            'dias_restantes': ob.get('dias_restantes', 0),
            'alerta': ob.get('alerta', False),
            'prioridad': ob.get('prioridad', 'media')
        })

    # Widget de calendario tributario
    calendario_widget = tax_calendar.get_calendar_widget_data()

    meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]

    # --- Ratios Financieros ---
    # Calcular Activo Corriente (1.1) y Pasivo Corriente (2.1)
    activo_corriente = sum(l.saldo for l in balance.activos.lineas if l.codigo.startswith('1.1') and not l.es_titulo)
    pasivo_corriente = sum(l.saldo for l in balance.pasivos.lineas if l.codigo.startswith('2.1') and not l.es_titulo)

    # Liquidez Corriente
    liquidez = 0
    if pasivo_corriente > 0:
        liquidez = float(activo_corriente / pasivo_corriente)

    # Capital de Trabajo
    capital_trabajo = float(activo_corriente - pasivo_corriente)

    # Solvencia (Activo Total / Pasivo Total)
    solvencia = 0
    if balance.total_pasivos > 0:
        solvencia = float(balance.total_activos / balance.total_pasivos)

    # --- Top Cuentas ---
    # Top 5 Ingresos
    top_ingresos = sorted(
        [l for l in estado_resultados.ingresos if not l.es_titulo],
        key=lambda x: x.saldo,
        reverse=True
    )[:5]

    # Top 5 Gastos
    top_gastos = sorted(
        [l for l in estado_resultados.gastos if not l.es_titulo],
        key=lambda x: x.saldo,
        reverse=True
    )[:5]

    return {
        'empresa': {
            'ruc': settings.sri_ruc,
            'razon_social': empresa.get('razon_social', settings.sri_razon_social),
            'nombre_comercial': empresa.get('nombre_comercial', settings.sri_nombre_comercial),
        },
        'periodo': {
            'anio': anio,
            'mes': mes,
            'mes_nombre': meses[mes - 1],
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
        },
        'balance': {
            'activos': float(balance.total_activos),
            'pasivos': float(balance.total_pasivos),
            'patrimonio': float(balance.total_patrimonio),
            'cuadrado': balance.esta_cuadrado,
        },
        'resultados': {
            'ingresos': float(estado_resultados.total_ingresos),
            'gastos': float(estado_resultados.total_gastos),
            'utilidad': float(estado_resultados.utilidad_bruta),
            'es_utilidad': estado_resultados.es_utilidad,
        },
        'ratios': {
            'liquidez': liquidez,
            'capital_trabajo': capital_trabajo,
            'solvencia': solvencia,
        },
        'top_cuentas': {
            'ingresos': [{'nombre': l.nombre, 'saldo': float(l.saldo)} for l in top_ingresos],
            'gastos': [{'nombre': l.nombre, 'saldo': float(l.saldo)} for l in top_gastos],
        },
        'iva': {
            'ventas_gravadas': float(datos_iva.ventas_locales_gravadas),
            'ventas_0': float(datos_iva.ventas_locales_0),
            'iva_ventas': float(datos_iva.iva_ventas),
            'iva_compras': float(datos_iva.iva_compras),
            'a_pagar': float(datos_iva.iva_a_pagar),
            'credito_proximo': float(datos_iva.credito_proximo_mes),
        },
        'transacciones': {
            'creditos': total_creditos,
            'debitos': total_debitos,
            'neto': total_creditos - total_debitos,
            'recientes': ultimas_transacciones,
        },
        'contabilidad': {
            'asientos_recientes': ultimos_asientos,
        },
        'clientes': {
            'total': total_clientes,
        },
        'facturacion': {
            'emitidas': facturas_autorizadas,
            'anuladas': facturas_anuladas,
            'total': total_facturado,
        },
        'banco': {
            'entradas': banco_entradas,
            'salidas': banco_salidas,
            'neto': banco_neto,
            'num_movimientos': len(mov_bancarios.data or []),
        },
        'obligaciones': obligaciones,
        'calendario': calendario_widget,
        'hoy': hoy,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    anio: int | None = None,
    mes: int | None = None
):
    """Muestra el dashboard principal."""
    hoy = date.today()
    anio = anio or hoy.year
    mes = mes or hoy.month

    try:
        data = get_dashboard_data(anio, mes)
    except Exception as e:
        # En caso de error de conexion, mostrar datos vacios
        settings = get_settings()
        meses = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        data = {
            'empresa': {
                'ruc': settings.sri_ruc,
                'razon_social': settings.sri_razon_social,
                'nombre_comercial': settings.sri_nombre_comercial,
            },
            'periodo': {
                'anio': anio,
                'mes': mes,
                'mes_nombre': meses[mes - 1],
                'fecha_inicio': date(anio, mes, 1),
                'fecha_fin': date(anio, mes, 28),
            },
            'balance': {'activos': 0, 'pasivos': 0, 'patrimonio': 0, 'cuadrado': True},
            'resultados': {'ingresos': 0, 'gastos': 0, 'utilidad': 0, 'es_utilidad': True},
            'ratios': {'liquidez': 0, 'capital_trabajo': 0, 'solvencia': 0},
            'top_cuentas': {'ingresos': [], 'gastos': []},
            'iva': {'ventas_gravadas': 0, 'ventas_0': 0, 'iva_ventas': 0, 'iva_compras': 0, 'a_pagar': 0, 'credito_proximo': 0},
            'transacciones': {'creditos': 0, 'debitos': 0, 'neto': 0, 'recientes': []},
            'contabilidad': {'asientos_recientes': []},
            'clientes': {'total': 0},
            'facturacion': {'emitidas': 0, 'anuladas': 0, 'total': 0},
            'banco': {'entradas': 0, 'salidas': 0, 'neto': 0, 'num_movimientos': 0},
            'obligaciones': [],
            'hoy': hoy,
            'error': f'Error de conexion: {str(e)[:100]}',
        }

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, **data}
    )


@router.get("/api/resumen")
async def api_resumen(anio: int | None = None, mes: int | None = None) -> dict[str, Any]:
    """API endpoint para obtener resumen del periodo."""
    hoy = date.today()
    anio = anio or hoy.year
    mes = mes or hoy.month

    try:
        return get_dashboard_data(anio, mes)
    except Exception as e:
        settings = get_settings()
        meses = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        return {
            'empresa': {
                'ruc': settings.sri_ruc,
                'razon_social': settings.sri_razon_social,
                'nombre_comercial': settings.sri_nombre_comercial,
            },
            'periodo': {
                'anio': anio,
                'mes': mes,
                'mes_nombre': meses[mes - 1],
                'fecha_inicio': str(date(anio, mes, 1)),
                'fecha_fin': str(date(anio, mes, 28)),
            },
            'balance': {'activos': 0, 'pasivos': 0, 'patrimonio': 0, 'cuadrado': True},
            'resultados': {'ingresos': 0, 'gastos': 0, 'utilidad': 0, 'es_utilidad': True},
            'iva': {'ventas_gravadas': 0, 'ventas_0': 0, 'iva_ventas': 0, 'iva_compras': 0, 'a_pagar': 0, 'credito_proximo': 0},
            'transacciones': {'creditos': 0, 'debitos': 0, 'neto': 0, 'recientes': []},
            'contabilidad': {'asientos_recientes': []},
            'clientes': {'total': 0},
            'facturacion': {'emitidas': 0, 'anuladas': 0, 'total': 0},
            'banco': {'entradas': 0, 'salidas': 0, 'neto': 0, 'num_movimientos': 0},
            'obligaciones': [],
            'hoy': str(hoy),
            'error': f'Error de conexion: {str(e)[:100]}',
        }


@router.get("/impuestos", response_class=HTMLResponse)
async def tax_hub(request: Request):
    """
    Centro de Impuestos: Calendario, ATS y Enlaces SRI.
    """
    try:
        # Obtener RUC para calcular calendario
        settings = get_settings()
        company = settings.sri_ruc
        calendar = TaxCalendar(company)
        
        # Fecha actual
        hoy = date.today()
        obligaciones = calendar.get_obligations(hoy.year, hoy.month)
        
        # Helper para nombre de mes
        meses = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]

        return templates.TemplateResponse(
            "tax/hub.html",
            {
                "request": request,
                "obligaciones": obligaciones,
                "ruc": company,
                "anio_actual": hoy.year,
                "mes_actual": hoy.month,
                "empresa": {
                    "razon_social": settings.sri_razon_social,
                    "ruc": settings.sri_ruc
                },
                "periodo": {
                    "anio": hoy.year,
                    "mes_nombre": meses[hoy.month - 1]
                },
                "sri_link": "https://srienlinea.sri.gob.ec/rig/pages/menuInicial.xhtml?codOperativo=IVA&contextoMPT=https://srienlinea.sri.gob.ec/tuportal-internet&pathMPT=&actualMPT=Anexo%20Transaccional%20Simplificado%20&linkMPT=%2Frig%2Fpages%2FmenuInicial.xhtml%3FcodOperativo%3DIVA&esFavorito=S"
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "dashboard.html", # Fallback
            {"request": request, "error": f"Error cargando impuestos: {str(e)}"}
        )


@router.post("/api/ats/generate")
async def generate_ats_endpoint(request: Request):
    """
    Genera el XML del ATS y lo descarga.
    """
    try:
        form = await request.form()
        anio = int(form.get('anio'))
        mes = int(form.get('mes'))
        
        # Reutilizar logica del script (idealmente mover a servicio)
        # Por ahora ejecutamos el script como subproceso para simplicidad
        # o importamos la funcion si la refactorizamos.
        # Vamos a refactorizar generate_ats.py a un servicio rapido aqui.
        
        from generate_ats import generate_ats
        
        # Redirigir stdout para capturar el XML (hack rapido)
        import io
        from contextlib import redirect_stdout
        from starlette.responses import Response
        
        f = io.StringIO()
        with redirect_stdout(f):
            generate_ats(anio, mes)
        
        output = f.getvalue()
        # Extraer XML del output (buscar <?xml ...)
        xml_start = output.find("<?xml")
        if xml_start != -1:
            xml_content = output[xml_start:]
            filename = f"ATS_{mes:02d}_{anio}.xml"
            
            return Response(
                content=xml_content,
                media_type="application/xml",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            raise Exception("No se genero XML valido")
            
    except Exception as e:
        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "error": f"Error generando ATS: {str(e)}"}
        )


@router.get("/reportes/balance", response_class=HTMLResponse)
async def reporte_balance(request: Request, anio: int | None = None, mes: int | None = None):
    """Reporte de Balance General."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)
        
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month
        
        # Fecha de corte: fin del mes seleccionado
        import calendar
        _, last_day = calendar.monthrange(anio, mes)
        fecha_corte = date(anio, mes, last_day)
        
        balance = generador.generar_balance_general(
            fecha_corte=fecha_corte,
            empresa=settings.sri_razon_social,
            incluir_cuentas_cero=True
        )
        
        # Contexto comun
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        
        return templates.TemplateResponse(
            "reports/balance.html",
            {
                "request": request,
                "balance": balance,
                "fecha_corte": fecha_corte,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en reporte_balance: {e}", exc_info=True)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "error": f"Error generando balance: {str(e)}",
                "empresa": {"razon_social": "Error", "ruc": "Error"},
                "periodo": {"anio": anio or 2025, "mes_nombre": "Error"}
            }
        )


@router.get("/reportes/balance/pdf")
async def exportar_balance_pdf(anio: int | None = None, mes: int | None = None):
    """Exporta Balance General a PDF."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        _, last_day = calendar.monthrange(anio, mes)
        fecha_corte = date(anio, mes, last_day)

        balance = generador.generar_balance_general(
            fecha_corte=fecha_corte,
            empresa=settings.sri_razon_social,
            incluir_cuentas_cero=True
        )

        exportador = ExportadorPDF(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_balance(balance, fecha_corte)

        filename = f"Balance_General_{anio}_{mes:02d}.pdf"
        return Response(
            content=contenido,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando balance PDF: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/reportes/balance/excel")
async def exportar_balance_excel(anio: int | None = None, mes: int | None = None):
    """Exporta Balance General a Excel."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        _, last_day = calendar.monthrange(anio, mes)
        fecha_corte = date(anio, mes, last_day)

        balance = generador.generar_balance_general(
            fecha_corte=fecha_corte,
            empresa=settings.sri_razon_social,
            incluir_cuentas_cero=True
        )

        exportador = ExportadorExcel(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_balance(balance, fecha_corte)

        filename = f"Balance_General_{anio}_{mes:02d}.xlsx"
        return Response(
            content=contenido,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando balance Excel: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/reportes/resultados", response_class=HTMLResponse)
async def reporte_resultados(request: Request, anio: int | None = None, mes: int | None = None):
    """Reporte de Estado de Resultados."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)
        
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month
        
        # Periodo: inicio y fin del mes
        import calendar
        _, last_day = calendar.monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, last_day)
        
        estado = generador.generar_estado_resultados(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=settings.sri_razon_social,
            incluir_cuentas_cero=True
        )
        
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        
        return templates.TemplateResponse(
            "reports/resultados.html",
            {
                "request": request,
                "estado": estado,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en reporte_resultados: {e}", exc_info=True)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "error": f"Error generando estado de resultados: {str(e)}",
                "empresa": {"razon_social": "Error", "ruc": "Error"},
                "periodo": {"anio": anio or 2025, "mes_nombre": "Error"}
            }
        )


@router.get("/reportes/resultados/pdf")
async def exportar_resultados_pdf(anio: int | None = None, mes: int | None = None):
    """Exporta Estado de Resultados a PDF."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        _, last_day = calendar.monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, last_day)

        estado = generador.generar_estado_resultados(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=settings.sri_razon_social,
            incluir_cuentas_cero=True
        )

        exportador = ExportadorPDF(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_resultados(estado, fecha_inicio, fecha_fin)

        filename = f"Estado_Resultados_{anio}_{mes:02d}.pdf"
        return Response(
            content=contenido,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando resultados PDF: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/reportes/resultados/excel")
async def exportar_resultados_excel(anio: int | None = None, mes: int | None = None):
    """Exporta Estado de Resultados a Excel."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        _, last_day = calendar.monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, last_day)

        estado = generador.generar_estado_resultados(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=settings.sri_razon_social,
            incluir_cuentas_cero=True
        )

        exportador = ExportadorExcel(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_resultados(estado, fecha_inicio, fecha_fin)

        filename = f"Estado_Resultados_{anio}_{mes:02d}.xlsx"
        return Response(
            content=contenido,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando resultados Excel: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/reportes/libro-diario", response_class=HTMLResponse)
async def reporte_libro_diario(request: Request, anio: int | None = None, mes: int | None = None):
    """Vista de Libro Diario (Asientos Contables)."""
    try:
        # Por ahora mostramos lista de asientos, idealmente seria un reporte mas detallado
        # Reutilizamos la logica de dashboard pero traemos mas datos
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month
        
        data = get_dashboard_data(anio, mes) # Reutilizamos para obtener asientos recientes
        # TODO: Crear metodo especifico en GeneradorReportes para traer TODOS los asientos del mes
        
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        settings = get_settings()

        return templates.TemplateResponse(
            "reports/libro_diario.html",
            {
                "request": request,
                "asientos": data['contabilidad']['asientos_recientes'], # Esto trae solo los ultimos, deberiamos paginar o traer todos
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en reporte_libro_diario: {e}", exc_info=True)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "error": f"Error generando libro diario: {str(e)}",
                "empresa": {"razon_social": "Error", "ruc": "Error"},
                "periodo": {"anio": anio or 2025, "mes_nombre": "Error"}
            }
        )


@router.get("/reportes/libro-diario/pdf")
async def exportar_libro_diario_pdf(anio: int | None = None, mes: int | None = None):
    """Exporta Libro Diario a PDF."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        _, last_day = calendar.monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, last_day)

        # Obtener asientos del periodo
        asientos = supabase.table('asientos_contables').select(
            '*'
        ).gte('fecha', str(fecha_inicio)).lte('fecha', str(fecha_fin)).order('fecha').execute()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        periodo = f"{meses[mes - 1]} {anio}"

        exportador = ExportadorPDF(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_libro_diario(asientos.data or [], periodo)

        filename = f"Libro_Diario_{anio}_{mes:02d}.pdf"
        return Response(
            content=contenido,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando libro diario PDF: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/reportes/libro-diario/excel")
async def exportar_libro_diario_excel(anio: int | None = None, mes: int | None = None):
    """Exporta Libro Diario a Excel."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        _, last_day = calendar.monthrange(anio, mes)
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, last_day)

        # Obtener asientos del periodo
        asientos = supabase.table('asientos_contables').select(
            '*'
        ).gte('fecha', str(fecha_inicio)).lte('fecha', str(fecha_fin)).order('fecha').execute()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        periodo = f"{meses[mes - 1]} {anio}"

        exportador = ExportadorExcel(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_libro_diario(asientos.data or [], periodo)

        filename = f"Libro_Diario_{anio}_{mes:02d}.xlsx"
        return Response(
            content=contenido,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando libro diario Excel: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/reportes/libro-mayor/{cuenta_codigo:path}", response_class=HTMLResponse)
async def reporte_libro_mayor_cuenta(
    request: Request,
    cuenta_codigo: str,
    anio: int | None = None,
    mes: int | None = None
):
    """
    Reporte de Libro Mayor para una cuenta específica.
    Muestra todos los movimientos con contrapartidas.
    """
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        # Período: mes seleccionado
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Generar libro mayor
        libro = generador.generar_libro_mayor(
            cuenta_codigo=cuenta_codigo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=settings.sri_razon_social
        )

        # Obtener contrapartidas para cada movimiento
        # Primero obtenemos los asientos por numero_asiento
        numeros_asiento = list(set(mov.numero_asiento for mov in libro.movimientos))

        # Cache de asientos con sus movimientos
        asientos_cache = {}
        asiento_id_map = {}
        if numeros_asiento:
            asientos = supabase.table('asientos_contables').select(
                'id, numero_asiento'
            ).in_('numero_asiento', numeros_asiento).execute().data

            asiento_id_map = {a['numero_asiento']: a['id'] for a in asientos}

            # Obtener todos los movimientos de estos asientos
            asiento_ids = list(asiento_id_map.values())
            if asiento_ids:
                todos_movimientos = supabase.table('movimientos_contables').select(
                    'asiento_id, cuenta_codigo, debe, haber'
                ).in_('asiento_id', asiento_ids).execute().data

                # Agrupar por asiento_id
                for m in todos_movimientos:
                    aid = m['asiento_id']
                    if aid not in asientos_cache:
                        asientos_cache[aid] = []
                    asientos_cache[aid].append(m)

        # Cache de nombres de cuentas
        cuentas_cache = {}
        codigos_unicos = set()
        for movs in asientos_cache.values():
            for m in movs:
                codigos_unicos.add(m['cuenta_codigo'])

        if codigos_unicos:
            cuentas = supabase.table('cuentas_contables').select(
                'codigo, nombre'
            ).in_('codigo', list(codigos_unicos)).execute().data
            cuentas_cache = {c['codigo']: c['nombre'] for c in cuentas}

        movimientos_con_contrapartida = []
        for mov in libro.movimientos:
            asiento_id = asiento_id_map.get(mov.numero_asiento)
            contrapartidas = []

            if asiento_id and asiento_id in asientos_cache:
                for m in asientos_cache[asiento_id]:
                    if m['cuenta_codigo'] != cuenta_codigo:
                        contrapartidas.append({
                            'codigo': m['cuenta_codigo'],
                            'nombre': cuentas_cache.get(m['cuenta_codigo'], m['cuenta_codigo']),
                            'monto': float(m['debe']) if float(m['debe']) > 0 else float(m['haber'])
                        })

            movimientos_con_contrapartida.append({
                'fecha': mov.fecha,
                'numero_asiento': mov.numero_asiento,
                'concepto': mov.concepto,
                'debe': mov.debe,
                'haber': mov.haber,
                'saldo': mov.saldo,
                'contrapartidas': contrapartidas if contrapartidas else [{'codigo': '-', 'nombre': 'Sin contrapartida', 'monto': 0}]
            })

        meses = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]

        return templates.TemplateResponse(
            "reports/libro_mayor_cuenta.html",
            {
                "request": request,
                "libro": libro,
                "movimientos": movimientos_con_contrapartida,
                "cuenta_codigo": cuenta_codigo,
                "cuenta_nombre": libro.cuenta_nombre,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en reporte_libro_mayor_cuenta: {e}", exc_info=True)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "error": f"Error generando libro mayor: {str(e)}",
                "empresa": {"razon_social": "Error", "ruc": "Error"},
                "periodo": {"anio": anio or 2025, "mes_nombre": "Error"}
            }
        )


@router.get("/reportes/libro-mayor/{cuenta_codigo:path}/excel")
async def exportar_libro_mayor_excel(
    cuenta_codigo: str,
    anio: int | None = None,
    mes: int | None = None
):
    """Exporta Libro Mayor a Excel."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        libro = generador.generar_libro_mayor(
            cuenta_codigo=cuenta_codigo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=settings.sri_razon_social
        )

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        periodo = f"{meses[mes - 1]} {anio}"

        exportador = ExportadorExcel(settings.sri_razon_social, settings.sri_ruc)
        contenido = exportador.exportar_libro_mayor(libro, periodo)

        cuenta_safe = cuenta_codigo.replace('.', '_')
        filename = f"Libro_Mayor_{cuenta_safe}_{anio}_{mes:02d}.xlsx"
        return Response(
            content=contenido,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exportando libro mayor Excel: {e}", exc_info=True)
        return Response(content=f"Error: {str(e)}", status_code=500)


@router.get("/asesor/optimizacion", response_class=HTMLResponse)
async def asesor_optimizacion(request: Request, anio: int | None = None, mes: int | None = None):
    """Asesor Fiscal: Optimizacion y Alertas."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        generador = GeneradorReportes(supabase)
        
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month
        
        # Analisis del anio completo hasta la fecha
        fecha_inicio = date(anio, 1, 1)
        import calendar
        _, last_day = calendar.monthrange(anio, mes)
        fecha_fin = date(anio, mes, last_day)
        
        estado = generador.generar_estado_resultados(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=settings.sri_razon_social
        )
        
        # Logica simple de optimizacion
        ingresos = estado.total_ingresos
        gastos = estado.total_gastos
        utilidad = estado.utilidad_bruta
        
        # Estimacion Impuesto Renta (Simplificado Regimen General ~25%)
        # TODO: Refinar segun regimen (RIMPE, General)
        impuesto_estimado = utilidad * Decimal("0.25") if utilidad > 0 else Decimal("0")
        
        sugerencias = []
        if utilidad > 0:
            sugerencias.append({
                "tipo": "info",
                "titulo": "Proyeccion de Impuesto a la Renta",
                "mensaje": f"Con la utilidad actual, se estima un impuesto de ${impuesto_estimado:,.2f}. Considere realizar gastos deducibles o inversiones antes de fin de anio."
            })
            
            margen = (utilidad / ingresos * 100) if ingresos > 0 else 0
            if margen > 30:
                sugerencias.append({
                    "tipo": "warning",
                    "titulo": "Margen de Utilidad Alto",
                    "mensaje": f"Su margen de utilidad es del {margen:.1f}%. Esto es positivo, pero implica una carga tributaria alta. Revise si ha registrado todos sus gastos operativos."
                })
        else:
            sugerencias.append({
                "tipo": "alert",
                "titulo": "Perdida Operativa",
                "mensaje": "La empresa registra perdidas. Si esto persiste, podria afectar su calificacion crediticia y levantar alertas en el SRI si es recurrente."
            })

        # Alerta de Gastos Personales (si aplica a persona natural, aqui asumimos empresa/persona con RUC)
        # TODO: Verificar tipo de contribuyente
        
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        
        return templates.TemplateResponse(
            "advisor/optimization.html",
            {
                "request": request,
                "estado": estado,
                "impuesto_estimado": impuesto_estimado,
                "sugerencias": sugerencias,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en asesor_optimizacion: {e}", exc_info=True)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "error": f"Error en asesor fiscal: {str(e)}",
                "empresa": {"razon_social": "Error", "ruc": "Error"},
                "periodo": {"anio": anio or 2025, "mes_nombre": "Error"}
            }
        )


# =====================================================
# MODULO DE VENTAS
# =====================================================

@router.get("/ventas", response_class=HTMLResponse)
async def ventas_facturas(request: Request, estado: str | None = None, mes: str | None = None, page: int = 1):
    """Listado de facturas emitidas."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Construir query
        query = supabase.table('comprobantes_electronicos').select('*', count='exact')
        query = query.eq('tipo_comprobante', '01')  # Solo facturas

        if estado:
            query = query.eq('estado', estado)

        if mes:
            # mes viene como "2025-11"
            try:
                anio, mes_num = mes.split('-')
                fecha_inicio = date(int(anio), int(mes_num), 1)
                ultimo_dia = calendar.monthrange(int(anio), int(mes_num))[1]
                fecha_fin = date(int(anio), int(mes_num), ultimo_dia)
                query = query.gte('fecha_emision', str(fecha_inicio)).lte('fecha_emision', str(fecha_fin))
            except Exception:
                pass

        # Paginacion
        limit = 20
        offset = (page - 1) * limit
        result = query.order('fecha_emision', desc=True).range(offset, offset + limit - 1).execute()

        facturas = []
        for f in result.data or []:
            facturas.append({
                **f,
                'numero': f"{f['establecimiento']}-{f['punto_emision']}-{str(f['secuencial']).zfill(9)}"
            })

        total = result.count or len(facturas)
        total_pages = (total + limit - 1) // limit

        # Resumen
        all_facturas = supabase.table('comprobantes_electronicos').select(
            'estado, importe_total, iva'
        ).eq('tipo_comprobante', '01').execute()

        resumen = {
            'autorizadas': len([f for f in all_facturas.data if f['estado'] == 'authorized']),
            'pendientes': len([f for f in all_facturas.data if f['estado'] == 'pending']),
            'total_facturado': sum(float(f['importe_total']) for f in all_facturas.data if f['estado'] == 'authorized'),
            'total_iva': sum(float(f['iva'] or 0) for f in all_facturas.data if f['estado'] == 'authorized'),
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "ventas/facturas.html",
            {
                "request": request,
                "facturas": facturas,
                "resumen": resumen,
                "estado": estado,
                "mes_filtro": mes or f"{hoy.year}-{hoy.month:02d}",
                "page": page,
                "total_pages": total_pages,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en ventas_facturas: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "ventas/facturas.html",
            {
                "request": request,
                "facturas": [],
                "resumen": {'autorizadas': 0, 'pendientes': 0, 'total_facturado': 0, 'total_iva': 0},
                "estado": None,
                "mes_filtro": "",
                "page": 1,
                "total_pages": 1,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


@router.get("/ventas/nueva", response_class=HTMLResponse)
async def ventas_nueva(request: Request):
    """Formulario de nueva factura."""
    try:
        settings = get_settings()
        hoy = date.today()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "ventas/nueva.html",
            {
                "request": request,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en ventas_nueva: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "ventas/nueva.html",
            {
                "request": request,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


@router.get("/ventas/clientes", response_class=HTMLResponse)
async def ventas_clientes(request: Request, q: str | None = None):
    """Catalogo de clientes."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Obtener clientes
        query = supabase.table('clientes').select('*')

        if q:
            query = query.or_(f"identificacion.ilike.%{q}%,razon_social.ilike.%{q}%")

        clientes_res = query.order('razon_social').execute()
        clientes = clientes_res.data or []

        # Obtener estadisticas de ventas por cliente
        for cliente in clientes:
            facturas = supabase.table('comprobantes_electronicos').select(
                'id, importe_total, estado'
            ).eq('cliente_id', cliente['id']).execute()

            cliente['total_ventas'] = sum(
                float(f['importe_total']) for f in facturas.data
                if f['estado'] == 'authorized'
            )
            cliente['total_facturas'] = len([f for f in facturas.data if f['estado'] == 'authorized'])

        # Estadisticas generales
        stats = {
            'total': len(clientes),
            'activos': len([c for c in clientes if c.get('activo', True)]),
            'con_ventas': len([c for c in clientes if c.get('total_facturas', 0) > 0]),
            'requieren_resu': len([c for c in clientes if c.get('requiere_resu', False)])
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "ventas/clientes.html",
            {
                "request": request,
                "clientes": clientes,
                "stats": stats,
                "query": q or "",
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en ventas_clientes: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "ventas/clientes.html",
            {
                "request": request,
                "clientes": [],
                "stats": {'total': 0, 'activos': 0, 'con_ventas': 0, 'requieren_resu': 0},
                "query": "",
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


@router.get("/ventas/{factura_id}", response_class=HTMLResponse)
async def ventas_detalle(request: Request, factura_id: str):
    """Detalle de una factura emitida."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Obtener factura
        factura_res = supabase.table('comprobantes_electronicos').select('*').eq('id', factura_id).single().execute()

        if not factura_res.data:
            return templates.TemplateResponse(
                "ventas/facturas.html",
                {"request": request, "error": "Factura no encontrada", "facturas": []}
            )

        factura = factura_res.data

        # Obtener detalles
        detalles_res = supabase.table('comprobante_detalles').select('*').eq('comprobante_id', factura_id).order('id').execute()

        # Obtener pagos
        pagos_res = supabase.table('comprobante_pagos').select('*').eq('comprobante_id', factura_id).execute()

        # Formatear datos
        factura_completa = {
            'id': factura['id'],
            'tipo_comprobante': factura['tipo_comprobante'],
            'numero': f"{factura['establecimiento']}-{factura['punto_emision']}-{str(factura['secuencial']).zfill(9)}",
            'clave_acceso': factura['clave_acceso'],
            'fecha_emision': factura['fecha_emision'],
            'fecha_autorizacion': factura.get('fecha_autorizacion'),
            'numero_autorizacion': factura.get('numero_autorizacion'),
            'estado': factura['estado'],
            'emisor': {
                'ruc': settings.sri_ruc,
                'razon_social': settings.sri_razon_social,
                'direccion_matriz': settings.sri_direccion_matriz,
            },
            'cliente': {
                'tipo_identificacion': factura['cliente_tipo_id'],
                'identificacion': factura['cliente_identificacion'],
                'razon_social': factura['cliente_razon_social'],
                'direccion': factura.get('cliente_direccion'),
                'email': factura.get('cliente_email'),
            },
            'detalles': detalles_res.data or [],
            'totales': {
                'subtotal_sin_impuestos': float(factura.get('subtotal_sin_impuestos', 0)),
                'subtotal_15': float(factura.get('subtotal_15', 0)),
                'subtotal_0': float(factura.get('subtotal_0', 0)),
                'iva': float(factura.get('iva', 0)),
                'importe_total': float(factura['importe_total']),
            },
            'pagos': pagos_res.data or [],
            'info_adicional': factura.get('info_adicional'),
            'mensajes_sri': factura.get('mensajes_sri'),
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "ventas/detalle.html",
            {
                "request": request,
                "factura": factura_completa,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en ventas_detalle: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "ventas/facturas.html",
            {
                "request": request,
                "facturas": [],
                "error": f"Error cargando factura: {str(e)}",
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


# =====================================================
# MODULO DE COMPRAS
# =====================================================

@router.get("/compras", response_class=HTMLResponse)
async def compras_facturas(request: Request, anio: int | None = None, mes: int | None = None):
    """Listado de facturas recibidas (compras)."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()

        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Obtener facturas del mes
        facturas_res = supabase.table('facturas_recibidas').select(
            '*'
        ).gte('fecha_emision', str(fecha_inicio)).lte('fecha_emision', str(fecha_fin)).order('fecha_emision', desc=True).execute()

        facturas = facturas_res.data or []

        # Resumen del mes desde la vista
        resumen_res = supabase.table('v_resumen_compras_mes').select(
            '*'
        ).eq('anio', anio).eq('mes', mes).execute()

        resumen = resumen_res.data[0] if resumen_res.data else {
            'total_compras': 0,
            'total_iva': 0,
            'credito_tributario': 0,
            'total_facturas': 0,
            'total_base_gravada': 0,
            'total_base_0': 0,
            'total_no_objeto': 0,
            'total_exento': 0,
            'total_retencion_renta': 0,
            'total_retencion_iva': 0
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "compras/facturas.html",
            {
                "request": request,
                "facturas": facturas,
                "resumen": resumen,
                "mes_actual": mes,
                "anio_actual": anio,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en compras_facturas: {e}", exc_info=True)
        settings = get_settings()
        return templates.TemplateResponse(
            "compras/facturas.html",
            {
                "request": request,
                "facturas": [],
                "resumen": {},
                "mes_actual": mes or date.today().month,
                "anio_actual": anio or date.today().year,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio or 2025, "mes_nombre": "Error"}
            }
        )


@router.get("/compras/proveedores", response_class=HTMLResponse)
async def compras_proveedores(request: Request, q: str | None = None):
    """Catalogo de proveedores."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Obtener proveedores con estadisticas
        query = supabase.table('v_proveedores_estadisticas').select('*')

        if q:
            # Busqueda por RUC o razon social
            query = query.or_(f"identificacion.ilike.%{q}%,razon_social.ilike.%{q}%")

        proveedores_res = query.order('razon_social').execute()
        proveedores = proveedores_res.data or []

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "compras/proveedores.html",
            {
                "request": request,
                "proveedores": proveedores,
                "query": q or "",
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en compras_proveedores: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "compras/proveedores.html",
            {
                "request": request,
                "proveedores": [],
                "query": "",
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


@router.get("/compras/importar", response_class=HTMLResponse)
async def compras_importar(request: Request):
    """Pagina de importacion de facturas XML/PDF."""
    try:
        settings = get_settings()
        hoy = date.today()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "compras/importar.html",
            {
                "request": request,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en compras_importar: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "compras/importar.html",
            {
                "request": request,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


@router.get("/compras/pendientes", response_class=HTMLResponse)
async def compras_pendientes(request: Request, page: int = 1):
    """Panel de revision de facturas pendientes de aprobacion."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Servicio de sincronizacion
        servicio = ServicioSincronizacionSRI(supabase)

        # Paginacion
        limit = 20
        offset = (page - 1) * limit

        # Obtener facturas pendientes
        facturas = await servicio.obtener_facturas_pendientes(limit=limit, offset=offset)

        # Total para paginacion
        total_res = supabase.table('facturas_recibidas').select(
            'id', count='exact'
        ).eq('estado', 'pendiente').execute()
        total = total_res.count or 0
        total_pages = (total + limit - 1) // limit

        # Estadisticas
        aprobadas_res = supabase.table('facturas_recibidas').select(
            'id', count='exact'
        ).eq('estado', 'aprobada').execute()
        rechazadas_res = supabase.table('facturas_recibidas').select(
            'id', count='exact'
        ).eq('estado', 'rechazada').execute()

        stats = {
            'pendientes': total,
            'aprobadas': aprobadas_res.count or 0,
            'rechazadas': rechazadas_res.count or 0,
        }

        # Obtener conceptos de retencion para el formulario
        servicio_ret = ServicioRetenciones(supabase)
        conceptos_ir = servicio_ret.obtener_conceptos_ir()
        conceptos_iva = servicio_ret.obtener_conceptos_iva()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "compras/pendientes.html",
            {
                "request": request,
                "facturas": facturas,
                "stats": stats,
                "conceptos_ir": conceptos_ir,
                "conceptos_iva": conceptos_iva,
                "page": page,
                "total_pages": total_pages,
                "total": total,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en compras_pendientes: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        return templates.TemplateResponse(
            "compras/pendientes.html",
            {
                "request": request,
                "facturas": [],
                "stats": {'pendientes': 0, 'aprobadas': 0, 'rechazadas': 0},
                "conceptos_ir": [],
                "conceptos_iva": [],
                "page": 1,
                "total_pages": 1,
                "total": 0,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes_nombre": "Error"}
            }
        )


# =====================================================
# MODULO DE CONTABILIDAD
# =====================================================

@router.get("/contabilidad/asientos", response_class=HTMLResponse)
async def contabilidad_asientos(
    request: Request,
    anio: int | None = None,
    mes: int | None = None,
    estado: str | None = None
):
    """Listado de asientos contables."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Construir query
        query = supabase.table('asientos_contables').select('*')
        query = query.gte('fecha', str(fecha_inicio)).lte('fecha', str(fecha_fin))

        if estado:
            query = query.eq('estado', estado)

        result = query.order('fecha', desc=True).order('numero_asiento', desc=True).execute()
        asientos = result.data or []

        # Estadisticas
        all_asientos = supabase.table('asientos_contables').select(
            'estado, total_debe'
        ).gte('fecha', str(fecha_inicio)).lte('fecha', str(fecha_fin)).execute()

        stats = {
            'total': len(all_asientos.data),
            'contabilizados': len([a for a in all_asientos.data if a['estado'] == 'contabilizado']),
            'borradores': len([a for a in all_asientos.data if a['estado'] == 'borrador']),
            'total_movimiento': sum(float(a['total_debe']) for a in all_asientos.data if a['estado'] == 'contabilizado'),
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "contabilidad/asientos.html",
            {
                "request": request,
                "asientos": asientos,
                "stats": stats,
                "estado_filtro": estado,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en contabilidad_asientos: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "contabilidad/asientos.html",
            {
                "request": request,
                "asientos": [],
                "stats": {'total': 0, 'contabilizados': 0, 'borradores': 0, 'total_movimiento': 0},
                "estado_filtro": None,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


@router.get("/contabilidad/asientos/nuevo", response_class=HTMLResponse)
async def contabilidad_nuevo_asiento(request: Request):
    """Formulario de nuevo asiento contable."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Obtener cuentas de movimiento
        cuentas_res = supabase.table('cuentas_contables').select(
            'codigo, nombre'
        ).eq('es_movimiento', True).eq('activa', True).order('codigo').execute()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "contabilidad/nuevo_asiento.html",
            {
                "request": request,
                "cuentas": cuentas_res.data or [],
                "today": str(hoy),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en contabilidad_nuevo_asiento: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "contabilidad/nuevo_asiento.html",
            {
                "request": request,
                "cuentas": [],
                "today": str(hoy),
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


@router.get("/contabilidad/asientos/{asiento_id}", response_class=HTMLResponse)
async def contabilidad_detalle_asiento(request: Request, asiento_id: str):
    """Detalle de un asiento contable."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        # Obtener asiento
        asiento_res = supabase.table('asientos_contables').select('*').eq('id', asiento_id).single().execute()
        asiento = asiento_res.data

        if not asiento:
            return templates.TemplateResponse(
                "contabilidad/asientos.html",
                {"request": request, "error": "Asiento no encontrado", "asientos": []}
            )

        # Obtener movimientos
        movimientos_res = supabase.table('movimientos_contables').select(
            '*, cuentas_contables(nombre)'
        ).eq('asiento_id', asiento_id).order('orden').execute()

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "contabilidad/detalle_asiento.html",
            {
                "request": request,
                "asiento": asiento,
                "movimientos": movimientos_res.data or [],
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en contabilidad_detalle_asiento: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "contabilidad/asientos.html",
            {
                "request": request,
                "asientos": [],
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


# =====================================================
# MODULO DE IMPUESTOS / SRI
# =====================================================

@router.get("/impuestos/form-104", response_class=HTMLResponse)
async def impuestos_form_104(request: Request, anio: int | None = None, mes: int | None = None):
    """Formulario 104 - Declaracion IVA mensual."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        anio = anio or hoy.year
        mes = mes or hoy.month

        # Calcular datos IVA
        calculador = CalculadorIVA(supabase)
        datos_iva = calculador.calcular_periodo(
            anio=anio,
            mes=mes,
            ruc=settings.sri_ruc,
            razon_social=settings.sri_razon_social
        )

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "impuestos/form_104.html",
            {
                "request": request,
                "datos": datos_iva.to_dict(),
                "anio": anio,
                "mes": mes,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en impuestos_form_104: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "impuestos/form_104.html",
            {
                "request": request,
                "datos": {
                    "ventas": {"401_ventas_locales_gravadas": 0, "403_ventas_activos_fijos_gravadas": 0,
                               "405_ventas_locales_0": 0, "407_ventas_activos_fijos_0": 0,
                               "409_exportaciones_bienes": 0, "411_exportaciones_servicios": 0,
                               "413_ventas_con_retencion": 0, "415_total_ventas_netas": 0},
                    "compras": {"501_compras_locales_gravadas": 0, "503_compras_activos_fijos_gravadas": 0,
                                "505_compras_locales_0": 0, "507_importaciones_bienes": 0,
                                "509_importaciones_activos_fijos": 0, "511_importaciones_0": 0,
                                "513_total_adquisiciones": 0},
                    "impuestos": {"601_iva_ventas": 0, "605_iva_compras": 0, "609_iva_importaciones": 0,
                                  "credito_tributario_mes": 0, "credito_tributario_anterior": 0,
                                  "721_iva_a_pagar": 0, "723_credito_proximo_mes": 0},
                    "estadisticas": {"total_facturas_emitidas": 0, "total_facturas_anuladas": 0}
                },
                "anio": hoy.year,
                "mes": hoy.month,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


@router.get("/impuestos/form-103", response_class=HTMLResponse)
async def impuestos_form_103(request: Request, anio: int | None = None, mes: int | None = None):
    """Formulario 103 - Retenciones en la Fuente."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Obtener comprobantes de retención del periodo
        retenciones = supabase.table('comprobantes_electronicos').select(
            '*, proveedores(razon_social, identificacion)'
        ).eq(
            'tipo_comprobante', '07'  # 07 = Comprobante de Retención
        ).gte(
            'fecha_emision', str(fecha_inicio)
        ).lte(
            'fecha_emision', str(fecha_fin)
        ).execute().data or []

        # Agrupar por concepto de retención IR
        retenciones_ir = {}
        retenciones_iva = {}
        detalle_proveedores = {}
        total_ir = 0
        total_iva = 0
        base_imponible = 0
        base_iva_total = 0

        for ret in retenciones:
            # Agrupar IR
            codigo_ir = ret.get('codigo_retencion_ir', '340')
            valor_ir = float(ret.get('valor_retencion_ir', 0) or 0)
            base_ir = float(ret.get('base_imponible', 0) or 0)

            if codigo_ir not in retenciones_ir:
                retenciones_ir[codigo_ir] = {
                    'codigo': codigo_ir,
                    'concepto': ret.get('concepto_retencion_ir', 'Otros'),
                    'porcentaje': float(ret.get('porcentaje_ir', 0) or 0),
                    'base': 0,
                    'valor': 0
                }
            retenciones_ir[codigo_ir]['base'] += base_ir
            retenciones_ir[codigo_ir]['valor'] += valor_ir
            total_ir += valor_ir
            base_imponible += base_ir

            # Agrupar IVA
            codigo_iva = ret.get('codigo_retencion_iva', '731')
            valor_iva = float(ret.get('valor_retencion_iva', 0) or 0)
            base_iva = float(ret.get('iva', 0) or 0)

            if valor_iva > 0:
                if codigo_iva not in retenciones_iva:
                    retenciones_iva[codigo_iva] = {
                        'codigo': codigo_iva,
                        'concepto': ret.get('concepto_retencion_iva', 'Retención IVA'),
                        'porcentaje': float(ret.get('porcentaje_iva', 0) or 0),
                        'base': 0,
                        'valor': 0
                    }
                retenciones_iva[codigo_iva]['base'] += base_iva
                retenciones_iva[codigo_iva]['valor'] += valor_iva
                total_iva += valor_iva
                base_iva_total += base_iva

            # Agrupar por proveedor
            prov = ret.get('proveedores', {})
            prov_id = ret.get('proveedor_id', 'sin_proveedor')
            if prov_id not in detalle_proveedores:
                detalle_proveedores[prov_id] = {
                    'razon_social': prov.get('razon_social', 'Sin nombre') if prov else 'Sin proveedor',
                    'identificacion': prov.get('identificacion', '-') if prov else '-',
                    'base_ir': 0,
                    'retencion_ir': 0,
                    'base_iva': 0,
                    'retencion_iva': 0
                }
            detalle_proveedores[prov_id]['base_ir'] += base_ir
            detalle_proveedores[prov_id]['retencion_ir'] += valor_ir
            detalle_proveedores[prov_id]['base_iva'] += base_iva
            detalle_proveedores[prov_id]['retencion_iva'] += valor_iva

        # Obtener conceptos de retención IR
        servicio_ret = ServicioRetenciones(supabase)
        conceptos_ir = servicio_ret.obtener_conceptos_ir()

        resumen = {
            'total_comprobantes': len(retenciones),
            'base_imponible': base_imponible,
            'total_ir': total_ir,
            'total_iva': total_iva,
            'base_iva_total': base_iva_total
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "impuestos/form_103.html",
            {
                "request": request,
                "resumen": resumen,
                "retenciones_ir": list(retenciones_ir.values()),
                "retenciones_iva": list(retenciones_iva.values()),
                "detalle_proveedores": list(detalle_proveedores.values()),
                "conceptos_ir": conceptos_ir[:12],  # Mostrar primeros 12 para referencia
                "anio": anio,
                "mes": mes,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en impuestos_form_103: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "impuestos/form_103.html",
            {
                "request": request,
                "resumen": {'total_comprobantes': 0, 'base_imponible': 0, 'total_ir': 0, 'total_iva': 0, 'base_iva_total': 0},
                "retenciones_ir": [],
                "retenciones_iva": [],
                "detalle_proveedores": [],
                "conceptos_ir": [],
                "anio": hoy.year,
                "mes": hoy.month,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


# =====================================================
# MODULO BANCARIO
# =====================================================

# =====================================================
# MODULO DE TESORERIA
# =====================================================

@router.get("/tesoreria/cuentas-cobrar", response_class=HTMLResponse)
async def tesoreria_cuentas_cobrar(
    request: Request,
    anio: int | None = None,
    mes: int | None = None
):
    """Vista de Cuentas por Cobrar con antiguedad de cartera."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_corte = date(anio, mes, ultimo_dia)

        # Obtener facturas pendientes de cobro
        facturas_res = supabase.table('comprobantes_electronicos').select(
            'id, establecimiento, punto_emision, secuencial, fecha_emision, '
            'cliente_razon_social, cliente_identificacion, cliente_id, importe_total, estado'
        ).eq('tipo_comprobante', '01').eq('estado', 'authorized').execute()

        # Agrupar por cliente y calcular antiguedad
        clientes_data = {}
        facturas_pendientes = []

        for f in facturas_res.data or []:
            # Calcular saldo pendiente (asumimos que no hay pagos parciales por ahora)
            pagado = 0
            saldo = float(f['importe_total']) - pagado

            if saldo <= 0:
                continue

            # Calcular dias de antiguedad
            fecha_emision = date.fromisoformat(f['fecha_emision']) if isinstance(f['fecha_emision'], str) else f['fecha_emision']
            dias = (fecha_corte - fecha_emision).days
            fecha_vencimiento = fecha_emision  # Sin credito por defecto

            cliente_id = f.get('cliente_id') or f['cliente_identificacion']
            if cliente_id not in clientes_data:
                clientes_data[cliente_id] = {
                    'id': cliente_id,
                    'razon_social': f['cliente_razon_social'] or 'Consumidor Final',
                    'identificacion': f['cliente_identificacion'] or '9999999999999',
                    'total': 0,
                    'vigente': 0,
                    'dias_31_60': 0,
                    'dias_61_90': 0,
                    'dias_90_mas': 0
                }

            clientes_data[cliente_id]['total'] += saldo
            if dias <= 30:
                clientes_data[cliente_id]['vigente'] += saldo
            elif dias <= 60:
                clientes_data[cliente_id]['dias_31_60'] += saldo
            elif dias <= 90:
                clientes_data[cliente_id]['dias_61_90'] += saldo
            else:
                clientes_data[cliente_id]['dias_90_mas'] += saldo

            numero = f"{f['establecimiento']}-{f['punto_emision']}-{str(f['secuencial']).zfill(9)}"
            facturas_pendientes.append({
                'id': f['id'],
                'numero': numero,
                'fecha_emision': fecha_emision.strftime('%d/%m/%Y'),
                'fecha_vencimiento': fecha_vencimiento.strftime('%d/%m/%Y'),
                'cliente_razon_social': f['cliente_razon_social'] or 'Consumidor Final',
                'importe_total': float(f['importe_total']),
                'pagado': pagado,
                'saldo': saldo,
                'dias_vencida': max(0, dias)
            })

        clientes = sorted(clientes_data.values(), key=lambda x: x['total'], reverse=True)

        # Calcular resumen
        total_cobrar = sum(c['total'] for c in clientes)
        vigente = sum(c['vigente'] for c in clientes)
        dias_31_60 = sum(c['dias_31_60'] for c in clientes)
        dias_61_90 = sum(c['dias_61_90'] for c in clientes)
        dias_90_mas = sum(c['dias_90_mas'] for c in clientes)

        resumen = {
            'total_cobrar': total_cobrar,
            'vigente': vigente,
            'por_vencer': dias_31_60,
            'vencido': dias_61_90 + dias_90_mas,
            'dias_31_60': dias_31_60,
            'dias_61_90': dias_61_90,
            'dias_90_mas': dias_90_mas
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "tesoreria/cuentas_cobrar.html",
            {
                "request": request,
                "clientes": clientes,
                "facturas": facturas_pendientes[:50],  # Limitar a 50 facturas
                "resumen": resumen,
                "anio": anio,
                "mes": mes,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en tesoreria_cuentas_cobrar: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "tesoreria/cuentas_cobrar.html",
            {
                "request": request,
                "clientes": [],
                "facturas": [],
                "resumen": {'total_cobrar': 0, 'vigente': 0, 'por_vencer': 0, 'vencido': 0,
                           'dias_31_60': 0, 'dias_61_90': 0, 'dias_90_mas': 0},
                "anio": hoy.year,
                "mes": hoy.month,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


@router.get("/tesoreria/cuentas-pagar", response_class=HTMLResponse)
async def tesoreria_cuentas_pagar(
    request: Request,
    anio: int | None = None,
    mes: int | None = None
):
    """Vista de Cuentas por Pagar con antiguedad de obligaciones."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_corte = date(anio, mes, ultimo_dia)

        # Obtener facturas recibidas pendientes
        facturas_res = supabase.table('facturas_recibidas').select(
            'id, numero_factura, fecha_emision, fecha_vencimiento, '
            'proveedor_razon_social, proveedor_ruc, proveedor_id, total, estado'
        ).neq('estado', 'pagada').execute()

        # Agrupar por proveedor y calcular antiguedad
        proveedores_data = {}
        facturas_pendientes = []
        proximos_pagos = []

        for f in facturas_res.data or []:
            # Calcular saldo pendiente
            abonado = float(f.get('abonado', 0) or 0)
            saldo = float(f['total']) - abonado

            if saldo <= 0:
                continue

            # Calcular dias de antiguedad
            fecha_emision = date.fromisoformat(f['fecha_emision']) if isinstance(f['fecha_emision'], str) else f['fecha_emision']
            fecha_vencimiento = date.fromisoformat(f['fecha_vencimiento']) if f.get('fecha_vencimiento') else fecha_emision
            dias = (fecha_corte - fecha_emision).days
            dias_para_vencer = (fecha_vencimiento - hoy).days

            prov_id = f.get('proveedor_id') or f['proveedor_ruc']
            if prov_id not in proveedores_data:
                proveedores_data[prov_id] = {
                    'id': prov_id,
                    'razon_social': f['proveedor_razon_social'] or 'Sin nombre',
                    'identificacion': f['proveedor_ruc'] or '-',
                    'total': 0,
                    'vigente': 0,
                    'dias_31_60': 0,
                    'dias_61_90': 0,
                    'dias_90_mas': 0
                }

            proveedores_data[prov_id]['total'] += saldo
            if dias <= 30:
                proveedores_data[prov_id]['vigente'] += saldo
            elif dias <= 60:
                proveedores_data[prov_id]['dias_31_60'] += saldo
            elif dias <= 90:
                proveedores_data[prov_id]['dias_61_90'] += saldo
            else:
                proveedores_data[prov_id]['dias_90_mas'] += saldo

            factura_data = {
                'id': f['id'],
                'numero_factura': f['numero_factura'],
                'fecha_emision': fecha_emision.strftime('%d/%m/%Y'),
                'fecha_vencimiento': fecha_vencimiento.strftime('%d/%m/%Y'),
                'proveedor': f['proveedor_razon_social'] or 'Sin nombre',
                'total': float(f['total']),
                'abonado': abonado,
                'saldo': saldo,
                'dias_vencida': max(0, dias - 30) if dias > 30 else 0,
                'dias_para_vencer': dias_para_vencer
            }

            facturas_pendientes.append(factura_data)

            # Agregar a proximos pagos si vence en 7 dias o menos
            if dias_para_vencer <= 7:
                proximos_pagos.append(factura_data)

        proveedores = sorted(proveedores_data.values(), key=lambda x: x['total'], reverse=True)
        proximos_pagos = sorted(proximos_pagos, key=lambda x: x['dias_para_vencer'])

        # Calcular resumen
        total_pagar = sum(p['total'] for p in proveedores)
        vigente = sum(p['vigente'] for p in proveedores)
        dias_31_60 = sum(p['dias_31_60'] for p in proveedores)
        dias_61_90 = sum(p['dias_61_90'] for p in proveedores)
        dias_90_mas = sum(p['dias_90_mas'] for p in proveedores)

        resumen = {
            'total_pagar': total_pagar,
            'vigente': vigente,
            'por_vencer': dias_31_60,
            'vencido': dias_61_90 + dias_90_mas,
            'dias_31_60': dias_31_60,
            'dias_61_90': dias_61_90,
            'dias_90_mas': dias_90_mas
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "tesoreria/cuentas_pagar.html",
            {
                "request": request,
                "proveedores": proveedores,
                "facturas": sorted(facturas_pendientes, key=lambda x: x['dias_vencida'], reverse=True)[:50],
                "proximos_pagos": proximos_pagos[:10],
                "resumen": resumen,
                "anio": anio,
                "mes": mes,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en tesoreria_cuentas_pagar: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "tesoreria/cuentas_pagar.html",
            {
                "request": request,
                "proveedores": [],
                "facturas": [],
                "proximos_pagos": [],
                "resumen": {'total_pagar': 0, 'vigente': 0, 'por_vencer': 0, 'vencido': 0,
                           'dias_31_60': 0, 'dias_61_90': 0, 'dias_90_mas': 0},
                "anio": hoy.year,
                "mes": hoy.month,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


@router.get("/tesoreria/flujo-caja", response_class=HTMLResponse)
async def tesoreria_flujo_caja(
    request: Request,
    anio: int | None = None,
    mes: int | None = None
):
    """Vista de Flujo de Caja proyectado."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Obtener saldo bancario actual (saldo inicial del mes)
        tx_anteriores = supabase.table('transacciones_bancarias').select(
            'tipo, monto'
        ).lt('fecha', str(fecha_inicio)).execute()

        saldo_inicial = sum(
            float(t['monto']) if t['tipo'] == 'credito' else -float(t['monto'])
            for t in tx_anteriores.data or []
        )

        # Ingresos proyectados: Cuentas por cobrar vigentes
        facturas_cobrar = supabase.table('comprobantes_electronicos').select(
            'importe_total'
        ).eq('tipo_comprobante', '01').eq('estado', 'authorized').execute()

        cobranzas_vigentes = sum(float(f['importe_total']) for f in facturas_cobrar.data or [])

        # Ventas contado estimadas (promedio de ultimos 3 meses)
        tx_creditos = supabase.table('transacciones_bancarias').select(
            'monto'
        ).eq('tipo', 'credito').gte('fecha', str(date(anio, max(1, mes-3), 1))).lt('fecha', str(fecha_inicio)).execute()

        ventas_contado = sum(float(t['monto']) for t in tx_creditos.data or []) / 3 if tx_creditos.data else 0

        # Egresos proyectados: Cuentas por pagar
        facturas_pagar = supabase.table('facturas_recibidas').select(
            'total'
        ).neq('estado', 'pagada').execute()

        pagos_proveedores = sum(float(f['total']) for f in facturas_pagar.data or [])

        # Estimaciones fijas (estos valores deberian venir de configuracion)
        nomina = 2500  # Placeholder
        impuestos = float(saldo_inicial * Decimal("0.05")) if saldo_inicial > 0 else 0  # 5% estimado
        servicios = 800  # Placeholder
        otros_gastos = 500  # Placeholder
        otros_ingresos = 0

        ingresos_proyectados = cobranzas_vigentes * 0.7 + ventas_contado + otros_ingresos  # 70% de cobranza
        egresos_proyectados = pagos_proveedores * 0.8 + nomina + impuestos + servicios + otros_gastos  # 80% de pagos
        flujo_neto = ingresos_proyectados - egresos_proyectados
        saldo_final = saldo_inicial + flujo_neto

        # Proyeccion semanal
        semanas = []
        saldo_semana = saldo_inicial
        ingresos_semana = ingresos_proyectados / 4
        egresos_semana = egresos_proyectados / 4

        for i in range(1, 5):
            flujo = ingresos_semana - egresos_semana
            saldo_final_semana = saldo_semana + flujo
            semanas.append({
                'nombre': f'Semana {i}',
                'saldo_inicial': saldo_semana,
                'ingresos': ingresos_semana,
                'egresos': egresos_semana,
                'flujo': flujo,
                'saldo_final': saldo_final_semana
            })
            saldo_semana = saldo_final_semana

        # Indicadores
        gasto_diario = egresos_proyectados / ultimo_dia if egresos_proyectados > 0 else 1
        dias_caja = int(saldo_inicial / gasto_diario) if gasto_diario > 0 else 0
        ratio_ie = ingresos_proyectados / egresos_proyectados if egresos_proyectados > 0 else 0
        cobranza_efectiva = 70  # Placeholder

        resumen = {
            'saldo_inicial': saldo_inicial,
            'ingresos_proyectados': ingresos_proyectados,
            'egresos_proyectados': egresos_proyectados,
            'flujo_neto': flujo_neto,
            'saldo_final': saldo_final
        }

        ingresos = {
            'cobranzas_vigentes': cobranzas_vigentes * 0.7,
            'ventas_contado': ventas_contado,
            'otros': otros_ingresos
        }

        egresos = {
            'pagos_proveedores': pagos_proveedores * 0.8,
            'nomina': nomina,
            'impuestos': impuestos,
            'servicios': servicios,
            'otros': otros_gastos
        }

        indicadores = {
            'dias_caja': dias_caja,
            'ratio_ie': ratio_ie,
            'cobranza_efectiva': cobranza_efectiva
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "tesoreria/flujo_caja.html",
            {
                "request": request,
                "resumen": resumen,
                "ingresos": ingresos,
                "egresos": egresos,
                "proyeccion_semanal": semanas,
                "indicadores": indicadores,
                "anio": anio,
                "mes": mes,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en tesoreria_flujo_caja: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "tesoreria/flujo_caja.html",
            {
                "request": request,
                "resumen": {'saldo_inicial': 0, 'ingresos_proyectados': 0, 'egresos_proyectados': 0,
                           'flujo_neto': 0, 'saldo_final': 0},
                "ingresos": {'cobranzas_vigentes': 0, 'ventas_contado': 0, 'otros': 0},
                "egresos": {'pagos_proveedores': 0, 'nomina': 0, 'impuestos': 0, 'servicios': 0, 'otros': 0},
                "proyeccion_semanal": [],
                "indicadores": {'dias_caja': 0, 'ratio_ie': 0, 'cobranza_efectiva': 0},
                "anio": hoy.year,
                "mes": hoy.month,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


@router.get("/banco/transacciones", response_class=HTMLResponse)
async def banco_transacciones(
    request: Request,
    anio: int | None = None,
    mes: int | None = None,
    estado: str | None = None,
    tipo: str | None = None
):
    """Vista de transacciones bancarias con filtros."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()

        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Construir query
        query = supabase.table('transacciones_bancarias').select('*')
        query = query.gte('fecha', str(fecha_inicio)).lte('fecha', str(fecha_fin))

        if estado:
            query = query.eq('estado', estado)
        if tipo:
            query = query.eq('tipo', tipo)

        result = query.order('fecha', desc=True).execute()
        transacciones = result.data or []

        # Estadisticas
        total_creditos = sum(float(t['monto']) for t in transacciones if t['tipo'] == 'credito')
        total_debitos = sum(float(t['monto']) for t in transacciones if t['tipo'] == 'debito')
        pendientes = len([t for t in transacciones if t['estado'] == 'pendiente'])

        stats = {
            'total': len(transacciones),
            'creditos': total_creditos,
            'debitos': total_debitos,
            'neto': total_creditos - total_debitos,
            'pendientes': pendientes
        }

        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "banco/transacciones.html",
            {
                "request": request,
                "transacciones": transacciones,
                "stats": stats,
                "estado_filtro": estado,
                "tipo_filtro": tipo,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en banco_transacciones: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "banco/transacciones.html",
            {
                "request": request,
                "transacciones": [],
                "stats": {'total': 0, 'creditos': 0, 'debitos': 0, 'neto': 0, 'pendientes': 0},
                "estado_filtro": None,
                "tipo_filtro": None,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": hoy.year, "mes": hoy.month, "mes_nombre": meses[hoy.month - 1]}
            }
        )


# ==============================================================================
# COMPRAS - LIQUIDACIONES DE COMPRA (CRIPTO)
# ==============================================================================

@router.get("/compras/liquidaciones", response_class=HTMLResponse)
async def compras_liquidaciones(
    request: Request,
    anio: int | None = None,
    mes: int | None = None
):
    """Lista de liquidaciones de compra (cripto)."""
    try:
        settings = get_settings()
        supabase = get_supabase_client()
        hoy = date.today()
        anio = anio or hoy.year
        mes = mes or hoy.month

        # Fechas del periodo
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio, mes, ultimo_dia)

        # Obtener liquidaciones del mes (tipo_comprobante = '03')
        liquidaciones_res = supabase.table('facturas_recibidas').select(
            '*'
        ).eq('tipo_comprobante', '03').gte(
            'fecha_emision', str(fecha_inicio)
        ).lte('fecha_emision', str(fecha_fin)).order('fecha_emision', desc=True).execute()

        liquidaciones = liquidaciones_res.data or []

        # Calcular totales
        monto_total = sum(float(l.get('total', 0)) for l in liquidaciones)

        # Calcular comisiones generadas (1.5% de cada transaccion)
        comisiones = monto_total * 0.015

        resumen = {
            'monto_total': monto_total,
            'comisiones': comisiones,
            'total': len(liquidaciones)
        }

        meses_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        return templates.TemplateResponse(
            "compras/liquidaciones.html",
            {
                "request": request,
                "liquidaciones": liquidaciones,
                "resumen": resumen,
                "mes_actual": mes,
                "anio_actual": anio,
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio, "mes": mes, "mes_nombre": meses_nombres[mes - 1]}
            }
        )
    except Exception as e:
        logger.error(f"Error en compras_liquidaciones: {e}", exc_info=True)
        settings = get_settings()
        hoy = date.today()
        meses_nombres = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        return templates.TemplateResponse(
            "compras/liquidaciones.html",
            {
                "request": request,
                "liquidaciones": [],
                "resumen": {'monto_total': 0, 'comisiones': 0, 'total': 0},
                "mes_actual": mes or hoy.month,
                "anio_actual": anio or hoy.year,
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc},
                "periodo": {"anio": anio or hoy.year, "mes_nombre": meses_nombres[(mes or hoy.month) - 1]}
            }
        )


@router.get("/compras/liquidaciones/transaccion", response_class=HTMLResponse)
async def compras_liquidaciones_transaccion(request: Request):
    """Formulario para crear transaccion completa de cripto."""
    try:
        settings = get_settings()
        hoy = date.today()

        return templates.TemplateResponse(
            "compras/nueva_transaccion_cripto.html",
            {
                "request": request,
                "today": hoy.isoformat(),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc}
            }
        )
    except Exception as e:
        logger.error(f"Error en formulario transaccion: {e}", exc_info=True)
        return RedirectResponse("/dashboard/compras/liquidaciones", status_code=302)


@router.post("/compras/liquidaciones/transaccion/crear", response_class=HTMLResponse)
async def compras_liquidaciones_transaccion_crear(
    request: Request,
    vendedor_cedula: str = Form(...),
    vendedor_nombre: str = Form(...),
    comprador_cedula: str = Form(...),
    comprador_nombre: str = Form(...),
    fecha: date = Form(...),
    monto_cripto: float = Form(...),
    tipo_cripto: str = Form("USDT"),
    concepto: str = Form("Compra de criptomonedas")
):
    """Procesa transaccion completa de cripto."""
    try:
        from decimal import Decimal as Dec
        from src.compras.liquidaciones import LiquidacionService

        service = LiquidacionService()
        result = await service.procesar_transaccion_cripto(
            vendedor_cedula=vendedor_cedula,
            vendedor_nombre=vendedor_nombre,
            comprador_cedula=comprador_cedula,
            comprador_nombre=comprador_nombre,
            monto_cripto=Dec(str(monto_cripto)),
            tipo_cripto=tipo_cripto,
            fecha=fecha,
            concepto=concepto
        )

        if result.get('success'):
            return RedirectResponse(
                "/dashboard/compras/liquidaciones?success=1",
                status_code=302
            )
        else:
            settings = get_settings()
            return templates.TemplateResponse(
                "compras/nueva_transaccion_cripto.html",
                {
                    "request": request,
                    "today": fecha.isoformat(),
                    "error": result.get('error', 'Error desconocido'),
                    "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc}
                }
            )

    except Exception as e:
        logger.error(f"Error creando transaccion: {e}", exc_info=True)
        settings = get_settings()
        return templates.TemplateResponse(
            "compras/nueva_transaccion_cripto.html",
            {
                "request": request,
                "today": date.today().isoformat(),
                "error": str(e),
                "empresa": {"razon_social": settings.sri_razon_social, "ruc": settings.sri_ruc}
            }
        )
