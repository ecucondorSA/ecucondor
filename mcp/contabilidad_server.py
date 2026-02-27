#!/usr/bin/env python3
"""
ECUCONDOR - MCP Server de Contabilidad/ERP

Este servidor MCP expone herramientas para interactuar con el sistema
contable ECUCONDOR desde agentes AI como Claude.

Herramientas disponibles:
- consultar_saldos: Obtiene saldos de cuentas contables
- generar_balance: Genera Balance General a una fecha
- generar_estado_resultados: Genera Estado de Resultados
- registrar_asiento: Registra un asiento contable
- consultar_movimientos: Consulta movimientos de una cuenta
- listar_facturas: Lista facturas de venta/compra
- consultar_cliente: Obtiene datos de un cliente
"""

import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import mcp.types as types

# Configurar path para imports del proyecto
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.supabase import get_supabase_client
from src.ledger.reportes import GeneradorReportes
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
server = Server("ecucondor-contabilidad")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Lista las herramientas disponibles en el servidor MCP."""
    return [
        Tool(
            name="consultar_saldos",
            description="Obtiene los saldos de todas las cuentas contables con movimiento en un período",
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
                    "tipo_cuenta": {
                        "type": "string",
                        "description": "Filtrar por tipo: activo, pasivo, patrimonio, ingreso, gasto",
                        "enum": ["activo", "pasivo", "patrimonio", "ingreso", "gasto"]
                    }
                },
                "required": ["fecha_inicio", "fecha_fin"]
            }
        ),
        Tool(
            name="generar_balance",
            description="Genera el Balance General (Estado de Situación Financiera) a una fecha de corte",
            inputSchema={
                "type": "object",
                "properties": {
                    "fecha_corte": {
                        "type": "string",
                        "description": "Fecha de corte para el balance (YYYY-MM-DD)",
                        "format": "date"
                    }
                },
                "required": ["fecha_corte"]
            }
        ),
        Tool(
            name="generar_estado_resultados",
            description="Genera el Estado de Resultados (Pérdidas y Ganancias) para un período",
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
                    }
                },
                "required": ["fecha_inicio", "fecha_fin"]
            }
        ),
        Tool(
            name="consultar_movimientos",
            description="Consulta los movimientos (libro mayor) de una cuenta contable específica",
            inputSchema={
                "type": "object",
                "properties": {
                    "cuenta_codigo": {
                        "type": "string",
                        "description": "Código de la cuenta contable (ej: 1.1.1.01)"
                    },
                    "fecha_inicio": {
                        "type": "string",
                        "description": "Fecha inicio del período (YYYY-MM-DD)",
                        "format": "date"
                    },
                    "fecha_fin": {
                        "type": "string",
                        "description": "Fecha fin del período (YYYY-MM-DD)",
                        "format": "date"
                    }
                },
                "required": ["cuenta_codigo", "fecha_inicio", "fecha_fin"]
            }
        ),
        Tool(
            name="listar_facturas",
            description="Lista las facturas de venta o compra con filtros opcionales",
            inputSchema={
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "description": "Tipo de factura: venta o compra",
                        "enum": ["venta", "compra"]
                    },
                    "fecha_inicio": {
                        "type": "string",
                        "description": "Filtrar desde esta fecha (YYYY-MM-DD)",
                        "format": "date"
                    },
                    "fecha_fin": {
                        "type": "string",
                        "description": "Filtrar hasta esta fecha (YYYY-MM-DD)",
                        "format": "date"
                    },
                    "estado": {
                        "type": "string",
                        "description": "Filtrar por estado",
                        "enum": ["pendiente", "pagada", "anulada"]
                    },
                    "limite": {
                        "type": "integer",
                        "description": "Número máximo de resultados (default: 50)",
                        "default": 50
                    }
                },
                "required": ["tipo"]
            }
        ),
        Tool(
            name="consultar_cliente",
            description="Obtiene los datos de un cliente por identificación o ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "identificacion": {
                        "type": "string",
                        "description": "RUC, cédula o pasaporte del cliente"
                    },
                    "id": {
                        "type": "string",
                        "description": "ID único del cliente (UUID)"
                    }
                }
            }
        ),
        Tool(
            name="resumen_financiero",
            description="Obtiene un resumen financiero general del mes actual o especificado",
            inputSchema={
                "type": "object",
                "properties": {
                    "anio": {
                        "type": "integer",
                        "description": "Año del resumen (default: año actual)"
                    },
                    "mes": {
                        "type": "integer",
                        "description": "Mes del resumen 1-12 (default: mes actual)"
                    }
                }
            }
        ),
        Tool(
            name="cuentas_por_cobrar",
            description="Obtiene el reporte de cuentas por cobrar (cartera de clientes)",
            inputSchema={
                "type": "object",
                "properties": {
                    "fecha_corte": {
                        "type": "string",
                        "description": "Fecha de corte para el reporte (YYYY-MM-DD)",
                        "format": "date"
                    }
                }
            }
        ),
        Tool(
            name="cuentas_por_pagar",
            description="Obtiene el reporte de cuentas por pagar (deudas con proveedores)",
            inputSchema={
                "type": "object",
                "properties": {
                    "fecha_corte": {
                        "type": "string",
                        "description": "Fecha de corte para el reporte (YYYY-MM-DD)",
                        "format": "date"
                    }
                }
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
    """Ejecuta una herramienta del servidor MCP."""
    try:
        supabase = get_supabase_client()
        settings = get_settings()

        if name == "consultar_saldos":
            return await _consultar_saldos(supabase, arguments)
        elif name == "generar_balance":
            return await _generar_balance(supabase, settings, arguments)
        elif name == "generar_estado_resultados":
            return await _generar_estado_resultados(supabase, settings, arguments)
        elif name == "consultar_movimientos":
            return await _consultar_movimientos(supabase, settings, arguments)
        elif name == "listar_facturas":
            return await _listar_facturas(supabase, arguments)
        elif name == "consultar_cliente":
            return await _consultar_cliente(supabase, arguments)
        elif name == "resumen_financiero":
            return await _resumen_financiero(supabase, settings, arguments)
        elif name == "cuentas_por_cobrar":
            return await _cuentas_por_cobrar(supabase, arguments)
        elif name == "cuentas_por_pagar":
            return await _cuentas_por_pagar(supabase, arguments)
        else:
            return [TextContent(type="text", text=f"Error: Herramienta '{name}' no encontrada")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error ejecutando {name}: {str(e)}")]


async def _consultar_saldos(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Consulta saldos de cuentas contables."""
    generador = GeneradorReportes(supabase.client)

    fecha_inicio = date.fromisoformat(arguments["fecha_inicio"])
    fecha_fin = date.fromisoformat(arguments["fecha_fin"])
    tipo_cuenta = arguments.get("tipo_cuenta")

    saldos = generador._obtener_saldos_directo(fecha_inicio, fecha_fin, tipo_cuenta)

    # Filtrar solo cuentas con movimiento
    resultado = []
    for codigo, datos in sorted(saldos.items()):
        if datos['debe'] > 0 or datos['haber'] > 0:
            resultado.append({
                "codigo": codigo,
                "nombre": datos["nombre"],
                "tipo": datos["tipo"],
                "debe": float(datos["debe"]),
                "haber": float(datos["haber"]),
                "saldo": float(datos["saldo"]),
            })

    return [TextContent(type="text", text=json_dumps({
        "periodo": f"{fecha_inicio} a {fecha_fin}",
        "cuentas": resultado,
        "total_cuentas": len(resultado)
    }))]


