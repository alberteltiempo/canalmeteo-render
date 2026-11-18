#!/bin/bash
# copia_datos.sh — copia local de datos pesados que cambian poco (18/11/2026)
# ─────────────────────────────────────────────────────────────────────
# El mapa de sequía (data/drought/usdm_current.json, 16 MB) solo cambia los
# jueves, pero cada render lo bajaba entero del Space: unos 3,5 GiB al día.
# Aquí se guarda en <proyecto>/public/datos/ y se pregunta al Space si ha
# cambiado (If-Modified-Since): si no, no se descarga nada.
# El motor (fetchDrought en lib/cdn.ts) lee la copia y, si falta, baja del
# Space como antes. Nunca se pierde un render por esto: siempre sale con 0.
#
# Uso: copia_datos.sh /opt/canalmeteo/remotion/tiempo
# ─────────────────────────────────────────────────────────────────────
PROY="${1:?falta la carpeta del proyecto}"
URL="https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/drought/usdm_current.json"
DIR="$PROY/public/datos"
F="$DIR/usdm_current.json"
VISTO="$F.visto"          # última vez que el Space contestó (200 o 304)
TMP="$F.tmp.$$"
MAX_DIAS=8                # sin contacto más de esto: se borra la copia y el motor baja del Space

mkdir -p "$DIR" || exit 0
ARGS=(-fsS --max-time 90 -o "$TMP" -w '%{http_code}')
[ -s "$F" ] && ARGS+=(-z "$F")
COD=$(curl "${ARGS[@]}" "$URL" 2>/dev/null)
case "$COD" in
    200)
        if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("features")' "$TMP" 2>/dev/null; then
            mv -f "$TMP" "$F" && touch "$VISTO"
            echo "  Sequía: copia local actualizada ($(du -h "$F" | cut -f1))"
        else
            echo "⚠ Sequía: la descarga no es un GeoJSON válido; se mantiene la copia anterior"
        fi ;;
    304)
        touch "$VISTO"
        echo "  Sequía: sin cambios, se usa la copia local" ;;
    *)
        echo "⚠ Sequía: el Space no contestó (código ${COD:-ninguno})"
        if [ -e "$F" ] && [ -z "$(find "$VISTO" -mtime -"$MAX_DIAS" 2>/dev/null)" ]; then
            rm -f "$F"
            echo "⚠ Sequía: copia de más de $MAX_DIAS días sin confirmar, borrada"
        fi ;;
esac
rm -f "$TMP"
exit 0
