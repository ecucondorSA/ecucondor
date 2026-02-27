#!/usr/bin/env python3
"""
Script para aplicar migraciones pendientes en Supabase.
"""

import asyncio
import os
import sys
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import get_settings
from src.db.supabase import get_supabase_client


async def ejecutar_sql_file(db, filepath: Path):
    """Ejecuta un archivo SQL."""
    print(f"\n{'='*60}")
    print(f"Ejecutando: {filepath.name}")
    print(f"{'='*60}")

    # Leer contenido
    with open(filepath, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # Conectar directamente con psycopg2 para ejecutar SQL DDL
    settings = get_settings()

    try:
        import psycopg2

        # Extraer componentes de DATABASE_URL
        # postgresql://postgres:password@db.xxxxx.supabase.co:5432/postgres
        db_url = settings.database_url

        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()

        # Ejecutar SQL
        cursor.execute(sql_content)

        cursor.close()
        conn.close()

        print(f"✅ Migración {filepath.name} aplicada exitosamente")
        return True

    except Exception as e:
        print(f"❌ Error en {filepath.name}:")
        print(f"   {str(e)}")
        return False


async def main():
    """Aplica todas las migraciones pendientes."""
    print("\n🚀 ECUCONDOR - Aplicación de Migraciones")
    print("=" * 60)

    # Verificar credenciales
    settings = get_settings()
    if not settings.database_url or "xxxxx" in settings.database_url:
        print("\n❌ ERROR: DATABASE_URL no configurada")
        print("   Configura las credenciales en el archivo .env")
        return

    print(f"\nConectando a: {settings.supabase_url}")

    # Migraciones a ejecutar (en orden)
    migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"

    migrations = [
        "005_ledger_journal.sql",
        "006_honorarios.sql",
        "007_uafe_compliance.sql",
    ]

    print(f"\nMigraciones a aplicar: {len(migrations)}")
    for m in migrations:
        print(f"  - {m}")

    input("\n¿Continuar? [Enter para sí, Ctrl+C para cancelar] ")

    # Ejecutar cada migración
    resultados = []
    for migration in migrations:
        filepath = migrations_dir / migration

        if not filepath.exists():
            print(f"\n⚠️  Archivo no encontrado: {migration}")
            resultados.append(False)
            continue

        exito = await ejecutar_sql_file(None, filepath)
        resultados.append(exito)

    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DE MIGRACIONES")
    print("=" * 60)

    exitosas = sum(resultados)
    fallidas = len(resultados) - exitosas

    print(f"\n✅ Exitosas: {exitosas}/{len(migrations)}")
    if fallidas > 0:
        print(f"❌ Fallidas:  {fallidas}/{len(migrations)}")

    if all(resultados):
        print("\n🎉 Todas las migraciones se aplicaron correctamente!")
    else:
        print("\n⚠️  Algunas migraciones fallaron. Revisa los errores arriba.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelado por el usuario")
        sys.exit(1)