async def _generar_balance(supabase, settings, arguments: dict) -> Sequence[types.TextContent]:
    """Genera Balance General."""
    generador = GeneradorReportes(supabase.client)
    fecha_corte = date.fromisoformat(arguments["fecha_corte"])

    balance = generador.generar_balance_general(
        fecha_corte=fecha_corte,
        empresa=settings.sri_razon_social
    )

    resultado = {
        "empresa": balance.empresa,
        "fecha_corte": balance.fecha_corte.isoformat(),
        "activos": {
            "total": float(balance.total_activos),
            "cuentas": [{"codigo": l.codigo, "nombre": l.nombre, "saldo": float(l.saldo)}
                       for l in balance.activos.lineas if not l.es_titulo]
        },
        "pasivos": {
            "total": float(balance.total_pasivos),
            "cuentas": [{"codigo": l.codigo, "nombre": l.nombre, "saldo": float(l.saldo)}
                       for l in balance.pasivos.lineas if not l.es_titulo]
        },
        "patrimonio": {
            "total": float(balance.total_patrimonio),
            "cuentas": [{"codigo": l.codigo, "nombre": l.nombre, "saldo": float(l.saldo)}
                       for l in balance.patrimonio.lineas if not l.es_titulo]
        },
        "pasivo_mas_patrimonio": float(balance.pasivo_mas_patrimonio),
        "esta_cuadrado": balance.esta_cuadrado
    }

    return [TextContent(type="text", text=json_dumps(resultado))]


