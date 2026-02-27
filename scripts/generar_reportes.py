#!/usr/bin/env python3
"""
ECUCONDOR - Generador de Reportes Contables

Genera Balance General, Estado de Resultados y Libro Mayor.

Uso:
    python scripts/generar_reportes.py balance [--fecha YYYY-MM-DD]
    python scripts/generar_reportes.py pyg --anio 2025 --mes 11
    python scripts/generar_reportes.py mayor --cuenta 1.1.1.07 --anio 2025 --mes 11
    python scripts/generar_reportes.py cuentas --anio 2025 --mes 11
"""

import os
import sys
import calendar
from pathlib import Path
from datetime import date
from decimal import Decimal

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
from src.ledger.reportes import GeneradorReportes

# Limpiar cache
get_settings.cache_clear()


def obtener_empresa(supabase) -> str:
    """Obtiene el nombre de la empresa."""
    result = supabase.table('company_info').select('razon_social').limit(1).execute()
    if result.data:
        return result.data[0]['razon_social']
    return "ECUCONDOR SAS"


def cmd_balance(args, supabase, generador, empresa):
    """Genera Balance General."""
    if args.fecha:
        fecha_corte = date.fromisoformat(args.fecha)
    else:
        fecha_corte = date.today()

    print(f"\nGenerando Balance General al {fecha_corte}...")
    print()

    balance = generador.generar_balance_general(
        fecha_corte=fecha_corte,
        empresa=empresa,
        incluir_cuentas_cero=args.incluir_cero
    )

    print(balance.to_text())

    # Guardar en archivo si se solicita
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(balance.to_text(), encoding='utf-8')
        print(f"\nGuardado en: {output_path}")


def cmd_pyg(args, supabase, generador, empresa):
    """Genera Estado de Resultados (P&G)."""
    anio = args.anio or date.today().year
    mes = args.mes or date.today().month

    fecha_inicio = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = date(anio, mes, ultimo_dia)

    print(f"\nGenerando Estado de Resultados {mes:02d}/{anio}...")
    print()

    estado = generador.generar_estado_resultados(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        empresa=empresa,
        incluir_cuentas_cero=args.incluir_cero
    )

    print(estado.to_text())

    # Guardar en archivo si se solicita
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(estado.to_text(), encoding='utf-8')
        print(f"\nGuardado en: {output_path}")


def cmd_mayor(args, supabase, generador, empresa):
    """Genera Libro Mayor de una cuenta."""
    if not args.cuenta:
        print("Error: Debe especificar una cuenta con --cuenta")
        sys.exit(1)

    anio = args.anio or date.today().year
    mes = args.mes or date.today().month

    fecha_inicio = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = date(anio, mes, ultimo_dia)

    print(f"\nGenerando Libro Mayor - Cuenta {args.cuenta} - {mes:02d}/{anio}...")
    print()

    try:
        libro = generador.generar_libro_mayor(
            cuenta_codigo=args.cuenta,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=empresa
        )

        print(libro.to_text())

        # Guardar en archivo si se solicita
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(libro.to_text(), encoding='utf-8')
            print(f"\nGuardado en: {output_path}")

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_cuentas(args, supabase, generador, empresa):
    """Lista cuentas con movimientos en el período."""
    anio = args.anio or date.today().year
    mes = args.mes or date.today().month

    fecha_inicio = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = date(anio, mes, ultimo_dia)

    print(f"\nCuentas con movimientos - {mes:02d}/{anio}")
    print("=" * 90)
    print(f"{'CÓDIGO':<12} {'CUENTA':<35} {'TIPO':<12} {'DEBE':>12} {'HABER':>12}")
    print("-" * 90)

    cuentas = generador.listar_cuentas_con_movimiento(fecha_inicio, fecha_fin)

    total_debe = Decimal("0")
    total_haber = Decimal("0")

    for c in cuentas:
        print(
            f"{c['codigo']:<12} "
            f"{c['nombre'][:35]:<35} "
            f"{c['tipo']:<12} "
            f"${c['debe']:>10,.2f} "
            f"${c['haber']:>10,.2f}"
        )
        total_debe += c['debe']
        total_haber += c['haber']

    print("-" * 90)
    print(f"{'TOTALES':<61} ${total_debe:>10,.2f} ${total_haber:>10,.2f}")
    print("=" * 90)

    if total_debe == total_haber:
        print("Estado: CUADRADO")
    else:
        print(f"Estado: DESCUADRADO (Diferencia: ${total_debe - total_haber:,.2f})")


