#!/usr/bin/env python3
"""
radar_compose_pipeline.py
─────────────────────────
Compone radar MRMS sobre basemap Mapbox Static en JPGs ligeros.
Genera manifest COMPATIBLE con el formato de MapasFetcher actual
para que el Roku NO necesite cambios.

Salida en CDN:
  - data/radar_conus/basemap.jpg     (cached 24h, solo se regenera 1 vez/día)
  - data/radar_conus/frame_NN.jpg    (12 frames)
  - data/radar_conus/manifest.json   (formato compatible mapas v1.1)

Cron: cada 5 minutos
"""

import io
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

CDN_BASE = "https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com"
S3_BUCKET = "canalmeteo-public"
S3_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
AWS_PROFILE = "do-tor1"

OUTPUT_PREFIX = "data/radar_conus"
LOCAL_DIR = Path("/tmp/radar_compose")
LOCAL_DIR.mkdir(exist_ok=True)

MANIFEST_MRMS = f"{CDN_BASE}/data/mrms/manifest.json"
MRMS_BOUNDS = {"north": 55.0, "south": 20.0, "west": -130.0, "east": -60.0}
CONUS_BOUNDS = {"north": 50.0, "south": 24.0, "west": -125.0, "east": -66.0}

OUT_WIDTH = 1280
OUT_HEIGHT = 720

MAPBOX_TOKEN = "pk.eyJ1IjoiYWxiZXJ0ZWx0aWVtcG8iLCJhIjoiY21rM2pqa29zMGd6NjNncHdlMWZ1NTNlayJ9.0d2lAZ-CmqEuoPe_h2JEHA"
MAPBOX_USERNAME = "alberteltiempo"
MAPBOX_STYLE = "cmnc3i60p005e01sj1qa3hyc1"

NUM_FRAMES = 12
RADAR_OPACITY = 0.80

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/canalmeteo/radar_compose.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def descargar_basemap_mapbox():
    """Descarga el basemap Mapbox 1 vez por día (caché local 24h)."""
    local_path = LOCAL_DIR / "basemap.jpg"

    if local_path.exists():
        edad_horas = (datetime.now().timestamp() - local_path.stat().st_mtime) / 3600
        if edad_horas < 24:
            log.info(f"  Basemap en caché ({edad_horas:.1f}h)")
            return local_path

    b = CONUS_BOUNDS
    bbox_str = f"[{b['west']},{b['south']},{b['east']},{b['north']}]"

    url = (
        f"https://api.mapbox.com/styles/v1/{MAPBOX_USERNAME}/{MAPBOX_STYLE}/static/"
        f"{bbox_str}/{OUT_WIDTH}x{OUT_HEIGHT}@2x"
        f"?access_token={MAPBOX_TOKEN}&logo=false&attribution=false"
    )
    log.info(f"  Descargando basemap Mapbox CONUS...")

    response = requests.get(url, timeout=30)
    if response.status_code != 200:
        log.error(f"  ✗ Mapbox error {response.status_code}: {response.text[:200]}")
        return None

    img = Image.open(io.BytesIO(response.content)).convert('RGB')
    if img.size != (OUT_WIDTH, OUT_HEIGHT):
        img = img.resize((OUT_WIDTH, OUT_HEIGHT), Image.LANCZOS)
    img.save(local_path, 'JPEG', quality=88, optimize=True)
    log.info(f"  ✓ Basemap: {local_path.stat().st_size // 1024} KB")

    subir_a_cdn(local_path, f"{OUTPUT_PREFIX}/basemap.jpg", "image/jpeg",
                cache_control="max-age=86400")

    return local_path


def descargar_mrms_manifest():
    try:
        r = requests.get(MANIFEST_MRMS, timeout=15)
        return r.json()
    except Exception as e:
        log.error(f"Error leyendo manifest MRMS: {e}")
        return None


def recortar_mrms_a_conus(png_bytes):
    """Recorta PNG MRMS (3500×1750) a bounds CONUS y reescala a 1280×720."""
    img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    w, h = img.size

    m = MRMS_BOUNDS
    c = CONUS_BOUNDS

    left_pct = (c['west'] - m['west']) / (m['east'] - m['west'])
    right_pct = (c['east'] - m['west']) / (m['east'] - m['west'])
    top_pct = (m['north'] - c['north']) / (m['north'] - m['south'])
    bottom_pct = (m['north'] - c['south']) / (m['north'] - m['south'])

    left_px = int(left_pct * w)
    right_px = int(right_pct * w)
    top_px = int(top_pct * h)
    bottom_px = int(bottom_pct * h)

    cropped = img.crop((left_px, top_px, right_px, bottom_px))
    cropped = cropped.resize((OUT_WIDTH, OUT_HEIGHT), Image.LANCZOS)
    return cropped


