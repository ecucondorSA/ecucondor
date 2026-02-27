#!/bin/bash

# =====================================================
# ECUCONDOR - Aplicar TODAS las Migraciones a Supabase
# =====================================================
# Este script aplica las 7 migraciones SQL en orden

set -e  # Salir ante cualquier error

echo "🚀 ECUCONDOR - Aplicando Migraciones a Supabase"
echo "================================================"

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
    echo ""
    echo "Debes configurar DATABASE_URL con tu conexión de Supabase:"
    echo "DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres"
    echo ""
    echo "Obtén estos datos desde:"
    echo "1. Ve a tu proyecto en https://supabase.com/dashboard"
    echo "2. Settings → Database → Connection string → URI"
    exit 1
fi

echo "✅ Conectando a Supabase..."
echo ""

# Lista de migraciones en orden
MIGRATIONS=(
    "001_initial_schema.sql"
    "002_chart_of_accounts.sql"
    "003_sri_invoices.sql"
    "004_bank_transactions.sql"
    "005_ledger_journal.sql"
    "006_honorarios.sql"
    "007_uafe_compliance.sql"
)

# Contador
TOTAL=${#MIGRATIONS[@]}
SUCCESS=0
FAILED=0

# Ejecutar cada migración
for i in "${!MIGRATIONS[@]}"; do
    NUM=$((i + 1))
    MIGRATION="${MIGRATIONS[$i]}"
    FILEPATH="supabase/migrations/$MIGRATION"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "[$NUM/$TOTAL] Aplicando: $MIGRATION"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [ ! -f "$FILEPATH" ]; then
        echo "   ⚠️  Archivo no encontrado: $FILEPATH"
        FAILED=$((FAILED + 1))
        continue
    fi
    
    # Ejecutar migración
    if psql "$DATABASE_URL" -f "$FILEPATH" > "/tmp/migration_$(printf "%03d" $NUM).log" 2>&1; then
        echo "   ✅ Migración aplicada exitosamente"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "   ❌ Error al aplicar migración"
        echo "   Ver detalles en: /tmp/migration_$(printf "%03d" $NUM).log"
        cat "/tmp/migration_$(printf "%03d" $NUM).log"
        FAILED=$((FAILED + 1))
        
        # Preguntar si continuar
        read -p "   ¿Continuar con las siguientes migraciones? (s/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Ss]$ ]]; then
            echo ""
            echo "⚠️  Proceso cancelado por el usuario"
            exit 1
        fi
    fi
    echo ""
done

# Resumen final
echo "================================================"
echo "📊 RESUMEN DE MIGRACIONES"
echo "================================================"
echo ""
echo "✅ Exitosas: $SUCCESS/$TOTAL"
if [ $FAILED -gt 0 ]; then
    echo "❌ Fallidas:  $FAILED/$TOTAL"
fi
echo ""

if [ $SUCCESS -eq $TOTAL ]; then
    echo "🎉 ¡Todas las migraciones se aplicaron correctamente!"
    echo ""
    echo "📋 Tablas creadas:"
    echo "   • company_info, establecimientos, puntos_emision"
    echo "   • clientes, secuenciales"
    echo "   • chart_of_accounts (plan contable)"
    echo "   • sri_invoices, sri_invoice_items"
    echo "   • bank_accounts, bank_transactions"
    echo "   • ledger_entries, ledger_journal"
    echo "   • honorarios_profesionales, honorarios_items"
    echo "   • uafe_resu, uafe_roii"
    echo ""
    echo "✨ Tu base de datos está lista para usar!"
else
    echo "⚠️  Algunas migraciones fallaron."
    echo "   Revisa los logs en /tmp/migration_*.log"
    exit 1
fi

