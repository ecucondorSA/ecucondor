#!/usr/bin/env python3
"""
ECUCONDOR SAS - Script de Importación de Extracto Bancario
Período: Diciembre 2024
Fuente: Produbanco - Historial de Transferencias

Conforme a NIIF 15 - Reconocimiento de Ingresos por Intermediación
"""

import os
import sys
import hashlib
import re
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


def parsear_fecha(fecha_str: str) -> Optional[datetime]:
    """
    Parsea fecha en formato Produbanco: "31 dic. 2024 20:21:22"
    """
    if pd.isna(fecha_str) or not isinstance(fecha_str, str):
        return None

    # Mapeo de meses en español
    meses = {
        'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'ago': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12'
    }

    try:
        # Extraer componentes: "31 dic. 2024 20:21:22"
        match = re.match(r'(\d{1,2})\s+(\w+)\.?\s+(\d{4})\s+(\d{2}:\d{2}:\d{2})', fecha_str)
        if match:
            dia, mes_str, anio, hora = match.groups()
            mes = meses.get(mes_str.lower()[:3], '01')
            fecha_iso = f"{anio}-{mes}-{dia.zfill(2)} {hora}"
            return datetime.strptime(fecha_iso, "%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return None


def parsear_monto(monto_str: str) -> Decimal:
    """
    Parsea monto en formato Produbanco: "+$265.00" o "-$20.44"
    Retorna valor absoluto como Decimal.
    """
    if pd.isna(monto_str):
        return Decimal("0")

    # Remover símbolos y espacios
    monto_limpio = str(monto_str).replace('$', '').replace(',', '').replace('+', '').replace(' ', '')

    try:
        return abs(Decimal(monto_limpio))
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
    print("                        DICIEMBRE 2024")
    print("=" * 80)
    print()

    # Configuración
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    # Archivo fuente
    archivo = Path('/home/edu/Documentos/historial_transferencias_ DICIEMBRE 2024 (1).xlsm')

    if not archivo.exists():
        print(f"ERROR: Archivo no encontrado: {archivo}")
        return 1

    print(f"Archivo: {archivo.name}")
    print(f"Cuenta: 27059070809 (Produbanco, Corriente)")
    print()

    # Leer Excel con skiprows para omitir encabezados
    print("Leyendo archivo Excel...")
    df = pd.read_excel(archivo, sheet_name=0, skiprows=4)

    # Renombrar columnas
    df.columns = [
        'Fecha', 'Monto', 'Tipo', 'Ordenante', 'Beneficiario',
        'Cuenta_Beneficiario', 'Descripcion', 'Estado',
        'Nro_Comprobante', 'Cedula', 'Correo',
        'Extra1', 'Extra2', 'Extra3', 'Extra4'
    ]

    # Limpiar filas vacías y encabezados duplicados
    df = df.dropna(subset=['Fecha', 'Monto'])
    df = df[df['Fecha'] != 'Fecha']
    df = df[df['Monto'].notna()]

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
            fecha = parsear_fecha(str(row['Fecha']))
            monto = parsear_monto(row['Monto'])
            tipo_original = str(row['Tipo']).strip() if pd.notna(row['Tipo']) else ''

            # Determinar tipo contable
            if tipo_original == 'Recibida':
                tipo_contable = 'credito'
                stats['creditos'] += 1
                stats['monto_creditos'] += monto
                contraparte = str(row['Ordenante']).strip() if pd.notna(row['Ordenante']) else ''
            else:
                tipo_contable = 'debito'
                stats['debitos'] += 1
                stats['monto_debitos'] += monto
                contraparte = str(row['Beneficiario']).strip() if pd.notna(row['Beneficiario']) else ''

            # Referencia
            referencia = str(row['Nro_Comprobante']) if pd.notna(row['Nro_Comprobante']) else ''

            # Generar hash único
            hash_unico = generar_hash(
                'produbanco', '27059070809', fecha, monto, tipo_contable, referencia
            )

            # Verificar duplicado
            if hash_unico in hashes_existentes:
                stats['duplicadas'] += 1
                continue

            # Preparar registro
            transaccion = {
                'hash_unico': hash_unico,
                'banco': 'produbanco',
                'cuenta_bancaria': '27059070809',
                'archivo_origen': archivo.name,
                'linea_origen': int(idx) + 6,  # +6 por las filas omitidas
                'fecha': fecha.strftime('%Y-%m-%d') if fecha else None,
                'fecha_valor': fecha.strftime('%Y-%m-%d') if fecha else None,
                'tipo': tipo_contable,
                'monto': float(monto),
                'descripcion_original': str(row['Descripcion']).strip() if pd.notna(row['Descripcion']) else tipo_original,
                'referencia': referencia if referencia and referencia != 'nan' else None,
                'contraparte_nombre': contraparte if contraparte and contraparte != 'nan' else None,
                'contraparte_identificacion': str(int(float(row['Cedula']))) if pd.notna(row['Cedula']) and str(row['Cedula']) != 'nan' else None,
                'contraparte_cuenta': str(row['Cuenta_Beneficiario']).strip() if pd.notna(row['Cuenta_Beneficiario']) else None,
                'estado': 'pendiente',
                'datos_originales': {
                    'tipo_original': tipo_original,
                    'estado_banco': str(row['Estado']) if pd.notna(row['Estado']) else None,
                    'correo': str(row['Correo']) if pd.notna(row['Correo']) else None,
                }
            }

            transacciones_a_insertar.append(transaccion)
            hashes_existentes.add(hash_unico)  # Evitar duplicados en el mismo lote

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
    print("    2. Ejecutar split de comisión")
    print("    3. Generar asientos contables")
    print("    4. Emitir Balance de Comprobación")
    print()

    return 0 if stats['errores'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
