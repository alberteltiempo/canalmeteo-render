#!/bin/bash
# =============================================================================
# nbm_runner.sh v2 — Canal Meteo TV
# =============================================================================
# Mejoras v2:
#   ★ Paralelización: 2 horas a la vez (PARALLEL=2 por defecto)
#   ★ nice/ionice: baja prioridad → NO mata MRMS, satellite, alertas
#   ★ Trap SIGTERM: si el cron lo mata, hace merge de emergencia
#   ★ Sin tee duplicado: el cron captura output con >> (sin doble write)
#
# Cómo funciona la paralelización:
#   - Usa bash job control (& + jobs -r + wait)
#   - Lanza una hora nueva en cuanto hay hueco libre
#   - Cada hora corre en un subshell independiente (memoria liberada al terminar)
#   - nice -n 10 + ionice -c 2 -n 7 → prioridad baja
#
# Tiempo esperado: ~45-50 min para 55 horas (vs ~110 min secuencial)
#
# Override de paralelización (test):
#   PARALLEL=3 ./nbm_runner.sh    # 3 horas a la vez (más agresivo)
# =============================================================================

set -u

# ── Config ───────────────────────────────────────────────────────────────
PY=/opt/canalmeteo/venv/bin/python3
PIPELINE=/opt/canalmeteo/scripts/model_pipeline_multi.py
TMPDIR=/tmp/nbm_hours
HOURS="1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 51 54 57 60 66 72 78"

# Paralelización (override con env var)
PARALLEL=${PARALLEL:-2}
HOUR_TIMEOUT=${HOUR_TIMEOUT:-240}

# Prioridad baja: los demás pipelines tienen preferencia de CPU y disco
NICE_PREFIX="nice -n 10 ionice -c 2 -n 7"

# Resultados (archivo único por PID)
RESULTS_FILE="/tmp/nbm_runner_results.$$"

# Variables para el trap (rellenadas más abajo)
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
  # Matar jobs background
  local pids
  pids=$(jobs -p 2>/dev/null)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    wait 2>/dev/null || true
  fi
  # Intentar merge con lo que haya
  if [ -n "$DATE" ] && [ -n "$CYCLE" ]; then
    log "Intentando merge de emergencia: ${DATE}/${CYCLE}z"
    $NICE_PREFIX "$PY" "$PIPELINE" --model nbm --merge-manifest \
        --date "$DATE" --cycle "$CYCLE" --output-dir "$TMPDIR" 2>&1 || true
  fi
  log "Salida forzada por señal"
  exit 1
}
trap emergency_merge SIGTERM SIGINT

# ── Inicio ───────────────────────────────────────────────────────────────
log "====================================================="
log "NBM Runner v2 (parallel=$PARALLEL, timeout/hora=${HOUR_TIMEOUT}s)"
log "====================================================="

# 1) Limpiar resultados anteriores
mkdir -p "$TMPDIR"
rm -f "$TMPDIR"/nbm_hour_*.json
log "Tmpdir limpio: $TMPDIR"

# 2) Detectar ciclo más reciente (sin paralelizar — única invocación)
CYCLE_INFO=$($NICE_PREFIX "$PY" "$PIPELINE" --model nbm --detect-cycle 2>/dev/null)
if [ -z "$CYCLE_INFO" ] || ! echo "$CYCLE_INFO" | grep -qE "^[0-9]{8} [0-9]+"; then
  log "❌ No se pudo detectar ciclo NBM. Abortando."
  log "Output: $CYCLE_INFO"
  exit 1
fi
DATE=$(echo "$CYCLE_INFO" | head -1 | awk '{print $1}')
CYCLE=$(echo "$CYCLE_INFO" | head -1 | awk '{print $2}')
log "Ciclo detectado: ${DATE}/${CYCLE}z"

# 3) Función para procesar una hora individual (en subshell)
process_hour() {
  local fh="$1"
  local fh_padded
  fh_padded=$(printf '%03d' "$fh")
  echo "[$(date +'%H:%M:%S')] ▶ f${fh_padded} start"

  if timeout "$HOUR_TIMEOUT" $NICE_PREFIX "$PY" "$PIPELINE" \
      --model nbm \
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

# 4) Loop con control de paralelismo
TOTAL=$(echo "$HOURS" | wc -w)
COUNT=0
START_TIME=$(date +%s)

for fh in $HOURS; do
  # Esperar a que haya hueco libre
  while [ "$(jobs -r | wc -l)" -ge "$PARALLEL" ]; do
    sleep 0.3
  done

  COUNT=$((COUNT + 1))
  log "── Lanzando f$(printf '%03d' $fh) ($COUNT/$TOTAL) ──"

  process_hour "$fh" &
done

# Esperar a que terminen todos los jobs en background
log "Esperando a que terminen las últimas $(jobs -r | wc -l) horas..."
wait

ELAPSED=$(($(date +%s) - START_TIME))
log "Procesamiento de horas terminado en ${ELAPSED}s ($(printf '%dm %ds' $((ELAPSED/60)) $((ELAPSED%60))))"

# 5) Contar resultados
OK=0
FAIL=0
if [ -f "$RESULTS_FILE" ]; then
  OK=$(grep -c "^OK " "$RESULTS_FILE" 2>/dev/null || echo 0)
  FAIL=$(grep -c "^FAIL " "$RESULTS_FILE" 2>/dev/null || echo 0)
fi
log "Horas procesadas: ${OK} OK · ${FAIL} fallos · ${TOTAL} total"

# 6) Mergear y subir manifest final
log "Construyendo manifest final..."
if $NICE_PREFIX "$PY" "$PIPELINE" \
    --model nbm \
    --merge-manifest \
    --date "$DATE" \
    --cycle "$CYCLE" \
    --output-dir "$TMPDIR" 2>&1; then
  log "✅ NBM Runner v2 completado: ${OK}/${TOTAL} horas subidas al CDN"
else
  log "❌ Fallo al construir manifest final"
  exit 2
fi
