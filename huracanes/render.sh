#!/bin/bash
# render.sh — Canal Meteo · Vistazo al Trópico (huracanes)
# ─────────────────────────────────────────────────────────────────────
# Renderiza el segmento tropical (auto-generado desde active_storms.json del
# CDN vía calculateMetadata), valida el MP4, lo sube al CDN y a Dropbox, y
# escribe status/history JSON. Pensado para correr en "calamarsa" (Vulkan).
#
# Uso:
#   ./render.sh                          # render + upload (horizontal 16:9)
#   ./render.sh --vertical               # versión Instagram 9:16 → TROPICO_REDES.mp4
#   ./render.sh --no-upload              # solo render local
#   ./render.sh --concurrency=4          # baja concurrencia (si la iGPU se queja)
#   ./render.sh --triggered-by=nhc-auto  # etiqueta de origen para el status
# ─────────────────────────────────────────────────────────────────────

set -e
set -o pipefail

# PATH robusto para cron (cron trae un PATH mínimo)
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

PROJECT_DIR="/opt/canalmeteo/remotion/huracanes"
TEMP_DIR="/opt/canalmeteo/data/temp"
LOG_DIR="/opt/canalmeteo/logs"
STATUS_DIR="/opt/canalmeteo/data/render-status"

# ─── Args ────────────────────────────────────────────────────────────
NO_UPLOAD=false
TRIGGERED_BY="manual"
# Concurrencia 4: a 8 la iGPU/Vulkan agota contextos WebGL al montar varios mapas
# Mapbox a la vez → "Failed to initialize WebGL" y el render aborta. 4 es estable.
# Se puede subir puntualmente con --concurrency=N si la máquina lo aguanta.
CONCURRENCY=4
VERTICAL=false

for arg in "$@"; do
    case $arg in
        --no-upload) NO_UPLOAD=true ;;
        --vertical) VERTICAL=true ;;
        --concurrency=*) CONCURRENCY="${arg#*=}" ;;
        --triggered-by=*) TRIGGERED_BY="${arg#*=}" ;;
    esac
done

# ─── Formato: horizontal (broadcast/web) o vertical (Instagram/redes) ──
if [ "$VERTICAL" = true ]; then
    COMPOSITION="TropicoVertical"
    SLUG="tropico-redes"
    DIRNAME="huracanes-redes"
    DROPBOX_NAME="TROPICO_REDES.mp4"
    LABEL="Vistazo al Trópico · Redes (vertical 1080×1920)"
else
    COMPOSITION="TropicoSegment"
    SLUG="tropico"
    DIRNAME="huracanes"
    DROPBOX_NAME="TROPICO.mp4"
    LABEL="Vistazo al Trópico (horizontal 1920×1080)"
fi

OUTPUT_DIR="/opt/canalmeteo/data/videos/$DIRNAME"
mkdir -p "$OUTPUT_DIR" "$TEMP_DIR" "$LOG_DIR" "$STATUS_DIR"
cd "$PROJECT_DIR"

# ─── Lock GLOBAL de GPU: un solo render a la vez ─────────────────────
# Dos renders simultáneos (Trópico + CONUS/NE, o cron + manual) compiten
# por la GPU y se matan entre sí ("Failed to initialize WebGL" / EPIPE al morir
# el navegador). Mismo lock en los render.sh de tiempo_CONUS y tiempo_NE.
# Espera hasta 15 min (antes abortaba con -n y se perdía el vídeo de la hora).
RENDER_LOCK="/tmp/canalmeteo-render.lock"
exec 9>"$RENDER_LOCK"
if ! flock -w 900 9; then
    echo "⚠ GPU ocupada >15 min (lock $RENDER_LOCK). Desisto." >&2
    exit 0
fi

# ─── Constantes ──────────────────────────────────────────────────────
TIMESTAMP=$(date -u +"%Y-%m-%dT%H-%M-00Z")
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
START_EPOCH=$(date +%s)
RENDER_ID="${SLUG}-${TIMESTAMP}-$(date +%s)"
OUTPUT_FILE="$OUTPUT_DIR/${SLUG}-${TIMESTAMP}.mp4"
LATEST_FILE="$OUTPUT_DIR/${SLUG}-latest.mp4"
LOG_FILE="$LOG_DIR/render-${SLUG}-${TIMESTAMP}.log"
STATUS_FILE="$STATUS_DIR/render-${SLUG}-status.json"
HISTORY_FILE="$STATUS_DIR/render-${SLUG}-history.json"
EST_TOTAL_FRAMES=2100   # ~70 s @ 30 fps (real lo detecta Remotion)

