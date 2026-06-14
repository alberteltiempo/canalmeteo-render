#!/bin/bash
#
# Script wrapper para ejecutar download_fires.py con el venv correcto
# Uso: ./run_fires.sh
#

VENV_PATH="/opt/canalmeteo/venv"
SCRIPT_PATH="/opt/canalmeteo/scripts/download_fires.py"
ENV_FILE="/opt/canalmeteo/.env"

# Verificar que existen los archivos necesarios
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "❌ Error: No se encontró el virtualenv en $VENV_PATH"
    exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ Error: No se encontró el script en $SCRIPT_PATH"
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: No se encontró el archivo .env en $ENV_FILE"
    exit 1
fi

# Cargar variables de entorno
export $(cat $ENV_FILE | xargs)

# Ejecutar script con Python del venv
echo "Ejecutando descarga de incendios..."
$VENV_PATH/bin/python $SCRIPT_PATH

# Mostrar resultado
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Ejecución completada exitosamente"
    echo "Ver logs: tail -f /opt/canalmeteo/logs/fires.log"
else
    echo ""
    echo "❌ Error en la ejecución"
    echo "Ver logs: tail -f /opt/canalmeteo/logs/fires.log"
    exit 1
fi
