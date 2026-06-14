#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# Canal Meteo TV — Records Diarios Pipeline · Instalación
# ═══════════════════════════════════════════════════════════════════════════
# Ejecutar como root en el droplet:
#   bash install_records_daily.sh
# ═══════════════════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="/opt/canalmeteo/scripts"
DATA_DIR="/opt/canalmeteo/data/records_daily"
ASSETS_DIR="/opt/canalmeteo/assets"
VENV="/opt/canalmeteo/venv"
LOG_DIR="/var/log/canalmeteo"

echo "═══════════════════════════════════════════════════"
echo "  Canal Meteo TV · Records Diarios · Instalación"
echo "═══════════════════════════════════════════════════"

# 1) Crear directorios
echo "[1/6] Creando directorios..."
mkdir -p "$DATA_DIR/output"
mkdir -p "$ASSETS_DIR"
mkdir -p "$LOG_DIR"

# 2) Copiar script
echo "[2/6] Instalando script..."
cp records_daily_pipeline.py "$SCRIPT_DIR/"
chmod +x "$SCRIPT_DIR/records_daily_pipeline.py"

# 3) Instalar dependencias
echo "[3/6] Verificando dependencias..."
$VENV/bin/pip install Pillow requests --quiet 2>/dev/null || true

# 4) Descargar logo
echo "[4/6] Descargando logo..."
if [ ! -f "$ASSETS_DIR/logo-canalmeteo-30.png" ]; then
    curl -sL -o "$ASSETS_DIR/logo-canalmeteo-30.png" \
        "https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png"
    echo "  ✅ Logo descargado"
else
    echo "  Logo ya existe"
fi

# 5) Crear .env si no existe
echo "[5/6] Configuración SMTP..."
ENV_FILE="/opt/canalmeteo/.env_records"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'ENVEOF'
# Canal Meteo TV — Records Diarios · SMTP Config
# Editar con credenciales reales
SMTP_HOST=smtpout.secureserver.net
SMTP_PORT=465
SMTP_USER=albert@canalmeteo.tv
SMTP_PASS=TU_PASSWORD_AQUI
MAIL_FROM=albert@canalmeteo.tv
MAIL_TO=albert@canalmeteo.tv
ENVEOF
    chmod 600 "$ENV_FILE"
    echo "  ⚠️  Editar $ENV_FILE con credenciales reales"
else
    echo "  Ya existe $ENV_FILE"
fi

# 6) Test rápido (dry-run)
echo "[6/6] Test rápido (dry-run)..."
$VENV/bin/python "$SCRIPT_DIR/records_daily_pipeline.py" --dry-run 2>&1 | tail -5

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Instalación completada"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Añadir a crontab (crontab -e):"
echo ""
echo '# Records diarios batidos (cada hora, minuto 15)'
echo '15 * * * * set -a; . /opt/canalmeteo/.env_records; set +a; flock -n /tmp/records_daily.lock /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/records_daily_pipeline.py >> /var/log/canalmeteo/records_daily.log 2>&1'
echo ""
echo "Primera ejecución manual:"
echo "  source /opt/canalmeteo/venv/bin/activate"
echo "  set -a; source /opt/canalmeteo/.env_records; set +a"
echo "  python /opt/canalmeteo/scripts/records_daily_pipeline.py --force-email"
echo ""
