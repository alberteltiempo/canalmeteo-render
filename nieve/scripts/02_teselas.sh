#!/bin/bash
# 02_teselas.sh — ¿Hay clases? · mapa de distritos en un solo fichero PMTiles.
# Entrada: fijos/distritos.geojsonl (de 01_distritos.py). Salida: fijos/districts.pmtiles
# Capa «d» con i (LEAID), n (nombre) y s (estado). No se descarta ningún distrito.
set -eu
cd /opt/canalmeteo/nieve/fijos
tippecanoe -o districts.pmtiles --force -l d \
  -Z2 -z10 \
  --no-feature-limit --no-tile-size-limit \
  --detect-shared-borders --simplification=8 \
  --read-parallel -q \
  distritos.geojsonl
ls -la districts.pmtiles search.json states.json distritos.csv distritos.gpkg
