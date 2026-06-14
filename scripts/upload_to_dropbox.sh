#!/bin/bash
# upload_to_dropbox.sh — Sube archivos a Dropbox usando refresh token
# ─────────────────────────────────────────────────────────────────────
# Pide un access token fresco antes de cada upload (vence en 4h pero
# siempre se renueva con el refresh token, que NO expira nunca).
#
# Configuración: /opt/canalmeteo/secrets/dropbox-token.env debe contener:
#   DROPBOX_APP_KEY=tu_app_key
#   DROPBOX_APP_SECRET=tu_app_secret
#   DROPBOX_REFRESH_TOKEN=tu_refresh_token
#
# Uso:
#   ./upload_to_dropbox.sh /ruta/local.mp4 /ruta/destino.mp4
#
# Ejemplo:
#   ./upload_to_dropbox.sh /tmp/test.mp4 /parques-oeste.mp4
# ─────────────────────────────────────────────────────────────────────

set -e

LOCAL_FILE="$1"
DROPBOX_PATH="$2"

if [ -z "$LOCAL_FILE" ] || [ -z "$DROPBOX_PATH" ]; then
    echo "Usage: $0 <local-file> <dropbox-path>"
    echo "Example: $0 /tmp/video.mp4 /parques-oeste.mp4"
    exit 1
fi

if [ ! -f "$LOCAL_FILE" ]; then
    echo "ERROR: Local file not found: $LOCAL_FILE"
    exit 1
fi

# ─── Cargar credenciales ────────────────────────────────────────────
SECRETS_FILE="/opt/canalmeteo/secrets/dropbox-token.env"

if [ -f "$SECRETS_FILE" ]; then
    source "$SECRETS_FILE"
fi

if [ -z "$DROPBOX_APP_KEY" ] || [ -z "$DROPBOX_APP_SECRET" ] || [ -z "$DROPBOX_REFRESH_TOKEN" ]; then
    echo "ERROR: Faltan credenciales en $SECRETS_FILE"
    echo "Necesarias: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN"
    exit 1
fi

# ─── Renovar access token ───────────────────────────────────────────
TOKEN_RESPONSE=$(curl -s https://api.dropboxapi.com/oauth2/token \
    -d grant_type=refresh_token \
    -d refresh_token="$DROPBOX_REFRESH_TOKEN" \
    -u "${DROPBOX_APP_KEY}:${DROPBOX_APP_SECRET}")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('access_token', ''))
except Exception:
    print('')
")

if [ -z "$ACCESS_TOKEN" ]; then
    echo "ERROR: No se pudo obtener access token"
    echo "Respuesta de Dropbox: $TOKEN_RESPONSE"
    exit 1
fi

# ─── Tamaño del archivo ─────────────────────────────────────────────
SIZE=$(stat -c%s "$LOCAL_FILE")
SIZE_MB=$(awk "BEGIN {printf \"%.1f\", $SIZE / 1024 / 1024}")

echo "▶ Uploading $LOCAL_FILE ($SIZE_MB MB) → Dropbox:$DROPBOX_PATH"

# ─── Upload ─────────────────────────────────────────────────────────
DROPBOX_API_ARG=$(cat <<EOF
{"path": "$DROPBOX_PATH", "mode": "overwrite", "autorename": false, "mute": true}
EOF
)

RESPONSE=$(curl -s -X POST https://content.dropboxapi.com/2/files/upload \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/octet-stream" \
    -H "Dropbox-API-Arg: $DROPBOX_API_ARG" \
    --data-binary "@$LOCAL_FILE")

if echo "$RESPONSE" | grep -q '"id":' ; then
    REV=$(echo "$RESPONSE" | grep -o '"rev":"[^"]*"' | head -1 | cut -d'"' -f4)
    echo "✓ Uploaded to Dropbox (rev: $REV)"
    exit 0
else
    echo "✗ Upload failed:"
    echo "$RESPONSE"
    exit 1
fi
