#!/usr/bin/env python3
"""
ECUCONDOR - Generador de Datos de Prueba UAFE
Inserta transacciones bancarias sintéticas para probar los umbrales RESU y ROII.
"""

import os
import sys
from datetime import date, timedelta
from typing import Dict, List
from uuid import uuid4

# Cargar entorno y dependencias
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

from src.config.settings import get_settings


def generar_datos_prueba():
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)

    print("--- INICIANDO GENERACIÓN DE DATOS UAFE ---")
    
    # 1. Crear un cliente ficticio que superará el umbral RESU (> $10k en un mes)
    cliente_resu_id = "0999999999001"
    cliente_resu_nombre = "CLIENTE PRUEBA RESU S.A."
    
    # 2. Crear un cliente ficticio que detonará alerta ROII (Monto inusual > $50k)
    cliente_roii_monto_id = "0999999999002"
    cliente_roii_monto_nombre = "CLIENTE PRUEBA ROII MONTO"
    
    # 3. Crear un cliente ficticio que detonará alerta ROII (Frecuencia > 5 por día)
    cliente_roii_freq_id = "0999999999003"
    cliente_roii_freq_nombre = "CLIENTE PRUEBA ROII FREC"

    # Preparar el mes actual para las transacciones
    hoy = date.today()
    primer_dia_mes = hoy.replace(day=1)

    transacciones_a_insertar = []

    # Generar transacciones para RESU (3 transacciones que suman $12k)
    for i in range(3):
        fecha = primer_dia_mes + timedelta(days=i)
        transacciones_a_insertar.append({
            "id": str(uuid4()),
            "banco": "PRODUBANCO",
            "cuenta_origen": "XXX-RESU",
            "tipo": "credito",
            "monto": 4000.00,
            "referencia": f"PRUEBA-RESU-{i}",
            "descripcion": "Abono factura prueba",
            "fecha": fecha.isoformat(),
            "estado": "conciliado",
            "contraparte_identificacion": cliente_resu_id,
            "contraparte_nombre": cliente_resu_nombre
        })

    # Generar transacción para ROII Monto (1 transacción de $60k)
    transacciones_a_insertar.append({
        "id": str(uuid4()),
        "banco": "PRODUBANCO",
        "cuenta_origen": "XXX-ROII-M",
        "tipo": "credito",
        "monto": 60000.00,
        "referencia": "PRUEBA-ROII-MONTO",
        "descripcion": "Abono extraordinario",
        "fecha": hoy.isoformat(),
        "estado": "conciliado",
        "contraparte_identificacion": cliente_roii_monto_id,
        "contraparte_nombre": cliente_roii_monto_nombre
    })

    # Generar transacciones para ROII Frecuencia (6 transacciones el mismo día)
    for i in range(6):
        transacciones_a_insertar.append({
            "id": str(uuid4()),
            "banco": "PRODUBANCO",
            "cuenta_origen": "XXX-ROII-F",
            "tipo": "credito",
            "monto": 100.00,
            "referencia": f"PRUEBA-ROII-FREQ-{i}",
            "descripcion": "Abono fraccionado",
            "fecha": hoy.isoformat(),
            "estado": "conciliado",
            "contraparte_identificacion": cliente_roii_freq_id,
            "contraparte_nombre": cliente_roii_freq_nombre
        })

    # Insertar en base de datos
    print(f"\nInsertando {len(transacciones_a_insertar)} transacciones...")
    
    # Importar el monitor y detector para simular el pipeline
    from src.uafe.detector import RoiiDetector
    from src.uafe.monitor import UafeMonitor
    
    monitor = UafeMonitor(supabase)
    detector = RoiiDetector(supabase)

    for i, tx in enumerate(transacciones_a_insertar):
        print(f"[{i+1}/{len(transacciones_a_insertar)}] Registrando {tx['referencia']} por ${tx['monto']:.2f}")
        
        # 1. Insertar en BD
        resp = supabase.table("transacciones_bancarias").insert(tx).execute()
        
        if resp.data:
            tx_registrada = resp.data[0]
            # 2. Evaluar RESU
            monitor.evaluar_transaccion(tx_registrada["id"])
            # 3. Evaluar ROII
            detector.evaluar_transaccion_roii(tx_registrada)

    print("\n--- GENERACIÓN COMPLETADA ---")
    print("Por favor verifica las tablas 'uafe_monitoreo_resu' y 'uafe_detecciones_roii'.")


if __name__ == "__main__":
    generar_datos_prueba()