def cmd_resumen(args, supabase, generador, empresa):
    """Genera resumen rápido del período."""
    anio = args.anio or date.today().year
    mes = args.mes or date.today().month

    fecha_inicio = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_fin = date(anio, mes, ultimo_dia)

    print()
    print("=" * 60)
    print(f"RESUMEN CONTABLE - {empresa}")
    print(f"Período: {mes:02d}/{anio}")
    print("=" * 60)

    # Balance
    balance = generador.generar_balance_general(fecha_fin, empresa)
    print()
    print("BALANCE GENERAL:")
    print(f"  Activos:     ${balance.total_activos:>12,.2f}")
    print(f"  Pasivos:     ${balance.total_pasivos:>12,.2f}")
    print(f"  Patrimonio:  ${balance.total_patrimonio:>12,.2f}")
    print(f"  P + P:       ${balance.pasivo_mas_patrimonio:>12,.2f}")
    print(f"  Estado:      {'CUADRADO' if balance.esta_cuadrado else 'DESCUADRADO'}")

    # Estado de Resultados
    estado = generador.generar_estado_resultados(fecha_inicio, fecha_fin, empresa)
    print()
    print("ESTADO DE RESULTADOS:")
    print(f"  Ingresos:    ${estado.total_ingresos:>12,.2f}")
    print(f"  Gastos:      ${estado.total_gastos:>12,.2f}")
    resultado = "UTILIDAD" if estado.es_utilidad else "PÉRDIDA"
    print(f"  {resultado}:    ${abs(estado.utilidad_bruta):>12,.2f}")

    # Cuentas principales
    cuentas = generador.listar_cuentas_con_movimiento(fecha_inicio, fecha_fin)
    print()
    print("CUENTAS PRINCIPALES (Top 5 por movimiento):")
    cuentas_ord = sorted(cuentas, key=lambda x: x['debe'] + x['haber'], reverse=True)[:5]
    for c in cuentas_ord:
        print(f"  {c['codigo']:<10} {c['nombre'][:30]:<30} ${c['debe'] + c['haber']:>10,.2f}")

    print()
    print("=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='ECUCONDOR - Generador de Reportes Contables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
    python scripts/generar_reportes.py balance
    python scripts/generar_reportes.py balance --fecha 2025-11-30
    python scripts/generar_reportes.py pyg --anio 2025 --mes 11
    python scripts/generar_reportes.py mayor --cuenta 1.1.1.07 --anio 2025 --mes 11
    python scripts/generar_reportes.py cuentas --anio 2025 --mes 11
    python scripts/generar_reportes.py resumen --anio 2025 --mes 11
        """
    )

    subparsers = parser.add_subparsers(dest='comando', help='Comando a ejecutar')

    # Balance General
    p_balance = subparsers.add_parser('balance', help='Genera Balance General')
    p_balance.add_argument('--fecha', help='Fecha de corte (YYYY-MM-DD)')
    p_balance.add_argument('--incluir-cero', action='store_true', help='Incluir cuentas con saldo cero')
    p_balance.add_argument('--output', '-o', help='Archivo de salida')

    # Estado de Resultados (P&G)
    p_pyg = subparsers.add_parser('pyg', help='Genera Estado de Resultados')
    p_pyg.add_argument('--anio', type=int, help='Año')
    p_pyg.add_argument('--mes', type=int, help='Mes (1-12)')
    p_pyg.add_argument('--incluir-cero', action='store_true', help='Incluir cuentas con saldo cero')
    p_pyg.add_argument('--output', '-o', help='Archivo de salida')

    # Libro Mayor
    p_mayor = subparsers.add_parser('mayor', help='Genera Libro Mayor')
    p_mayor.add_argument('--cuenta', required=True, help='Código de cuenta')
    p_mayor.add_argument('--anio', type=int, help='Año')
    p_mayor.add_argument('--mes', type=int, help='Mes (1-12)')
    p_mayor.add_argument('--output', '-o', help='Archivo de salida')

    # Listar cuentas
    p_cuentas = subparsers.add_parser('cuentas', help='Lista cuentas con movimientos')
    p_cuentas.add_argument('--anio', type=int, help='Año')
    p_cuentas.add_argument('--mes', type=int, help='Mes (1-12)')

    # Resumen
    p_resumen = subparsers.add_parser('resumen', help='Genera resumen rápido')
    p_resumen.add_argument('--anio', type=int, help='Año')
    p_resumen.add_argument('--mes', type=int, help='Mes (1-12)')

    args = parser.parse_args()

    if not args.comando:
        parser.print_help()
        sys.exit(1)

    # Conectar a Supabase
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    empresa = obtener_empresa(supabase)
    generador = GeneradorReportes(supabase)

    # Ejecutar comando
    if args.comando == 'balance':
        cmd_balance(args, supabase, generador, empresa)
    elif args.comando == 'pyg':
        cmd_pyg(args, supabase, generador, empresa)
    elif args.comando == 'mayor':
        cmd_mayor(args, supabase, generador, empresa)
    elif args.comando == 'cuentas':
        cmd_cuentas(args, supabase, generador, empresa)
    elif args.comando == 'resumen':
        cmd_resumen(args, supabase, generador, empresa)


if __name__ == '__main__':
    main()
