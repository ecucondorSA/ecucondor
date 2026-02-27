#!/usr/bin/env python3
"""
ECUCONDOR SAS - Script de Importación de Extracto Bancario
Período: Enero - Noviembre 2025
Fuente: Produbanco - Estado de Cuenta

Conforme a NIIF 15 - Reconocimiento de Ingresos por Intermediación
"""

import os
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Cargar variables de entorno
from dotenv import dotenv_values
ENV_FILE = Path(__file__).parent.parent / ".env"
env_values = dotenv_values(ENV_FILE)
for key, value in env_values.items():
    if value is not None:
        os.environ[key] = value

import pandas as pd
from supabase import create_client

from src.config.settings import get_settings
get_settings.cache_clear()


def parsear_fecha_2025(fecha_str) -> Optional[datetime]:
    """
    Parsea fecha en formato del nuevo extracto: "01/01/2025 11:50:00 AM"
    """
    if pd.isna(fecha_str):
        return None

    fecha_str = str(fecha_str).strip()

    # Formato: MM/DD/YYYY HH:MM:SS AM/PM
    formatos = [
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(fecha_str, fmt)
        except ValueError:
            continue

    return None


def parsear_monto(valor) -> Decimal:
    """
    Parsea monto numérico a Decimal.
    """
    if pd.isna(valor):
        return Decimal("0")

    try:
        return abs(Decimal(str(valor).replace(',', '')))
    except Exception:
        return Decimal("0")


def generar_hash(banco: str, cuenta: str, fecha: datetime, monto: Decimal,
                 tipo: str, referencia: str) -> str:
    """
    Genera hash único SHA-256 truncado para deduplicación.
    """
    datos = f"{banco}|{cuenta}|{fecha.isoformat() if fecha else ''}|{monto}|{tipo}|{referencia}"
    return hashlib.sha256(datos.encode()).hexdigest()[:32]


def main():
    """Proceso principal de importación."""

    print("=" * 80)
    print("         ECUCONDOR SAS - IMPORTACIÓN DE EXTRACTO BANCARIO")
    print("                   ENERO - NOVIEMBRE 2025")
    print("=" * 80)
    print()

    # Configuración
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    # Archivo fuente
    archivo = Path('/home/edu/Documentos/XXXXXX70809_11262025258.xlsx')

    if not archivo.exists():
        print(f"ERROR: Archivo no encontrado: {archivo}")
        return 1

    print(f"Archivo: {archivo.name}")
    print(f"Cuenta: 27059070809 (Produbanco, Corriente)")
    print()

    # Leer Excel - encontrar la fila de encabezados
    print("Leyendo archivo Excel...")
    df_raw = pd.read_excel(archivo, header=None)

    # Buscar la fila con FECHA
    header_row = None
    for i, row in df_raw.iterrows():
        if 'FECHA' in str(row.values):
            header_row = i
            break

    if header_row is None:
        print("ERROR: No se encontró la fila de encabezados")
        return 1

    # Cargar datos desde la fila correcta
    df = pd.read_excel(archivo, skiprows=header_row+1, header=None)
    df.columns = ['FECHA', 'REFERENCIA', 'DESCRIPCION', 'SIGNO', 'VALOR',
                  'SALDO_CONTABLE', 'SALDO_DISPONIBLE', 'OFICINA']

    # Limpiar filas vacías
    df = df.dropna(subset=['FECHA'])
    df = df[df['FECHA'].astype(str).str.contains('2025', na=False)]

    print(f"Transacciones encontradas: {len(df)}")
    print()

    # Estadísticas
    stats = {
        'total': 0,
        'creditos': 0,
        'debitos': 0,
        'monto_creditos': Decimal("0"),
        'monto_debitos': Decimal("0"),
        'insertadas': 0,
        'duplicadas': 0,
        'errores': 0
    }

    # Obtener hashes existentes para deduplicación
    print("Verificando transacciones existentes...")
    try:
        existentes = supabase.table('transacciones_bancarias').select('hash_unico').execute()
        hashes_existentes = {r['hash_unico'] for r in existentes.data} if existentes.data else set()
    except Exception:
        hashes_existentes = set()

    print(f"Transacciones previas en BD: {len(hashes_existentes)}")
    print()

    # Procesar cada transacción
    print("-" * 80)
    print("PROCESANDO TRANSACCIONES")
    print("-" * 80)

    transacciones_a_insertar = []

    for idx, row in df.iterrows():
        stats['total'] += 1

        try:
            # Parsear datos
            fecha = parsear_fecha_2025(row['FECHA'])
            monto = parsear_monto(row['VALOR'])
            signo = str(row['SIGNO']).strip() if pd.notna(row['SIGNO']) else ''
            descripcion = str(row['DESCRIPCION']).strip() if pd.notna(row['DESCRIPCION']) else ''
            referencia = str(row['REFERENCIA']).strip() if pd.notna(row['REFERENCIA']) else ''

            # Determinar tipo contable
            if signo == '+':
                tipo_contable = 'credito'
                stats['creditos'] += 1
                stats['monto_creditos'] += monto
            else:
                tipo_contable = 'debito'
                stats['debitos'] += 1
                stats['monto_debitos'] += monto

            # Generar hash único
            hash_unico = generar_hash(
                'produbanco', '27059070809', fecha, monto, tipo_contable, referencia
            )

            # Verificar duplicado
            if hash_unico in hashes_existentes:
                stats['duplicadas'] += 1
                continue

            # Extraer información de contraparte de la referencia/descripción
            contraparte = None
            if 'Pago Freelancer' in referencia or 'Pago Freelancer' in descripcion:
                contraparte = 'FREELANCER'
            elif '-' in referencia:
                partes = referencia.split('-')
                if len(partes) > 1:
                    contraparte = partes[1].strip()

            # Preparar registro
            transaccion = {
                'hash_unico': hash_unico,
                'banco': 'produbanco',
                'cuenta_bancaria': '27059070809',
                'archivo_origen': archivo.name,
                'linea_origen': int(idx) + header_row + 2,
                'fecha': fecha.strftime('%Y-%m-%d') if fecha else None,
                'fecha_valor': fecha.strftime('%Y-%m-%d') if fecha else None,
                'tipo': tipo_contable,
                'monto': float(monto),
                'descripcion_original': descripcion,
                'referencia': referencia if referencia and referencia != 'nan' else None,
                'contraparte_nombre': contraparte,
                'contraparte_identificacion': None,
                'contraparte_cuenta': None,
                'estado': 'pendiente',
                'datos_originales': {
                    'signo': signo,
                    'saldo_contable': float(row['SALDO_CONTABLE']) if pd.notna(row['SALDO_CONTABLE']) else None,
                    'saldo_disponible': float(row['SALDO_DISPONIBLE']) if pd.notna(row['SALDO_DISPONIBLE']) else None,
                    'oficina': str(row['OFICINA']) if pd.notna(row['OFICINA']) else None,
                }
            }

            transacciones_a_insertar.append(transaccion)
            hashes_existentes.add(hash_unico)

        except Exception as e:
            stats['errores'] += 1
            print(f"  ERROR en línea {idx}: {e}")

    # Insertar en lote
    if transacciones_a_insertar:
        print()
        print(f"Insertando {len(transacciones_a_insertar)} transacciones...")

        try:
            # Insertar en lotes de 50
            for i in range(0, len(transacciones_a_insertar), 50):
                lote = transacciones_a_insertar[i:i+50]
                result = supabase.table('transacciones_bancarias').insert(lote).execute()
                stats['insertadas'] += len(lote)
                print(f"  Lote {i//50 + 1}: {len(lote)} transacciones insertadas")

        except Exception as e:
            print(f"ERROR en inserción: {e}")
            stats['errores'] += len(transacciones_a_insertar)

    # Resumen final
    print()
    print("=" * 80)
    print("                    RESUMEN DE IMPORTACIÓN")
    print("=" * 80)
    print()
    print(f"  Total procesadas:      {stats['total']:>8}")
    print(f"  Insertadas:            {stats['insertadas']:>8}")
    print(f"  Duplicadas (omitidas): {stats['duplicadas']:>8}")
    print(f"  Errores:               {stats['errores']:>8}")
    print()
    print("-" * 80)
    print("  ANÁLISIS POR TIPO DE OPERACIÓN")
    print("-" * 80)
    print()
    print(f"  CRÉDITOS (Fondos Recibidos)")
    print(f"    Operaciones:         {stats['creditos']:>8}")
    print(f"    Monto Total:      USD {stats['monto_creditos']:>12,.2f}")
    print()
    print(f"  DÉBITOS (Liquidaciones)")
    print(f"    Operaciones:         {stats['debitos']:>8}")
    print(f"    Monto Total:      USD {stats['monto_debitos']:>12,.2f}")
    print()
    print("-" * 80)
    print("  PROYECCIÓN CONTABLE (Modelo Comisionista 1.5%)")
    print("-" * 80)
    print()

    comision = (stats['monto_creditos'] * Decimal("0.015")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    pasivo = stats['monto_creditos'] - comision
    variacion_neta = stats['monto_creditos'] - stats['monto_debitos']

    print(f"  Ingresos por Comisión (1.5%):     USD {comision:>12,.2f}")
    print(f"  Pasivo Fondos de Terceros:        USD {pasivo:>12,.2f}")
    print(f"  Variación Neta del Período:       USD {variacion_neta:>12,.2f}")
    print()
    print("=" * 80)
    print("  IMPORTACIÓN COMPLETADA EXITOSAMENTE")
    print("=" * 80)
    print()
    print("  Próximos pasos:")
    print("    1. Revisar transacciones en Supabase Dashboard")
    print("    2. Ejecutar: python scripts/generar_asientos_2025.py")
    print("    3. Emitir Balance de Comprobación")
    print()

    return 0 if stats['errores'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
