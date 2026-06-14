#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canal Meteo · Pipeline de Sistemas Tropicales (NHC)
====================================================

Descarga el KML maestro nhc_active.kml del National Hurricane Center,
extrae todos los recursos por sistema (cono, trayectoria, puntos de pronóstico,
alertas Watch/Warning y radios de viento) y genera GeoJSONs estructurados
listos para consumir desde canalmeteo.tv y tormenta.canalmeteo.tv.

Salidas (en /var/www/canalmeteo-public/tropical/ y CDN data/tropical/):
  - active_storms.json            → índice de sistemas activos con metadata
  - <storm_id>_cone.geojson       → cono de incertidumbre
  - <storm_id>_track.geojson      → trayectoria oficial (línea)
  - <storm_id>_points.geojson     → puntos de pronóstico (con viento, presión, categoría)
  - <storm_id>_alerts.geojson     → alertas Watch/Warning
  - <storm_id>_wind_radii.geojson → radios de viento (34/50/64 kt)

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
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

NHC_ACTIVE_KML = "https://www.nhc.noaa.gov/gis/kml/nhc_active.kml"
USER_AGENT = "CanalMeteoTV/1.0 (https://canalmeteo.tv; contacto@canalmeteo.tv)"
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

DEFAULT_OUTPUT_DIR = Path("/var/www/canalmeteo-public/tropical")
CDN_PREFIX = "s3://canalmeteo-public/data/tropical/"
CDN_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CDN_PROFILE = "do-tor1"

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
# Utilidades HTTP
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
# Parsing genérico de coordenadas KML
# ---------------------------------------------------------------------------

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


def find_all(root: ET.Element, path: str) -> list[ET.Element]:
    """find_all con namespace KML."""
    return root.findall(path, KML_NS)


# ---------------------------------------------------------------------------
# Clasificación de huracán
# ---------------------------------------------------------------------------

def saffir_simpson(wind_mph: Optional[float]) -> tuple[str, str]:
    """Devuelve (código, descripción) según escala Saffir-Simpson."""
    if wind_mph is None:
        return ("UNK", "Desconocido")
    for threshold, code, desc in SAFFIR_SIMPSON:
        if wind_mph < threshold:
            return (code, desc)
    return ("CAT5", "Huracán categoría 5 (mayor)")


# ---------------------------------------------------------------------------
# Parsing de descripciones HTML del NHC
# ---------------------------------------------------------------------------

# El NHC empaqueta los detalles del pronóstico dentro de tablas HTML en
# <description>. Extraemos los campos relevantes con regex.

