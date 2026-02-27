#!/usr/bin/env python3
"""
ECUCONDOR - Regularizador de Ventas de Comisiones

Este script calcula las comisiones por intermediacion de cripto que debieron
facturarse pero no se facturaron. Genera:

1. Resumen de comisiones por mes
2. IVA a pagar por mes (para regularizar con SRI)
3. Registro de ventas internas para ATS (si se requiere)

Uso:
    python scripts/regularizar_ventas_comisiones.py 2025
    python scripts/regularizar_ventas_comisiones.py 2025 --generar-registros
"""

import os
import sys
from pathlib import Path
from decimal import Decimal
from collections import defaultdict
from datetime import date

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar variables de .env
from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

from supabase import create_client
from src.config.settings import get_settings

# Limpiar cache
get_settings.cache_clear()

TASA_COMISION = Decimal("0.015")  # 1.5%
TASA_IVA = Decimal("0.15")  # 15%


def calcular_comisiones_por_mes(supabase, anio: int) -> dict:
    """
    Calcula las comisiones basadas en las liquidaciones de compra.

    Por cada liquidacion de compra (pago a vendedor de cripto),
    ECUCONDOR debio cobrar 1.5% de comision + IVA al comprador.
    """
    print(f"\nConsultando liquidaciones de compra para {anio}...")

    # Obtener liquidaciones de compra del año
    fecha_inicio = f"{anio}-01-01"
    fecha_fin = f"{anio}-12-31"

    liquidaciones = supabase.table("facturas_recibidas").select(
        "id,fecha_emision,tipo_comprobante,subtotal_exento,total"
    ).eq(
        "tipo_comprobante", "03"  # Liquidaciones de compra
    ).gte(
        "fecha_emision", fecha_inicio
    ).lte(
        "fecha_emision", fecha_fin
    ).execute()

    print(f"   Liquidaciones encontradas: {len(liquidaciones.data)}")

    # Agrupar por mes
    por_mes = defaultdict(lambda: {
        "cantidad": 0,
        "total_cripto": Decimal("0"),
        "comision_base": Decimal("0"),
        "iva_comision": Decimal("0"),
        "total_comision": Decimal("0")
    })

    for liq in liquidaciones.data:
        fecha = liq.get("fecha_emision", "")
        if not fecha:
            continue

        mes = int(fecha.split("-")[1])
        monto = Decimal(str(liq.get("subtotal_exento", 0) or liq.get("total", 0) or 0))

        comision = monto * TASA_COMISION
        iva = comision * TASA_IVA

        por_mes[mes]["cantidad"] += 1
        por_mes[mes]["total_cripto"] += monto
        por_mes[mes]["comision_base"] += comision
        por_mes[mes]["iva_comision"] += iva
        por_mes[mes]["total_comision"] += comision + iva

    return dict(por_mes)


def verificar_facturas_existentes(supabase, anio: int) -> dict:
    """
    Verifica facturas de venta (comisiones) ya emitidas.
    """
    fecha_inicio = f"{anio}-01-01"
    fecha_fin = f"{anio}-12-31"

    facturas = supabase.table("comprobantes_electronicos").select(
        "id,fecha_emision,subtotal_15,iva,importe_total"
    ).eq(
        "tipo_comprobante", "01"
    ).eq(
        "estado", "authorized"
    ).gte(
        "fecha_emision", fecha_inicio
    ).lte(
        "fecha_emision", fecha_fin
    ).execute()

    # Agrupar por mes
    por_mes = defaultdict(lambda: {
        "cantidad": 0,
        "total_base": Decimal("0"),
        "total_iva": Decimal("0")
    })

    for f in facturas.data:
        fecha = f.get("fecha_emision", "")
        if not fecha:
            continue
        mes = int(fecha.split("-")[1])
        por_mes[mes]["cantidad"] += 1
        por_mes[mes]["total_base"] += Decimal(str(f.get("subtotal_15", 0) or 0))
        por_mes[mes]["total_iva"] += Decimal(str(f.get("iva", 0) or 0))

    return dict(por_mes)


