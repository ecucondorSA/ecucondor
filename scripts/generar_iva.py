#!/usr/bin/env python3
"""
ECUCONDOR - Generador de Datos para Declaración IVA

Genera los datos necesarios para llenar el Formulario 2011 del SRI.

Uso:
    python scripts/generar_iva.py 2025 11
    python scripts/generar_iva.py 2025 11 --json
    python scripts/generar_iva.py 2025 --anual
"""

import os
import sys
import json
from pathlib import Path
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
from src.sri.iva.calculator import CalculadorIVA

# Limpiar cache
get_settings.cache_clear()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='ECUCONDOR - Generador de Datos para Declaración IVA',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
    python scripts/generar_iva.py 2025 11           # IVA Noviembre 2025
    python scripts/generar_iva.py 2025 11 --json    # Salida en JSON
    python scripts/generar_iva.py 2025 --anual      # Resumen anual
        """
    )

    parser.add_argument('anio', type=int, help='Año (ej: 2025)')
    parser.add_argument('mes', type=int, nargs='?', help='Mes (1-12)')
    parser.add_argument('--anual', action='store_true', help='Generar resumen anual')
    parser.add_argument('--json', action='store_true', help='Salida en formato JSON')
    parser.add_argument('--credito-anterior', type=float, default=0,
                       help='Crédito tributario del mes anterior')
    parser.add_argument('--output', '-o', help='Archivo de salida')

    args = parser.parse_args()

    if not args.anual and not args.mes:
        print("Error: Debe especificar el mes o usar --anual")
        sys.exit(1)

    if args.mes and not (1 <= args.mes <= 12):
        print(f"Error: Mes inválido ({args.mes}). Debe estar entre 1 y 12.")
        sys.exit(1)

    # Conectar a Supabase
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    calculador = CalculadorIVA(supabase)

    if args.anual:
        # Resumen anual
        print(f"\nGenerando resumen IVA anual {args.anio}...\n")

        resumen = calculador.generar_resumen_anual(
            anio=args.anio,
            ruc=settings.sri_ruc,
            razon_social=settings.sri_razon_social
        )

        if args.json:
            output = {
                "anio": args.anio,
                "meses": [datos.to_dict() for datos in resumen]
            }
            content = json.dumps(output, indent=2, ensure_ascii=False)
        else:
            lineas = [
                "=" * 90,
                f"RESUMEN ANUAL IVA {args.anio} - {settings.sri_razon_social}",
                f"RUC: {settings.sri_ruc}",
                "=" * 90,
                "",
                f"{'MES':<8} {'VENTAS':>12} {'IVA VENTAS':>12} {'COMPRAS':>12} {'IVA COMPRAS':>12} {'A PAGAR':>12}",
                "-" * 90,
            ]

            total_ventas = Decimal("0")
            total_iva_ventas = Decimal("0")
            total_compras = Decimal("0")
            total_iva_compras = Decimal("0")
            total_pagar = Decimal("0")

            meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

            for datos in resumen:
                mes_str = meses[datos.mes - 1]
                lineas.append(
                    f"{mes_str:<8} "
                    f"${datos.total_ventas_netas:>10,.2f} "
                    f"${datos.iva_ventas:>10,.2f} "
                    f"${datos.total_adquisiciones:>10,.2f} "
                    f"${datos.credito_tributario_mes:>10,.2f} "
                    f"${datos.iva_a_pagar:>10,.2f}"
                )
                total_ventas += datos.total_ventas_netas
                total_iva_ventas += datos.iva_ventas
                total_compras += datos.total_adquisiciones
                total_iva_compras += datos.credito_tributario_mes
                total_pagar += datos.iva_a_pagar

            lineas.extend([
                "-" * 90,
                f"{'TOTAL':<8} "
                f"${total_ventas:>10,.2f} "
                f"${total_iva_ventas:>10,.2f} "
                f"${total_compras:>10,.2f} "
                f"${total_iva_compras:>10,.2f} "
                f"${total_pagar:>10,.2f}",
                "=" * 90,
            ])

            content = "\n".join(lineas)

    else:
        # Mes específico
        print(f"\nGenerando datos IVA {args.mes:02d}/{args.anio}...\n")

        datos = calculador.calcular_periodo(
            anio=args.anio,
            mes=args.mes,
            ruc=settings.sri_ruc,
            razon_social=settings.sri_razon_social,
            credito_anterior=Decimal(str(args.credito_anterior))
        )

        if args.json:
            content = json.dumps(datos.to_dict(), indent=2, ensure_ascii=False)
        else:
            content = datos.to_text()

    # Mostrar o guardar
    print(content)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(content, encoding='utf-8')
        print(f"\nGuardado en: {output_path}")

    # Resumen adicional para declaración mensual
    if not args.anual and not args.json:
        print()
        print("-" * 70)
        print("INSTRUCCIONES PARA DECLARAR:")
        print("-" * 70)
        print("1. Ingresar a: https://srienlinea.sri.gob.ec")
        print("2. Ir a: DECLARACIONES > Declaración de IVA")
        print(f"3. Seleccionar período: {args.mes:02d}/{args.anio}")
        print("4. Completar casilleros con los valores indicados arriba")
        print("5. Validar y enviar")
        print()


if __name__ == '__main__':
    main()
