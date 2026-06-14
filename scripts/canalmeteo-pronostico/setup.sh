#!/bin/bash
# ============================================================
# Canal Meteo TV - Instalación del sistema de pronóstico por estado
# Ejecutar en el servidor de producción
# ============================================================

set -e

echo "============================================"
echo "Canal Meteo TV - Setup Pronóstico por Estado"
echo "============================================"

# Directorio base
BASE_DIR="/opt/canalmeteo"
SCRIPTS_DIR="$BASE_DIR/scripts/pronostico_estados"
VENV_DIR="$BASE_DIR/venv"
CACHE_DIR="$BASE_DIR/cache/pronostico_estados"
WEB_DIR="/var/www/canalmeteo/pronostico"
LOG_DIR="/var/log/canalmeteo"

# Crear directorios
echo "Creando directorios..."
mkdir -p "$SCRIPTS_DIR"
mkdir -p "$CACHE_DIR"
mkdir -p "$WEB_DIR"
mkdir -p "$LOG_DIR"

# Copiar scripts
echo "Copiando scripts..."
cp scripts/states_config.py "$SCRIPTS_DIR/"
cp scripts/generate_forecasts.py "$SCRIPTS_DIR/"
chmod +x "$SCRIPTS_DIR/generate_forecasts.py"

# Instalar dependencias en el venv existente
echo "Instalando dependencias..."
$VENV_DIR/bin/pip install requests anthropic 2>/dev/null || pip install requests anthropic --break-system-packages

# Verificar que la API key esté configurada
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "⚠️  ANTHROPIC_API_KEY no está configurada."
    echo "   Añádela al crontab o al archivo de entorno:"
    echo "   export ANTHROPIC_API_KEY='tu-key-aquí'"
    echo ""
fi

# Configurar cron
echo ""
echo "Configurando cron..."
CRON_CMD="0 */6 * * * cd $SCRIPTS_DIR && ANTHROPIC_API_KEY=\$(cat $BASE_DIR/.env_anthropic_key 2>/dev/null) $VENV_DIR/bin/python3 generate_forecasts.py >> $LOG_DIR/forecast_estados.log 2>&1"

echo "Línea de cron sugerida:"
echo "$CRON_CMD"
echo ""

read -p "¿Añadir al crontab? (s/n): " CONFIRM
if [ "$CONFIRM" = "s" ]; then
    (crontab -l 2>/dev/null | grep -v "generate_forecasts.py"; echo "$CRON_CMD") | crontab -
    echo "✓ Cron configurado"
fi

# Test rápido
echo ""
echo "Ejecutando test con un estado..."
cd "$SCRIPTS_DIR"
$VENV_DIR/bin/python3 generate_forecasts.py texas --no-ai

if [ -f "$WEB_DIR/texas/index.html" ]; then
    echo "✓ Test exitoso! Página de Texas generada."
else
    echo "✗ Error en el test. Revisa los logs."
fi

echo ""
echo "============================================"
echo "Setup completado."
echo ""
echo "Próximos pasos:"
echo "1. Configurar ANTHROPIC_API_KEY en $BASE_DIR/.env_anthropic_key"
echo "2. Ejecutar generación completa: cd $SCRIPTS_DIR && $VENV_DIR/bin/python3 generate_forecasts.py"
echo "3. Verificar en: https://www.canalmeteo.tv/pronostico/"
echo "4. Configurar nginx si es necesario (ver README)"
echo "============================================"
