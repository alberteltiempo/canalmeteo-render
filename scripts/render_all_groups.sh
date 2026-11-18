#!/bin/bash
# render_all_groups.sh — Renderiza los 4 grupos de parques en serie
# ─────────────────────────────────────────────────────────────────────
# Llama a render.sh para cada grupo, uno detrás de otro.
# Tiempo total estimado: ~20-25 min con scale=0.75 en 2vCPU.
#
# Uso:
#   ./render_all_groups.sh
#   ./render_all_groups.sh --triggered-by=cron
# ─────────────────────────────────────────────────────────────────────

RENDER_SCRIPT="/opt/canalmeteo/remotion/parques-webcams/render.sh"

TRIGGERED_BY="manual-batch"
for arg in "$@"; do
    case "$arg" in
        --triggered-by=*) TRIGGERED_BY="${arg#*=}" ;;
    esac
done

START=$(date +%s)
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "==============================================================="
echo "  Render All Groups - Canal Meteo Parques Webcams"
echo "  Inicio:        $(date -u +'%H:%M:%S UTC')"
echo "  Triggered by:  $TRIGGERED_BY"
echo "  Estimacion:    ~20-25 minutos (4 grupos x ~5 min)"
echo "==============================================================="

OK_COUNT=0
FAIL_COUNT=0
FAILED_GROUPS=""

# ─── Función helper ─────────────────────────────────────────────────
render_one() {
    local group="$1"
    echo ""
    echo "=== Render: $group =================================="
    local group_start=$(date +%s)

    # nimbus-03 (11/09/2026): mismo lock de GPU que los render.sh regionales
    # (/tmp/canalmeteo-render.lock, espera máx. 15 min) → los grupos se intercalan
    # con CONUS :33 / NW :39 en vez de pelearse por la iGPU.
    if flock -w 900 /tmp/canalmeteo-render.lock "$RENDER_SCRIPT" --group="$group" --triggered-by="$TRIGGERED_BY"; then
        local group_end=$(date +%s)
        local elapsed=$((group_end - group_start))
        echo "OK $group completado en ${elapsed}s"
        OK_COUNT=$((OK_COUNT + 1))
    else
        echo "FAIL $group"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_GROUPS="$FAILED_GROUPS $group"
    fi
}

# ─── METAR: una sola descarga para los 4 grupos (18/11/2026) ───────
# Cada grupo bajaba 4 veces surface_obs.geojson (3,7 MB). Se deja una copia en
# public/datos/ y fetchMetar.ts la usa si es reciente; si esto falla, cada
# render baja del Space como antes.
METAR_DIR="/opt/canalmeteo/remotion/parques-webcams/public/datos"
METAR_TMP="$METAR_DIR/surface_obs.geojson.tmp.$$"
mkdir -p "$METAR_DIR"
if curl -fsS --max-time 60 -o "$METAR_TMP" \
        "https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/metar/surface_obs.geojson" \
   && python3 -c 'import json,sys; assert json.load(open(sys.argv[1])).get("features")' "$METAR_TMP" 2>/dev/null; then
    mv -f "$METAR_TMP" "$METAR_DIR/surface_obs.geojson"
    echo "  METAR: copia local actualizada"
else
    rm -f "$METAR_TMP"
    echo "  METAR: no se pudo actualizar la copia local; cada render bajará del Space"
fi

# ─── Renderizar los 4 grupos ────────────────────────────────────────
render_one oeste
render_one montanas
render_one apalaches
render_one iconicos

# ─── Resumen ────────────────────────────────────────────────────────
TOTAL=$(($(date +%s) - START))

echo ""
echo "==============================================================="
echo "  TODOS los grupos procesados en ${TOTAL}s"
echo "  Inicio: $START_ISO"
echo "  Fin:    $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo "  OK:     $OK_COUNT"
echo "  Fail:   $FAIL_COUNT"
if [ "$FAIL_COUNT" -gt 0 ]; then
    echo "  Fallidos:$FAILED_GROUPS"
fi
echo "==============================================================="

[ "$FAIL_COUNT" -eq 0 ] && exit 0 || exit 1
