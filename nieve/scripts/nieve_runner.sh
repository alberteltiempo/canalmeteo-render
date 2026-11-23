#!/bin/bash
# nieve_runner.sh — ¿Hay clases? · ciclo horario en nimbus-03 (usuario canalmeteo).
# Guarda en /opt/canalmeteo/nieve y publica en el CDN (data/nieve/), autorizado el 14-nov-2026.
#   05  pronóstico del NBM por distrito (solo si hay ciclo nuevo)
#   05b avisos de invierno del NWS (siempre: cambian a cualquier hora)
#   07  índice → archivo/<AAAAMM>/ y salida/actual/
#   09  salida/actual/ → CDN data/nieve/
# cron:  50 * * * * flock -n /tmp/nieve.lock /opt/canalmeteo/nieve/scripts/nieve_runner.sh >> /opt/canalmeteo/nieve/logs/runner.log 2>&1
set -u
cd /opt/canalmeteo/nieve/scripts || exit 1
V=/opt/canalmeteo/nieve/venv/bin/python3
echo "=== $(date -u +%Y-%m-%dT%H:%MZ)"
nice -n 10 $V 05_extrae_nbm.py --si-nuevo 2>&1 | grep -E "Ciclo|total|ya estaba|Error|Traceback"
$V 05b_avisos.py 2>&1 | tail -3
$V 07_indice.py 2>&1 | tail -12 && $V 09_publica.py 2>&1 | tail -3
# Las series horarias pesan 25 MB por ciclo: se guardan 3 días. El índice se archiva siempre.
find ../trabajo -name 'nbm_*.npz' -mmin +4320 -delete
find ../trabajo -name 'dias_*.csv' -mmin +4320 -delete
# El registro, a raya
[ "$(stat -c %s ../logs/runner.log 2>/dev/null || echo 0)" -gt 20000000 ] && tail -c 5000000 ../logs/runner.log > ../logs/runner.log.1 && : > ../logs/runner.log
exit 0
