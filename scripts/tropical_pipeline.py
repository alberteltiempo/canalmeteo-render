#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canal Meteo · Pipeline de Sistemas Tropicales (NHC)
====================================================

Fuente de verdad: CurrentStorms.json del National Hurricane Center.
Ese feed trae la lista de sistemas activos con metadata limpia (nombre,
clasificación, viento, presión, posición, movimiento, número de aviso) y el
enlace al zip GIS de 5 días por sistema.

A partir de él:
  - METADATA (nombre, categoría, viento, presión, ubicación, movimiento, aviso)
    → directamente del JSON.
  - GEOMETRÍA cono/trayectoria/puntos → de los shapefiles del zip _5day
    (_pgn = cono, _lin = trayectoria, _pts = puntos con MAXWIND/GUST/MSLP/TAU).
    Los KMZ del feed venían vacíos/empobrecidos esta temporada; el zip es la
    fuente autoritativa.
  - AVISOS Watch/Warning → del KMZ windWatchesWarnings (cuando existe).

Salidas (en /var/www/canalmeteo-public/tropical/ y CDN data/tropical/):
  - active_storms.json            → índice de sistemas activos con metadata
  - <storm_id>_cone.geojson       → cono de incertidumbre
  - <storm_id>_track.geojson      → trayectoria oficial (línea)
  - <storm_id>_points.geojson     → puntos de pronóstico (viento, presión, categoría)
  - <storm_id>_alerts.geojson     → alertas Watch/Warning

Uso:
  python3 tropical_pipeline.py [--once] [--output-dir DIR] [--upload-cdn]

Cron sugerido (cada 15 min, con flock y timeout):
  */15 * * * * flock -n /tmp/tropical_pipeline.lock \
      timeout 600 /opt/canalmeteo/venv/bin/python3 \
      /opt/canalmeteo/scripts/tropical_pipeline.py --once --upload-cdn \
      >> /var/log/canalmeteo/tropical_pipeline.log 2>&1
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

# pyshp (lectura de shapefiles). Import protegido: si faltara, el pipeline
# sigue funcionando con metadata + alertas, solo sin cono/track/puntos.
try:
    import shapefile  # pyshp
    HAVE_PYSHP = True
except ImportError:
    HAVE_PYSHP = False

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

NHC_CURRENT_STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"
USER_AGENT = "CanalMeteoTV/1.0 (https://canalmeteo.tv; contacto@canalmeteo.tv)"
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

DEFAULT_OUTPUT_DIR = Path("/var/www/canalmeteo-public/tropical")
CDN_PREFIX = "s3://canalmeteo-public/data/tropical/"
CDN_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CDN_PROFILE = "do-tor1"

# El campo intensity/MAXWIND del NHC viene en nudos. Convertimos a mph y
# redondeamos al múltiplo de 5 más cercano (convención de los avisos públicos).
INTENSITY_IS_KNOTS = True
KT_TO_MPH = 1.15078

# Valor centinela "sin dato" en los shapefiles del NHC (presión, dirección...)
NHC_MISSING = 9000  # cualquier valor >= 9000 (ej. 9999) es "no disponible"

# Clasificación Saffir-Simpson por viento máximo sostenido (mph)
SAFFIR_SIMPSON = [
    (39,  "TD",   "Depresión tropical"),
    (74,  "TS",   "Tormenta tropical"),
    (96,  "CAT1", "Huracán categoría 1"),
    (111, "CAT2", "Huracán categoría 2"),
    (130, "CAT3", "Huracán categoría 3 (mayor)"),
    (157, "CAT4", "Huracán categoría 4 (mayor)"),
    (999, "CAT5", "Huracán categoría 5 (mayor)"),
]

# Prefijo de nombre largo en español por clasificación NHC
SPANISH_PREFIX = {
    "TD":  "Depresión Tropical",
    "TS":  "Tormenta Tropical",
    "STD": "Depresión Subtropical",
    "STS": "Tormenta Subtropical",
    "PTC": "Ciclón Tropical Potencial",
    "PC":  "Ciclón Postropical",
    "LO":  "Baja Remanente",
    "HU":  "Huracán",
    "MH":  "Huracán",
}

