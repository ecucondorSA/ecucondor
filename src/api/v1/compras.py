"""
ECUCONDOR - API de Compras (Facturas Recibidas)
Endpoints para gestión de facturas de proveedores.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field

from src.db.supabase import get_supabase_client
from src.ingestor.parsers.factura_xml import ParserFacturaXML

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["Compras"])  # prefix se define en router.py


# =====================================================
# MODELOS PYDANTIC
# =====================================================

class ProveedorCreate(BaseModel):
    """Crear nuevo proveedor."""
    tipo_identificacion: str = "04"
    identificacion: str
    razon_social: str
    nombre_comercial: Optional[str] = None
    direccion: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    obligado_contabilidad: bool = False
    agente_retencion: bool = False
    porcentaje_retencion_renta_default: Decimal = Decimal("1.00")
    porcentaje_retencion_iva_default: Decimal = Decimal("30.00")
    cuenta_gasto_default: Optional[str] = None
    categoria: Optional[str] = None


class ProveedorResponse(BaseModel):
    """Respuesta de proveedor."""
    id: UUID
    tipo_identificacion: str
    identificacion: str
    razon_social: str
    nombre_comercial: Optional[str]
    categoria: Optional[str]
    activo: bool


class FacturaRecibidaCreate(BaseModel):
    """Crear factura recibida manualmente."""
    # Proveedor
    proveedor_tipo_id: str = "04"
    proveedor_identificacion: str
    proveedor_razon_social: str

    # Documento
    tipo_comprobante: str = "01"
    establecimiento: str
    punto_emision: str
    secuencial: str
    clave_acceso: Optional[str] = None
    fecha_emision: date

    # Montos
    subtotal_sin_impuestos: Decimal
    subtotal_15: Decimal = Decimal("0")
    subtotal_0: Decimal = Decimal("0")
    subtotal_no_objeto: Decimal = Decimal("0")
    subtotal_exento: Decimal = Decimal("0")
    iva: Decimal = Decimal("0")
    total: Decimal

    # Clasificación
    tipo_gasto: str = "operacional"
    genera_credito_tributario: bool = True
    cuenta_gasto: Optional[str] = None

    # Retenciones
    aplica_retencion_renta: bool = True
    porcentaje_retencion_renta: Decimal = Decimal("1.00")
    aplica_retencion_iva: bool = False
    porcentaje_retencion_iva: Decimal = Decimal("30.00")

    # Notas
    concepto: Optional[str] = None


class FacturaRecibidaResponse(BaseModel):
    """Respuesta de factura recibida."""
    id: UUID
    proveedor_razon_social: str
    numero_factura: str
    fecha_emision: date
    subtotal_sin_impuestos: Decimal
    iva: Decimal
    total: Decimal
    estado: str
    genera_credito_tributario: bool


# =====================================================
# ENDPOINTS DE PROVEEDORES
# =====================================================

@router.get("/proveedores")
async def listar_proveedores(
    activo: Optional[bool] = None,
    categoria: Optional[str] = None,
    buscar: Optional[str] = None,
    limit: int = 50
):
    """Lista proveedores con filtros opcionales."""
    try:
        supabase = get_supabase_client()
        query = supabase.table('proveedores').select('*')

        if activo is not None:
            query = query.eq('activo', activo)
        if categoria:
            query = query.eq('categoria', categoria)
        if buscar:
            query = query.or_(f"razon_social.ilike.%{buscar}%,identificacion.ilike.%{buscar}%")

        result = query.order('razon_social').limit(limit).execute()
        return {"proveedores": result.data, "total": len(result.data)}

    except Exception as e:
        logger.error(f"Error listando proveedores: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proveedores/{identificacion}")
async def obtener_proveedor(identificacion: str):
    """Obtiene un proveedor por identificación (RUC/Cédula)."""
    try:
        supabase = get_supabase_client()
        result = supabase.table('proveedores').select('*').eq(
            'identificacion', identificacion
        ).single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo proveedor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proveedores")
async def crear_proveedor(proveedor: ProveedorCreate):
    """Crea un nuevo proveedor."""
    try:
        supabase = get_supabase_client()

        # Verificar si ya existe
        existing = supabase.table('proveedores').select('id').eq(
            'identificacion', proveedor.identificacion
        ).execute()

        if existing.data:
            raise HTTPException(status_code=400, detail="Proveedor ya existe")

        result = supabase.table('proveedores').insert(
            proveedor.model_dump(mode='json')
        ).execute()

        return {"message": "Proveedor creado", "proveedor": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando proveedor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# ENDPOINTS DE FACTURAS RECIBIDAS
# =====================================================

@router.get("/facturas")
async def listar_facturas_recibidas(
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    estado: Optional[str] = None,
    proveedor_id: Optional[str] = None,
    limit: int = 100
):
    """Lista facturas recibidas con filtros."""
    try:
        supabase = get_supabase_client()
        query = supabase.table('facturas_recibidas').select('*')

        if anio and mes:
            fecha_inicio = date(anio, mes, 1)
            if mes == 12:
                fecha_fin = date(anio + 1, 1, 1)
            else:
                fecha_fin = date(anio, mes + 1, 1)
            query = query.gte('fecha_emision', fecha_inicio.isoformat())
            query = query.lt('fecha_emision', fecha_fin.isoformat())

        if estado:
            query = query.eq('estado', estado)
        if proveedor_id:
            query = query.eq('proveedor_id', proveedor_id)

        result = query.order('fecha_emision', desc=True).limit(limit).execute()

        # Formatear respuesta
        facturas = []
        for f in result.data:
            facturas.append({
                **f,
                'numero_factura': f"{f['establecimiento']}-{f['punto_emision']}-{f['secuencial']}"
            })

        return {"facturas": facturas, "total": len(facturas)}

    except Exception as e:
        logger.error(f"Error listando facturas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/facturas/{factura_id}")
async def obtener_factura_recibida(factura_id: str):
    """Obtiene detalle de una factura recibida."""
    try:
        supabase = get_supabase_client()

        # Factura
        factura = supabase.table('facturas_recibidas').select('*').eq(
            'id', factura_id
        ).single().execute()

        if not factura.data:
            raise HTTPException(status_code=404, detail="Factura no encontrada")

        # Detalles
        detalles = supabase.table('factura_recibida_detalles').select('*').eq(
            'factura_id', factura_id
        ).order('orden').execute()

        return {
            "factura": factura.data,
            "detalles": detalles.data,
            "numero_factura": f"{factura.data['establecimiento']}-{factura.data['punto_emision']}-{factura.data['secuencial']}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo factura: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/facturas")
async def crear_factura_recibida(factura: FacturaRecibidaCreate):
    """Crea una factura recibida manualmente."""
    try:
        supabase = get_supabase_client()

        # Calcular retenciones
        retencion_renta = Decimal("0")
        retencion_iva = Decimal("0")

        if factura.aplica_retencion_renta:
            retencion_renta = factura.subtotal_sin_impuestos * factura.porcentaje_retencion_renta / 100

        if factura.aplica_retencion_iva and factura.iva > 0:
            retencion_iva = factura.iva * factura.porcentaje_retencion_iva / 100

        # Buscar o crear proveedor
        proveedor = supabase.table('proveedores').select('id').eq(
            'identificacion', factura.proveedor_identificacion
        ).execute()

        proveedor_id = None
        if proveedor.data:
            proveedor_id = proveedor.data[0]['id']
        else:
            # Crear proveedor
            nuevo_proveedor = supabase.table('proveedores').insert({
                'tipo_identificacion': factura.proveedor_tipo_id,
                'identificacion': factura.proveedor_identificacion,
                'razon_social': factura.proveedor_razon_social,
            }).execute()
            if nuevo_proveedor.data:
                proveedor_id = nuevo_proveedor.data[0]['id']

        # Crear factura
        data = {
            'proveedor_id': proveedor_id,
            'proveedor_tipo_id': factura.proveedor_tipo_id,
            'proveedor_identificacion': factura.proveedor_identificacion,
            'proveedor_razon_social': factura.proveedor_razon_social,
            'tipo_comprobante': factura.tipo_comprobante,
            'establecimiento': factura.establecimiento,
            'punto_emision': factura.punto_emision,
            'secuencial': factura.secuencial,
            'clave_acceso': factura.clave_acceso,
            'fecha_emision': factura.fecha_emision.isoformat(),
            'subtotal_sin_impuestos': float(factura.subtotal_sin_impuestos),
            'subtotal_15': float(factura.subtotal_15),
            'subtotal_0': float(factura.subtotal_0),
            'subtotal_no_objeto': float(factura.subtotal_no_objeto),
            'subtotal_exento': float(factura.subtotal_exento),
            'iva': float(factura.iva),
            'total': float(factura.total),
            'tipo_gasto': factura.tipo_gasto,
            'genera_credito_tributario': factura.genera_credito_tributario,
            'cuenta_gasto': factura.cuenta_gasto,
            'aplica_retencion_renta': factura.aplica_retencion_renta,
            'porcentaje_retencion_renta': float(factura.porcentaje_retencion_renta),
            'retencion_renta': float(retencion_renta),
            'aplica_retencion_iva': factura.aplica_retencion_iva,
            'porcentaje_retencion_iva': float(factura.porcentaje_retencion_iva),
            'retencion_iva': float(retencion_iva),
            'concepto': factura.concepto,
            'estado': 'pendiente'
        }

        result = supabase.table('facturas_recibidas').insert(data).execute()

        return {
            "message": "Factura registrada",
            "factura": result.data[0],
            "retenciones": {
                "renta": float(retencion_renta),
                "iva": float(retencion_iva),
                "total": float(retencion_renta + retencion_iva)
            }
        }

    except Exception as e:
        logger.error(f"Error creando factura: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/facturas/preview-xml")
async def preview_factura_xml(request: Request):
    """
    Parsea un XML del SRI y devuelve los datos sin guardar.
    Usado para preview antes de importar.
    """
    try:
        body = await request.body()
        xml_content = body.decode('utf-8')

        parser = ParserFacturaXML()
        factura_data = parser.parse(xml_content)

        if not factura_data:
            raise HTTPException(status_code=400, detail="No se pudo parsear el XML")

        return factura_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en preview XML: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error procesando XML: {str(e)}")


@router.post("/facturas/importar-xml")
async def importar_factura_xml(request: Request):
    """
    Importa una factura desde XML del SRI (recibe XML crudo en body).
    Descarga el XML desde: https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet/
    """
    try:
        # Leer contenido del XML
        content = await request.body()
        xml_content = content.decode('utf-8')

        # Parsear XML
        parser = ParserFacturaXML()
        factura_data = parser.parse(xml_content)

        if not factura_data:
            raise HTTPException(status_code=400, detail="No se pudo parsear el XML")

        supabase = get_supabase_client()

        # Verificar si ya existe
        existing = supabase.table('facturas_recibidas').select('id').eq(
            'clave_acceso', factura_data.get('clave_acceso')
        ).execute()

        if existing.data:
            raise HTTPException(status_code=400, detail="Esta factura ya fue importada")

        # Buscar o crear proveedor
        proveedor = supabase.table('proveedores').select('id').eq(
            'identificacion', factura_data['proveedor_ruc']
        ).execute()

        proveedor_id = None
        if proveedor.data:
            proveedor_id = proveedor.data[0]['id']
        else:
            nuevo_proveedor = supabase.table('proveedores').insert({
                'tipo_identificacion': '04',
                'identificacion': factura_data['proveedor_ruc'],
                'razon_social': factura_data['proveedor_razon_social'],
            }).execute()
            if nuevo_proveedor.data:
                proveedor_id = nuevo_proveedor.data[0]['id']

        # Calcular retenciones por defecto
        subtotal = factura_data.get('subtotal', Decimal("0"))
        iva = factura_data.get('iva', Decimal("0"))
        retencion_renta = subtotal * Decimal("0.01")  # 1% por defecto
        retencion_iva = Decimal("0")  # Se activa manualmente

        # Crear factura
        data = {
            'proveedor_id': proveedor_id,
            'proveedor_tipo_id': '04',
            'proveedor_identificacion': factura_data['proveedor_ruc'],
            'proveedor_razon_social': factura_data['proveedor_razon_social'],
            'tipo_comprobante': factura_data.get('tipo_comprobante', '01'),
            'establecimiento': factura_data['establecimiento'],
            'punto_emision': factura_data['punto_emision'],
            'secuencial': factura_data['secuencial'],
            'clave_acceso': factura_data.get('clave_acceso'),
            'numero_autorizacion': factura_data.get('numero_autorizacion'),
            'fecha_emision': factura_data['fecha_emision'],
            'subtotal_sin_impuestos': float(factura_data.get('subtotal', 0)),
            'subtotal_15': float(factura_data.get('subtotal_15', 0)),
            'subtotal_0': float(factura_data.get('subtotal_0', 0)),
            'subtotal_no_objeto': float(factura_data.get('subtotal_no_objeto', 0)),
            'subtotal_exento': float(factura_data.get('subtotal_exento', 0)),
            'iva': float(iva),
            'total': float(factura_data.get('total', 0)),
            'tipo_gasto': tipo_gasto,
            'genera_credito_tributario': genera_credito,
            'cuenta_gasto': cuenta_gasto,
            'aplica_retencion_renta': True,
            'porcentaje_retencion_renta': 1.00,
            'retencion_renta': float(retencion_renta),
            'aplica_retencion_iva': False,
            'porcentaje_retencion_iva': 30.00,
            'retencion_iva': 0,
            'xml_original': xml_content,
            'estado': 'pendiente'
        }

        result = supabase.table('facturas_recibidas').insert(data).execute()

        # Insertar detalles si existen
        if 'detalles' in factura_data and factura_data['detalles']:
            for i, detalle in enumerate(factura_data['detalles']):
                supabase.table('factura_recibida_detalles').insert({
                    'factura_id': result.data[0]['id'],
                    'codigo': detalle.get('codigo', ''),
                    'descripcion': detalle.get('descripcion', ''),
                    'cantidad': float(detalle.get('cantidad', 1)),
                    'precio_unitario': float(detalle.get('precio_unitario', 0)),
                    'descuento': float(detalle.get('descuento', 0)),
                    'precio_total': float(detalle.get('precio_total', 0)),
                    'tipo_iva': detalle.get('tipo_iva', 'gravado_15'),
                    'tarifa_iva': float(detalle.get('tarifa_iva', 15)),
                    'valor_iva': float(detalle.get('valor_iva', 0)),
                    'orden': i
                }).execute()

        return {
            "message": "Factura importada exitosamente",
            "factura": result.data[0],
            "proveedor": factura_data['proveedor_razon_social'],
            "numero_factura": f"{factura_data['establecimiento']}-{factura_data['punto_emision']}-{factura_data['secuencial']}",
            "total": float(factura_data.get('total', 0))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importando XML: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error procesando XML: {str(e)}")


# =====================================================
# RESUMEN Y ESTADÍSTICAS
# =====================================================

@router.get("/resumen/{anio}/{mes}")
async def resumen_compras_mes(anio: int, mes: int):
    """Obtiene resumen de compras del mes para crédito tributario."""
    try:
        supabase = get_supabase_client()

        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)

        facturas = supabase.table('facturas_recibidas').select('*').gte(
            'fecha_emision', fecha_inicio.isoformat()
        ).lt(
            'fecha_emision', fecha_fin.isoformat()
        ).neq('estado', 'anulada').execute()

        # Calcular totales
        total_subtotal = Decimal("0")
        total_base_gravada = Decimal("0")
        total_base_0 = Decimal("0")
        total_no_objeto = Decimal("0")
        total_exento = Decimal("0")
        total_iva = Decimal("0")
        total_credito_tributario = Decimal("0")
        total_retencion_renta = Decimal("0")
        total_retencion_iva = Decimal("0")
        total_compras = Decimal("0")

        for f in facturas.data:
            total_subtotal += Decimal(str(f['subtotal_sin_impuestos']))
            total_base_gravada += Decimal(str(f['subtotal_15']))
            total_base_0 += Decimal(str(f['subtotal_0']))
            total_no_objeto += Decimal(str(f['subtotal_no_objeto']))
            total_exento += Decimal(str(f['subtotal_exento']))
            total_iva += Decimal(str(f['iva']))
            total_compras += Decimal(str(f['total']))
            total_retencion_renta += Decimal(str(f['retencion_renta']))
            total_retencion_iva += Decimal(str(f['retencion_iva']))

            # Crédito tributario solo si genera
            if f['genera_credito_tributario']:
                porcentaje = Decimal(str(f.get('porcentaje_credito', 100)))
                total_credito_tributario += Decimal(str(f['iva'])) * porcentaje / 100

        return {
            "periodo": f"{mes:02d}/{anio}",
            "total_facturas": len(facturas.data),
            "subtotal": float(total_subtotal),
            "base_gravada_15": float(total_base_gravada),
            "base_0": float(total_base_0),
            "no_objeto_iva": float(total_no_objeto),
            "exento_iva": float(total_exento),
            "total_iva": float(total_iva),
            "credito_tributario": float(total_credito_tributario),
            "retencion_renta": float(total_retencion_renta),
            "retencion_iva": float(total_retencion_iva),
            "total_compras": float(total_compras)
        }

    except Exception as e:
        logger.error(f"Error en resumen: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# ENDPOINTS DE LIQUIDACIONES DE COMPRA (CRIPTO)
# =====================================================

class LiquidacionCriptoCreate(BaseModel):
    """Crear liquidación de compra de criptomonedas."""
    # Vendedor (persona natural)
    vendedor_cedula: str
    vendedor_nombre: str

    # Transacción
    fecha_emision: date
    monto_cripto: Decimal
    tipo_cripto: str = "USDT"
    concepto: str = "Compra de criptomonedas"

    # Contabilización
    auto_contabilizar: bool = True


class TransaccionCriptoCreate(BaseModel):
    """Procesar transacción completa de intermediación cripto."""
    # Vendedor (Paula)
    vendedor_cedula: str
    vendedor_nombre: str

    # Comprador (Luis)
    comprador_cedula: str
    comprador_nombre: str

    # Transacción
    fecha: Optional[date] = None
    monto_cripto: Decimal
    tipo_cripto: str = "USDT"
    concepto: str = "Compra de criptomonedas"


@router.post("/liquidaciones")
async def crear_liquidacion_cripto(data: LiquidacionCriptoCreate):
    """
    Crea una liquidación de compra para criptomonedas.

    - Se emite cuando compramos cripto a persona natural
    - Criptomonedas son exentas de IVA
    - Se registra como Liquidación de Compra (tipo 03)
    """
    try:
        from src.compras.liquidaciones import LiquidacionService, LiquidacionCripto

        service = LiquidacionService()
        liquidacion_data = LiquidacionCripto(
            vendedor_tipo_id="05",
            vendedor_identificacion=data.vendedor_cedula,
            vendedor_nombre=data.vendedor_nombre,
            fecha_emision=data.fecha_emision,
            concepto=data.concepto,
            monto_cripto=data.monto_cripto,
            tipo_cripto=data.tipo_cripto,
            auto_contabilizar=data.auto_contabilizar
        )

        result = await service.crear_liquidacion_cripto(liquidacion_data)

        if not result.get('success'):
            raise HTTPException(status_code=400, detail=result.get('error'))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando liquidación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/liquidaciones")
async def listar_liquidaciones(
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    limit: int = 100
):
    """Lista liquidaciones de compra del período."""
    try:
        from src.compras.liquidaciones import LiquidacionService

        if not anio or not mes:
            from datetime import date
            hoy = date.today()
            anio = anio or hoy.year
            mes = mes or hoy.month

        service = LiquidacionService()
        result = await service.listar_liquidaciones(anio, mes, limit)

        return result

    except Exception as e:
        logger.error(f"Error listando liquidaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/liquidaciones/{liquidacion_id}")
async def obtener_liquidacion(liquidacion_id: str):
    """Obtiene detalle de una liquidación de compra."""
    try:
        supabase = get_supabase_client()

        result = supabase.table('facturas_recibidas').select('*').eq(
            'id', liquidacion_id
        ).eq('tipo_comprobante', '03').single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Liquidación no encontrada")

        liquidacion = result.data
        numero = f"{liquidacion['establecimiento']}-{liquidacion['punto_emision']}-{liquidacion['secuencial']}"

        return {
            "liquidacion": liquidacion,
            "numero": numero,
            "vendedor": liquidacion['proveedor_razon_social'],
            "monto": liquidacion['total']
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo liquidación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transaccion-cripto")
async def procesar_transaccion_cripto(data: TransaccionCriptoCreate):
    """
    Procesa una transacción completa de intermediación cripto.

    Genera automáticamente:
    1. Liquidación de Compra a vendedor (Paula) - tipo 03
    2. Factura de Comisión a comprador (Luis) - tipo 01

    Modelo de negocio:
    - Luis paga: monto_cripto + comisión (1.5%) + IVA
    - Paula recibe: monto_cripto
    - ECUCONDOR gana: comisión
    """
    try:
        from src.compras.liquidaciones import LiquidacionService

        service = LiquidacionService()
        result = await service.procesar_transaccion_cripto(
            vendedor_cedula=data.vendedor_cedula,
            vendedor_nombre=data.vendedor_nombre,
            comprador_cedula=data.comprador_cedula,
            comprador_nombre=data.comprador_nombre,
            monto_cripto=data.monto_cripto,
            tipo_cripto=data.tipo_cripto,
            fecha=data.fecha,
            concepto=data.concepto
        )

        if not result.get('success'):
            raise HTTPException(status_code=400, detail=result.get('error'))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error procesando transacción: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# IMPORTACION EXTRACTO BANCARIO PRODUBANCO
# =====================================================

@router.post("/importar-produbanco")
async def importar_extracto_produbanco(
    file: UploadFile = File(...),
    generar_liquidaciones: bool = Form(True),
    solo_debitos: bool = Form(True)
):
    """
    Importa un extracto bancario de Produbanco y genera liquidaciones.

    - Procesa archivo Excel (.xlsx)
    - Importa movimientos a transacciones_bancarias
    - Genera Liquidaciones de Compra automaticamente (debitos)

    Returns:
        dict con resumen de importacion
    """
    import tempfile
    import os

    try:
        # Guardar archivo temporalmente
        suffix = ".xlsx" if file.filename.endswith(".xlsx") else ".xlsm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            from src.ingestor.importador_produbanco import procesar_extracto_produbanco

            result = await procesar_extracto_produbanco(
                file_path=tmp_path,
                generar_liquidaciones=generar_liquidaciones,
                solo_debitos=solo_debitos
            )

            return {
                "success": True,
                "archivo": file.filename,
                **result
            }

        finally:
            # Limpiar archivo temporal
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        logger.error(f"Error importando extracto: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/importar-produbanco-ruta")
async def importar_extracto_produbanco_ruta(
    file_path: str,
    generar_liquidaciones: bool = True,
    solo_debitos: bool = True
):
    """
    Importa un extracto bancario de Produbanco desde una ruta local.

    Args:
        file_path: Ruta absoluta al archivo Excel
        generar_liquidaciones: Si generar las liquidaciones
        solo_debitos: Solo procesar debitos para liquidaciones
    """
    import os

    try:
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {file_path}")

        from src.ingestor.importador_produbanco import procesar_extracto_produbanco

        result = await procesar_extracto_produbanco(
            file_path=file_path,
            generar_liquidaciones=generar_liquidaciones,
            solo_debitos=solo_debitos
        )

        return {
            "success": True,
            **result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importando extracto: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
