#!/bin/bash
# ECUCONDOR - ATS Mensual
# Genera el ATS del mes anterior y lo sube al SRI.
# Uso: click en el botón del escritorio, o ejecutar directamente.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROYECTO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROYECTO_DIR/.venv"
LOG_FILE="$PROYECTO_DIR/output/ats/ultimo_ats.log"

# Activar venv si existe
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi

# Crear directorio de output si no existe
mkdir -p "$PROYECTO_DIR/output/ats"

# Ejecutar con terminal visible para ver el progreso
echo "================================================"
echo "  ECUCONDOR - ATS Mensual Automático"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================"

cd "$PROYECTO_DIR"
python scripts/ats_mensual_auto.py "$@" 2>&1 | tee "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "RESULTADO: EXITOSO"
    notify-send -i dialog-information "ECUCONDOR ATS" "ATS del mes anterior generado y subido correctamente" 2>/dev/null
else
    echo "RESULTADO: ERROR (ver log arriba)"
    notify-send -i dialog-error "ECUCONDOR ATS" "Error al procesar el ATS. Revisar el log." 2>/dev/null
fi

echo ""
echo "Presiona ENTER para cerrar..."
read -r