def generar_registros_ventas_internas(supabase, anio: int, comisiones: dict, facturas: dict):
    """
    Genera registros de ventas internas para los meses faltantes.
    Estos registros sirven para el calculo de IVA y ATS.
    """
    print("\n" + "=" * 60)
    print("GENERANDO REGISTROS DE VENTAS INTERNAS")
    print("=" * 60)

    meses_nombre = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    registros_creados = 0

    for mes in range(1, 13):
        datos_comision = comisiones.get(mes, {})
        datos_factura = facturas.get(mes, {})

        if not datos_comision.get("cantidad", 0):
            continue

        # Calcular diferencia (lo que falta por registrar)
        comision_esperada = datos_comision.get("comision_base", Decimal("0"))
        comision_facturada = datos_factura.get("total_base", Decimal("0"))
        diferencia = comision_esperada - comision_facturada

        if diferencia <= 0:
            print(f"   {meses_nombre[mes]}: Ya facturado - OK")
            continue

        iva_diferencia = diferencia * TASA_IVA

        # Crear registro de venta interna
        # Usar el ultimo dia del mes como fecha
        import calendar
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        fecha_registro = f"{anio}-{mes:02d}-{ultimo_dia:02d}"

        registro = {
            "tipo_comprobante": "01",  # Factura
            "establecimiento": "001",
            "punto_emision": "001",
            "secuencial": f"INT{mes:02d}{anio}",  # Secuencial interno
            "clave_acceso": f"INTERNO-COMISION-{anio}-{mes:02d}",
            "fecha_emision": fecha_registro,
            "cliente_tipo_id": "07",  # Consumidor final
            "cliente_identificacion": "9999999999999",
            "cliente_razon_social": "CONSUMIDOR FINAL - COMISIONES CRIPTO",
            "subtotal_sin_impuestos": float(diferencia),
            "subtotal_15": float(diferencia),
            "subtotal_0": 0.0,
            "iva": float(iva_diferencia),
            "total_descuento": 0.0,
            "importe_total": float(diferencia + iva_diferencia),
            "estado": "authorized",  # Registros autorizados (internos)
            "info_adicional": {
                "tipo": "REGULARIZACION_COMISIONES_CRIPTO",
                "liquidaciones_relacionadas": datos_comision.get("cantidad", 0),
                "total_cripto_base": float(datos_comision.get("total_cripto", 0)),
                "observacion": f"Comisiones de intermediacion cripto {meses_nombre[mes]} {anio}"
            }
        }

        # Verificar si ya existe
        existing = supabase.table("comprobantes_electronicos").select("id").eq(
            "clave_acceso", registro["clave_acceso"]
        ).execute()

        if existing.data:
            print(f"   {meses_nombre[mes]}: Registro ya existe")
            continue

        # Insertar
        supabase.table("comprobantes_electronicos").insert(registro).execute()
        registros_creados += 1
        print(f"   {meses_nombre[mes]}: Registro creado - Base ${diferencia:.2f}, IVA ${iva_diferencia:.2f}")

    return registros_creados


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='ECUCONDOR - Regularizador de Ventas de Comisiones'
    )
    parser.add_argument('anio', type=int, help='Año a regularizar')
    parser.add_argument('--generar-registros', action='store_true',
                       help='Generar registros de ventas internas')
    parser.add_argument('--output', '-o', help='Archivo de salida para resumen')

    args = parser.parse_args()

    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    print("=" * 70)
    print(f"ECUCONDOR - Regularización de Comisiones {args.anio}")
    print(f"RUC: {settings.sri_ruc}")
    print("=" * 70)

    # 1. Calcular comisiones esperadas
    comisiones = calcular_comisiones_por_mes(supabase, args.anio)

    # 2. Verificar facturas existentes
    print("\nConsultando facturas de venta existentes...")
    facturas = verificar_facturas_existentes(supabase, args.anio)

    # 3. Mostrar resumen
    print("\n" + "=" * 70)
    print("RESUMEN DE COMISIONES POR MES")
    print("=" * 70)
    print()
    print(f"{'MES':<6} {'LIQ.':<6} {'CRIPTO':>12} {'COMISION':>12} {'IVA':>10} "
          f"{'FACT.':>6} {'FALTA IVA':>12}")
    print("-" * 70)

    meses_nombre = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    total_comision = Decimal("0")
    total_iva_comision = Decimal("0")
    total_facturado = Decimal("0")
    total_iva_faltante = Decimal("0")

    resultados_mes = []

    for mes in range(1, 13):
        datos_com = comisiones.get(mes, {})
        datos_fac = facturas.get(mes, {})

        cant_liq = datos_com.get("cantidad", 0)
        cripto = datos_com.get("total_cripto", Decimal("0"))
        comision = datos_com.get("comision_base", Decimal("0"))
        iva = datos_com.get("iva_comision", Decimal("0"))

        cant_fac = datos_fac.get("cantidad", 0)
        iva_facturado = datos_fac.get("total_iva", Decimal("0"))

        iva_faltante = iva - iva_facturado
        if iva_faltante < 0:
            iva_faltante = Decimal("0")

        total_comision += comision
        total_iva_comision += iva
        total_facturado += iva_facturado
        total_iva_faltante += iva_faltante

        if cant_liq > 0 or cant_fac > 0:
            print(f"{meses_nombre[mes]:<6} {cant_liq:<6} ${cripto:>10,.2f} ${comision:>10,.2f} "
                  f"${iva:>8,.2f} {cant_fac:>6} ${iva_faltante:>10,.2f}")

            resultados_mes.append({
                "mes": mes,
                "mes_nombre": meses_nombre[mes],
                "liquidaciones": cant_liq,
                "total_cripto": float(cripto),
                "comision_base": float(comision),
                "iva_esperado": float(iva),
                "facturas_emitidas": cant_fac,
                "iva_faltante": float(iva_faltante)
            })

    print("-" * 70)
    print(f"{'TOTAL':<6} {'':<6} ${sum(c.get('total_cripto', 0) for c in comisiones.values()):>10,.2f} "
          f"${total_comision:>10,.2f} ${total_iva_comision:>8,.2f} "
          f"{'':<6} ${total_iva_faltante:>10,.2f}")
    print("=" * 70)

    # 4. Resumen de IVA a pagar
    print()
    print("=" * 70)
    print("IVA A PAGAR POR MES (para regularización)")
    print("=" * 70)
    print()

    for res in resultados_mes:
        if res["iva_faltante"] > 0:
            print(f"   {res['mes_nombre']} {args.anio}: ${res['iva_faltante']:.2f}")

    print()
    print(f"   TOTAL IVA A REGULARIZAR: ${total_iva_faltante:.2f}")
    print()

    # 5. Generar registros si se solicita
    if args.generar_registros:
        registros = generar_registros_ventas_internas(
            supabase, args.anio, comisiones, facturas
        )
        print(f"\n   Registros creados: {registros}")

    # 6. Guardar resumen si se especifica
    if args.output:
        import json
        output_data = {
            "anio": args.anio,
            "ruc": settings.sri_ruc,
            "total_cripto": float(sum(c.get('total_cripto', 0) for c in comisiones.values())),
            "total_comision": float(total_comision),
            "total_iva_comision": float(total_iva_comision),
            "total_iva_faltante": float(total_iva_faltante),
            "meses": resultados_mes
        }
        Path(args.output).write_text(json.dumps(output_data, indent=2), encoding='utf-8')
        print(f"\nResumen guardado en: {args.output}")

    print()
    print("-" * 70)
    print("NOTA IMPORTANTE:")
    print("-" * 70)
    print("1. El IVA no declarado debe pagarse con multas e intereses")
    print("2. Use el Formulario 104 (sustituiva) para declarar cada mes")
    print("3. Calcule intereses: 1% mensual desde la fecha de vencimiento")
    print("4. Multa: 3% por mes de retraso (maximo 100%)")
    print()
    print("Consulte con su contador o el SRI para el proceso de regularizacion.")
    print()


if __name__ == '__main__':
    main()
