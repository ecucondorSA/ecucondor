#!/usr/bin/env python3
"""
Script para ejecutar la migración 010: Contabilización automática de gastos bancarios.

Uso:
    python scripts/run_migration_010.py

O con credenciales específicas:
    DATABASE_URL="postgresql://..." python scripts/run_migration_010.py
"""

import os
import sys
from pathlib import Path

# Agregar el directorio raíz al path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")


def get_db_connection():
    """Obtener conexión a la base de datos."""
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    # Fallback: construir URL desde variables individuales
    supabase_url = os.getenv("SUPABASE_URL", "")
    if "supabase.co" in supabase_url:
        # Extraer project ref de la URL
        project_ref = supabase_url.split("//")[1].split(".")[0]
        password = os.getenv("DB_PASSWORD", "")

        if password:
            return psycopg2.connect(
                host=f"db.{project_ref}.supabase.co",
                port=5432,
                database="postgres",
                user="postgres",
                password=password,
            )

    raise ValueError(
        "No se encontró DATABASE_URL ni credenciales válidas.\n"
        "Configure DATABASE_URL en .env o pase como variable de entorno."
    )


def run_migration():
    """Ejecutar la migración 010."""
    migration_file = ROOT_DIR / "supabase/migrations/010_auto_contabilizar_bancarios.sql"

    if not migration_file.exists():
        print(f"❌ No se encontró el archivo de migración: {migration_file}")
        sys.exit(1)

    print(f"📄 Leyendo migración: {migration_file.name}")
    sql = migration_file.read_text()

    try:
        print("🔌 Conectando a la base de datos...")
        conn = get_db_connection()
        cursor = conn.cursor()

        print("🚀 Ejecutando migración...")
        cursor.execute(sql)
        conn.commit()

        print("✅ Migración 010 ejecutada exitosamente!")

        # Verificar que se crearon los objetos
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'transacciones_bancarias'
            AND column_name IN ('asiento_id', 'contabilizada', 'fecha_contabilizacion')
        """)
        cols = cursor.fetchone()[0]
        print(f"   - Columnas nuevas en transacciones_bancarias: {cols}/3")

        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.routines
            WHERE routine_name IN (
                'contabilizar_gasto_bancario',
                'contabilizar_gasto_bancario_con_iva',
                'contabilizar_transacciones_pendientes'
            )
        """)
        funcs = cursor.fetchone()[0]
        print(f"   - Funciones creadas: {funcs}/3")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error ejecutando migración: {e}")
        sys.exit(1)


def contabilizar_pendientes():
    """Contabilizar las transacciones bancarias pendientes."""
    try:
        print("\n📊 Contabilizando transacciones pendientes...")
        conn = get_db_connection()
        cursor = conn.cursor()

        # Ejecutar la función de contabilización en lote
        cursor.execute("""
            SELECT * FROM contabilizar_transacciones_pendientes('gasto_bancario%')
        """)

        results = cursor.fetchall()
        ok_count = sum(1 for r in results if r[2] == 'OK')
        error_count = len(results) - ok_count

        print(f"✅ Contabilizadas: {ok_count}")
        if error_count > 0:
            print(f"⚠️  Con errores: {error_count}")

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error contabilizando: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ejecutar migración 010")
    parser.add_argument(
        "--contabilizar",
        action="store_true",
        help="También contabilizar transacciones pendientes después de la migración",
    )
    args = parser.parse_args()

    run_migration()

    if args.contabilizar:
        contabilizar_pendientes()