# Rosa de los vientos en español (16 rumbos)
DIRS_ES = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("tropical")


# ---------------------------------------------------------------------------
# Utilidades HTTP / KMZ
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: int = 30) -> bytes:
    """Descarga binaria con User-Agent identificable."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def unzip_kmz(blob: bytes) -> str:
    """Extrae el primer .kml dentro de un KMZ."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.lower().endswith(".kml"):
                return z.read(name).decode("utf-8", errors="replace")
    raise ValueError("KMZ sin archivo .kml dentro")


def fetch_kml_or_kmz(url: str) -> str:
    """Descarga KML o KMZ y devuelve el contenido KML como texto."""
    blob = http_get(url)
    if url.lower().endswith(".kmz") or blob[:2] == b"PK":
        return unzip_kmz(blob)
    return blob.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Helpers numéricos / geográficos
# ---------------------------------------------------------------------------

def parse_int(v) -> Optional[int]:
    """Convierte a int robustamente (acepta str, float, None)."""
    try:
        return int(round(float(v)))
    except (ValueError, TypeError):
        return None


def kt_to_mph5(kt) -> Optional[int]:
    """Nudos → mph redondeado al múltiplo de 5 (convención del NHC).

    Devuelve None ante valores centinela (>= NHC_MISSING) o no numéricos.
    """
    n = parse_int(kt)
    if n is None or n >= NHC_MISSING:
        return None
    return int(round(n * KT_TO_MPH / 5.0)) * 5


def to_mph(intensity) -> Optional[int]:
    """Normaliza el campo intensity de CurrentStorms.json a mph."""
    n = parse_int(intensity)
    if n is None:
        return None
    if not INTENSITY_IS_KNOTS:
        return n
    return int(round(n * KT_TO_MPH / 5.0)) * 5


def clean_mb(v) -> Optional[int]:
    """Presión en mb, filtrando centinela 9999 y ceros."""
    n = parse_int(v)
    if n is None or n <= 0 or n >= NHC_MISSING:
        return None
    return n


def compass_es(deg) -> Optional[str]:
    """Grados (0-360, 0=N) → rumbo en español (16 puntos)."""
    if not isinstance(deg, (int, float)) or deg >= NHC_MISSING:
        return None
    return DIRS_ES[int((deg % 360) / 22.5 + 0.5) % 16]


def saffir_simpson(wind_mph: Optional[float]) -> tuple[str, str]:
    """Devuelve (código, descripción) según escala Saffir-Simpson."""
    if wind_mph is None:
        return ("UNK", "Desconocido")
    for threshold, code, desc in SAFFIR_SIMPSON:
        if wind_mph < threshold:
            return (code, desc)
    return ("CAT5", "Huracán categoría 5 (mayor)")


def classify(classification: str, wind_mph: Optional[int]) -> tuple[str, str]:
    """Mapea la clasificación NHC (+ viento) a (código, descripción) en español."""
    cls = (classification or "").upper()
    if cls in ("HU", "MH"):
        if wind_mph is not None:
            return saffir_simpson(wind_mph)
        return ("CAT1", "Huracán")
    fixed = {
        "TD":  ("TD",  "Depresión tropical"),
        "TS":  ("TS",  "Tormenta tropical"),
        "STD": ("STD", "Depresión subtropical"),
        "STS": ("STS", "Tormenta subtropical"),
        "PTC": ("PTC", "Ciclón tropical potencial"),
        "PC":  ("PC",  "Ciclón postropical"),
        "LO":  ("LO",  "Baja remanente"),
        "DB":  ("DB",  "Perturbación"),
        "WV":  ("WV",  "Onda tropical"),
    }
    if cls in fixed:
        return fixed[cls]
    return saffir_simpson(wind_mph)


