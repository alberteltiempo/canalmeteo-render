#!/usr/bin/env python3
"""
regional_satellite_compositor.py v3 (GIBS IR edition)
═══════════════════════════════════════════════════════════════════
Genera frames de satellite IR (Band 13 enhanced) por region usando
GIBS NASA WMS.

v3 changes:
  - Producto principal: goes-east-ir (Band 13 enhanced color)
  - Latencia GIBS: 90 minutos (antes 30) para garantizar datos completos
  - Validacion de tiles negros: descarta frames con >5% pixels negros
  - Mantiene goes-east-geocolor opcional como fallback

Output:  /data/satellite-regional/{region}/{product}_{ts}.jpg
Manifest: /data/satellite-regional/manifest-{region}.json
═══════════════════════════════════════════════════════════════════
"""

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone, timedelta
from io import BytesIO

import numpy as np
import requests
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────
CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
CDN_BASE_URL = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'

REGIONAL_BASE = 'data/satellite-regional'

OUT_WIDTH = 1920
OUT_HEIGHT = 1080

# Productos GIBS soportados
GIBS_LAYERS = {
    'goes-east-ir':        'GOES-East_ABI_Band13_Clean_Infrared',
    'goes-east-geocolor':  'GOES-East_ABI_GeoColor',
    'goes-west-ir':        'GOES-West_ABI_Band13_Clean_Infrared',
    'goes-west-geocolor':  'GOES-West_ABI_GeoColor',
}

# IR como producto principal (mejor para broadcast meteo)
PRODUCTS_TO_GENERATE = ['goes-east-ir']

# Bboxes 16:9
REGIONS = {
    'noreste':       {'west': -86.22, 'east': -65.78, 'south': 36.00, 'north': 47.50},
    'sureste':       {'west': -92.00, 'east': -75.00, 'south': 29.22, 'north': 38.78},
    'florida':       {'west': -89.53, 'east': -77.97, 'south': 24.50, 'north': 31.00},
    'grandes-lagos': {'west': -93.00, 'east': -75.00, 'south': 39.94, 'north': 50.06},
    'texas':         {'west': -109.76, 'east': -90.74, 'south': 25.80, 'north': 36.50},
    'medio-oeste':   {'west': -107.06, 'east': -83.94, 'south': 36.00, 'north': 49.00},
    'suroeste':      {'west': -118.78, 'east': -99.22, 'south': 31.00, 'north': 42.00},
    'noroeste':      {'west': -125.00, 'east': -110.00, 'south': 40.78, 'north': 49.22},
}

# GIBS frame interval (10 min standard)
FRAME_INTERVAL_MIN = 10
NUM_FRAMES_TO_FETCH = 12  # ~2 horas de animacion
GIBS_LATENCY_MIN = 90  # GIBS retraso seguro (probado: 30=fail, 60=intermitente, 90=OK)

# Validacion de calidad
MAX_BLACK_RATIO = 0.05   # max 5% pixels negros (gap de tiles)
MIN_FILE_SIZE_KB = 30    # JPEG IR real es >50KB

# Cleanup
MAX_AGE_HOURS = 6


# ─── GIBS WMS ─────────────────────────────────────────────────────
def fetch_gibs_image(layer: str, bbox: dict, ts_iso: str, output_path: str) -> bool:
    """Descarga imagen GIBS WMS para un bbox y timestamp dados."""
    bbox_str = f"{bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']}"

    url = (
        "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        "?SERVICE=WMS"
        "&REQUEST=GetMap"
        "&VERSION=1.3.0"
        f"&LAYERS={layer}"
        "&CRS=EPSG:4326"
        f"&BBOX={bbox_str}"
        f"&WIDTH={OUT_WIDTH}"
        f"&HEIGHT={OUT_HEIGHT}"
        "&FORMAT=image/jpeg"
        f"&TIME={ts_iso}"
    )

    try:
        r = requests.get(url, timeout=60,
                        headers={'User-Agent': 'CanalMeteoTV/1.0 (contacto@canalmeteo.tv)'})
        if r.status_code != 200:
            log.warning(f"  HTTP {r.status_code}: {url[:120]}")
            return False

        ctype = r.headers.get('content-type', '')
        if 'image' not in ctype.lower():
            log.warning(f"  Bad content-type {ctype}")
            return False

        # Validar tamaño minimo
        if len(r.content) < MIN_FILE_SIZE_KB * 1024:
            log.warning(f"  Image too small ({len(r.content)//1024} KB) - probably empty")
            return False

        with open(output_path, 'wb') as f:
            f.write(r.content)

        # Validar que NO sea mayoritariamente negro
        if not validate_image_not_black(output_path):
            log.warning(f"  Image too black, discarding")
            try:
                os.remove(output_path)
            except Exception:
                pass
            return False

        return True

    except Exception as e:
        log.warning(f"  Fetch error: {e}")
        return False


