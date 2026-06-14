#!/usr/bin/env python3
"""
download_spc.py - Descarga el SPC Day 1 Categorical Outlook
y lo guarda en formato GeoJSON accesible para el radar HTML.

Ubicación: /opt/canalmeteo/scripts/radar/download_spc.py
Destino:   /var/www/html/radar/spc_day1_cat.json
Cron:      */15 * * * *

Fuentes (en orden de prioridad):
  1. SPC GeoJSON directo
  2. NOAA MapServer (fallback)
"""

import json
import sys
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

import requests

# ─── Configuración ───────────────────────────────────────────
OUTPUT_DIR = Path("/var/www/html/radar")
OUTPUT_FILE = OUTPUT_DIR / "spc_day1_cat.json"
LOG_FILE = Path("/opt/canalmeteo/scripts/radar/logs/download_spc.log")

TIMEOUT = 30  # segundos

# Fuentes SPC
SPC_GEOJSON_URL = "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson"
NOAA_MAPSERVER_URL = (
    "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/"
    "SPC_wx_outlks/MapServer/1/query"
)
NOAA_PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "f": "geojson",
}

HEADERS = {
    "User-Agent": "CanalMeteoTV/1.0 (weather broadcast; contact@canalmeteo.tv)",
    "Accept": "application/json",
}

# ─── Logging ─────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("download_spc")


def download_spc_geojson() -> dict | None:
    """Fuente 1: GeoJSON directo del SPC."""
    try:
        log.info("Intentando SPC GeoJSON directo...")
        resp = requests.get(SPC_GEOJSON_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # El GeoJSON del SPC tiene features con LABEL2 (TSTM, MRGL, SLGT, ENH, MDT, HIGH)
        if data.get("features") and len(data["features"]) > 0:
            log.info(f"SPC GeoJSON OK: {len(data['features'])} features")
            return {
                "source": "spc_geojson",
                "updated": datetime.now(timezone.utc).isoformat(),
                "categorical_outlook": data,
            }
        else:
            log.warning("SPC GeoJSON sin features")
            return None

    except Exception as e:
        log.warning(f"SPC GeoJSON falló: {e}")
        return None


def download_noaa_mapserver() -> dict | None:
    """Fuente 2: NOAA MapServer (ArcGIS REST → GeoJSON)."""
    try:
        log.info("Intentando NOAA MapServer...")
        resp = requests.get(
            NOAA_MAPSERVER_URL, params=NOAA_PARAMS, headers=HEADERS, timeout=TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("features") and len(data["features"]) > 0:
            # Normalizar: el MapServer usa "dn" o "idp_source" pero también
            # puede traer "LABEL2". Vamos a mapear dn → LABEL2 si falta.
            dn_to_label = {
                2: "TSTM",
                3: "MRGL",
                4: "SLGT",
                5: "ENH",
                6: "MDT",
                8: "HIGH",
            }
            for feat in data["features"]:
                props = feat.get("properties", {})
                if "LABEL2" not in props and "dn" in props:
                    props["LABEL2"] = dn_to_label.get(props["dn"], "TSTM")

            log.info(f"NOAA MapServer OK: {len(data['features'])} features")
            return {
                "source": "noaa_mapserver",
                "updated": datetime.now(timezone.utc).isoformat(),
                "categorical_outlook": data,
            }
        else:
            log.warning("NOAA MapServer sin features")
            return None

    except Exception as e:
        log.warning(f"NOAA MapServer falló: {e}")
        return None


def save_json(data: dict) -> None:
    """Guarda el JSON en la ruta de salida."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Escribir a archivo temporal y luego mover (atómico)
    tmp_file = OUTPUT_FILE.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    tmp_file.rename(OUTPUT_FILE)
    log.info(f"Guardado en {OUTPUT_FILE} ({os.path.getsize(OUTPUT_FILE)} bytes)")


def save_empty() -> None:
    """Guarda un JSON vacío cuando no hay datos SPC (no hay riesgo hoy)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    empty = {
        "source": "none",
        "updated": datetime.now(timezone.utc).isoformat(),
        "categorical_outlook": {"type": "FeatureCollection", "features": []},
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(empty, f, ensure_ascii=False)
    log.info("Sin datos SPC hoy, guardado archivo vacío")


def main():
    log.info("=" * 50)
    log.info("Descargando SPC Day 1 Categorical Outlook...")

    # Intentar fuente 1: SPC directo
    data = download_spc_geojson()

    # Intentar fuente 2: NOAA MapServer
    if data is None:
        data = download_noaa_mapserver()

    # Guardar resultado
    if data is not None:
        save_json(data)
    else:
        log.warning("Ninguna fuente disponible")
        save_empty()

    log.info("Proceso completado")


if __name__ == "__main__":
    main()