def full_name_es(name: str, classification: str, cat_code: str) -> str:
    """Compone el nombre largo, ej. 'Tormenta Tropical Amanda', 'Huracán Otis'."""
    prefix = SPANISH_PREFIX.get((classification or "").upper())
    if prefix is None and cat_code.startswith("CAT"):
        prefix = "Huracán"
    return f"{prefix} {name}".strip() if prefix else name


def featurecollection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Lectura del zip GIS de 5 días (shapefiles)
# ---------------------------------------------------------------------------

def _open_shp(zf: zipfile.ZipFile, base: str):
    """Abre un shapefile (shp/dbf/shx) desde dentro del zip en memoria."""
    return shapefile.Reader(
        shp=io.BytesIO(zf.read(base + ".shp")),
        dbf=io.BytesIO(zf.read(base + ".dbf")),
        shx=io.BytesIO(zf.read(base + ".shx")),
    )


def _reader_by_suffix(zf: zipfile.ZipFile, suffix: str):
    """Devuelve el Reader cuyo nombre base termina en `suffix` (ej. '_5day_pgn')."""
    bases = {os.path.splitext(n)[0] for n in zf.namelist()}
    for b in sorted(bases):
        if b.lower().endswith(suffix):
            try:
                return _open_shp(zf, b)
            except KeyError:
                return None
    return None


def _geom_features(reader, props_fn) -> Optional[dict]:
    """Convierte un Reader en FeatureCollection usando props_fn(record_dict)."""
    if reader is None:
        return None
    fields = [f[0] for f in reader.fields[1:]]
    feats: list[dict] = []
    for sr in reader.shapeRecords():
        geom = sr.shape.__geo_interface__
        if not geom or not geom.get("coordinates"):
            continue
        rec = dict(zip(fields, list(sr.record)))
        feats.append({
            "type": "Feature",
            "properties": props_fn(rec),
            "geometry": geom,   # coords de precisión completa desde la geometría
        })
    return featurecollection(feats) if feats else None


def read_5day_zip(zip_url: str) -> tuple[Optional[dict], Optional[dict], Optional[dict]]:
    """Descarga el zip _5day y devuelve (cono, track, puntos) como FeatureCollections."""
    if not HAVE_PYSHP:
        log.warning("pyshp no disponible: no se generan cono/track/puntos")
        return (None, None, None)

    zf = zipfile.ZipFile(io.BytesIO(http_get(zip_url)))

    def meta_props(rec: dict) -> dict:
        return {
            "name": rec.get("STORMNAME"),
            "storm_type": rec.get("STORMTYPE"),
            "advisory": str(rec.get("ADVISNUM") or "").strip(),
        }

    def point_props(rec: dict) -> dict:
        wind = kt_to_mph5(rec.get("MAXWIND"))
        cat_code, cat_desc = classify(rec.get("STORMTYPE"), wind)
        return {
            "name": rec.get("STORMNAME"),
            "forecast_hour": parse_int(rec.get("TAU")),
            "max_wind_mph": wind,
            "gusts_mph": kt_to_mph5(rec.get("GUST")),
            "pressure_mb": clean_mb(rec.get("MSLP")),
            "category": cat_code,
            "category_desc": cat_desc,
            "dev_type": rec.get("TCDVLP"),
            "valid_label": rec.get("DATELBL"),
        }

    cone = _geom_features(_reader_by_suffix(zf, "_5day_pgn"), meta_props)
    track = _geom_features(_reader_by_suffix(zf, "_5day_lin"), meta_props)
    points = _geom_features(_reader_by_suffix(zf, "_5day_pts"), point_props)
    return (cone, track, points)


# ---------------------------------------------------------------------------
# Parsers KML (solo para avisos Watch/Warning)
# ---------------------------------------------------------------------------

def find_all(root: ET.Element, path: str) -> list[ET.Element]:
    return root.findall(path, KML_NS)


