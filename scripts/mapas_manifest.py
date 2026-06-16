#!/usr/bin/env python3
"""
mapas_manifest.py v3
────────────────────
Genera manifest unificado para la sección MAPAS de la Roku app.
Ahora con basemap_url por cada mapa.

Output: s3://canalmeteo-public/data/mapas/manifest.json
Cron: cada 5 minutos
"""

import json
import logging
import subprocess
from datetime import datetime, timezone

CDN_BASE = "https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com"
S3_BUCKET = "canalmeteo-public"
S3_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
AWS_PROFILE = "do-tor1"
OUTPUT_KEY = "data/mapas/manifest.json"
LOCAL_TMP = "/tmp/mapas_manifest.json"

MANIFEST_MRMS = f"{CDN_BASE}/data/mrms/manifest.json"
MANIFEST_SATELLITE = f"{CDN_BASE}/data/satellite/manifest.json"

# Basemaps en CDN
BASEMAP_MRMS = f"{CDN_BASE}/data/mapas/basemap_mrms.png"
BASEMAP_SATELLITE = f"{CDN_BASE}/data/mapas/basemap_satellite.png"

MAX_FRAMES = 12

SATELITE_PRODUCTOS = [
    {
        'manifest_key': 'goes-east-geocolor',
        'id': 'satelite_geocolor',
        'nombre': 'Geocolor',
        'descripcion': 'GOES-East · color real',
        'intervalo_ms': 400,
        'basemap': BASEMAP_SATELLITE,
    },
    {
        'manifest_key': 'goes-east-ir',
        'id': 'satelite_ir',
        'nombre': 'Infrarrojo',
        'descripcion': 'GOES-East · topes de nubes',
        'intervalo_ms': 400,
        'basemap': BASEMAP_SATELLITE,
    },
    {
        'manifest_key': 'goes-east-wv',
        'id': 'satelite_wv',
        'nombre': 'Vapor de Agua',
        'descripcion': 'GOES-East · humedad atmosférica',
        'intervalo_ms': 400,
        'basemap': BASEMAP_SATELLITE,
    },
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/var/log/canalmeteo/mapas_manifest.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def fetch_json(url):
    try:
        result = subprocess.run(
            ['curl', '-sf', '--max-time', '15', url],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            log.warning(f"curl falló para {url}: {result.stderr}")
            return None
        return json.loads(result.stdout)
    except Exception as e:
        log.warning(f"Error descargando {url}: {e}")
        return None


def to_cdn_url(url):
    if url and 'sfo3.digitaloceanspaces.com' in url and 'cdn.' not in url:
        return url.replace('sfo3.digitaloceanspaces.com', 'sfo3.cdn.digitaloceanspaces.com')
    return url


def build_radar_entry():
    data = fetch_json(MANIFEST_MRMS)
    if not data:
        return None
    frames_raw = data.get('frames', [])
    if not frames_raw:
        return None
    frames_sorted = sorted(frames_raw, key=lambda f: f.get('timestamp', 0))
    frames_recent = frames_sorted[-MAX_FRAMES:]
    frame_urls = []
    timestamps = []
    for f in frames_recent:
        url = to_cdn_url(f.get('url'))
        if url:
            frame_urls.append(url)
            ts = f.get('iso', '')
            if ts:
                timestamps.append(ts)
    if not frame_urls:
        return None
    ultima = timestamps[-1] if timestamps else datetime.now(timezone.utc).isoformat()
    return {
        'id': 'radar_mrms',
        'nombre': 'Radar',
        'descripcion': 'Reflectividad MRMS · 1 km',
        'categoria': 'radar',
        'tipo': 'loop',
        'basemap_url': BASEMAP_MRMS,
        'frames': frame_urls,
        'frame_ultimo': frame_urls[-1],
        'actualizado': ultima,
        'tiene_animacion': True,
        'intervalo_ms': 500,
        'fuente': 'NOAA MRMS',
    }


def build_satelite_entries():
    data = fetch_json(MANIFEST_SATELLITE)
    if not data:
        return []
    productos = data.get('products', {})
    entries = []
    for prod_cfg in SATELITE_PRODUCTOS:
        key = prod_cfg['manifest_key']
        frames_raw = productos.get(key, [])
        if not frames_raw:
            log.warning(f"Producto satélite '{key}' sin frames")
            continue
        frames_sorted = sorted(frames_raw, key=lambda f: f.get('time', 0))
        frames_recent = frames_sorted[-MAX_FRAMES:]
        frame_urls = []
        timestamps = []
        for f in frames_recent:
            url = to_cdn_url(f.get('url'))
            if url:
                frame_urls.append(url)
                ts_unix = f.get('time')
                if ts_unix:
                    ts_iso = datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat()
                    timestamps.append(ts_iso)
        if not frame_urls:
            continue
        ultima = timestamps[-1] if timestamps else datetime.now(timezone.utc).isoformat()
        entries.append({
            'id': prod_cfg['id'],
            'nombre': prod_cfg['nombre'],
            'descripcion': prod_cfg['descripcion'],
            'categoria': 'satelite',
            'tipo': 'loop',
            'basemap_url': prod_cfg['basemap'],
            'frames': frame_urls,
            'frame_ultimo': frame_urls[-1],
            'actualizado': ultima,
            'tiene_animacion': True,
            'intervalo_ms': prod_cfg['intervalo_ms'],
            'fuente': 'NOAA GOES-East',
        })
        log.info(f"  ✓ {prod_cfg['nombre']}: {len(frame_urls)} frames")
    return entries


def main():
    log.info("═══ Generando manifest unificado MAPAS ═══")
    mapas = []
    radar = build_radar_entry()
    if radar:
        mapas.append(radar)
        log.info(f"  ✓ Radar: {len(radar['frames'])} frames")
    else:
        log.warning("  ✗ Radar no disponible")
    satelites = build_satelite_entries()
    mapas.extend(satelites)
    if not mapas:
        log.error("Ningún mapa disponible")
        return 1
    manifest = {
        'version': '1.1',
        'actualizado': datetime.now(timezone.utc).isoformat(),
        'mapas': mapas,
    }
    with open(LOCAL_TMP, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log.info(f"  📝 Manifest local: {LOCAL_TMP} ({len(mapas)} mapas)")
    upload_cmd = [
        'aws', 's3', 'cp', LOCAL_TMP,
        f's3://{S3_BUCKET}/{OUTPUT_KEY}',
        '--profile', AWS_PROFILE,
        '--endpoint-url', S3_ENDPOINT,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=60',
    ]
    result = subprocess.run(upload_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        log.info(f"  ☁️  Subido: {CDN_BASE}/{OUTPUT_KEY}")
    else:
        log.error(f"  ✗ Error subiendo: {result.stderr}")
        return 1
    log.info(f"═══ Complete · {len(mapas)} mapas ═══")
    return 0


if __name__ == '__main__':
    exit(main())