def parse_nhc_html(desc: str) -> dict:
    """Extrae campos del HTML <description> de un punto de pronóstico."""
    if not desc:
        return {}

    # Limpiar entidades comunes
    txt = (desc
           .replace("&nbsp;", " ")
           .replace("&amp;", "&")
           .replace("&lt;", "<")
           .replace("&gt;", ">"))

    # Quitar tags pero conservar saltos
    txt = re.sub(r"<\s*br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"</\s*tr\s*>", "\n", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"[ \t]+", " ", txt)

    out: dict = {}

    def grab(pattern: str, key: str, cast=str):
        m = re.search(pattern, txt, flags=re.I)
        if m:
            try:
                out[key] = cast(m.group(1).strip())
            except (ValueError, TypeError):
                pass

    grab(r"Advisory\s*#?\s*([A-Z0-9.\-]+)", "advisory")
    grab(r"Valid\s*at:\s*([^\n]+?)(?:Location|Maximum|Movement|$)", "valid_at")
    grab(r"Location:\s*([0-9.\-]+\s*[NSEW]\s*[0-9.\-]+\s*[NSEW])", "location")
    grab(r"Maximum\s*Wind:\s*([0-9]+)\s*mph", "max_wind_mph", int)
    grab(r"Wind\s*Gusts?:\s*([0-9]+)\s*mph", "gusts_mph", int)
    grab(r"Movement:\s*([^\n]+?)(?:Pressure|Maximum|$)", "movement")
    grab(r"Pressure:\s*([0-9]+)\s*mb", "pressure_mb", int)
    grab(r"(\d{1,3})\s*hr\s*Forecast", "forecast_hour", int)

    return out


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

@dataclass
class StormResource:
    """Un recurso enlazado desde nhc_active.kml para un sistema concreto."""
    storm_id: str
    storm_name: str
    kind: str            # 'cone' | 'track' | 'points' | 'alerts' | 'wind_radii'
    url: str


@dataclass
class StormData:
    """Datos consolidados de un sistema tropical activo."""
    storm_id: str             # Ej. AL052024
    storm_name: str           # Ej. "Tropical Storm Helene"
    basin: str                # AL | EP | CP
    current_wind_mph: Optional[int] = None
    current_pressure_mb: Optional[int] = None
    current_category: str = "UNK"
    current_category_desc: str = "Desconocido"
    current_location: Optional[list[float]] = None  # [lon, lat]
    advisory: Optional[str] = None
    valid_at: Optional[str] = None
    cone: Optional[dict] = None        # GeoJSON FeatureCollection
    track: Optional[dict] = None
    points: Optional[dict] = None
    alerts: Optional[dict] = None
    wind_radii: Optional[dict] = None

    def to_index_entry(self) -> dict:
        return {
            "storm_id": self.storm_id,
            "storm_name": self.storm_name,
            "basin": self.basin,
            "current_wind_mph": self.current_wind_mph,
            "current_pressure_mb": self.current_pressure_mb,
            "current_category": self.current_category,
            "current_category_desc": self.current_category_desc,
            "current_location": self.current_location,
            "advisory": self.advisory,
            "valid_at": self.valid_at,
            "files": {
                "cone": f"{self.storm_id}_cone.geojson" if self.cone else None,
                "track": f"{self.storm_id}_track.geojson" if self.track else None,
                "points": f"{self.storm_id}_points.geojson" if self.points else None,
                "alerts": f"{self.storm_id}_alerts.geojson" if self.alerts else None,
                "wind_radii": f"{self.storm_id}_wind_radii.geojson" if self.wind_radii else None,
            },
        }


# ---------------------------------------------------------------------------
# Detección de tipo de recurso desde la URL
# ---------------------------------------------------------------------------

STORM_ID_RE = re.compile(r"(?:^|[/\W_])(AL|EP|CP)(\d{2})(\d{4})?(?=[\W_]|$)", re.I)


def detect_resource_kind(url: str) -> Optional[str]:
    """Clasifica un href del KML maestro según patrones del NHC.

    El NHC usa varios formatos a lo largo de los años:
      - AL092024_CONE_latest.kmz   (formato API moderno)
      - al092024_5day_cone.kmz     (formato GIS clásico)
      - al092024_fcst_track.kmz
    """
    u = url.lower()
    # Orden importa por solapamientos.
    if re.search(r"(_cone|5day_cone|cone_latest)", u):
        return "cone"
    if re.search(r"(_pts|_pgn|fcst_pts|track_pts|pts_latest|points_latest)", u):
        return "points"
    if re.search(r"(_track|track_latest|fcst_track|track_lin|_lin)", u):
        return "track"
    if re.search(r"(_ww|ww_latest|watches?_warnings?)", u):
        return "alerts"
    if re.search(r"(_radii|radii_latest|wind_radii|wind_field)", u):
        return "wind_radii"
    return None


def detect_storm_id(url: str) -> Optional[str]:
    """Extrae el storm_id (ej. AL052024) de un URL."""
    m = STORM_ID_RE.search(url)
    if not m:
        return None
    basin = m.group(1).upper()
    num = m.group(2)
    year = m.group(3) or str(datetime.now(timezone.utc).year)
    return f"{basin}{num}{year}"


# ---------------------------------------------------------------------------
# Parsers por tipo de KML
# ---------------------------------------------------------------------------

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
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],
                },
            })
    return features


