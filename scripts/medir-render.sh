#!/usr/bin/env bash
# medir-render.sh — mide el coste real de un render Remotion en sfo3-c
# Uso:  bash medir-render.sh "<comando de render>"
# Ej.:  bash medir-render.sh "npx remotion render TropicoSegment out/Tropico_2026.mp4 --gl=swangle --scale=1 --concurrency=1"
set -uo pipefail

CMD="${1:?Pasa el comando de render entre comillas}"
LOG_MEM="/tmp/bench_mem_$$.log"
TIME_OUT="/tmp/bench_time_$$.log"

echo "=== Antes del render ==="
free -m | awk 'NR==1||/Mem|Swap/'
echo "Procesos remotion/chrome activos ahora:"
pgrep -af "remotion|chrome|node" | grep -vi pgrep | wc -l
echo ""

# Muestreo de memoria cada 2s en segundo plano
( while true; do
    free -m | awk '/Mem/{printf "%s avail=%s used=%s\n", strftime("%H:%M:%S"), $7, $3}'
    free -m | awk '/Swap/{printf "        swap_used=%s\n", $3}'
    sleep 2
  done ) > "$LOG_MEM" &
SAMPLER=$!

echo "=== Ejecutando render (con /usr/bin/time -v) ==="
START=$(date +%s)
/usr/bin/time -v bash -c "$CMD" 2> "$TIME_OUT"
RC=$?
END=$(date +%s)
kill "$SAMPLER" 2>/dev/null

echo ""
echo "=== Resumen ==="
echo "Código de salida: $RC  (137 = matado por OOM)"
echo "Duración: $(( END - START )) s"
PEAK_KB=$(grep -i "Maximum resident set size" "$TIME_OUT" | grep -o '[0-9]\+')
[ -n "${PEAK_KB:-}" ] && echo "Pico RAM del proceso (RSS): $(( PEAK_KB / 1024 )) MB"
echo "Mínimo de RAM disponible durante el render:"
awk '/avail=/{gsub("avail=","",$2); if($2+0<min||min==""){min=$2}} END{print "  available min = " min " MB"}' "$LOG_MEM"
echo "Máximo de swap usado durante el render:"
awk '/swap_used=/{gsub("swap_used=","",$2); if($2+0>max){max=$2}} END{print "  swap max = " max " MB"}' "$LOG_MEM"
echo ""
echo "Log de memoria completo: $LOG_MEM"
echo "Salida de /usr/bin/time -v: $TIME_OUT"
