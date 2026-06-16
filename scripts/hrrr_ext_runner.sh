#!/bin/bash
# =============================================================================
# hrrr_runner.sh v2 — Canal Meteo TV
# =============================================================================
# Mejoras v2:
#   ★ Paralelización: 2 horas a la vez (PARALLEL=2 por defecto)
#   ★ nice/ionice: baja prioridad → NO mata MRMS, satellite, alertas
#   ★ Trap SIGTERM: si el cron lo mata, hace merge de emergencia
#   ★ timeout 240s por hora (subido desde 180 — algunas horas tardaban más)
#   ★ Sin tee duplicado: el cron captura output con >>
#
# Tiempo esperado: ~18-22 min para 19 horas (vs ~30 min secuencial)
#
# Override de paralelización (test):
#   PARALLEL=3 ./hrrr_runner.sh
# =============================================================================

set -u

# ── Config ───────────────────────────────────────────────────────────────
PY=/opt/canalmeteo/venv/bin/python3
PIPELINE=/opt/canalmeteo/scripts/model_pipeline_multi.py
TMPDIR=/tmp/hrrr_ext_hours
HOURS="0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48"

PARALLEL=${PARALLEL:-2}
HOUR_TIMEOUT=${HOUR_TIMEOUT:-240}
NICE_PREFIX="nice -n 10 ionice -c 2 -n 7"

RESULTS_FILE="/tmp/hrrr_ext_runner_results.$$"

DATE=""
CYCLE=""

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

cleanup() {
  rm -f "$RESULTS_FILE"
}
trap cleanup EXIT

emergency_merge() {
  log "⚠️  Señal recibida — terminando jobs y haciendo merge de emergencia"
  local pids
  pids=$(jobs -p 2>/dev/null)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    wait 2>/dev/null || true
  fi
  if [ -n "$DATE" ] && [ -n "$CYCLE" ]; then
    log "Intentando merge de emergencia: ${DATE}/${CYCLE}z"
    $NICE_PREFIX "$PY" "$PIPELINE" --model hrrr_ext --merge-manifest \
        --date "$DATE" --cycle "$CYCLE" --output-dir "$TMPDIR" 2>&1 || true
  fi
  log "Salida forzada por señal"
  exit 1
}
trap emergency_merge SIGTERM SIGINT

log "====================================================="
log "HRRR EXT Runner — 0-48h (parallel=$PARALLEL, timeout/hora=${HOUR_TIMEOUT}s)"
log "====================================================="

mkdir -p "$TMPDIR"
rm -f "$TMPDIR"/hrrr_hour_*.json
log "Tmpdir limpio: $TMPDIR"

CYCLE_INFO=$($NICE_PREFIX "$PY" "$PIPELINE" --model hrrr_ext --detect-cycle 2>/dev/null)
if [ -z "$CYCLE_INFO" ] || ! echo "$CYCLE_INFO" | grep -qE "^[0-9]{8} [0-9]+"; then
  log "❌ No se pudo detectar ciclo HRRR. Abortando."
  log "Output: $CYCLE_INFO"
  exit 1
fi
DATE=$(echo "$CYCLE_INFO" | head -1 | awk '{print $1}')
CYCLE=$(echo "$CYCLE_INFO" | head -1 | awk '{print $2}')
log "Ciclo detectado: ${DATE}/${CYCLE}z"

process_hour() {
  local fh="$1"
  local fh_padded
  fh_padded=$(printf '%03d' "$fh")
  echo "[$(date +'%H:%M:%S')] ▶ f${fh_padded} start"

  if timeout "$HOUR_TIMEOUT" $NICE_PREFIX "$PY" "$PIPELINE" \
      --model hrrr_ext \
      --single-hour "$fh" \
      --date "$DATE" \
      --cycle "$CYCLE" \
      --output-dir "$TMPDIR" 2>&1; then
    echo "OK $fh" >> "$RESULTS_FILE"
    echo "[$(date +'%H:%M:%S')] ✓ f${fh_padded} OK"
  else
    local rc=$?
    echo "FAIL $fh $rc" >> "$RESULTS_FILE"
    echo "[$(date +'%H:%M:%S')] ⚠️  f${fh_padded} falló (exit=$rc)"
  fi
}

TOTAL=$(echo "$HOURS" | wc -w)
COUNT=0
START_TIME=$(date +%s)

for fh in $HOURS; do
  while [ "$(jobs -r | wc -l)" -ge "$PARALLEL" ]; do
    sleep 0.3
  done

  COUNT=$((COUNT + 1))
  log "── Lanzando f$(printf '%03d' $fh) ($COUNT/$TOTAL) ──"

  process_hour "$fh" &
done

log "Esperando a que terminen las últimas $(jobs -r | wc -l) horas..."
wait

ELAPSED=$(($(date +%s) - START_TIME))
log "Procesamiento de horas terminado en ${ELAPSED}s ($(printf '%dm %ds' $((ELAPSED/60)) $((ELAPSED%60))))"

OK=0
FAIL=0
if [ -f "$RESULTS_FILE" ]; then
  OK=$(grep -c "^OK " "$RESULTS_FILE" 2>/dev/null || echo 0)
  FAIL=$(grep -c "^FAIL " "$RESULTS_FILE" 2>/dev/null || echo 0)
fi
log "Horas procesadas: ${OK} OK · ${FAIL} fallos · ${TOTAL} total"

log "Construyendo manifest final..."
if $NICE_PREFIX "$PY" "$PIPELINE" \
    --model hrrr_ext \
    --merge-manifest \
    --date "$DATE" \
    --cycle "$CYCLE" \
    --output-dir "$TMPDIR" 2>&1; then
  log "✅ HRRR Runner v2 completado: ${OK}/${TOTAL} horas subidas al CDN"
else
  log "❌ Fallo al construir manifest final"
  exit 2
fi
