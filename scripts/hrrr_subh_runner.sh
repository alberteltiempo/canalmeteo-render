#!/bin/bash
# =============================================================================
# hrrr_subh_runner.sh — Canal Meteo TV
# =============================================================================
# Genera los frames sub-horarios (15 min) del HRRR para 1-18h y FUSIONA el
# manifest con los frames horarios ya subidos por hrrr_runner.sh.
#
# Diseño:
#   - Corre en su PROPIO cron, desfasado del horario (que va en min 50).
#   - Usa el MISMO ciclo que detecta find_latest_cycle (el del wrfsfcf completo).
#   - Escribe en /tmp/hrrr_subh (NO toca /tmp/hrrr_hours del horario).
#   - El merge fusionado lee el ciclo del manifest horario ya subido, así que
#     horario y sub-horario SIEMPRE cuadran.
#   - Si el horario aún no ha subido manifest, el merge aborta limpio (sin daño).
#
# Tiempo esperado: ~7-10 min (18 bloques en serie, ~21s c/u).
# =============================================================================
set -u

PY=/opt/canalmeteo/venv/bin/python3
PIPELINE=/opt/canalmeteo/scripts/model_pipeline_multi.py
SUBH_DIR=/tmp/hrrr_subh
HOURLY_DIR=/tmp/hrrr_hours          # mismo que usa el runner horario
HOURS="1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18"

PARALLEL=${PARALLEL:-1}
HOUR_TIMEOUT=${HOUR_TIMEOUT:-180}
NICE_PREFIX="nice -n 12 ionice -c 2 -n 7"

DATE=""
CYCLE=""

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }

log "====================================================="
log "HRRR Sub-horario Runner — 15 min, 1-18h (parallel=$PARALLEL)"
log "====================================================="

mkdir -p "$SUBH_DIR"
rm -f "$SUBH_DIR"/hrrr_hour_*.json
log "Tmpdir limpio: $SUBH_DIR"

# Detectar el mismo ciclo que el horario
CYCLE_INFO=$($NICE_PREFIX "$PY" "$PIPELINE" --model hrrr --detect-cycle 2>/dev/null)
if [ -z "$CYCLE_INFO" ] || ! echo "$CYCLE_INFO" | grep -qE "^[0-9]{8} [0-9]+"; then
  log "❌ No se pudo detectar ciclo HRRR. Abortando."
  exit 1
fi
DATE=$(echo "$CYCLE_INFO" | head -1 | awk '{print $1}')
CYCLE=$(echo "$CYCLE_INFO" | head -1 | awk '{print $2}')
log "Ciclo detectado: ${DATE}/${CYCLE}z"

process_block() {
  local fh="$1"
  local fhp
  fhp=$(printf '%03d' "$fh")
  if timeout "$HOUR_TIMEOUT" $NICE_PREFIX "$PY" "$PIPELINE" \
      --model hrrr --subh-hour "$fh" \
      --date "$DATE" --cycle "$CYCLE" --output-dir "$SUBH_DIR" 2>&1; then
    echo "[$(date +'%H:%M:%S')] ✓ subh f${fhp}"
  else
    echo "[$(date +'%H:%M:%S')] ⚠️  subh f${fhp} falló"
  fi
}

START_TIME=$(date +%s)
for fh in $HOURS; do
  while [ "$(jobs -r | wc -l)" -ge "$PARALLEL" ]; do sleep 0.3; done
  log "── Bloque f$(printf '%03d' $fh) ──"
  process_block "$fh" &
done
wait

ELAPSED=$(($(date +%s) - START_TIME))
NJSON=$(ls -1 "$SUBH_DIR"/hrrr_hour_*.json 2>/dev/null | wc -l)
log "Sub-frames generados: ${NJSON} en ${ELAPSED}s"

# Merge fusionado: horario (HOURLY_DIR) + sub-horario (SUBH_DIR)
log "Fusionando manifest (horario + sub-horario)..."
if $NICE_PREFIX "$PY" "$PIPELINE" \
    --model hrrr --merge-subh \
    --output-dir "$HOURLY_DIR" --subh-dir "$SUBH_DIR" 2>&1; then
  log "✅ Manifest fusionado subido al CDN"
else
  log "⚠️  No se pudo fusionar (¿manifest horario aún no disponible?). El horario sigue intacto."
fi
