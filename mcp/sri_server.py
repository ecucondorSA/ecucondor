#!/usr/bin/env python3
"""
ECUCONDOR - MCP Server para Servicios SRI

Este servidor MCP expone herramientas para interactuar con los
servicios del SRI (Servicio de Rentas Internas) de Ecuador.

Herramientas disponibles:
- consultar_ruc: Consulta información de un RUC en el SRI
- validar_comprobante: Valida un comprobante electrónico en el SRI
- generar_ats: Genera el Anexo Transaccional Simplificado (ATS)
- consultar_estado_tributario: Verifica estado tributario de un contribuyente
- listar_retenciones: Lista retenciones pendientes/emitidas
"""

import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence
import calendar

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import mcp.types as types

# Configurar path para imports del proyecto
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.supabase import get_supabase_client
from src.config import get_settings


class DecimalEncoder(json.JSONEncoder):
    """Encoder para serializar Decimals a JSON."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def json_dumps(obj: Any) -> str:
    """Serializa objeto a JSON con soporte para Decimal y date."""
    return json.dumps(obj, cls=DecimalEncoder, ensure_ascii=False, indent=2)


# Crear servidor MCP
server = Server("ecucondor-sri")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Lista las herramientas disponibles en el servidor MCP."""
    return [
        Tool(
            name="consultar_ruc",
            description="Consulta información de un RUC en la base de datos local y opcionalmente en el SRI",
            inputSchema={
                "type": "object",
                "properties": {
                    "ruc": {
                        "type": "string",
                        "description": "Número de RUC a consultar (13 dígitos)",
                        "pattern": "^[0-9]{13}$"
                    },
                    "consultar_sri": {
                        "type": "boolean",
                        "description": "Si true, consulta también en el webservice del SRI",
                        "default": False
                    }
                },
                "required": ["ruc"]
            }
        ),
        Tool(
            name="validar_comprobante",
            description="Valida un comprobante electrónico (factura, retención, etc.) contra el SRI",
            inputSchema={
                "type": "object",
                "properties": {
                    "clave_acceso": {
                        "type": "string",
                        "description": "Clave de acceso del comprobante (49 dígitos)",
                        "pattern": "^[0-9]{49}$"
                    }
                },
                "required": ["clave_acceso"]
            }
        ),
        Tool(
            name="generar_ats",
            description="Genera el Anexo Transaccional Simplificado (ATS) para un período",
            inputSchema={
                "type": "object",
                "properties": {
                    "anio": {
                        "type": "integer",
                        "description": "Año del ATS (ej: 2025)"
                    },
                    "mes": {
                        "type": "integer",
                        "description": "Mes del ATS (1-12)"
                    },
                    "guardar_archivo": {
                        "type": "boolean",
                        "description": "Si true, guarda el XML en archivo",
                        "default": False
                    }
                },
                "required": ["anio", "mes"]
            }
        ),
        Tool(
            name="consultar_estado_tributario",
            description="Consulta el estado tributario del contribuyente configurado",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="listar_retenciones",
            description="Lista las retenciones emitidas o pendientes de emitir",
            inputSchema={
                "type": "object",
                "properties": {
                    "fecha_inicio": {
                        "type": "string",
                        "description": "Fecha inicio del período (YYYY-MM-DD)",
                        "format": "date"
                    },
                    "fecha_fin": {
                        "type": "string",
                        "description": "Fecha fin del período (YYYY-MM-DD)",
                        "format": "date"
                    },
                    "estado": {
                        "type": "string",
                        "description": "Filtrar por estado",
                        "enum": ["pendiente", "emitida", "anulada"]
                    }
                }
            }
        ),
        Tool(
            name="resumen_impuestos_mes",
            description="Genera un resumen de impuestos (IVA, retenciones) del mes",
            inputSchema={
                "type": "object",
                "properties": {
                    "anio": {
                        "type": "integer",
                        "description": "Año del resumen"
                    },
                    "mes": {
                        "type": "integer",
                        "description": "Mes del resumen (1-12)"
                    }
                },
                "required": ["anio", "mes"]
            }
        ),
        Tool(
            name="proximos_vencimientos",
            description="Muestra los próximos vencimientos de obligaciones tributarias",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
    """Ejecuta una herramienta del servidor MCP."""
    try:
        supabase = get_supabase_client()
        settings = get_settings()

        if name == "consultar_ruc":
            return await _consultar_ruc(supabase, arguments)
        elif name == "validar_comprobante":
            return await _validar_comprobante(arguments)
        elif name == "generar_ats":
            return await _generar_ats(supabase, settings, arguments)
        elif name == "consultar_estado_tributario":
            return await _consultar_estado_tributario(settings)
        elif name == "listar_retenciones":
            return await _listar_retenciones(supabase, arguments)
        elif name == "resumen_impuestos_mes":
            return await _resumen_impuestos_mes(supabase, arguments)
        elif name == "proximos_vencimientos":
            return await _proximos_vencimientos(settings)
        else:
            return [TextContent(type="text", text=f"Error: Herramienta '{name}' no encontrada")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error ejecutando {name}: {str(e)}")]


async def _consultar_ruc(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Consulta información de un RUC."""
    ruc = arguments["ruc"]

    # Buscar en clientes
    cliente = supabase.client.table("clientes").select("*").eq("identificacion", ruc).execute()
    if cliente.data:
        c = cliente.data[0]
        return [TextContent(type="text", text=json_dumps({
            "encontrado": True,
            "tipo": "cliente",
            "ruc": ruc,
            "razon_social": c.get("razon_social"),
            "tipo_identificacion": c.get("tipo_identificacion"),
            "direccion": c.get("direccion"),
            "email": c.get("email"),
            "telefono": c.get("telefono")
        }))]

    # Buscar en proveedores
    proveedor = supabase.client.table("proveedores").select("*").eq("identificacion", ruc).execute()
    if proveedor.data:
        p = proveedor.data[0]
        return [TextContent(type="text", text=json_dumps({
            "encontrado": True,
            "tipo": "proveedor",
            "ruc": ruc,
            "razon_social": p.get("razon_social"),
            "nombre_comercial": p.get("nombre_comercial"),
            "direccion": p.get("direccion"),
            "obligado_contabilidad": p.get("obligado_contabilidad"),
            "agente_retencion": p.get("agente_retencion")
        }))]

    return [TextContent(type="text", text=json_dumps({
        "encontrado": False,
        "ruc": ruc,
        "mensaje": "RUC no encontrado en la base de datos local"
    }))]


async def _validar_comprobante(arguments: dict) -> Sequence[types.TextContent]:
    """Valida un comprobante en el SRI."""
    clave_acceso = arguments["clave_acceso"]

    # Extraer información de la clave de acceso
    # Formato: DDMMAAAA + TipoEmision + RUC + TipoDoc + Serie + Secuencial + Código + TipoEmisión + Dígito
    info = {
        "clave_acceso": clave_acceso,
        "fecha_emision": f"{clave_acceso[0:2]}/{clave_acceso[2:4]}/{clave_acceso[4:8]}",
        "tipo_comprobante": clave_acceso[8:10],
        "ruc_emisor": clave_acceso[10:23],
        "ambiente": "Producción" if clave_acceso[23] == "2" else "Pruebas",
        "establecimiento": clave_acceso[24:27],
        "punto_emision": clave_acceso[27:30],
        "secuencial": clave_acceso[30:39],
    }

    tipos_doc = {
        "01": "Factura",
        "03": "Liquidación de Compra",
        "04": "Nota de Crédito",
        "05": "Nota de Débito",
        "06": "Guía de Remisión",
        "07": "Comprobante de Retención"
    }
    info["tipo_documento"] = tipos_doc.get(info["tipo_comprobante"], "Desconocido")

    # TODO: Implementar llamada real al webservice del SRI
    # Por ahora solo devolvemos la información parseada
    return [TextContent(type="text", text=json_dumps({
        "validacion": "Información extraída de clave de acceso",
        "nota": "Consulta al SRI pendiente de implementar",
        "datos": info
    }))]


async def _generar_ats(supabase, settings, arguments: dict) -> Sequence[types.TextContent]:
    """Genera el ATS del período."""
    anio = arguments["anio"]
    mes = arguments["mes"]

    _, ultimo_dia = calendar.monthrange(anio, mes)
    fecha_inicio = date(anio, mes, 1)
    fecha_fin = date(anio, mes, ultimo_dia)

    # Obtener ventas del período
    ventas = supabase.client.table("facturas_venta").select(
        "id, numero, fecha_emision, cliente_razon_social, cliente_identificacion, importe_total, subtotal_0, subtotal_12, iva"
    ).gte("fecha_emision", fecha_inicio.isoformat()).lte(
        "fecha_emision", fecha_fin.isoformat()
    ).neq("estado", "anulada").execute()

    # Obtener compras del período
    compras = supabase.client.table("facturas_compra").select(
        "id, numero_factura, fecha_emision, proveedor_razon_social, proveedor_ruc, importe_total, subtotal_0, subtotal_12, iva"
    ).gte("fecha_emision", fecha_inicio.isoformat()).lte(
        "fecha_emision", fecha_fin.isoformat()
    ).neq("estado", "anulada").execute()

    resumen = {
        "periodo": f"{mes:02d}/{anio}",
        "contribuyente": {
            "ruc": settings.sri_ruc,
            "razon_social": settings.sri_razon_social
        },
        "ventas": {
            "cantidad": len(ventas.data) if ventas.data else 0,
            "total": sum(float(v.get("importe_total", 0)) for v in (ventas.data or [])),
            "iva": sum(float(v.get("iva", 0)) for v in (ventas.data or []))
        },
        "compras": {
            "cantidad": len(compras.data) if compras.data else 0,
            "total": sum(float(c.get("importe_total", 0)) for c in (compras.data or [])),
            "iva": sum(float(c.get("iva", 0)) for c in (compras.data or []))
        },
        "estado": "Datos recopilados",
        "nota": "Para generar el XML completo, use el endpoint /api/v1/sri/ats"
    }

    return [TextContent(type="text", text=json_dumps(resumen))]


async def _consultar_estado_tributario(settings) -> Sequence[types.TextContent]:
    """Consulta estado tributario del contribuyente configurado."""
    return [TextContent(type="text", text=json_dumps({
        "contribuyente": {
            "ruc": settings.sri_ruc,
            "razon_social": settings.sri_razon_social,
            "obligado_contabilidad": settings.sri_obligado_contabilidad,
            "tipo_contribuyente": settings.sri_tipo_contribuyente,
            "regimen": getattr(settings, 'sri_regimen', 'GENERAL'),
        },
        "certificado": {
            "configurado": bool(settings.sri_certificate_path),
            "ambiente": settings.sri_ambiente
        },
        "nota": "Para verificar estado real en SRI, consulte el portal web"
    }))]


async def _listar_retenciones(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Lista retenciones emitidas o pendientes."""
    # Buscar retenciones en la tabla (si existe)
    try:
        query = supabase.client.table("retenciones").select("*")

        if fecha_inicio := arguments.get("fecha_inicio"):
            query = query.gte("fecha_emision", fecha_inicio)
        if fecha_fin := arguments.get("fecha_fin"):
            query = query.lte("fecha_emision", fecha_fin)
        if estado := arguments.get("estado"):
            query = query.eq("estado", estado)

        query = query.order("fecha_emision", desc=True).limit(50)
        result = query.execute()

        return [TextContent(type="text", text=json_dumps({
            "total": len(result.data) if result.data else 0,
            "retenciones": result.data or []
        }))]
    except Exception:
        return [TextContent(type="text", text=json_dumps({
            "mensaje": "Tabla de retenciones no encontrada o vacía",
            "retenciones": []
        }))]


async def _resumen_impuestos_mes(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Genera resumen de impuestos del mes."""
    anio = arguments["anio"]
    mes = arguments["mes"]

    _, ultimo_dia = calendar.monthrange(anio, mes)
    fecha_inicio = date(anio, mes, 1)
    fecha_fin = date(anio, mes, ultimo_dia)

    # Obtener datos de ventas
    ventas = supabase.client.table("facturas_venta").select(
        "subtotal_0, subtotal_12, iva"
    ).gte("fecha_emision", fecha_inicio.isoformat()).lte(
        "fecha_emision", fecha_fin.isoformat()
    ).neq("estado", "anulada").execute()

    # Obtener datos de compras
    compras = supabase.client.table("facturas_compra").select(
        "subtotal_0, subtotal_12, iva"
    ).gte("fecha_emision", fecha_inicio.isoformat()).lte(
        "fecha_emision", fecha_fin.isoformat()
    ).neq("estado", "anulada").execute()

    iva_ventas = sum(float(v.get("iva", 0)) for v in (ventas.data or []))
    iva_compras = sum(float(c.get("iva", 0)) for c in (compras.data or []))

    return [TextContent(type="text", text=json_dumps({
        "periodo": f"{mes:02d}/{anio}",
        "iva": {
            "ventas": {
                "base_0": sum(float(v.get("subtotal_0", 0)) for v in (ventas.data or [])),
                "base_12": sum(float(v.get("subtotal_12", 0)) for v in (ventas.data or [])),
                "iva_generado": iva_ventas
            },
            "compras": {
                "base_0": sum(float(c.get("subtotal_0", 0)) for c in (compras.data or [])),
                "base_12": sum(float(c.get("subtotal_12", 0)) for c in (compras.data or [])),
                "iva_pagado": iva_compras
            },
            "saldo": iva_ventas - iva_compras,
            "resultado": "A favor del contribuyente" if iva_compras > iva_ventas else "A pagar"
        }
    }))]


async def _proximos_vencimientos(settings) -> Sequence[types.TextContent]:
    """Muestra próximos vencimientos tributarios."""
    hoy = date.today()
    noveno_digito = settings.sri_ruc[8] if settings.sri_ruc else "0"

    # Tabla de vencimientos según noveno dígito del RUC
    vencimientos_dia = {
        "1": 10, "2": 12, "3": 14, "4": 16, "5": 18,
        "6": 20, "7": 22, "8": 24, "9": 26, "0": 28
    }
    dia_vencimiento = vencimientos_dia.get(noveno_digito, 28)

    # Próximo mes
    if hoy.month == 12:
        proximo_mes = date(hoy.year + 1, 1, dia_vencimiento)
    else:
        proximo_mes = date(hoy.year, hoy.month + 1, dia_vencimiento)

    return [TextContent(type="text", text=json_dumps({
        "noveno_digito_ruc": noveno_digito,
        "dia_vencimiento": dia_vencimiento,
        "obligaciones": [
            {
                "obligacion": "Declaración IVA Mensual (F104)",
                "vencimiento": proximo_mes.isoformat(),
                "dias_restantes": (proximo_mes - hoy).days
            },
            {
                "obligacion": "Anexo Transaccional (ATS)",
                "vencimiento": proximo_mes.isoformat(),
                "dias_restantes": (proximo_mes - hoy).days
            },
            {
                "obligacion": "Retenciones en la Fuente",
                "vencimiento": proximo_mes.isoformat(),
                "dias_restantes": (proximo_mes - hoy).days
            }
        ],
        "nota": "Fechas basadas en calendario tributario estándar del SRI"
    }))]


async def main():
    """Punto de entrada principal del servidor MCP."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