def kml_to_lines(kml_text: str) -> list[dict]:
    """Convierte LineStrings de un KML en lista de Features GeoJSON."""
    features: list[dict] = []
    try:
        root = ET.fromstring(kml_text)
    except ET.ParseError as e:
        log.warning("KML inválido: %s", e)
        return features

    for placemark in find_all(root, ".//kml:Placemark"):
        name_el = placemark.find("kml:name", KML_NS)
        name = name_el.text if name_el is not None else ""
        for ls in find_all(placemark, ".//kml:LineString"):
            coords_el = ls.find("kml:coordinates", KML_NS)
            if coords_el is None or not coords_el.text:
                continue
            line = parse_coords(coords_el.text)
            if len(line) < 2:
                continue
            features.append({
                "type": "Feature",
                "properties": {"name": (name or "").strip()},
                "geometry": {
                    "type": "LineString",
                    "coordinates": line,
                },
            })
    return features


def kml_to_points(kml_text: str) -> list[dict]:
    """Convierte puntos de pronóstico en Features GeoJSON con metadata."""
    features: list[dict] = []
    try:
        root = ET.fromstring(kml_text)
    except ET.ParseError as e:
        log.warning("KML inválido: %s", e)
        return features

    for placemark in find_all(root, ".//kml:Placemark"):
        pt = placemark.find(".//kml:Point/kml:coordinates", KML_NS)
        if pt is None or not pt.text:
            continue
        coords = parse_coords(pt.text)
        if not coords:
            continue
        lon, lat = coords[0]

        name_el = placemark.find("kml:name", KML_NS)
        desc_el = placemark.find("kml:description", KML_NS)
        name = (name_el.text or "").strip() if name_el is not None else ""
        desc = (desc_el.text or "").strip() if desc_el is not None else ""

        meta = parse_nhc_html(desc)
        wind = meta.get("max_wind_mph")
        cat_code, cat_desc = saffir_simpson(wind)

        props = {
            "name": name,
            "advisory": meta.get("advisory"),
            "valid_at": meta.get("valid_at"),
            "max_wind_mph": wind,
            "gusts_mph": meta.get("gusts_mph"),
            "pressure_mb": meta.get("pressure_mb"),
            "movement": meta.get("movement"),
            "forecast_hour": meta.get("forecast_hour"),
            "category": cat_code,
            "category_desc": cat_desc,
        }

        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })

    return features


def kml_to_alerts(kml_text: str) -> list[dict]:
    """Convierte alertas Watch/Warning en Features GeoJSON con tipo clasificado."""
    features: list[dict] = []
    polygons = kml_to_polygons(kml_text)
    for f in polygons:
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
# Procesado del KML maestro
# ---------------------------------------------------------------------------

def collect_resources(master_kml: str, base_url: str) -> dict[str, list[StormResource]]:
    """Lee nhc_active.kml y agrupa los hrefs hijo por storm_id."""
    resources: dict[str, list[StormResource]] = {}

    try:
        root = ET.fromstring(master_kml)
    except ET.ParseError as e:
        log.error("nhc_active.kml inválido: %s", e)
        return resources

    # Mapa de nombres de sistema: buscamos en Document/Folder/name + NetworkLinks adyacentes
    storm_names: dict[str, str] = {}

    for nl in find_all(root, ".//kml:NetworkLink"):
        href_el = nl.find(".//kml:href", KML_NS)
        name_el = nl.find("kml:name", KML_NS)
        if href_el is None or not href_el.text:
            continue
        href_raw = href_el.text.strip()
        # Absolutizar
        href = href_raw if href_raw.startswith("http") else urljoin(base_url, href_raw)

        sid = detect_storm_id(href)
        if not sid:
            continue
        kind = detect_resource_kind(href)
        if not kind:
            continue

        nl_name = (name_el.text or "").strip() if name_el is not None else ""
        if nl_name and sid not in storm_names:
            # Limpiar el nombre típico "Cone of Uncertainty: Tropical Storm Helene"
            cleaned = re.sub(r"^.*?:\s*", "", nl_name).strip()
            if cleaned and cleaned.lower() not in ("track", "cone", "points", "watches", "warnings"):
                storm_names[sid] = cleaned

        resources.setdefault(sid, []).append(StormResource(
            storm_id=sid,
            storm_name=storm_names.get(sid, sid),
            kind=kind,
            url=href,
        ))

    # Propagar nombres ya descubiertos
    for sid, res_list in resources.items():
        if sid in storm_names:
            for r in res_list:
                r.storm_name = storm_names[sid]

    return resources


