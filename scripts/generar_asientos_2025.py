#!/usr/bin/env python3
"""
ECUCONDOR SAS - Generación de Asientos Contables
Período: Enero - Noviembre 2025
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

MESES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
    5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
    9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}


def obtener_o_crear_periodo(supabase, anio: int, mes: int):
    """Obtiene o crea el período contable para el mes especificado."""
    periodo = supabase.table('periodos_contables').select('id').eq(
        'anio', anio
    ).eq('mes', mes).execute()

    if periodo.data:
        return periodo.data[0]['id']

    # Crear período
    from calendar import monthrange
    ultimo_dia = monthrange(anio, mes)[1]

    periodo_data = {
        'anio': anio,
        'mes': mes,
        'nombre': f'{MESES[mes]} {anio}',
        'fecha_inicio': f'{anio}-{mes:02d}-01',
        'fecha_fin': f'{anio}-{mes:02d}-{ultimo_dia}',
        'estado': 'abierto'
    }
    resultado = supabase.table('periodos_contables').insert(periodo_data).execute()
    return resultado.data[0]['id']


def main():
    """Genera asientos contables para las transacciones de 2025."""

    print("=" * 80)
    print("     ECUCONDOR SAS - GENERACIÓN DE ASIENTOS CONTABLES")
    print("                   ENERO - DICIEMBRE 2025")
    print("     Conforme a NIIF 15 - Modelo de Intermediación")
    print("=" * 80)
    print()

    # Configuración
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    # Obtener transacciones de 2025 pendientes de contabilizar
    print("Obteniendo transacciones pendientes...")
    transacciones = supabase.table('transacciones_bancarias').select('*').eq(
        'estado', 'pendiente'
    ).gte('fecha', '2025-01-01').lte('fecha', '2025-12-31').order('fecha').execute()

    if not transacciones.data:
        print("No hay transacciones pendientes de contabilizar.")
        return 0

    print(f"Transacciones pendientes: {len(transacciones.data)}")
    print()

    # Crear períodos contables para 2025
    print("Creando períodos contables 2025...")
    periodos_cache = {}
    for mes in range(1, 13):  # Enero a Diciembre
        periodo_id = obtener_o_crear_periodo(supabase, 2025, mes)
        periodos_cache[(2025, mes)] = periodo_id
    print(f"  {len(periodos_cache)} períodos configurados")
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

    # Contador global de asientos
    ultimo_asiento = supabase.table('asientos_contables').select('numero_asiento').order(
        'numero_asiento', desc=True
    ).limit(1).execute()
    numero_asiento_base = ultimo_asiento.data[0]['numero_asiento'] if ultimo_asiento.data else 0

    print("-" * 80)
    print("PROCESANDO TRANSACCIONES")
    print("-" * 80)

    lote_asientos = []
    lote_movimientos = []
    actualizaciones = []

    for i, tx in enumerate(transacciones.data):
        try:
            tx_id = tx['id']
            fecha = tx['fecha']
            tipo = tx['tipo']
            monto = Decimal(str(tx['monto']))
            descripcion = tx.get('descripcion_original', '') or ''
            contraparte = tx.get('contraparte_nombre', '') or 'Sin identificar'
            referencia = tx.get('referencia', '') or ''

            # Obtener mes de la transacción para asignar período
            fecha_dt = datetime.strptime(fecha, '%Y-%m-%d')
            periodo_id = periodos_cache.get((fecha_dt.year, fecha_dt.month))

            if not periodo_id:
                stats['errores'] += 1
                continue

            asiento_id = str(uuid4())
            numero_asiento = numero_asiento_base + stats['asientos_creados'] + 1

            if tipo == 'credito':
                # Recepción de fondos - Aplicar split de comisión
                comision = (monto * PORCENTAJE_COMISION).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                pasivo = monto - comision

                concepto = f"Recepción fondos intermediación - {contraparte[:50]}"

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
                lote_asientos.append(asiento)

                # Movimientos contables
                lote_movimientos.extend([
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
                ])

                stats['creditos_procesados'] += 1
                stats['monto_creditos'] += monto
                stats['comision_total'] += comision
                stats['pasivo_total'] += pasivo

            else:
                # Débito - Liquidación de fondos
                concepto = f"Liquidación fondos - {contraparte[:50]}"

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
                lote_asientos.append(asiento)

                lote_movimientos.extend([
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
                ])

                stats['debitos_procesados'] += 1
                stats['monto_debitos'] += monto

            actualizaciones.append({'id': tx_id, 'asiento_id': asiento_id})
            stats['asientos_creados'] += 1

            # Insertar en lotes de 100
            if len(lote_asientos) >= 100:
                print(f"  Insertando lote de {len(lote_asientos)} asientos...")
                supabase.table('asientos_contables').insert(lote_asientos).execute()
                supabase.table('movimientos_contables').insert(lote_movimientos).execute()

                for upd in actualizaciones:
                    supabase.table('transacciones_bancarias').update({
                        'estado': 'conciliada',
                        'asiento_id': upd['asiento_id']
                    }).eq('id', upd['id']).execute()

                lote_asientos = []
                lote_movimientos = []
                actualizaciones = []

        except Exception as e:
            stats['errores'] += 1
            print(f"  ERROR en transacción {tx.get('id', 'N/A')}: {e}")

    # Insertar último lote
    if lote_asientos:
        print(f"  Insertando lote final de {len(lote_asientos)} asientos...")
        supabase.table('asientos_contables').insert(lote_asientos).execute()
        supabase.table('movimientos_contables').insert(lote_movimientos).execute()

        for upd in actualizaciones:
            supabase.table('transacciones_bancarias').update({
                'estado': 'conciliada',
                'asiento_id': upd['asiento_id']
            }).eq('id', upd['id']).execute()

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

    return 0 if stats['errores'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
