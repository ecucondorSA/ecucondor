#!/bin/bash

# ECUCONDOR - CLI Push Migrations
# Script para ejecutar migraciones usando Supabase CLI o psql

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║    ECUCONDOR - EJECUTOR DE MIGRACIONES VIA CLI             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Detectar qué herramienta usar
if command -v supabase &> /dev/null; then
    echo -e "${GREEN}✅ Supabase CLI detectado${NC}"
    USE_SUPABASE_CLI=true
else
    echo -e "${YELLOW}⚠️  Supabase CLI no detectado, usando psql${NC}"
    USE_SUPABASE_CLI=false
fi

if command -v psql &> /dev/null; then
    echo -e "${GREEN}✅ psql detectado${NC}"
else
    echo -e "${RED}❌ psql no detectado, necesario para ejecutar migraciones${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "OPCIONES DE EJECUCIÓN"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

if [ "$USE_SUPABASE_CLI" = true ]; then
    echo "Opción 1: Supabase CLI (Recomendado)"
    echo "  supabase db push"
    echo ""
fi

echo "Opción 2: psql directo (Manual)"
echo "  Requiere: PGPASSWORD variable de entorno"
echo ""

# Preguntar al usuario
read -p "¿Qué opción deseas usar? (1/2): " choice

if [ "$choice" = "1" ] && [ "$USE_SUPABASE_CLI" = true ]; then
    # Usar Supabase CLI
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo "EJECUTANDO CON SUPABASE CLI"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    echo -e "${YELLOW}Verificando autenticación...${NC}"
    if ! supabase projects list &> /dev/null; then
        echo -e "${YELLOW}No estás autenticado. Por favor, ejecuta:${NC}"
        echo "  supabase login"
        echo ""
        echo "Después regresa y ejecuta este script nuevamente."
        exit 1
    fi

    echo -e "${GREEN}✅ Autenticación verificada${NC}"
    echo ""

    echo -e "${YELLOW}Ejecutando migraciones...${NC}"
    cd "$(dirname "$0")/.."
    supabase db push

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✅ MIGRACIONES EJECUTADAS EXITOSAMENTE${NC}"
        echo ""
        echo "Las siguientes migraciones fueron aplicadas:"
        echo "  1. 005_ledger_journal.sql"
        echo "  2. 006_honorarios.sql"
        echo "  3. 007_uafe_compliance.sql"
    else
        echo ""
        echo -e "${RED}❌ ERROR DURANTE LA EJECUCIÓN${NC}"
        exit 1
    fi

else
    # Usar psql
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo "EJECUTANDO CON PSQL"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    # Solicitar credenciales
    read -sp "Ingresa contraseña PostgreSQL (Supabase): " DB_PASSWORD
    echo ""

    export PGPASSWORD="$DB_PASSWORD"

    DB_HOST="db.qfgieogzspihbglvpqs.supabase.co"
    DB_PORT="5432"
    DB_USER="postgres"
    DB_NAME="postgres"

    echo ""
    echo -e "${YELLOW}Conectando a: $DB_HOST${NC}"

    # Array de migraciones
    migrations=(
        "005_ledger_journal.sql"
        "006_honorarios.sql"
        "007_uafe_compliance.sql"
    )

    failed=0

    # Ejecutar cada migración
    for i in "${!migrations[@]}"; do
        migration="${migrations[$i]}"
        count=$((i+1))

        echo ""
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}Ejecutando ($count/3): $migration${NC}"
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        migration_path="supabase/migrations/$migration"

        if [ ! -f "$migration_path" ]; then
            echo -e "${RED}❌ Archivo no encontrado: $migration_path${NC}"
            failed=$((failed + 1))
            continue
        fi

        # Ejecutar migración
        if psql -h "$DB_HOST" \
                -p "$DB_PORT" \
                -U "$DB_USER" \
                -d "$DB_NAME" \
                -f "$migration_path" > /tmp/migration_$count.log 2>&1; then
            echo -e "${GREEN}✅ $migration ejecutada exitosamente${NC}"
        else
            echo -e "${RED}❌ Error ejecutando $migration${NC}"
            echo "Detalles:"
            cat /tmp/migration_$count.log
            failed=$((failed + 1))
        fi
    done

    unset PGPASSWORD

    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo "RESUMEN"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    if [ $failed -eq 0 ]; then
        echo -e "${GREEN}✅ TODAS LAS MIGRACIONES SE EJECUTARON EXITOSAMENTE${NC}"
        echo ""
        echo "Se han creado:"
        echo "  • 13 tablas nuevas"
        echo "  • 7 vistas nuevas"
        echo "  • 7 funciones nuevas"
        echo ""
        echo "Sistema listo para:"
        echo "  1. Cargar datos 2024"
        echo "  2. Generar asientos contables"
        echo "  3. Registrar honorarios IESS"
        echo "  4. Generar reportes financieros"
    else
        echo -e "${RED}❌ $failed migración(es) fallaron${NC}"
        echo ""
        echo "Revisa los logs en /tmp/migration_*.log"
        exit 1
    fi
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo "PRÓXIMO PASO: VERIFICAR INTEGRIDAD"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "Para verificar que todo se creó correctamente, ejecuta:"
echo ""
echo "  psql -h db.qfgieogzspihbglvpqs.supabase.co \\\"
echo "       -U postgres -d postgres \\\"
echo "       -f scripts/verify_migrations.sql"
echo ""