def parse_coords(text: str) -> list[list[float]]:
    """Convierte el texto <coordinates> de KML en [[lon, lat], ...]."""
    out: list[list[float]] = []
    for tok in re.split(r"\s+", text.strip()):
        if not tok:
            continue
        parts = tok.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        out.append([lon, lat])
    return out


def kml_to_polygons(kml_text: str) -> list[dict]:
    """Convierte polígonos de un KML en lista de Features GeoJSON."""
    features: list[dict] = []
    try:
        root = ET.fromstring(kml_text)
    except ET.ParseError as e:
        log.warning("KML inválido: %s", e)
        return features

    for placemark in find_all(root, ".//kml:Placemark"):
        name_el = placemark.find("kml:name", KML_NS)
        desc_el = placemark.find("kml:description", KML_NS)
        name = name_el.text if name_el is not None else ""
        desc = desc_el.text if desc_el is not None else ""

        for poly in find_all(placemark, ".//kml:Polygon"):
            outer = poly.find(".//kml:outerBoundaryIs//kml:coordinates", KML_NS)
            if outer is None or not outer.text:
                continue
            ring = parse_coords(outer.text)
            if len(ring) < 4:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "name": (name or "").strip(),
                    "description": (desc or "").strip(),
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })
    return features


def kml_to_alerts(kml_text: str) -> list[dict]:
    """Convierte alertas Watch/Warning en Features GeoJSON con tipo clasificado."""
    features: list[dict] = []
    for f in kml_to_polygons(kml_text):
        desc_upper = (f["properties"].get("description") or "").upper()
        name_upper = (f["properties"].get("name") or "").upper()
        haystack = f"{name_upper} {desc_upper}"

        alert_type = None
        if "HURRICANE WARNING" in haystack:
            alert_type = "HURRICANE_WARNING"
        elif "HURRICANE WATCH" in haystack:
            alert_type = "HURRICANE_WATCH"
        elif "TROPICAL STORM WARNING" in haystack:
            alert_type = "TROPICAL_STORM_WARNING"
        elif "TROPICAL STORM WATCH" in haystack:
            alert_type = "TROPICAL_STORM_WATCH"
        elif "STORM SURGE WARNING" in haystack:
            alert_type = "STORM_SURGE_WARNING"
        elif "STORM SURGE WATCH" in haystack:
            alert_type = "STORM_SURGE_WATCH"

        f["properties"]["alert_type"] = alert_type
        features.append(f)
    return features


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

@dataclass
class StormData:
    """Datos consolidados de un sistema tropical activo."""
    storm_id: str                 # Ej. EP012026
    storm_name: str               # Nombre largo, ej. "Tormenta Tropical Amanda"
    basin: str                    # AL | EP | CP
    storm_proper_name: str = ""   # Solo el nombre propio, ej. "Amanda"
    classification: str = ""      # Clasificación NHC cruda (TS/HU/PTC/...)
    current_wind_mph: Optional[int] = None
    current_pressure_mb: Optional[int] = None
    current_category: str = "UNK"
    current_category_desc: str = "Desconocido"
    current_location: Optional[list[float]] = None  # [lon, lat]
    current_movement: Optional[str] = None          # Ej. "ONO a 9 mph"
    movement_deg: Optional[float] = None
    movement_speed_mph: Optional[float] = None
    advisory: Optional[str] = None
    valid_at: Optional[str] = None
    cone: Optional[dict] = None
    track: Optional[dict] = None
    points: Optional[dict] = None
    alerts: Optional[dict] = None

    def to_index_entry(self) -> dict:
        return {
            "storm_id": self.storm_id,
            "storm_name": self.storm_name,
            "storm_proper_name": self.storm_proper_name,
            "classification": self.classification,
            "basin": self.basin,
            "current_wind_mph": self.current_wind_mph,
            "current_pressure_mb": self.current_pressure_mb,
            "current_category": self.current_category,
            "current_category_desc": self.current_category_desc,
            "current_location": self.current_location,
            "current_movement": self.current_movement,
            "movement_deg": self.movement_deg,
            "movement_speed_mph": self.movement_speed_mph,
            "advisory": self.advisory,
            "valid_at": self.valid_at,
            "files": {
                "cone": f"{self.storm_id}_cone.geojson" if self.cone else None,
                "track": f"{self.storm_id}_track.geojson" if self.track else None,
                "points": f"{self.storm_id}_points.geojson" if self.points else None,
                "alerts": f"{self.storm_id}_alerts.geojson" if self.alerts else None,
                "wind_radii": None,  # pendiente: añadir radios de viento
            },
        }


