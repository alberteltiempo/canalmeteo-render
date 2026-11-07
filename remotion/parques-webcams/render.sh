#!/bin/bash
# render.sh — Canal Meteo Parques Webcams
# ─────────────────────────────────────────────────────────────────────
# Renderiza el segmento de 60s de UN grupo, sube al CDN y a Dropbox
# con nombre específico (parques-{group}.mp4).
#
# Status JSON (compartido entre todos los grupos):
#   - render-status.json  (estado del render activo)
#   - render-history.json (últimos 50 renders de cualquier grupo)
#
# Uso:
#   ./render.sh                            # default: grupo "oeste"
#   ./render.sh --group=oeste              # grupo específico
#   ./render.sh --group=montanas
#   ./render.sh --group=apalaches
#   ./render.sh --group=iconicos
#   ./render.sh --group=oeste --no-upload  # solo render local
#
# Compatibilidad legacy:
#   --region=xxx funciona como --group=xxx
# ─────────────────────────────────────────────────────────────────────

set -e

PROJECT_DIR="/opt/canalmeteo/remotion/parques-webcams"
OUTPUT_DIR="/opt/canalmeteo/data/videos/parques-webcams"
TEMP_DIR="/opt/canalmeteo/data/temp"
LOG_DIR="/var/log/canalmeteo"
STATUS_DIR="/opt/canalmeteo/data/render-status"

mkdir -p "$OUTPUT_DIR" "$TEMP_DIR" "$LOG_DIR" "$STATUS_DIR"

cd "$PROJECT_DIR"

# ─── Args ────────────────────────────────────────────────────────────
GROUP="oeste"
NO_UPLOAD=false
TRIGGERED_BY="manual"

for arg in "$@"; do
    case $arg in
        --group=*) GROUP="${arg#*=}" ;;
        --region=*) GROUP="${arg#*=}" ;;  # legacy alias
        --no-upload) NO_UPLOAD=true ;;
        --triggered-by=*) TRIGGERED_BY="${arg#*=}" ;;
    esac
done

# Validar grupo
case "$GROUP" in
    oeste|montanas|apalaches|iconicos) ;;
    *)
        echo "ERROR: Grupo inválido '$GROUP'. Válidos: oeste, montanas, apalaches, iconicos"
        exit 1
        ;;
esac

# ─── Constants ───────────────────────────────────────────────────────
TIMESTAMP=$(date -u +"%Y-%m-%dT%H-00Z")
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
START_EPOCH=$(date +%s)
GROUP_UPPER=$(echo "PARQUES_${GROUP}" | tr '[:lower:]' '[:upper:]')
RENDER_ID="parques-${GROUP}-${TIMESTAMP}-$(date +%s)"
OUTPUT_FILE="$OUTPUT_DIR/parques-${GROUP}-${TIMESTAMP}.mp4"
LATEST_FILE="$OUTPUT_DIR/parques-${GROUP}-latest.mp4"
LOG_FILE="$LOG_DIR/render-${GROUP}-${TIMESTAMP}.log"
STATUS_FILE="$STATUS_DIR/render-status.json"
HISTORY_FILE="$STATUS_DIR/render-history.json"

CDN_BUCKET="canalmeteo-public"
CDN_PREFIX="data/videos/parques-webcams"
CDN_ENDPOINT="https://sfo3.digitaloceanspaces.com"
CDN_BASE_URL="https://canalmeteo-public.sfo3.digitaloceanspaces.com"

# ─── Helper functions ───────────────────────────────────────────────
log() {
    echo "[$(date -u +'%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

write_status() {
    local status_json="$1"
    echo "$status_json" > "$STATUS_FILE"

    if [ "$NO_UPLOAD" = false ]; then
        aws s3 cp "$STATUS_FILE" \
            "s3://${CDN_BUCKET}/${CDN_PREFIX}/render-status.json" \
            --profile do-tor1 \
            --endpoint-url "$CDN_ENDPOINT" \
            --acl public-read \
            --content-type application/json \
            --cache-control "no-cache, max-age=0" \
            --quiet 2>/dev/null || true
    fi
}

status_running() {
    local progress_pct="$1"
    local current_frame="$2"
    local total_frames="$3"
    local elapsed=$(( $(date +%s) - START_EPOCH ))
    local eta_seconds=0
    if [ "$progress_pct" -gt 0 ]; then
        eta_seconds=$(( elapsed * (100 - progress_pct) / progress_pct ))
    fi

    cat <<EOF
{
  "render_id": "$RENDER_ID",
  "status": "rendering",
  "started_at": "$START_ISO",
  "elapsed_seconds": $elapsed,
  "group": "$GROUP",
  "region": "$GROUP",
  "timestamp": "$TIMESTAMP",
  "current_frame": $current_frame,
  "total_frames": $total_frames,
  "progress_pct": $progress_pct,
  "eta_seconds": $eta_seconds,
  "triggered_by": "$TRIGGERED_BY",
  "log_url": "$CDN_BASE_URL/$CDN_PREFIX/logs/render-${GROUP}-${TIMESTAMP}.log"
}
EOF
}

status_completed() {
    local size_bytes=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || echo 0)
    local size_mb=$(awk "BEGIN {printf \"%.1f\", $size_bytes / 1024 / 1024}")
    local elapsed=$(( $(date +%s) - START_EPOCH ))

    cat <<EOF
{
  "render_id": "$RENDER_ID",
  "status": "completed",
  "started_at": "$START_ISO",
  "completed_at": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "elapsed_seconds": $elapsed,
  "duration_seconds": $elapsed,
  "group": "$GROUP",
  "region": "$GROUP",
  "timestamp": "$TIMESTAMP",
  "file_size_bytes": $size_bytes,
  "file_size_mb": $size_mb,
  "video_url": "$CDN_BASE_URL/$CDN_PREFIX/parques-${GROUP}-${TIMESTAMP}.mp4",
  "video_url_latest": "$CDN_BASE_URL/$CDN_PREFIX/parques-${GROUP}-latest.mp4",
  "dropbox_filename": "parques-${GROUP}.mp4",
  "triggered_by": "$TRIGGERED_BY"
}
EOF
}

