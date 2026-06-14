#!/bin/bash
# =============================================================================
# nbm_runner.sh — Canal Meteo TV
# =============================================================================
# Ejecuta el pipeline NBM hora por hora en subprocesos aislados.
# Cada hora corre como un proceso Python nuevo → memoria liberada al 100% al
# terminar, evitando la fuga acumulada que causaba OOM tras ~30 horas.
#
# Uso:
#   ./nbm_runner.sh
#
# Salida:
#   - Cada hora: /tmp/nbm_hour_NNN.json (dict del manifest para esa hora)
#   - Manifest final: subido a CDN al terminar
#   - Log único: /var/log/canalmeteo/nbm.log
# =============================================================================

set -u
LOG=/var/log/canalmeteo/nbm.log
PY=/opt/canalmeteo/venv/bin/python3
PIPELINE=/opt/canalmeteo/scripts/model_pipeline_multi.py
TMPDIR=/tmp/nbm_hours
HOURS="1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 51 54 57 60 66 72 78"

log() {
  local msg="[$(date +'%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" | tee -a "$LOG"
}

log "====================================================="
log "NBM Runner — subprocess-per-hour"
log "====================================================="

# 1) Limpiar resultados anteriores
mkdir -p "$TMPDIR"
rm -f "$TMPDIR"/nbm_hour_*.json
log "Tmpdir limpio: $TMPDIR"

# 2) Detectar el ciclo más reciente una sola vez
CYCLE_INFO=$("$PY" "$PIPELINE" --model nbm --detect-cycle 2>>"$LOG")
if [ -z "$CYCLE_INFO" ]; then
  log "❌ No se pudo detectar ciclo NBM. Abortando."
  exit 1
fi
DATE=$(echo "$CYCLE_INFO" | awk '{print $1}')
CYCLE=$(echo "$CYCLE_INFO" | awk '{print $2}')
log "Ciclo detectado: ${DATE}/${CYCLE}z"

# 3) Procesar cada hora en subproceso aislado
TOTAL=$(echo "$HOURS" | wc -w)
COUNT=0
OK=0
FAIL=0

for fh in $HOURS; do
  COUNT=$((COUNT + 1))
  log "── f$(printf '%03d' $fh) (${COUNT}/${TOTAL}) ──"

  # timeout 90s por hora — si una hora cuelga, no bloquea las demás
  if timeout 90 "$PY" "$PIPELINE" \
      --model nbm \
      --single-hour "$fh" \
      --date "$DATE" \
      --cycle "$CYCLE" \
      --output-dir "$TMPDIR" \
      >> "$LOG" 2>&1; then
    OK=$((OK + 1))
  else
    rc=$?
    log "  ⚠️  f$(printf '%03d' $fh) falló (exit=$rc), continuando"
    FAIL=$((FAIL + 1))
  fi
done

log "Horas procesadas: ${OK} OK · ${FAIL} fallos · ${TOTAL} total"

# 4) Mergear y subir manifest final
log "Construyendo manifest final..."
if "$PY" "$PIPELINE" \
    --model nbm \
    --merge-manifest \
    --date "$DATE" \
    --cycle "$CYCLE" \
    --output-dir "$TMPDIR" \
    >> "$LOG" 2>&1; then
  log "✅ NBM Runner completado: ${OK} horas subidas al CDN"
else
  log "❌ Fallo al construir manifest final"
  exit 2
fi
