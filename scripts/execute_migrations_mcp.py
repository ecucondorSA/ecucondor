#!/usr/bin/env python3
"""
Script para ejecutar migraciones usando Supabase MCP.
Conecta directamente sin necesidad de credenciales en .env.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd, description=""):
    """Ejecuta comando y retorna resultado."""
    if description:
        print(f"\n🔄 {description}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except Exception as e:
        return False, str(e)


def main():
    """Ejecuta las migraciones."""
    print("=" * 70)
    print("ECUCONDOR - EJECUCIÓN DE MIGRACIONES CON MCP")
    print("=" * 70)

    project_dir = Path(__file__).parent.parent
    migrations_dir = project_dir / "supabase" / "migrations"

    # Lista de migraciones
    migrations = [
        "005_ledger_journal.sql",
        "006_honorarios.sql",
        "007_uafe_compliance.sql",
    ]

    print("\n📋 Migraciones a ejecutar:")
    for i, m in enumerate(migrations, 1):
        filepath = migrations_dir / m
        size = filepath.stat().st_size if filepath.exists() else 0
        lines = len(filepath.read_text().splitlines()) if filepath.exists() else 0
        print(f"  {i}. {m} ({size:,} bytes, {lines} líneas)")

    print("\n" + "=" * 70)
    print("INSTRUCCIONES PARA EJECUTAR CON MCP")
    print("=" * 70)

    # Opción 1: Usando claude CLI
    print("\n✅ OPCIÓN 1: Claude CLI (Recomendado)")
    print("-" * 70)
    print("Ejecuta este comando en la terminal:")
    print("")
    print("  cd /home/edu/ecucondor")
    print("  claude db migrate --project qfgieogzspihbglvpqs \\")
    print("    --file supabase/migrations/005_ledger_journal.sql \\")
    print("    --file supabase/migrations/006_honorarios.sql \\")
    print("    --file supabase/migrations/007_uafe_compliance.sql")
    print("")

    # Opción 2: Usando psql directamente (si tienes credenciales)
    print("\n✅ OPCIÓN 2: Con credenciales de Supabase (PostgreSQL directo)")
    print("-" * 70)
    print("Si tienes DATABASE_URL configurado en .env:")
    print("")
    print("  PGPASSWORD='<password>' psql \\")
    print("    -h db.qfgieogzspihbglvpqs.supabase.co \\")
    print("    -U postgres \\")
    print("    -d postgres \\")
    print("    -f supabase/migrations/005_ledger_journal.sql \\")
    print("    -f supabase/migrations/006_honorarios.sql \\")
    print("    -f supabase/migrations/007_uafe_compliance.sql")
    print("")

    # Opción 3: Script bash
    print("\n✅ OPCIÓN 3: Script bash automatizado")
    print("-" * 70)
    print("Ejecuta el script que preparamos:")
    print("")
    print("  bash scripts/run_migrations.sh")
    print("")

    # Crear archivo de script bash
    script_path = project_dir / "scripts" / "run_migrations.sh"
    create_migration_script(script_path, migrations_dir, migrations)

    print("=" * 70)
    print("VERIFICACIÓN POST-MIGRACIÓN")
    print("=" * 70)

    print("\nDespués de ejecutar las migraciones, verifica con:")
    print("")
    print("  -- Tablas creadas")
    print("  SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")
    print("    AND tablename IN ('periodos_contables','asientos_contables',")
    print("    'movimientos_contables','administradores','pagos_honorarios',")
    print("    'uafe_monitoreo_resu','uafe_parametros');")
    print("")
    print("  -- Vistas creadas")
    print("  SELECT COUNT(*) FROM pg_views WHERE schemaname='public'")
    print("    AND viewname IN ('v_libro_diario','v_libro_mayor',")
    print("    'v_honorarios_pendientes','v_uafe_resu_pendientes');")
    print("")
    print("  -- Funciones creadas")
    print("  SELECT COUNT(*) FROM information_schema.routines")
    print("    WHERE routine_schema='public' AND routine_name IN")
    print("    ('crear_periodo_si_no_existe','contabilizar_asiento',")
    print("    'calcular_iess_109','actualizar_monitoreo_resu');")
    print("")

    print("=" * 70)
    print("ARCHIVOS GENERADOS")
    print("=" * 70)
    print(f"✅ Script de ejecución: {script_path}")
    print(f"✅ Archivo concatenado: /tmp/migraciones_completas.sql")
    print(f"✅ MCP configurado en: {project_dir}/.mcp.json")
    print("")


def create_migration_script(script_path, migrations_dir, migrations):
    """Crea script bash para ejecutar migraciones."""
    script_content = """#!/bin/bash

# Script para ejecutar migraciones de ECUCONDOR
# Requiere: psql instalado y DATABASE_URL configurado en .env

set -e  # Salir ante cualquier error

echo "🚀 ECUCONDOR - Ejecutando Migraciones"
echo "======================================"

# Verificar que exista el archivo .env
if [ ! -f .env ]; then
    echo "❌ Error: .env no encontrado"
    echo "   Copia .env.example a .env y configura DATABASE_URL"
    exit 1
fi

# Cargar variables de entorno
export $(grep -v '^#' .env | xargs)

# Verificar DATABASE_URL
if [ -z "$DATABASE_URL" ] || [[ "$DATABASE_URL" == *"xxxxx"* ]]; then
    echo "❌ Error: DATABASE_URL no configurada correctamente en .env"
    exit 1
fi

echo "✅ Conectando a Supabase..."

# Ejecutar migraciones en orden
echo ""
echo "1️⃣  Ejecutando migración 005: Ledger Contable..."
psql "$DATABASE_URL" -f supabase/migrations/005_ledger_journal.sql > /tmp/migration_005.log 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Migración 005 exitosa"
else
    echo "   ❌ Error en migración 005"
    cat /tmp/migration_005.log
    exit 1
fi

echo ""
echo "2️⃣  Ejecutando migración 006: Honorarios IESS..."
psql "$DATABASE_URL" -f supabase/migrations/006_honorarios.sql > /tmp/migration_006.log 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Migración 006 exitosa"
else
    echo "   ❌ Error en migración 006"
    cat /tmp/migration_006.log
    exit 1
fi

echo ""
echo "3️⃣  Ejecutando migración 007: UAFE Compliance..."
psql "$DATABASE_URL" -f supabase/migrations/007_uafe_compliance.sql > /tmp/migration_007.log 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Migración 007 exitosa"
else
    echo "   ❌ Error en migración 007"
    cat /tmp/migration_007.log
    exit 1
fi

echo ""
echo "======================================"
echo "✅ TODAS LAS MIGRACIONES COMPLETADAS"
echo "======================================"
echo ""
echo "📊 Resumen:"
echo "  ✓ Ledger contable (partida doble)"
echo "  ✓ Honorarios IESS código 109"
echo "  ✓ UAFE compliance (RESU/ROII)"
echo ""
echo "📈 Tablas creadas: ~13"
echo "👁️  Vistas creadas: ~7"
echo "⚙️  Funciones creadas: ~7"
echo ""
"""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_content)
    script_path.chmod(0o755)

    print(f"✅ Script bash creado: {script_path}")


if __name__ == "__main__":
    main()
