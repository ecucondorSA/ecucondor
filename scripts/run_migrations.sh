#!/bin/bash

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
