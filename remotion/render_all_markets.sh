#!/bin/bash
# render_all_markets.sh — Canal Meteo · renderiza TODOS los segmentos
# "Vistazo al Tiempo" (CONUS + 8 regionales) de una tacada, en serie.
#
# El lock GLOBAL de GPU (/tmp/canalmeteo-render.lock, dentro de cada
# render.sh) ya impide que dos renders se pisen; aquí solo encadenamos,
# esperamos a que cada uno termine y resumimos al final. Cuenta ~4 min por
# segmento → ~35-40 min la tanda completa.
#
# Uso:
#   ./render_all_markets.sh                # render + subida a CDN/Dropbox
#   ./render_all_markets.sh --no-upload    # solo render local (pruebas)
# Cualquier argumento se pasa tal cual a cada render.sh.
#
# Los renders de cron pueden colarse entre segmento y segmento (cada uno
# espera su turno en el lock de GPU): no pasa nada, solo alarga la tanda.
set -u

BASE="/opt/canalmeteo/remotion"
LOG_DIR="/opt/canalmeteo/logs"
mkdir -p "$LOG_DIR"

# Lock propio: dos tandas a la vez no tienen sentido (18 renders encolados).
exec 9>/tmp/render-all-markets.lock
if ! flock -n 9; then
  echo "Ya hay un render_all_markets.sh en marcha; saliendo." >&2
  exit 1
fi

# Orden: el nacional primero y luego las regiones (mismo orden que los crons).
SEGMENTS=(tiempo_CONUS tiempo_NE tiempo_SE tiempo_FL tiempo_SP tiempo_MW tiempo_NP tiempo_NW tiempo_SW)

ok=()
ko=()
t0=$(date +%s)
echo "═══════════════════════════════════════════════════════════════"
echo "  Render de TODOS los mercados (${#SEGMENTS[@]} segmentos) · $(date '+%F %H:%M:%S')"
echo "  Args: ${*:-（ninguno: con subida a CDN/Dropbox）}"
echo "═══════════════════════════════════════════════════════════════"

for seg in "${SEGMENTS[@]}"; do
  slug=$(echo "$seg" | tr '[:upper:]_' '[:lower:]-')
  log="$LOG_DIR/render-all-${slug}.log"
  t1=$(date +%s)
  printf "▶ %-14s %s … " "$seg" "$(date '+%H:%M:%S')"
  if "$BASE/$seg/render.sh" "$@" > "$log" 2>&1; then
    printf "✓ (%ss)\n" "$(($(date +%s) - t1))"
    ok+=("$seg")
  else
    printf "✗ FALLO (%ss) → %s\n" "$(($(date +%s) - t1))" "$log"
    ko+=("$seg")
  fi
done

echo "═══════════════════════════════════════════════════════════════"
echo "  Tanda completada en $((($(date +%s) - t0) / 60)) min · OK: ${#ok[@]}/${#SEGMENTS[@]}"
if [ "${#ko[@]}" -gt 0 ]; then
  echo "  FALLARON: ${ko[*]}"
  echo "═══════════════════════════════════════════════════════════════"
  exit 1
fi
echo "═══════════════════════════════════════════════════════════════"
