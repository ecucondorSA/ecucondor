#!/usr/bin/env python3
"""
ECUCONDOR SAS - Generación de Asientos Contables
Período: Diciembre 2024
Conforme a NIIF 15 - Modelo de Agente/Intermediario

Tratamiento Contable:
- Créditos (fondos recibidos): Se reconoce 1.5% como ingreso por comisión
- Débitos (liquidaciones): Reduce el pasivo de fondos de terceros
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar variables de entorno
from dotenv import dotenv_values
ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

from supabase import create_client
from src.config.settings import get_settings
get_settings.cache_clear()

# Cuentas contables según plan de cuentas ECUCONDOR
CUENTA_BANCO_PRODUBANCO = "1.1.1.07"
CUENTA_INGRESO_COMISION = "4.1.1.01"
CUENTA_FONDOS_TERCEROS = "2.1.5.01"

# Porcentaje de comisión (modelo NIIF 15 - Agente)
PORCENTAJE_COMISION = Decimal("0.015")  # 1.5%


def main():
    """Genera asientos contables para las transacciones de Diciembre 2024."""

    print("=" * 80)
    print("     ECUCONDOR SAS - GENERACIÓN DE ASIENTOS CONTABLES")
    print("                    DICIEMBRE 2024")
    print("     Conforme a NIIF 15 - Modelo de Intermediación")
    print("=" * 80)
    print()

    # Configuración
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    # Obtener período contable Diciembre 2024
    print("Verificando período contable...")
    periodo = supabase.table('periodos_contables').select('id').eq(
        'anio', 2024
    ).eq('mes', 12).execute()

    if not periodo.data:
        print("Creando período contable Diciembre 2024...")
        periodo_data = {
            'anio': 2024,
            'mes': 12,
            'nombre': 'Diciembre 2024',
            'fecha_inicio': '2024-12-01',
            'fecha_fin': '2024-12-31',
            'estado': 'abierto'
        }
        periodo = supabase.table('periodos_contables').insert(periodo_data).execute()

    periodo_id = periodo.data[0]['id']
    print(f"Período fiscal ID: {periodo_id}")
    print()

    # Obtener transacciones de Diciembre 2024 pendientes de contabilizar
    print("Obteniendo transacciones pendientes...")
    transacciones = supabase.table('transacciones_bancarias').select('*').eq(
        'estado', 'pendiente'
    ).gte('fecha', '2024-12-01').lte('fecha', '2024-12-31').execute()

    if not transacciones.data:
        print("No hay transacciones pendientes de contabilizar.")
        return 0

    print(f"Transacciones pendientes: {len(transacciones.data)}")
    print()

    # Estadísticas
    stats = {
        'asientos_creados': 0,
        'creditos_procesados': 0,
        'debitos_procesados': 0,
        'monto_creditos': Decimal("0"),
        'monto_debitos': Decimal("0"),
        'comision_total': Decimal("0"),
        'pasivo_total': Decimal("0"),
        'errores': 0
    }

    print("-" * 80)
    print("PROCESANDO TRANSACCIONES")
    print("-" * 80)

    for tx in transacciones.data:
        try:
            tx_id = tx['id']
            fecha = tx['fecha']
            tipo = tx['tipo']
            monto = Decimal(str(tx['monto']))
            descripcion = tx.get('descripcion_original', '') or ''
            contraparte = tx.get('contraparte_nombre', '') or 'Sin identificar'
            referencia = tx.get('referencia', '') or ''

            if tipo == 'credito':
                # Recepción de fondos - Aplicar split de comisión
                comision = (monto * PORCENTAJE_COMISION).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                pasivo = monto - comision

                concepto = f"Recepción fondos intermediación - {contraparte[:50]}"

                # Crear asiento con 3 movimientos
                asiento_id = str(uuid4())
                numero_asiento = stats['asientos_creados'] + 1
                asiento = {
                    'id': asiento_id,
                    'numero_asiento': numero_asiento,
                    'fecha': fecha,
                    'concepto': concepto,
                    'tipo': 'automatico',
                    'estado': 'borrador',
                    'periodo_id': periodo_id,
                    'referencia': referencia if referencia else None,
                    'origen_tipo': 'transaccion_bancaria',
                    'origen_id': tx_id,
                    'total_debe': float(monto),
                    'total_haber': float(monto),
                }

                # Insertar asiento
                supabase.table('asientos_contables').insert(asiento).execute()

                # Movimientos contables
                movimientos = [
                    {
                        'asiento_id': asiento_id,
                        'cuenta_codigo': CUENTA_BANCO_PRODUBANCO,
                        'concepto': f"Depósito {contraparte[:40]}",
                        'debe': float(monto),
                        'haber': 0.0,
                        'orden': 1
                    },
                    {
                        'asiento_id': asiento_id,
                        'cuenta_codigo': CUENTA_INGRESO_COMISION,
                        'concepto': f"Comisión 1.5% intermediación",
                        'debe': 0.0,
                        'haber': float(comision),
                        'orden': 2
                    },
                    {
                        'asiento_id': asiento_id,
                        'cuenta_codigo': CUENTA_FONDOS_TERCEROS,
                        'concepto': f"Fondos por liquidar - {contraparte[:30]}",
                        'debe': 0.0,
                        'haber': float(pasivo),
                        'orden': 3
                    }
                ]

                for mov in movimientos:
                    supabase.table('movimientos_contables').insert(mov).execute()

                stats['creditos_procesados'] += 1
                stats['monto_creditos'] += monto
                stats['comision_total'] += comision
                stats['pasivo_total'] += pasivo

            else:
                # Débito - Liquidación de fondos
                concepto = f"Liquidación fondos - {contraparte[:50]}"

                asiento_id = str(uuid4())
                numero_asiento = stats['asientos_creados'] + 1
                asiento = {
                    'id': asiento_id,
                    'numero_asiento': numero_asiento,
                    'fecha': fecha,
                    'concepto': concepto,
                    'tipo': 'automatico',
                    'estado': 'borrador',
                    'periodo_id': periodo_id,
                    'referencia': referencia if referencia else None,
                    'origen_tipo': 'transaccion_bancaria',
                    'origen_id': tx_id,
                    'total_debe': float(monto),
                    'total_haber': float(monto),
                }

                supabase.table('asientos_contables').insert(asiento).execute()

                # Movimientos contables (liquidación reduce pasivo)
                movimientos = [
                    {
                        'asiento_id': asiento_id,
                        'cuenta_codigo': CUENTA_FONDOS_TERCEROS,
                        'concepto': f"Liquidación - {contraparte[:40]}",
                        'debe': float(monto),
                        'haber': 0.0,
                        'orden': 1
                    },
                    {
                        'asiento_id': asiento_id,
                        'cuenta_codigo': CUENTA_BANCO_PRODUBANCO,
                        'concepto': f"Transferencia {contraparte[:40]}",
                        'debe': 0.0,
                        'haber': float(monto),
                        'orden': 2
                    }
                ]

                for mov in movimientos:
                    supabase.table('movimientos_contables').insert(mov).execute()

                stats['debitos_procesados'] += 1
                stats['monto_debitos'] += monto

            # Actualizar transacción como conciliada
            supabase.table('transacciones_bancarias').update({
                'estado': 'conciliada',
                'asiento_id': asiento_id
            }).eq('id', tx_id).execute()

            stats['asientos_creados'] += 1

        except Exception as e:
            stats['errores'] += 1
            print(f"  ERROR en transacción {tx.get('id', 'N/A')}: {e}")

    # Resumen
    print()
    print("=" * 80)
    print("                    RESUMEN DE CONTABILIZACIÓN")
    print("=" * 80)
    print()
    print(f"  Asientos creados:          {stats['asientos_creados']:>8}")
    print(f"  Errores:                   {stats['errores']:>8}")
    print()
    print("-" * 80)
    print("  ANÁLISIS POR TIPO DE OPERACIÓN")
    print("-" * 80)
    print()
    print(f"  CRÉDITOS (Recepción de Fondos)")
    print(f"    Operaciones:             {stats['creditos_procesados']:>8}")
    print(f"    Monto Total:          USD {stats['monto_creditos']:>12,.2f}")
    print()
    print(f"  DÉBITOS (Liquidaciones)")
    print(f"    Operaciones:             {stats['debitos_procesados']:>8}")
    print(f"    Monto Total:          USD {stats['monto_debitos']:>12,.2f}")
    print()
    print("-" * 80)
    print("  RECONOCIMIENTO DE INGRESOS (NIIF 15)")
    print("-" * 80)
    print()
    print(f"  Ingresos por Comisión (1.5%):     USD {stats['comision_total']:>12,.2f}")
    print(f"  Pasivo Fondos de Terceros:        USD {stats['pasivo_total']:>12,.2f}")
    print()
    print("-" * 80)
    print("  MOVIMIENTO NETO DEL PERÍODO")
    print("-" * 80)
    print()

    variacion_banco = stats['monto_creditos'] - stats['monto_debitos']
    variacion_pasivo = stats['pasivo_total'] - stats['monto_debitos']

    print(f"  Variación Bancos:                 USD {variacion_banco:>12,.2f}")
    print(f"  Variación Pasivo F. Terceros:     USD {variacion_pasivo:>12,.2f}")
    print(f"  Ingresos Reconocidos:             USD {stats['comision_total']:>12,.2f}")
    print()
    print("=" * 80)
    print("  CONTABILIZACIÓN COMPLETADA")
    print("=" * 80)
    print()
    print("  Los asientos se encuentran en estado 'borrador'.")
    print("  Revisar y aprobar en el módulo de contabilidad.")
    print()

    return 0 if stats['errores'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