def build_storm_data(storm_id: str, res_list: list[StormResource]) -> StormData:
    """Descarga todos los recursos de un sistema y arma su StormData."""
    name = res_list[0].storm_name if res_list else storm_id
    basin = storm_id[:2] if len(storm_id) >= 2 else "??"

    storm = StormData(storm_id=storm_id, storm_name=name, basin=basin)

    for res in res_list:
        try:
            kml_text = fetch_kml_or_kmz(res.url)
        except Exception as e:
            log.warning("[%s] %s: error descargando %s: %s",
                        storm_id, res.kind, res.url, e)
            continue

        try:
            if res.kind == "cone":
                feats = kml_to_polygons(kml_text)
                if feats:
                    storm.cone = featurecollection(feats)

            elif res.kind == "track":
                feats = kml_to_lines(kml_text)
                if feats:
                    storm.track = featurecollection(feats)

            elif res.kind == "points":
                feats = kml_to_points(kml_text)
                if feats:
                    storm.points = featurecollection(feats)
                    # Inferir condiciones actuales (hora 0)
                    current = None
                    for f in feats:
                        fh = f["properties"].get("forecast_hour")
                        if fh == 0 or fh is None and current is None:
                            current = f
                            break
                    if current is None and feats:
                        current = feats[0]
                    if current:
                        p = current["properties"]
                        storm.current_wind_mph = p.get("max_wind_mph")
                        storm.current_pressure_mb = p.get("pressure_mb")
                        storm.current_category = p.get("category", "UNK")
                        storm.current_category_desc = p.get("category_desc", "Desconocido")
                        storm.current_location = current["geometry"]["coordinates"]
                        storm.advisory = p.get("advisory")
                        storm.valid_at = p.get("valid_at")

            elif res.kind == "alerts":
                feats = kml_to_alerts(kml_text)
                if feats:
                    storm.alerts = featurecollection(feats)

            elif res.kind == "wind_radii":
                feats = kml_to_polygons(kml_text)
                if feats:
                    storm.wind_radii = featurecollection(feats)

        except Exception as e:
            log.warning("[%s] %s: error parseando %s",
                        storm_id, res.kind, e)

    return storm


def featurecollection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


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
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Descargar KML maestro
    try:
        master = fetch_kml_or_kmz(NHC_ACTIVE_KML)
    except Exception as e:
        log.error("No se pudo descargar nhc_active.kml: %s", e)
        return 1

    # 2) Agrupar recursos por sistema
    resources = collect_resources(master, NHC_ACTIVE_KML)
    log.info("Sistemas detectados: %d", len(resources))

    storms: list[StormData] = []
    for sid, res_list in resources.items():
        log.info("Procesando %s (%d recursos)", sid, len(res_list))
        storms.append(build_storm_data(sid, res_list))

    # 3) Escribir GeoJSONs por sistema
    written: list[Path] = []
    for storm in storms:
        for attr, suffix in [
            ("cone", "_cone.geojson"),
            ("track", "_track.geojson"),
            ("points", "_points.geojson"),
            ("alerts", "_alerts.geojson"),
            ("wind_radii", "_wind_radii.geojson"),
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
        uploaded = 0
        for p in written:
            if upload_to_cdn(p, p.name):
                uploaded += 1
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