status_failed() {
    local error_msg="$1"
    local elapsed=$(( $(date +%s) - START_EPOCH ))

    cat <<EOF
{
  "render_id": "$RENDER_ID",
  "status": "failed",
  "started_at": "$START_ISO",
  "failed_at": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "elapsed_seconds": $elapsed,
  "group": "$GROUP",
  "region": "$GROUP",
  "timestamp": "$TIMESTAMP",
  "error": "$error_msg",
  "triggered_by": "$TRIGGERED_BY",
  "log_url": "$CDN_BASE_URL/$CDN_PREFIX/logs/render-${GROUP}-${TIMESTAMP}.log"
}
EOF
}

add_to_history() {
    local entry_json="$1"
    /opt/canalmeteo/venv/bin/python3 <<PYEOF
import json
import os

history_file = "$HISTORY_FILE"
new_entry = json.loads('''$entry_json''')

if os.path.exists(history_file):
    try:
        with open(history_file) as f:
            data = json.load(f)
        history = data.get('history', [])
    except Exception:
        history = []
else:
    history = []

history.insert(0, new_entry)
history = history[:50]

with open(history_file, 'w') as f:
    json.dump({'history': history, 'updated_at': '$START_ISO'}, f, indent=2)
PYEOF

    if [ "$NO_UPLOAD" = false ]; then
        aws s3 cp "$HISTORY_FILE" \
            "s3://${CDN_BUCKET}/${CDN_PREFIX}/render-history.json" \
            --profile do-tor1 \
            --endpoint-url "$CDN_ENDPOINT" \
            --acl public-read \
            --content-type application/json \
            --cache-control "public, max-age=30" \
            --quiet 2>/dev/null || true
    fi
}

# ─── Trap errores ───────────────────────────────────────────────────
on_error() {
    local exit_code=$?
    # nimbus-03 (11/09): llamado a mano (sin fallo previo) $? vale 0 y el lote lo
    # contaba como OK aunque no hubiera vídeo (así pasó desde mayo). Forzar error.
    [ "$exit_code" -eq 0 ] && exit_code=1
    local error_msg=${1:-"Render failed with exit code $exit_code"}
    log "✗ ERROR: $error_msg"
    local fail_json=$(status_failed "$error_msg")
    write_status "$fail_json"
    add_to_history "$fail_json"
    exit "$exit_code"
}

trap 'on_error' ERR

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

log "═══════════════════════════════════════════════════════════════"
log "  Canal Meteo Parques Webcams — Render"
log "  ID:           $RENDER_ID"
log "  Grupo:        $GROUP"
log "  Triggered:    $TRIGGERED_BY"
log "  Output:       $OUTPUT_FILE"
log "  Dropbox:      parques-${GROUP}.mp4"
log "═══════════════════════════════════════════════════════════════"

write_status "$(status_running 0 0 1800)"

# ─── Render ─────────────────────────────────────────────────────────
log "▶ Renderizando con Remotion..."

PROGRESS_FILE="$TEMP_DIR/progress-${RENDER_ID}.txt"
> "$PROGRESS_FILE"

REMOTION_ARGS=(
    src/index.ts
    ParquesWebcams
    "$OUTPUT_FILE"
    --concurrency=3
    --scale=1
    --log=info
    --props="{\"regionOverride\":\"$GROUP\"}"
)

(npx remotion render "${REMOTION_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE" > "$PROGRESS_FILE") &
RENDER_PID=$!

