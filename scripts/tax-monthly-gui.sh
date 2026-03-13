#!/usr/bin/env bash
# ECUCONDOR - Lanzador GUI para Declaracion Tributaria Mensual
# Usa zenity para seleccionar opciones y ejecuta tax_monthly.py

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/.venv/bin/python"
TAX_SCRIPT="$SCRIPT_DIR/tax_monthly.py"

# Mes anterior por defecto
PREV_MONTH=$(date -d "last month" +%m | sed 's/^0//')
PREV_YEAR=$(date -d "last month" +%Y)

# 1. Elegir modo
MODE=$(zenity --list \
    --title="ECUCONDOR - Declaracion Mensual" \
    --text="Selecciona el modo de ejecucion:" \
    --column="Modo" --column="Descripcion" \
    --width=500 --height=320 \
    "dryrun"    "Dry-Run (solo calcular, NO envia al SRI)" \
    "full"      "Ejecutar TODO (IVA + ATS al SRI)" \
    "iva"       "Solo calcular IVA" \
    "ats"       "Solo generar ATS (XML+ZIP)" \
    "reconcile" "Solo reconciliar depositos" \
    2>/dev/null) || exit 0

# 2. Elegir periodo
PERIOD=$(zenity --forms \
    --title="Periodo Fiscal" \
    --text="Ingresa el periodo (default: mes anterior)" \
    --add-entry="Año (ej: $PREV_YEAR)" \
    --add-entry="Mes (1-12, ej: $PREV_MONTH)" \
    2>/dev/null) || exit 0

INPUT_YEAR=$(echo "$PERIOD" | cut -d'|' -f1)
INPUT_MONTH=$(echo "$PERIOD" | cut -d'|' -f2)

YEAR="${INPUT_YEAR:-$PREV_YEAR}"
MONTH="${INPUT_MONTH:-$PREV_MONTH}"

# Validar
if [[ "$MONTH" -lt 1 || "$MONTH" -gt 12 ]] 2>/dev/null; then
    zenity --error --text="Mes invalido: $MONTH (debe ser 1-12)" 2>/dev/null
    exit 1
fi

# 3. Construir argumentos
ARGS=("$YEAR" "$MONTH")
LABEL=""

case "$MODE" in
    dryrun)
        ARGS+=("--dry-run")
        LABEL="DRY-RUN"
        ;;
    full)
        LABEL="EJECUCION COMPLETA"
        ;;
    iva)
        ARGS+=("--step" "calculate_iva")
        LABEL="SOLO IVA"
        ;;
    ats)
        ARGS+=("--step" "generate_ats")
        LABEL="SOLO ATS"
        ;;
    reconcile)
        ARGS+=("--step" "reconcile")
        LABEL="RECONCILIAR"
        ;;
esac

# 4. Confirmar
zenity --question \
    --title="Confirmar" \
    --text="Ejecutar $LABEL para $MONTH/$YEAR?\n\nComando:\npython tax_monthly.py ${ARGS[*]}" \
    --width=400 \
    2>/dev/null || exit 0

# 5. Ejecutar
echo "========================================================"
echo "  ECUCONDOR - $LABEL - Periodo: $MONTH/$YEAR"
echo "========================================================"
echo ""

cd "$PROJECT_DIR"
"$PYTHON" "$TAX_SCRIPT" "${ARGS[@]}" 2>&1
EXIT_CODE=$?

echo ""
echo "========================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  COMPLETADO EXITOSAMENTE"
    notify-send -i dialog-information "ECUCONDOR" "$LABEL $MONTH/$YEAR completado" 2>/dev/null || true
else
    echo "  ERROR (codigo: $EXIT_CODE)"
    notify-send -i dialog-error "ECUCONDOR" "$LABEL $MONTH/$YEAR fallo (codigo $EXIT_CODE)" 2>/dev/null || true
fi
echo "========================================================"
echo ""
read -rp "Presiona Enter para cerrar..."
