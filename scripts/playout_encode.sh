#!/bin/bash
# playout_encode.sh — Re-encode a la especificación de entrega del playout.
# ─────────────────────────────────────────────────────────────────────
# Requisitos de Canal Meteo playout (2026-08):
#   · Sonoridad −16 LUFS integrados ±1 (EBU R128), pico real máx −1 dBTP
#   · H.264 High, yuv420p rango LIMITADO (tv) + etiquetas BT.709
#   · 10 Mb/s (máx 12, buffer 20M), GOP 60 (2 s @ 30 fps), 30 fps, faststart
#   · AAC-LC 48 kHz estéreo 256 kb/s
#
# La sonoridad se hace con loudnorm en DOS pasadas (medir → aplicar en modo
# lineal): la pasada única del comando de referencia trabaja en modo dinámico
# y puede quedarse a >1 LU del objetivo en piezas cortas con música.
#
# Uso: playout_encode.sh <entrada.mp4> <salida.mp4>
set -e
set -o pipefail

IN="$1"
OUT="$2"
[ -f "$IN" ] || { echo "ERROR: no existe $IN"; exit 1; }
[ -n "$OUT" ] || { echo "Uso: $0 <entrada> <salida>"; exit 1; }

# ─── Pasada 1: medir sonoridad ───────────────────────────────────────
MEASURE_JSON=$(ffmpeg -hide_banner -nostats -i "$IN" -map 0:a:0 \
    -af loudnorm=I=-16:TP=-1:LRA=11:print_format=json -f null - 2>&1 \
    | sed -n '/^{/,/^}/p')

read -r M_I M_TP M_LRA M_TH M_OFF <<< "$(python3 - "$MEASURE_JSON" <<'PYEOF'
import json, sys
d = json.loads(sys.argv[1])
print(d["input_i"], d["input_tp"], d["input_lra"], d["input_thresh"], d["target_offset"])
PYEOF
)"
echo "loudnorm medido: I=${M_I} LUFS · TP=${M_TP} dBTP · LRA=${M_LRA}"

AF="loudnorm=I=-16:TP=-1:LRA=11:measured_I=${M_I}:measured_TP=${M_TP}:measured_LRA=${M_LRA}:measured_thresh=${M_TH}:offset=${M_OFF}:linear=true"

# ─── Pasada 2: encode completo a la spec ─────────────────────────────
# El filtro scale normaliza matriz y rango desde lo que traiga la entrada
# (másters antiguos: yuvj420p rango completo) a BT.709 limitado; con másters
# ya en BT.709/tv es un no-op. format=yuv420p quita la variante "j".
TMP="${OUT}.part.mp4"
# CBR real (nal-hrd): con ABR los mapas comprimen tanto que el promedio caía
# a ~5 Mb/s, por debajo del mínimo de 6 que pide el playout.
ffmpeg -hide_banner -loglevel error -y -i "$IN" \
    -vf "scale=in_range=auto:out_range=tv:in_color_matrix=auto:out_color_matrix=bt709,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
    -c:v libx264 -profile:v high -preset medium \
    -color_range:v tv -colorspace:v bt709 -color_primaries:v bt709 -color_trc:v bt709 \
    -b:v 10M -minrate 10M -maxrate 10M -bufsize 20M -x264-params nal-hrd=cbr -g 60 -r 30 \
    -c:a aac -b:a 256k -ar 48000 -ac 2 -af "$AF" \
    -movflags +faststart \
    "$TMP"
mv "$TMP" "$OUT"

# ─── Verificación rápida de la salida ────────────────────────────────
OUT_I=$(ffmpeg -hide_banner -nostats -i "$OUT" -map 0:a:0 \
    -af loudnorm=I=-16:TP=-1:LRA=11:print_format=json -f null - 2>&1 \
    | sed -n '/^{/,/^}/p' | python3 -c "import json,sys; print(json.load(sys.stdin)['input_i'])")
echo "salida: $(du -h "$OUT" | cut -f1) · sonoridad ${OUT_I} LUFS (objetivo −16 ±1)"
awk "BEGIN{exit !(${OUT_I} >= -17.2 && ${OUT_I} <= -14.8)}" \
    || { echo "AVISO: sonoridad fuera de −16 ±1 (${OUT_I} LUFS)"; exit 2; }