# ---------------------------------------------------------------------------
# Lectura de CurrentStorms.json y construcción de cada sistema
# ---------------------------------------------------------------------------

def fetch_current_storms() -> list[dict]:
    """Descarga CurrentStorms.json y devuelve la lista de sistemas activos."""
    raw = http_get(NHC_CURRENT_STORMS)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    storms = data.get("activeStorms")
    if not isinstance(storms, list):
        return []
    return [s for s in storms if isinstance(s, dict)]


def kmz_link(node) -> Optional[str]:
    """Devuelve el .kmz de un nodo de recurso (avisos), si existe."""
    if isinstance(node, dict):
        url = node.get("kmzFile")
        if url and url.lower().endswith(".kmz"):
            return url
    return None


def zip5_link(s: dict) -> Optional[str]:
    """Devuelve la URL del zip GIS de 5 días del sistema."""
    for key in ("trackCone", "forecastTrack"):
        node = s.get(key) or {}
        z = node.get("zipFile")
        if z and z.lower().endswith(".zip"):
            return z
    return None


def build_storm_from_json(s: dict) -> StormData:
    """Construye un StormData a partir de una entrada de CurrentStorms.json."""
    sid = (s.get("id") or "").upper()
    name = (s.get("name") or sid).strip()
    classification = (s.get("classification") or "").upper()
    basin = sid[:2] if len(sid) >= 2 else "??"

    wind = to_mph(s.get("intensity"))
    pressure = clean_mb(s.get("pressure"))
    cat_code, cat_desc = classify(classification, wind)

    lat = s.get("latitudeNumeric")
    lon = s.get("longitudeNumeric")
    location = ([lon, lat]
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                else None)

    storm = StormData(
        storm_id=sid,
        storm_name=full_name_es(name, classification, cat_code),
        basin=basin,
        storm_proper_name=name,
        classification=classification,
        current_wind_mph=wind,
        current_pressure_mb=pressure,
        current_category=cat_code,
        current_category_desc=cat_desc,
        current_location=location,
    )

    # Movimiento
    md = s.get("movementDir")
    ms = s.get("movementSpeed")
    if isinstance(ms, (int, float)):
        storm.movement_speed_mph = ms
        storm.movement_deg = md if isinstance(md, (int, float)) else None
        comp = compass_es(md)
        storm.current_movement = (f"{comp} a {int(round(ms))} mph"
                                  if comp else f"{int(round(ms))} mph")

    # Número de aviso y hora de validez
    pub = s.get("publicAdvisory") or {}
    adv = pub.get("advNum")
    if adv:
        try:
            storm.advisory = str(int(adv))
        except (ValueError, TypeError):
            storm.advisory = str(adv).strip()
    storm.valid_at = s.get("lastUpdate") or pub.get("issuance")

    # ---- Geometría: cono/track/puntos desde el zip GIS de 5 días ----
    zurl = zip5_link(s)
    if zurl:
        try:
            cone, track, points = read_5day_zip(zurl)
            storm.cone = cone
            storm.track = track
            storm.points = points
        except Exception as e:
            log.warning("[%s] zip 5day: %s", sid, e)
    else:
        log.warning("[%s] sin zipFile de 5 días en el feed", sid)

    # ---- Avisos Watch/Warning desde KMZ (cuando hay) ----
    ww_url = kmz_link(s.get("windWatchesWarnings"))
    if ww_url:
        try:
            feats = kml_to_alerts(fetch_kml_or_kmz(ww_url))
            if feats:
                storm.alerts = featurecollection(feats)
        except Exception as e:
            log.warning("[%s] avisos: %s", sid, e)

    return storm


