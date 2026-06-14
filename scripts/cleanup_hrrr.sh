#!/bin/bash
# cleanup_hrrr.sh — Limpieza periódica del cache HRRR de Herbie
#
# Mantiene solo el último día de cache local.
# Las salidas en /opt/canalmeteo/data/hrrr_output/ se sobrescriben rolling
# por el propio pipeline (sync --delete), así que no necesitan cleanup separado.
#
# Cron sugerido (ejecutar diariamente a las 04:30 UTC):
#   30 4 * * * /opt/canalmeteo/scripts/cleanup_hrrr.sh >> /opt/canalmeteo/logs/cleanup_hrrr.log 2>&1

set -e

CACHE_DIR="/opt/canalmeteo/data/herbie_cache"
OUTPUT_DIR="/opt/canalmeteo/data/hrrr_output"
LOG_PREFIX="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

echo "[$LOG_PREFIX] Iniciando cleanup HRRR"

# 1. Cache de Herbie (descargas crudas) — mantener solo último día
if [ -d "$CACHE_DIR" ]; then
    BEFORE_SIZE=$(du -sh "$CACHE_DIR" 2>/dev/null | awk '{print $1}')
    BEFORE_COUNT=$(find "$CACHE_DIR" -type f 2>/dev/null | wc -l)

    # Borrar archivos GRIB y subset más viejos que 24h
    find "$CACHE_DIR" -type f \( -name "*.grib2" -o -name "subset_*" -o -name "*.idx" \) -mtime +1 -delete 2>/dev/null || true

    # Borrar directorios vacíos
    find "$CACHE_DIR" -type d -empty -delete 2>/dev/null || true

    AFTER_SIZE=$(du -sh "$CACHE_DIR" 2>/dev/null | awk '{print $1}')
    AFTER_COUNT=$(find "$CACHE_DIR" -type f 2>/dev/null | wc -l)
    echo "[$LOG_PREFIX]   Herbie cache: $BEFORE_COUNT archivos ($BEFORE_SIZE) → $AFTER_COUNT archivos ($AFTER_SIZE)"
fi

# 2. Output local de PNGs (los recientes se sobrescriben, los huérfanos eliminamos)
# Si por alguna razón quedan PNGs de variables que ya no procesamos, los borramos
# Esto es defensivo; el pipeline ya hace cleanup por variable.
if [ -d "$OUTPUT_DIR" ]; then
    OUTPUT_SIZE=$(du -sh "$OUTPUT_DIR" 2>/dev/null | awk '{print $1}')
    echo "[$LOG_PREFIX]   Output local: $OUTPUT_SIZE"
fi

# 3. Logs antiguos (rotar logs > 30 días)
LOG_DIR="/opt/canalmeteo/logs"
if [ -d "$LOG_DIR" ]; then
    find "$LOG_DIR" -name "model_pipeline_*.log.*" -mtime +30 -delete 2>/dev/null || true
fi

echo "[$LOG_PREFIX] Cleanup completado"