CDN_BUCKET="canalmeteo-public"
CDN_PREFIX="data/videos/$DIRNAME"
CDN_ENDPOINT="https://sfo3.digitaloceanspaces.com"
CDN_BASE_URL="https://canalmeteo-public.sfo3.digitaloceanspaces.com"
DROPBOX_PATH="/Playout/RenderFarm/$DROPBOX_NAME"

# python para el history (sistema; cae al venv si no hay)
PYBIN="$(command -v python3 || echo /opt/canalmeteo/venv/bin/python3)"

# ─── Helpers ─────────────────────────────────────────────────────────
log() { echo "[$(date -u +'%H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

write_status() {
    echo "$1" > "$STATUS_FILE"
    if [ "$NO_UPLOAD" = false ]; then
        aws s3 cp "$STATUS_FILE" \
            "s3://${CDN_BUCKET}/${CDN_PREFIX}/render-status.json" \
            --profile do-tor1 --endpoint-url "$CDN_ENDPOINT" \
            --acl public-read --content-type application/json \
            --cache-control "no-cache, max-age=0" --quiet 2>/dev/null || true
    fi
}

status_running() {
    local pct="$1" cur="$2" total="$3"
    local elapsed=$(( $(date +%s) - START_EPOCH )) eta=0
    [ "$pct" -gt 0 ] && eta=$(( elapsed * (100 - pct) / pct ))
    cat <<EOF
{
  "render_id": "$RENDER_ID",
  "status": "rendering",
  "started_at": "$START_ISO",
  "elapsed_seconds": $elapsed,
  "product": "$SLUG",
  "timestamp": "$TIMESTAMP",
  "current_frame": $cur,
  "total_frames": $total,
  "progress_pct": $pct,
  "eta_seconds": $eta,
  "triggered_by": "$TRIGGERED_BY",
  "log_url": "$CDN_BASE_URL/$CDN_PREFIX/logs/render-${SLUG}-${TIMESTAMP}.log"
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
  "product": "$SLUG",
  "timestamp": "$TIMESTAMP",
  "file_size_bytes": $size_bytes,
  "file_size_mb": $size_mb,
  "video_url": "$CDN_BASE_URL/$CDN_PREFIX/${SLUG}-${TIMESTAMP}.mp4",
  "video_url_latest": "$CDN_BASE_URL/$CDN_PREFIX/${SLUG}-latest.mp4",
  "dropbox_filename": "$DROPBOX_NAME",
  "triggered_by": "$TRIGGERED_BY"
}
EOF
}

status_failed() {
    local err="$1" elapsed=$(( $(date +%s) - START_EPOCH ))
    cat <<EOF
{
  "render_id": "$RENDER_ID",
  "status": "failed",
  "started_at": "$START_ISO",
  "failed_at": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "elapsed_seconds": $elapsed,
  "product": "$SLUG",
  "timestamp": "$TIMESTAMP",
  "error": "$err",
  "triggered_by": "$TRIGGERED_BY",
  "log_url": "$CDN_BASE_URL/$CDN_PREFIX/logs/render-${SLUG}-${TIMESTAMP}.log"
}
EOF
}

add_to_history() {
    local entry_json="$1"
    "$PYBIN" <<PYEOF
import json, os
hf = "$HISTORY_FILE"
new = json.loads('''$entry_json''')
hist = []
if os.path.exists(hf):
    try:
        hist = json.load(open(hf)).get('history', [])
    except Exception:
        hist = []
hist.insert(0, new); hist = hist[:50]
json.dump({'history': hist, 'updated_at': '$START_ISO'}, open(hf,'w'), indent=2)
PYEOF
    if [ "$NO_UPLOAD" = false ]; then
        aws s3 cp "$HISTORY_FILE" \
            "s3://${CDN_BUCKET}/${CDN_PREFIX}/render-history.json" \
            --profile do-tor1 --endpoint-url "$CDN_ENDPOINT" \
            --acl public-read --content-type application/json \
            --cache-control "public, max-age=30" --quiet 2>/dev/null || true
    fi
}

on_error() {
    local exit_code=$?
    local error_msg=${1:-"Render failed with exit code $exit_code"}
    log "✗ ERROR: $error_msg"
    local fail_json; fail_json=$(status_failed "$error_msg")
    write_status "$fail_json"; add_to_history "$fail_json"
    exit "$exit_code"
}
trap 'on_error' ERR

# ═══════════════════════════════════════════════════════════════════
log "═══════════════════════════════════════════════════════════════"
log "  Canal Meteo · $LABEL — Render"
log "  ID:           $RENDER_ID"
log "  Triggered:    $TRIGGERED_BY"
log "  Concurrency:  $CONCURRENCY  ·  GL: vulkan"
log "  Output:       $OUTPUT_FILE"
log "  Dropbox:      $DROPBOX_PATH"
log "═══════════════════════════════════════════════════════════════"

write_status "$(status_running 0 0 $EST_TOTAL_FRAMES)"

# ─── Limpiar caché de bundle de Remotion (evita estados raros) ─────
# Solo bundles antiguos (>2 h): borrar todos podía tumbar el bundle vivo de
# otro render en marcha (CONUS/NE) antes de existir el lock global.
find /tmp -maxdepth 1 -name 'remotion-webpack-bundle-*' -mmin +120 -exec rm -rf {} + 2>/dev/null || true

# ─── Render ─────────────────────────────────────────────────────────
log "▶ Renderizando con Remotion (Vulkan)..."
PROGRESS_FILE="$TEMP_DIR/progress-${RENDER_ID}.txt"; > "$PROGRESS_FILE"

# Usar el binario local de Remotion si existe (evita "npx no encuentra el ejecutable")
if [ -x "./node_modules/.bin/remotion" ]; then
    REMOTION_CMD=(./node_modules/.bin/remotion)
else
    REMOTION_CMD=(npx remotion)
fi
log "  Remotion: ${REMOTION_CMD[*]}"

REMOTION_ARGS=(
    render
    src/index.ts
    "$COMPOSITION"
    "$OUTPUT_FILE"
    --gl=vulkan
    --concurrency="$CONCURRENCY"
    --scale=1
    --log=info
)

("${REMOTION_CMD[@]}" "${REMOTION_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE" > "$PROGRESS_FILE") &
RENDER_PID=$!

# ─── Barra de progreso en terminal (solo si hay TTY; en cron no se dibuja) ──
TTY_BAR=false; [ -t 1 ] && TTY_BAR=true
BAR_W=42
draw_bar() {
    local pct="$1" cur="$2" tot="$3" phase="$4"
    local elapsed=$(( $(date +%s) - START_EPOCH ))
    local fps="0.0"; [ "$elapsed" -gt 0 ] && fps=$(awk "BEGIN{printf \"%.1f\", $cur/$elapsed}")
    local eta=0; [ "$pct" -gt 0 ] && eta=$(( elapsed * (100 - pct) / pct ))
    local em=$(( eta / 60 )) es=$(( eta % 60 ))
    local filled=$(( pct * BAR_W / 100 )) empty
    [ "$filled" -gt "$BAR_W" ] && filled=$BAR_W
    empty=$(( BAR_W - filled ))
    local bar=""
    [ "$filled" -gt 0 ] && bar=$(printf '█%.0s' $(seq 1 "$filled"))
    [ "$empty" -gt 0 ] && bar+=$(printf '░%.0s' $(seq 1 "$empty"))
    printf "\r\033[2K\033[36m%-12s\033[0m \033[1m%3d%%\033[0m │%s│ %d/%d  %s fps  ETA %d:%02d" \
        "$phase" "$pct" "$bar" "$cur" "$tot" "$fps" "$em" "$es"
}
$TTY_BAR && printf "  ⏳ Preparando bundle de Remotion…"

LAST_PCT=0
while kill -0 $RENDER_PID 2>/dev/null; do
    sleep 2
    PROGRESS_LINE=$(grep -E "(Rendered|Encoded) [0-9]+/[0-9]+" "$PROGRESS_FILE" 2>/dev/null | tail -1 || echo "")
    if [[ "$PROGRESS_LINE" =~ (Rendered|Encoded)\ ([0-9]+)/([0-9]+) ]]; then
        KW="${BASH_REMATCH[1]}"; CUR="${BASH_REMATCH[2]}"; TOT="${BASH_REMATCH[3]}"
        PCT=$(( CUR * 100 / TOT ))
        if [ "$KW" = "Encoded" ]; then PHASE="Codificando"; else PHASE="Renderizando"; fi
        $TTY_BAR && draw_bar "$PCT" "$CUR" "$TOT" "$PHASE"
        if [ "$PCT" != "$LAST_PCT" ]; then
            write_status "$(status_running "$PCT" "$CUR" "$TOT")"; LAST_PCT="$PCT"
        fi
    fi
done
$TTY_BAR && printf "\n"
set +e
wait $RENDER_PID; RENDER_EXIT=$?
set -e
if [ $RENDER_EXIT -ne 0 ]; then
    log "✗ Remotion falló (exit $RENDER_EXIT). Últimas líneas del log:"
    tail -40 "$PROGRESS_FILE" 2>/dev/null | sed 's/^/    /' | tee -a "$LOG_FILE"
    on_error "Remotion render exited with code $RENDER_EXIT"
fi

DURATION=$(( $(date +%s) - START_EPOCH ))
log "✓ Render completado en ${DURATION}s"

# ─── Validar el archivo ────────────────────────────────────────────
[ -f "$OUTPUT_FILE" ] && [ -s "$OUTPUT_FILE" ] || on_error "Output no creado o vacío"
SIZE=$(stat -c%s "$OUTPUT_FILE")
[ "$SIZE" -lt 1000000 ] && on_error "Output demasiado pequeño: $SIZE bytes"

if command -v ffprobe >/dev/null 2>&1; then
    DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUTPUT_FILE" 2>/dev/null || echo 0)
    awk "BEGIN{exit !($DUR>5)}" || on_error "Video inválido/corrupto (duración=${DUR}s)"
    log "  Duración: ${DUR}s · Tamaño: $(du -h "$OUTPUT_FILE" | cut -f1)"
else
    log "  Tamaño: $(du -h "$OUTPUT_FILE" | cut -f1) (ffprobe no disponible, salto validación de duración)"
fi

cp "$OUTPUT_FILE" "$LATEST_FILE"
log "✓ ${SLUG}-latest.mp4 actualizado (local)"

# ─── Upload CDN + Dropbox ──────────────────────────────────────────
if [ "$NO_UPLOAD" = false ]; then
    log "▶ Subiendo al CDN..."
    aws s3 cp "$OUTPUT_FILE" "s3://${CDN_BUCKET}/${CDN_PREFIX}/${SLUG}-${TIMESTAMP}.mp4" \
        --profile do-tor1 --endpoint-url "$CDN_ENDPOINT" --acl public-read \
        --content-type video/mp4 --cache-control "public, max-age=86400" --quiet
    aws s3 cp "$OUTPUT_FILE" "s3://${CDN_BUCKET}/${CDN_PREFIX}/${SLUG}-latest.mp4" \
        --profile do-tor1 --endpoint-url "$CDN_ENDPOINT" --acl public-read \
        --content-type video/mp4 --cache-control "public, max-age=300" --quiet
    aws s3 cp "$LOG_FILE" "s3://${CDN_BUCKET}/${CDN_PREFIX}/logs/render-${SLUG}-${TIMESTAMP}.log" \
        --profile do-tor1 --endpoint-url "$CDN_ENDPOINT" --acl public-read \
        --content-type text/plain --cache-control "public, max-age=86400" --quiet 2>/dev/null || true
    log "✓ Subido al CDN"

    log "▶ Subiendo a Dropbox como $DROPBOX_NAME..."
    if /opt/canalmeteo/scripts/upload_to_dropbox.sh "$OUTPUT_FILE" "$DROPBOX_PATH" >> "$LOG_FILE" 2>&1; then
        log "✓ Subido a Dropbox: $DROPBOX_PATH"
    else
        log "⚠ Upload a Dropbox falló (no crítico, sigo)"
    fi
fi

# ─── Cleanup local: últimos 24 ─────────────────────────────────────
ls -t "$OUTPUT_DIR"/${SLUG}-2*.mp4 2>/dev/null | tail -n +25 | xargs -r rm
log "✓ Solo últimos 24 archivos retenidos"

COMPLETED_JSON=$(status_completed)
write_status "$COMPLETED_JSON"; add_to_history "$COMPLETED_JSON"

TOTAL=$(( $(date +%s) - START_EPOCH ))
log "═══════════════════════════════════════════════════════════════"
log "  ✓ Completado en ${TOTAL}s · $(du -h "$OUTPUT_FILE" | cut -f1)"
log "  Dropbox: $DROPBOX_NAME"
log "═══════════════════════════════════════════════════════════════"