# ---------------------------------------------------------------------------
# Escritura y subida a CDN
# ---------------------------------------------------------------------------

def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    tmp.replace(path)


def upload_to_cdn(local_path: Path, key: str) -> bool:
    """Sube un archivo a DO Spaces usando AWS CLI."""
    s3_uri = f"{CDN_PREFIX}{key}"
    cmd = [
        "aws", "s3", "cp", str(local_path), s3_uri,
        "--profile", CDN_PROFILE,
        "--acl", "public-read",
        "--content-type", "application/json",
        "--cache-control", "public, max-age=60",
        "--endpoint-url", CDN_ENDPOINT,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return True
    except subprocess.CalledProcessError as e:
        log.error("Subida CDN falló para %s: %s", key, e.stderr.decode(errors="replace"))
        return False
    except subprocess.TimeoutExpired:
        log.error("Subida CDN timeout para %s", key)
        return False
    except FileNotFoundError:
        log.error("aws CLI no encontrado")
        return False


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_once(output_dir: Path, upload_cdn: bool = False) -> int:
    t0 = time.time()
    log.info("Iniciando pipeline tropical → %s", output_dir)
    if not HAVE_PYSHP:
        log.warning("pyshp no instalado: cono/track/puntos quedarán vacíos")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Descargar el feed oficial de sistemas activos
    try:
        raw_storms = fetch_current_storms()
    except Exception as e:
        log.error("No se pudo descargar CurrentStorms.json: %s", e)
        return 1

    log.info("Sistemas detectados: %d", len(raw_storms))

    # 2) Construir cada sistema (metadata del JSON + geometría de los shapefiles)
    storms: list[StormData] = []
    for s in raw_storms:
        sid = (s.get("id") or "?").upper()
        log.info("Procesando %s (%s · %s)", sid, s.get("name"), s.get("classification"))
        try:
            storms.append(build_storm_from_json(s))
        except Exception as e:
            log.warning("Error construyendo %s: %s", sid, e)

    # 3) Escribir GeoJSONs por sistema
    written: list[Path] = []
    for storm in storms:
        for attr, suffix in [
            ("cone", "_cone.geojson"),
            ("track", "_track.geojson"),
            ("points", "_points.geojson"),
            ("alerts", "_alerts.geojson"),
        ]:
            data = getattr(storm, attr)
            if not data:
                continue
            fpath = output_dir / f"{storm.storm_id}{suffix}"
            write_json(fpath, data)
            written.append(fpath)

    # 4) Escribir índice
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_count": len(storms),
        "storms": [s.to_index_entry() for s in storms],
    }
    index_path = output_dir / "active_storms.json"
    write_json(index_path, index)
    written.append(index_path)

    # 5) Subir a CDN si procede
    if upload_cdn:
        uploaded = sum(1 for p in written if upload_to_cdn(p, p.name))
        log.info("Subidos a CDN: %d/%d", uploaded, len(written))

    log.info("Pipeline tropical completado en %.1fs (%d sistemas, %d archivos)",
             time.time() - t0, len(storms), len(written))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline tropical Canal Meteo")
    parser.add_argument("--once", action="store_true",
                        help="Ejecutar una sola vez (recomendado, usar con cron)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Directorio de salida (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--upload-cdn", action="store_true",
                        help="Subir resultados a DO Spaces CDN")
    args = parser.parse_args()

    if not args.once:
        log.error("Solo se admite modo --once (usar cron para periodicidad)")
        return 2

    return run_once(args.output_dir, upload_cdn=args.upload_cdn)


if __name__ == "__main__":
    sys.exit(main())