def componer_frame(basemap_path, mrms_png_bytes, output_path):
    """Compone basemap + radar y guarda JPG ligero."""
    base = Image.open(basemap_path).convert('RGBA')
    radar = recortar_mrms_a_conus(mrms_png_bytes)

    if RADAR_OPACITY < 1.0:
        alpha = radar.split()[-1]
        alpha = alpha.point(lambda p: int(p * RADAR_OPACITY))
        radar.putalpha(alpha)

    base.paste(radar, (0, 0), radar)
    final = base.convert('RGB')
    final.save(output_path, 'JPEG', quality=85, optimize=True)


def subir_a_cdn(local_path, s3_key, content_type, cache_control="max-age=120"):
    cmd = [
        'aws', 's3', 'cp', str(local_path),
        f's3://{S3_BUCKET}/{s3_key}',
        '--profile', AWS_PROFILE,
        '--endpoint-url', S3_ENDPOINT,
        '--acl', 'public-read',
        '--content-type', content_type,
        '--cache-control', cache_control,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"  ✗ Error subiendo {s3_key}: {result.stderr}")
        return False
    return True


def main():
    log.info("═══ Generando RADAR compuesto CONUS ═══")

    basemap_path = descargar_basemap_mapbox()
    if not basemap_path:
        return 1

    manifest_mrms = descargar_mrms_manifest()
    if not manifest_mrms or 'frames' not in manifest_mrms:
        log.error("Manifest MRMS no disponible")
        return 1

    frames_mrms = sorted(manifest_mrms['frames'], key=lambda f: f.get('timestamp', 0))
    frames_recent = frames_mrms[-NUM_FRAMES:]
    if not frames_recent:
        log.error("No hay frames MRMS recientes")
        return 1

    log.info(f"  Procesando {len(frames_recent)} frames...")

    frame_urls = []
    timestamps = []

    for i, frame in enumerate(frames_recent):
        url = frame.get('url')
        if not url:
            continue
        if 'cdn.' not in url:
            url = url.replace('sfo3.digitaloceanspaces.com', 'sfo3.cdn.digitaloceanspaces.com')

        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                log.warning(f"  ✗ Frame {i}: HTTP {r.status_code}")
                continue
        except Exception as e:
            log.warning(f"  ✗ Frame {i} fallo descarga: {e}")
            continue

        local_jpg = LOCAL_DIR / f"frame_{i:02d}.jpg"
        componer_frame(basemap_path, r.content, local_jpg)

        s3_key = f"{OUTPUT_PREFIX}/frame_{i:02d}.jpg"
        if subir_a_cdn(local_jpg, s3_key, "image/jpeg"):
            cdn_url = f"{CDN_BASE}/{s3_key}"
            frame_urls.append(cdn_url)
            timestamps.append(frame.get('iso', ''))
            size_kb = local_jpg.stat().st_size // 1024
            log.info(f"  ✓ Frame {i:02d}: {size_kb} KB")

    if not frame_urls:
        log.error("Ningún frame procesado")
        return 1

    # Manifest COMPATIBLE con el formato MapasFetcher v1.1 (array "mapas")
    ultima = timestamps[-1] if timestamps else datetime.now(timezone.utc).isoformat()
    manifest = {
        'version': '1.1',
        'actualizado': datetime.now(timezone.utc).isoformat(),
        'mapas': [
            {
                'id': 'radar_conus',
                'nombre': 'Radar',
                'descripcion': 'Reflectividad MRMS · Estados Unidos',
                'categoria': 'radar',
                'tipo': 'loop',
                # basemap_url vacío - basemap ya está incluido en cada frame
                'basemap_url': '',
                'frames': frame_urls,
                'frame_ultimo': frame_urls[-1],
                'actualizado': ultima,
                'tiene_animacion': True,
                'intervalo_ms': 400,
                'fuente': 'NOAA MRMS + Mapbox',
            }
        ]
    }

    manifest_local = LOCAL_DIR / "manifest.json"
    with open(manifest_local, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    if subir_a_cdn(manifest_local, f"{OUTPUT_PREFIX}/manifest.json",
                   "application/json", cache_control="max-age=60"):
        log.info(f"  ☁️  Manifest: {CDN_BASE}/{OUTPUT_PREFIX}/manifest.json")

    log.info(f"═══ Complete · {len(frame_urls)} frames ═══")
    return 0


if __name__ == '__main__':
    exit(main())