async def _generar_estado_resultados(supabase, settings, arguments: dict) -> Sequence[types.TextContent]:
    """Genera Estado de Resultados."""
    generador = GeneradorReportes(supabase.client)
    fecha_inicio = date.fromisoformat(arguments["fecha_inicio"])
    fecha_fin = date.fromisoformat(arguments["fecha_fin"])

    estado = generador.generar_estado_resultados(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        empresa=settings.sri_razon_social
    )

    resultado = {
        "empresa": estado.empresa,
        "periodo": f"{fecha_inicio} a {fecha_fin}",
        "ingresos": {
            "total": float(estado.total_ingresos),
            "cuentas": [{"codigo": l.codigo, "nombre": l.nombre, "saldo": float(l.saldo)}
                       for l in estado.ingresos]
        },
        "gastos": {
            "total": float(estado.total_gastos),
            "cuentas": [{"codigo": l.codigo, "nombre": l.nombre, "saldo": float(l.saldo)}
                       for l in estado.gastos]
        },
        "utilidad_bruta": float(estado.utilidad_bruta),
        "es_utilidad": estado.es_utilidad
    }

    return [TextContent(type="text", text=json_dumps(resultado))]


async def _consultar_movimientos(supabase, settings, arguments: dict) -> Sequence[types.TextContent]:
    """Consulta libro mayor de una cuenta."""
    generador = GeneradorReportes(supabase.client)

    cuenta_codigo = arguments["cuenta_codigo"]
    fecha_inicio = date.fromisoformat(arguments["fecha_inicio"])
    fecha_fin = date.fromisoformat(arguments["fecha_fin"])

    libro = generador.generar_libro_mayor(
        cuenta_codigo=cuenta_codigo,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        empresa=settings.sri_razon_social
    )

    resultado = {
        "cuenta": {
            "codigo": libro.cuenta_codigo,
            "nombre": libro.cuenta_nombre
        },
        "periodo": f"{fecha_inicio} a {fecha_fin}",
        "saldo_inicial": float(libro.saldo_inicial),
        "movimientos": [
            {
                "fecha": m.fecha.isoformat(),
                "numero_asiento": m.numero_asiento,
                "concepto": m.concepto,
                "debe": float(m.debe),
                "haber": float(m.haber),
                "saldo": float(m.saldo)
            }
            for m in libro.movimientos
        ],
        "totales": {
            "debe": float(libro.total_debe),
            "haber": float(libro.total_haber),
            "saldo_final": float(libro.saldo_final)
        }
    }

    return [TextContent(type="text", text=json_dumps(resultado))]