def validate_image_not_black(path: str) -> bool:
    """Retorna True si la imagen tiene <MAX_BLACK_RATIO de pixels negros puros."""
    try:
        img = Image.open(path).convert('RGB')
        arr = np.array(img)
        # Pixel "negro" = los 3 canales <10
        is_black = np.all(arr < 10, axis=2)
        ratio = is_black.sum() / is_black.size
        return ratio < MAX_BLACK_RATIO
    except Exception as e:
        log.warning(f"  Validate error: {e}")
        return True  # En caso de error, aceptar para no bloquear todo


def get_gibs_timestamps() -> list[tuple[str, str]]:
    """Genera timestamps con latencia adecuada (cada 10min)."""
    now = datetime.now(timezone.utc)
    minute_floor = (now.minute // FRAME_INTERVAL_MIN) * FRAME_INTERVAL_MIN
    latest = now.replace(minute=minute_floor, second=0, microsecond=0) - timedelta(minutes=GIBS_LATENCY_MIN)

    timestamps = []
    for i in range(NUM_FRAMES_TO_FETCH):
        t = latest - timedelta(minutes=FRAME_INTERVAL_MIN * i)
        ts_filename = t.strftime('%Y%m%d%H%M')
        ts_iso = t.strftime('%Y-%m-%dT%H:%M:00Z')
        timestamps.append((ts_filename, ts_iso))

    return timestamps


# ─── CDN helpers ──────────────────────────────────────────────────
def upload_to_cdn(filepath: str, cdn_key: str, content_type: str = 'image/jpeg',
                  cache_control: str = 'public, max-age=300') -> bool:
    cmd = [
        'aws', 's3', 'cp', filepath,
        f's3://{CDN_BUCKET}/{cdn_key}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', content_type,
        '--cache-control', cache_control,
        '--endpoint-url', CDN_ENDPOINT,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except Exception:
        return False


def cdn_list(prefix: str) -> list[str]:
    cmd = [
        'aws', 's3', 'ls',
        f's3://{CDN_BUCKET}/{prefix}',
        '--profile', AWS_PROFILE,
        '--endpoint-url', CDN_ENDPOINT,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return []
        files = []
        for line in result.stdout.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) >= 4:
                files.append(parts[-1])
        return files
    except Exception:
        return []


def cdn_object_exists(cdn_key: str) -> bool:
    cmd = ['aws', 's3api', 'head-object',
           '--bucket', CDN_BUCKET,
           '--key', cdn_key,
           '--profile', AWS_PROFILE,
           '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def cdn_delete(cdn_key: str) -> bool:
    cmd = ['aws', 's3', 'rm', f's3://{CDN_BUCKET}/{cdn_key}',
           '--profile', AWS_PROFILE,
           '--endpoint-url', CDN_ENDPOINT]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return True
    except Exception:
        return False


# ─── Manifest ─────────────────────────────────────────────────────
def build_regional_manifest(region_id: str) -> dict:
    manifest = {
        'generated': datetime.now(timezone.utc).isoformat(),
        'region': region_id,
        'bounds': REGIONS[region_id],
        'width': OUT_WIDTH,
        'height': OUT_HEIGHT,
        'source': 'GIBS NASA',
        'products': {},
    }

    for product in PRODUCTS_TO_GENERATE:
        prefix = f'{REGIONAL_BASE}/{region_id}/{product}_'
        files = cdn_list(prefix)
        frames = []
        for fname in files:
            m = re.search(r'_(\d{12})\.jpg$', fname)
            if not m:
                continue
            ts = m.group(1)
            try:
                dt = datetime.strptime(ts, '%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                frames.append({
                    'time': int(dt.timestamp()),
                    'ts': ts,
                    'url': f'{CDN_BASE_URL}/{REGIONAL_BASE}/{region_id}/{fname}',
                })
            except ValueError:
                continue

        frames.sort(key=lambda f: f['time'])
        manifest['products'][product] = frames

    return manifest


def cleanup_old_regional_frames(region_id: str, max_age_hours: int = MAX_AGE_HOURS):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    cutoff_ts = cutoff.strftime('%Y%m%d%H%M')

    for product in PRODUCTS_TO_GENERATE:
        prefix = f'{REGIONAL_BASE}/{region_id}/{product}_'
        files = cdn_list(prefix)
        for fname in files:
            m = re.search(r'_(\d{12})\.jpg$', fname)
            if not m:
                continue
            file_ts = m.group(1)
            if file_ts < cutoff_ts:
                full_key = f'{REGIONAL_BASE}/{region_id}/{fname}'
                cdn_delete(full_key)
                log.info(f"  🗑️  {region_id}/{fname}")


# ─── Procesamiento ────────────────────────────────────────────────
def process_region(region_id: str, bbox: dict, timestamps: list[tuple[str, str]]) -> dict:
    log.info(f"\n[{region_id}] bbox=W={bbox['west']} S={bbox['south']} E={bbox['east']} N={bbox['north']}")
    results = {'ok': 0, 'cached': 0, 'failed': 0, 'rejected': 0}

    for product in PRODUCTS_TO_GENERATE:
        layer = GIBS_LAYERS.get(product)
        if not layer:
            log.warning(f"  Unknown product: {product}")
            continue

        for ts_filename, ts_iso in timestamps:
            cdn_key = f'{REGIONAL_BASE}/{region_id}/{product}_{ts_filename}.jpg'

            if cdn_object_exists(cdn_key):
                results['cached'] += 1
                continue

            tmp_path = f'/tmp/gibs_{region_id}_{product}_{ts_filename}.jpg'
            if not fetch_gibs_image(layer, bbox, ts_iso, tmp_path):
                # Distinguir si fallo descarga vs validacion (rejected)
                if os.path.exists(tmp_path):
                    results['failed'] += 1
                else:
                    results['rejected'] += 1
                continue

            if upload_to_cdn(tmp_path, cdn_key):
                results['ok'] += 1
                log.info(f"  ✅ {product}_{ts_filename}")
            else:
                results['failed'] += 1

            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return results


# ─── Main ─────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    log.info("=== Regional Satellite Compositor v3 (GIBS IR) ===")
    log.info(f"Productos: {PRODUCTS_TO_GENERATE}")
    log.info(f"Latencia GIBS: {GIBS_LATENCY_MIN} min")

    timestamps = get_gibs_timestamps()
    log.info(f"Timestamps: {len(timestamps)} frames, latest={timestamps[0][0]}, oldest={timestamps[-1][0]}")

    total_ok = 0
    total_cached = 0
    total_failed = 0
    total_rejected = 0

    for region_id, bbox in REGIONS.items():
        results = process_region(region_id, bbox, timestamps)
        total_ok += results['ok']
        total_cached += results['cached']
        total_failed += results['failed']
        total_rejected += results['rejected']

    log.info(f"\n  Procesados: {total_ok} nuevos, {total_cached} cached, {total_failed} fail, {total_rejected} rejected")

    # Cleanup + manifest por region
    log.info("\n  Generando manifests regionales...")
    for region_id in REGIONS:
        cleanup_old_regional_frames(region_id)

        manifest = build_regional_manifest(region_id)
        manifest_path = f'/tmp/sat_regional_manifest_{region_id}.json'
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f)

        cdn_key = f'{REGIONAL_BASE}/manifest-{region_id}.json'
        if upload_to_cdn(manifest_path, cdn_key, 'application/json',
                        'public, max-age=60'):
            n_total = sum(len(v) for v in manifest['products'].values())
            log.info(f"  ✅ manifest-{region_id}.json ({n_total} frames)")
        try:
            os.remove(manifest_path)
        except Exception:
            pass

    log.info(f"\n=== Done in {time.time()-t0:.1f}s ===")
    return 0


if __name__ == '__main__':
    exit(main())