# Loop de tracking de progreso (cada 5s)
# Remotion v4 imprime: "Encoded NNNN/MMMM" (último frame procesado)
LAST_PCT=0
while kill -0 $RENDER_PID 2>/dev/null; do
    sleep 5
    PROGRESS_LINE=$(grep -E "(Rendered|Encoded) [0-9]+/[0-9]+" "$PROGRESS_FILE" 2>/dev/null | tail -1 || echo "")
    if [[ "$PROGRESS_LINE" =~ (Rendered|Encoded)\ ([0-9]+)/([0-9]+) ]]; then
        CURRENT_FRAME="${BASH_REMATCH[2]}"
        TOTAL_FRAMES="${BASH_REMATCH[3]}"
        PCT=$(( CURRENT_FRAME * 100 / TOTAL_FRAMES ))
        if [ "$PCT" != "$LAST_PCT" ]; then
            write_status "$(status_running "$PCT" "$CURRENT_FRAME" "$TOTAL_FRAMES")"
            LAST_PCT="$PCT"
        fi
    fi
done

wait $RENDER_PID
RENDER_EXIT=$?

if [ $RENDER_EXIT -ne 0 ]; then
    on_error "Remotion render exited with code $RENDER_EXIT"
fi

DURATION=$(( $(date +%s) - START_EPOCH ))
log "✓ Render completado en ${DURATION}s"

# ─── Validar el archivo ────────────────────────────────────────────
if [ ! -f "$OUTPUT_FILE" ] || [ ! -s "$OUTPUT_FILE" ]; then
    on_error "Output file not created or empty"
fi

SIZE=$(stat -c%s "$OUTPUT_FILE")
if [ "$SIZE" -lt 1000000 ]; then
    on_error "Output file too small: $SIZE bytes"
fi

log "  Tamaño: $(du -h "$OUTPUT_FILE" | cut -f1)"

# ─── Crear/actualizar latest del grupo ─────────────────────────────
cp "$OUTPUT_FILE" "$LATEST_FILE"
log "✓ parques-${GROUP}-latest.mp4 actualizado (local)"

# ─── Upload al CDN ──────────────────────────────────────────────────
if [ "$NO_UPLOAD" = false ]; then
    log "▶ Subiendo al CDN..."

    # Versión con timestamp
    aws s3 cp "$OUTPUT_FILE" \
        "s3://${CDN_BUCKET}/${CDN_PREFIX}/parques-${GROUP}-${TIMESTAMP}.mp4" \
        --profile do-tor1 \
        --endpoint-url "$CDN_ENDPOINT" \
        --acl public-read \
        --content-type video/mp4 \
        --cache-control "public, max-age=86400" \
        --quiet

    # Versión "latest" del grupo
    aws s3 cp "$OUTPUT_FILE" \
        "s3://${CDN_BUCKET}/${CDN_PREFIX}/parques-${GROUP}-latest.mp4" \
        --profile do-tor1 \
        --endpoint-url "$CDN_ENDPOINT" \
        --acl public-read \
        --content-type video/mp4 \
        --cache-control "public, max-age=300" \
        --quiet

    # Log
    aws s3 cp "$LOG_FILE" \
        "s3://${CDN_BUCKET}/${CDN_PREFIX}/logs/render-${GROUP}-${TIMESTAMP}.log" \
        --profile do-tor1 \
        --endpoint-url "$CDN_ENDPOINT" \
        --acl public-read \
        --content-type text/plain \
        --cache-control "public, max-age=86400" \
        --quiet 2>/dev/null || true

    log "✓ Subido al CDN"

    # ─── Upload a Dropbox para PlayoutManager ──────────────────────
    log "▶ Subiendo a Dropbox como parques-${GROUP}.mp4..."
    if /opt/canalmeteo/scripts/upload_to_dropbox.sh \
        "$OUTPUT_FILE" \
        "/Playout/RenderFarm/${GROUP_UPPER}.mp4" >> "$LOG_FILE" 2>&1; then
        log "✓ Subido a Dropbox: parques-${GROUP}.mp4"
    else
        log "⚠ Upload a Dropbox falló (no crítico, sigo)"
    fi
fi

# ─── Cleanup local: mantener solo últimos 24 archivos por grupo ────
log "▶ Cleanup local..."
ls -t "$OUTPUT_DIR"/parques-${GROUP}-2*.mp4 2>/dev/null | tail -n +25 | xargs -r rm
log "✓ Solo últimos 24 archivos de '$GROUP' retenidos"

# ─── Estado final + history ────────────────────────────────────────
COMPLETED_JSON=$(status_completed)
write_status "$COMPLETED_JSON"
add_to_history "$COMPLETED_JSON"

# ─── Resumen ────────────────────────────────────────────────────────
TOTAL=$(( $(date +%s) - START_EPOCH ))
log "═══════════════════════════════════════════════════════════════"
log "  ✓ Completado en ${TOTAL}s"
log "  Archivo: $OUTPUT_FILE ($(du -h "$OUTPUT_FILE" | cut -f1))"
log "  Grupo:   $GROUP"
log "  Dropbox: parques-${GROUP}.mp4"
log "═══════════════════════════════════════════════════════════════"