async def _listar_facturas(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Lista facturas de venta o compra."""
    tipo = arguments["tipo"]
    tabla = "facturas_venta" if tipo == "venta" else "facturas_compra"
    limite = arguments.get("limite", 50)

    query = supabase.client.table(tabla).select("*")

    if fecha_inicio := arguments.get("fecha_inicio"):
        query = query.gte("fecha_emision", fecha_inicio)
    if fecha_fin := arguments.get("fecha_fin"):
        query = query.lte("fecha_emision", fecha_fin)
    if estado := arguments.get("estado"):
        query = query.eq("estado", estado)

    query = query.order("fecha_emision", desc=True).limit(limite)
    result = query.execute()

    facturas = []
    for f in result.data:
        facturas.append({
            "id": f.get("id"),
            "numero": f.get("numero") or f.get("numero_factura"),
            "fecha": f.get("fecha_emision"),
            "cliente": f.get("cliente_razon_social") or f.get("proveedor_razon_social"),
            "total": float(f.get("importe_total", 0)),
            "estado": f.get("estado", "pendiente")
        })

    return [TextContent(type="text", text=json_dumps({
        "tipo": tipo,
        "total_facturas": len(facturas),
        "facturas": facturas
    }))]


async def _consultar_cliente(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Consulta datos de un cliente."""
    query = supabase.client.table("clientes").select("*")

    if identificacion := arguments.get("identificacion"):
        query = query.eq("identificacion", identificacion)
    elif cliente_id := arguments.get("id"):
        query = query.eq("id", cliente_id)
    else:
        return [TextContent(type="text", text="Error: Debe proporcionar identificacion o id")]

    result = query.execute()

    if not result.data:
        return [TextContent(type="text", text="Cliente no encontrado")]

    cliente = result.data[0]
    return [TextContent(type="text", text=json_dumps({
        "id": cliente.get("id"),
        "identificacion": cliente.get("identificacion"),
        "razon_social": cliente.get("razon_social"),
        "tipo_identificacion": cliente.get("tipo_identificacion"),
        "email": cliente.get("email"),
        "telefono": cliente.get("telefono"),
        "direccion": cliente.get("direccion")
    }))]


async def _resumen_financiero(supabase, settings, arguments: dict) -> Sequence[types.TextContent]:
    """Genera resumen financiero del mes."""
    import calendar

    hoy = date.today()
    anio = arguments.get("anio", hoy.year)
    mes = arguments.get("mes", hoy.month)

    _, ultimo_dia = calendar.monthrange(anio, mes)
    fecha_inicio = date(anio, mes, 1)
    fecha_fin = date(anio, mes, ultimo_dia)

    generador = GeneradorReportes(supabase.client)

    # Obtener saldos
    saldos = generador._obtener_saldos_directo(fecha_inicio, fecha_fin)

    # Calcular totales por tipo
    totales = {"activo": 0, "pasivo": 0, "patrimonio": 0, "ingreso": 0, "gasto": 0}
    for codigo, datos in saldos.items():
        if datos['debe'] > 0 or datos['haber'] > 0:
            totales[datos['tipo']] += float(abs(datos['saldo']))

    # Contar facturas del mes
    facturas_venta = supabase.client.table("facturas_venta").select(
        "id", count="exact"
    ).gte("fecha_emision", fecha_inicio.isoformat()).lte(
        "fecha_emision", fecha_fin.isoformat()
    ).execute()

    resultado = {
        "periodo": f"{mes:02d}/{anio}",
        "empresa": settings.sri_razon_social,
        "resumen": {
            "total_activos": totales["activo"],
            "total_pasivos": totales["pasivo"],
            "total_patrimonio": totales["patrimonio"],
            "total_ingresos": totales["ingreso"],
            "total_gastos": totales["gasto"],
            "utilidad_neta": totales["ingreso"] - totales["gasto"]
        },
        "actividad": {
            "facturas_emitidas": facturas_venta.count or 0
        }
    }

    return [TextContent(type="text", text=json_dumps(resultado))]


async def _cuentas_por_cobrar(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Obtiene reporte de cuentas por cobrar."""
    fecha_corte = date.fromisoformat(arguments.get("fecha_corte", date.today().isoformat()))

    # Obtener facturas pendientes de cobro
    facturas = supabase.client.table("facturas_venta").select(
        "id, numero, fecha_emision, fecha_vencimiento, cliente_razon_social, importe_total, estado"
    ).neq("estado", "pagada").neq("estado", "anulada").execute()

    total_por_cobrar = 0
    pendientes = []

    for f in facturas.data:
        saldo = float(f.get("importe_total", 0))
        total_por_cobrar += saldo

        fecha_venc = date.fromisoformat(f["fecha_vencimiento"]) if f.get("fecha_vencimiento") else None
        dias_vencida = (fecha_corte - fecha_venc).days if fecha_venc else 0

        pendientes.append({
            "numero": f.get("numero"),
            "fecha": f.get("fecha_emision"),
            "cliente": f.get("cliente_razon_social"),
            "total": saldo,
            "dias_vencida": max(0, dias_vencida)
        })

    return [TextContent(type="text", text=json_dumps({
        "fecha_corte": fecha_corte.isoformat(),
        "total_por_cobrar": total_por_cobrar,
        "cantidad_facturas": len(pendientes),
        "facturas": sorted(pendientes, key=lambda x: x.get("dias_vencida", 0), reverse=True)
    }))]


async def _cuentas_por_pagar(supabase, arguments: dict) -> Sequence[types.TextContent]:
    """Obtiene reporte de cuentas por pagar."""
    fecha_corte = date.fromisoformat(arguments.get("fecha_corte", date.today().isoformat()))

    # Obtener facturas de compra pendientes de pago
    facturas = supabase.client.table("facturas_compra").select(
        "id, numero_factura, fecha_emision, fecha_vencimiento, proveedor_razon_social, importe_total, estado"
    ).neq("estado", "pagada").neq("estado", "anulada").execute()

    total_por_pagar = 0
    pendientes = []

    for f in facturas.data:
        saldo = float(f.get("importe_total", 0))
        total_por_pagar += saldo

        fecha_venc = date.fromisoformat(f["fecha_vencimiento"]) if f.get("fecha_vencimiento") else None
        dias_vencida = (fecha_corte - fecha_venc).days if fecha_venc else 0

        pendientes.append({
            "numero": f.get("numero_factura"),
            "fecha": f.get("fecha_emision"),
            "proveedor": f.get("proveedor_razon_social"),
            "total": saldo,
            "dias_vencida": max(0, dias_vencida)
        })

    return [TextContent(type="text", text=json_dumps({
        "fecha_corte": fecha_corte.isoformat(),
        "total_por_pagar": total_por_pagar,
        "cantidad_facturas": len(pendientes),
        "facturas": sorted(pendientes, key=lambda x: x.get("dias_vencida", 0), reverse=True)
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
