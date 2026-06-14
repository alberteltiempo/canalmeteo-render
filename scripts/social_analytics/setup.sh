#!/bin/bash
# ============================================
# YouTube Analytics - Setup Script
# ============================================
# Este script configura todo el entorno.
# Ejecutar en el servidor: bash setup.sh
# ============================================

set -e

echo "============================================"
echo "YouTube Analytics - Configuración Inicial"
echo "============================================"
echo ""

# Directorio base (ajustar según tu servidor)
BASE_DIR="/opt/canalmeteo/scripts/social_analytics"
ENV_DIR="/opt/canalmeteo/env"
VENV_DIR="$ENV_DIR/social_analytics"

# Crear estructura de directorios
echo "[1/5] Creando estructura de directorios..."
mkdir -p "$BASE_DIR"/{config,scripts,data,logs}
mkdir -p "$ENV_DIR"

# Crear entorno virtual
echo "[2/5] Creando entorno virtual de Python..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Activar entorno e instalar dependencias
echo "[3/5] Instalando dependencias..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2 requests

# Copiar scripts (si se ejecuta desde el directorio de desarrollo)
echo "[4/5] Verificando archivos..."
if [ -f "scripts/youtube_auth_setup.py" ]; then
    cp scripts/*.py "$BASE_DIR/scripts/"
    echo "  Scripts copiados a $BASE_DIR/scripts/"
fi

if [ -f "requirements.txt" ]; then
    cp requirements.txt "$BASE_DIR/"
fi

# Crear script wrapper para cron
echo "[5/5] Creando wrapper para cron..."
cat > "$BASE_DIR/run_youtube_collector.sh" << 'EOF'
#!/bin/bash
# Wrapper para ejecutar el collector desde cron
source /opt/canalmeteo/env/social_analytics/bin/activate
cd /opt/canalmeteo/scripts/social_analytics
python3 scripts/youtube_daily_collector.py "$@"
EOF

chmod +x "$BASE_DIR/run_youtube_collector.sh"

cat > "$BASE_DIR/run_youtube_exporter.sh" << 'EOF'
#!/bin/bash
# Wrapper para ejecutar el exporter desde cron
source /opt/canalmeteo/env/social_analytics/bin/activate
cd /opt/canalmeteo/scripts/social_analytics
python3 scripts/youtube_exporter.py "$@"
EOF

chmod +x "$BASE_DIR/run_youtube_exporter.sh"

echo ""
echo "============================================"
echo "✓ Configuración completada"
echo "============================================"
echo ""
echo "PRÓXIMOS PASOS:"
echo ""
echo "1. Crear proyecto en Google Cloud Console:"
echo "   https://console.cloud.google.com/"
echo ""
echo "2. Habilitar APIs:"
echo "   - YouTube Data API v3"
echo "   - YouTube Analytics API"
echo ""
echo "3. Crear OAuth 2.0 credentials (Desktop app)"
echo "   y descargar como client_secrets.json"
echo ""
echo "4. Copiar client_secrets.json a:"
echo "   $BASE_DIR/config/client_secrets.json"
echo ""
echo "5. Ejecutar autenticación:"
echo "   source $VENV_DIR/bin/activate"
echo "   cd $BASE_DIR"
echo "   python3 scripts/youtube_auth_setup.py"
echo ""
echo "6. Probar recolección manual:"
echo "   python3 scripts/youtube_daily_collector.py --backfill 7"
echo ""
echo "7. Configurar cron (ver crontab_example.txt)"
echo ""
