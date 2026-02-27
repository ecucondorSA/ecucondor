#!/usr/bin/env python3
"""
Script para ejecutar migraciones pendientes.

Uso:
    python scripts/run_migrations.py

O con credenciales específicas:
    DATABASE_URL="postgresql://..." python scripts/run_migrations.py
"""

import os
import sys
from pathlib import Path

# Agregar el directorio raíz al path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")

# Migraciones a ejecutar (en orden)
MIGRATIONS = [
    "009_transacciones_iva.sql",
    "010_auto_contabilizar_bancarios.sql",
    "011_credito_tributario.sql",
    "012_calendario_tributario.sql",
    "013_tablas_retenciones.sql",
]


def get_db_connection():
    """Obtener conexión a la base de datos."""
    try:
        import psycopg2
    except ImportError:
        print("❌ psycopg2 no está instalado. Ejecute: pip install psycopg2-binary")
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if database_url and "<PASSWORD>" not in database_url:
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
        "Configure DATABASE_URL en .env o establezca DB_PASSWORD."
    )


def run_migration(cursor, migration_file: Path) -> bool:
    """Ejecutar una migración específica."""
    if not migration_file.exists():
        print(f"   ⚠️  No encontrado: {migration_file.name}")
        return False

    print(f"   📄 Ejecutando: {migration_file.name}")
    try:
        sql = migration_file.read_text()
        cursor.execute(sql)
        print(f"   ✅ {migration_file.name} - OK")
        return True
    except Exception as e:
        print(f"   ❌ {migration_file.name} - Error: {e}")
        return False


def main():
    """Función principal."""
    migrations_dir = ROOT_DIR / "supabase/migrations"

    print("=" * 50)
    print("ECUCONDOR - Ejecutar Migraciones")
    print("=" * 50)

    try:
        print("\n🔌 Conectando a la base de datos...")
        conn = get_db_connection()
        cursor = conn.cursor()
        print("   ✅ Conexión establecida")

        print("\n🚀 Ejecutando migraciones...")
        success_count = 0
        for migration_name in MIGRATIONS:
            migration_file = migrations_dir / migration_name
            if run_migration(cursor, migration_file):
                success_count += 1

        conn.commit()
        print(f"\n📊 Resultado: {success_count}/{len(MIGRATIONS)} migraciones ejecutadas")

        # Verificar objetos creados
        print("\n🔍 Verificando objetos creados...")

        # Verificar columnas
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'transacciones_bancarias'
            AND column_name IN ('tipo_iva', 'base_imponible', 'valor_iva',
                               'genera_credito_tributario', 'asiento_id', 'contabilizada')
        """)
        cols = cursor.fetchall()
        print(f"   - Columnas IVA en transacciones: {len(cols)}")

        # Verificar tablas
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name IN ('resumen_iva_mensual', 'detalle_credito_tributario',
                                'cuentas_bancarias_mapeadas')
        """)
        tables = cursor.fetchall()
        print(f"   - Tablas nuevas: {len(tables)}")

        # Verificar funciones
        cursor.execute("""
            SELECT routine_name FROM information_schema.routines
            WHERE routine_name IN (
                'clasificar_transaccion_iva',
                'contabilizar_gasto_bancario',
                'contabilizar_gasto_bancario_con_iva',
                'generar_resumen_iva_mensual',
                'calcular_credito_facturas_recibidas',
                'calcular_credito_transacciones'
            )
        """)
        funcs = cursor.fetchall()
        print(f"   - Funciones creadas: {len(funcs)}")

        cursor.close()
        conn.close()
        print("\n✅ Migraciones completadas!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
