#!/usr/bin/env python3
"""
MRMS Radar HD Pipeline — Canal Meteo TV
Downloads MergedBaseReflectivityQC from NCEP every 2 minutes,
renders as transparent PNG with NWS colormap, uploads to CDN.

Keeps last 20 frames (~1 hour) for animation.

Usage (cron):
  */2 * * * * flock -n /tmp/mrms.lock /opt/canalmeteo/venv/bin/python3 \
    /opt/canalmeteo/scripts/mrms_pipeline.py --once >> /var/log/canalmeteo/mrms.log 2>&1
"""

import os
import sys
import json
import time
import gzip
import shutil
import logging
import argparse
import subprocess
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
import cfgrib
import xarray as xr
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────
MRMS_BASE = 'https://mrms.ncep.noaa.gov/2D/MergedBaseReflectivityQC'
PRODUCT = 'MergedBaseReflectivityQC_00.50'

CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_BASE = 'data/mrms'
CDN_URL_BASE = f'https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CDN_BASE}'

WORK_DIR = Path('/tmp/mrms_work')
WORK_DIR.mkdir(exist_ok=True)

# Cubrir las últimas ~3 h con 1 frame por bucket de 10 min (cadencia estable para
# el cache). MRMS llega cada ~2 min; agrupamos por bucket y guardamos el más nuevo.
SPAN_MIN = 190
BUCKET_SEC = 600
MAX_FRAMES = 20  # tope de frames en el manifest

# Output PNG dimensions (CONUS)
# Grid is 0.01° resolution, ~1km. Full CONUS grid = 3500×7000 points.
# We'll render to 3000×1700 PNG for good quality at web zoom levels.
OUT_WIDTH = 3500
OUT_HEIGHT = 1750

# CONUS bounds (from MRMS grid metadata)
# The MRMS grid nominally covers 20-55°N, -130 to -60°W
BOUNDS = {
    'north': 55.0,
    'south': 20.0,
    'west': -130.0,
    'east': -60.0,
}

# ─── NWS Reflectivity colormap ────────────────────────────────────
def make_nws_reflectivity_cmap():
    """Standard NWS reflectivity colormap (same as RadarScope/EverythingWX)."""
    # Key-value: dBZ → hex color
    stops = [
        (-30, '#000000'),
        (-10, '#1a1a1a'),
        (5,   '#9C9C9C'),   # near-threshold gray
        (10,  '#767676'),
        (15,  '#4A4A4A'),
        (20,  '#04e9e7'),   # light cyan
        (25,  '#019ff4'),   # blue
        (30,  '#0300f4'),   # dark blue
        (35,  '#02fd02'),   # light green
        (40,  '#01c501'),   # green
        (45,  '#008e00'),   # dark green
        (50,  '#fdf802'),   # yellow
        (55,  '#e5bc00'),   # gold
        (60,  '#fd9500'),   # orange
        (65,  '#fd0000'),   # red
        (70,  '#d40000'),   # dark red
        (75,  '#bc0000'),   # deeper red
        (80,  '#f800fd'),   # magenta
        (85,  '#9854c6'),   # purple
        (90,  '#fdfdfd'),   # white
    ]
    vmin, vmax = stops[0][0], stops[-1][0]
    positions = [(v - vmin) / (vmax - vmin) for v, _ in stops]
    colors = [c for _, c in stops]
    return LinearSegmentedColormap.from_list('nws_refl', list(zip(positions, colors)), N=256), vmin, vmax

NWS_CMAP, NWS_VMIN, NWS_VMAX = make_nws_reflectivity_cmap()

# ─── MRMS file discovery ──────────────────────────────────────────
def list_remote_files():
    """Fetch file listing from MRMS server."""
    url = f'{MRMS_BASE}/'
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            log.error(f"  Listing failed: HTTP {r.status_code}")
            return []
        # Parse HTML directory listing
        pattern = re.compile(r'href="(MRMS_' + re.escape(PRODUCT) + r'_\d{8}-\d{6}\.grib2\.gz)"')
        files = pattern.findall(r.text)
        files.sort(reverse=True)
        return files
    except Exception as e:
        log.error(f"  Listing error: {e}")
        return []


def parse_timestamp(filename: str) -> datetime:
    """Extract timestamp from filename like MRMS_MergedBaseReflectivityQC_00.50_20260422-143200.grib2.gz"""
    m = re.search(r'(\d{8})-(\d{6})', filename)
    if not m:
        return None
    date_str, time_str = m.groups()
    return datetime.strptime(date_str + time_str, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)


def download_file(filename: str) -> Path:
    """Download and decompress a MRMS grib2.gz file."""
    url = f'{MRMS_BASE}/{filename}'
    gz_path = WORK_DIR / filename
    grib_path = gz_path.with_suffix('')  # removes .gz

    try:
        log.info(f"  ⬇️  Downloading {filename}")
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            log.error(f"  HTTP {r.status_code}")
            return None
        with open(gz_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

        # Decompress
        with gzip.open(gz_path, 'rb') as gz, open(grib_path, 'wb') as out:
            shutil.copyfileobj(gz, out)

        gz_path.unlink()
        return grib_path
    except Exception as e:
        log.error(f"  Download error: {e}")
        return None


def render_to_png(grib_path: Path, png_path: Path) -> bool:
    """Load GRIB2, reproject to equirectangular PNG with NWS colormap + transparency."""
    try:
        t0 = time.time()

        # Open with cfgrib
        ds = xr.open_dataset(grib_path, engine='cfgrib',
                             backend_kwargs={'indexpath': ''})

        # The reflectivity field is typically 'unknown' or 'paramId_0' for MRMS
        # because GRIB tables don't always map cleanly. Use the only data var.
        var_name = list(ds.data_vars)[0]
        data = ds[var_name].values  # shape (lat, lon), -999 for missing

        lats = ds['latitude'].values
        lons = ds['longitude'].values
        # Longitudes may be 0-360; normalize to -180..180 if needed
        if lons.max() > 180:
            lons = np.where(lons > 180, lons - 360, lons)

        t_load = time.time() - t0

        # Mask: missing data and values below threshold → fully transparent
        MISSING = -999.0
        mask_missing = (data <= MISSING + 1) | np.isnan(data)
        mask_below_thresh = data < 5.0  # below 5 dBZ = no precip

        # Clamp for colormap normalization
        clipped = np.clip(data, NWS_VMIN, NWS_VMAX)
        norm = Normalize(vmin=NWS_VMIN, vmax=NWS_VMAX)
        rgba = NWS_CMAP(norm(clipped))  # (H, W, 4) floats 0..1

        # Apply transparency
        rgba[mask_missing, 3] = 0.0
        rgba[mask_below_thresh, 3] = 0.0

        # Smooth alpha transition near low thresholds (5–10 dBZ)
        low_range = (data >= 5.0) & (data < 10.0)
        rgba[low_range, 3] = np.clip((data[low_range] - 5.0) / 5.0, 0.0, 1.0)

        # Convert to 8-bit
        rgba_8 = (rgba * 255).astype(np.uint8)

        # The MRMS grid is lat descending (north to south). PIL wants row 0 at top.
        # Check if lats are descending; if so, the array is already correctly oriented for PIL.
        if lats[0] < lats[-1]:
            rgba_8 = np.flipud(rgba_8)

        img = Image.fromarray(rgba_8, mode='RGBA')

        # Resize to output dimensions for consistency
        img = img.resize((OUT_WIDTH, OUT_HEIGHT), Image.BILINEAR)

        img.save(png_path, 'PNG', optimize=True, compress_level=6)

        t_total = time.time() - t0
        log.info(f"    rendered {png_path.name} in {t_total:.1f}s (load={t_load:.1f}s, shape={data.shape})")

        ds.close()
        return True

    except Exception as e:
        log.error(f"  Render error: {e}")
        import traceback
        traceback.print_exc()
        return False


# ─── CDN operations ───────────────────────────────────────────────
def cdn_upload(local_path: str, cdn_key: str, content_type: str = 'image/png') -> bool:
    """Upload file to DigitalOcean Spaces CDN."""
    cmd = ['aws', 's3', 'cp', str(local_path), f's3://{CDN_BUCKET}/{cdn_key}',
           '--profile', AWS_PROFILE, '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=300',
           '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception as e:
        log.warning(f"  CDN upload failed: {e}")
        return False


def cdn_list(prefix: str) -> list:
    """List objects in CDN with given prefix."""
    cmd = ['aws', 's3', 'ls', f's3://{CDN_BUCKET}/{prefix}',
           '--profile', AWS_PROFILE, '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        keys = []
        for line in r.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 4:
                keys.append(parts[-1])
        return keys
    except Exception as e:
        log.warning(f"  CDN list failed: {e}")
        return []


def cdn_delete(cdn_key: str) -> bool:
    cmd = ['aws', 's3', 'rm', f's3://{CDN_BUCKET}/{cdn_key}',
           '--profile', AWS_PROFILE, '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def cdn_exists(cdn_key: str) -> bool:
    cmd = ['aws', 's3api', 'head-object',
           '--bucket', CDN_BUCKET, '--key', cdn_key,
           '--profile', AWS_PROFILE, '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


# ─── Main pipeline ────────────────────────────────────────────────
def run_pipeline():
    """One pipeline iteration."""
    t0 = time.time()
    log.info(f"═══ MRMS pipeline ({datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC) ═══")

    # 1. List available files on NCEP
    remote_files = list_remote_files()
    if not remote_files:
        log.error("  No remote files found — aborting")
        return

    log.info(f"  {len(remote_files)} files on NCEP server")

    # 2. Cubrir las últimas SPAN_MIN con 1 frame por bucket de BUCKET_SEC (cadencia
    #    estable). MRMS llega cada ~2 min; agrupamos y guardamos el más nuevo de
    #    cada bucket → ~18 frames sobre 3 h a 10 min.
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - SPAN_MIN * 60
    by_bucket = {}
    for fn in remote_files:
        ts = parse_timestamp(fn)
        if not ts or ts.timestamp() < cutoff:
            continue
        b = int(ts.timestamp() // BUCKET_SEC)
        if b not in by_bucket or ts > by_bucket[b][0]:
            by_bucket[b] = (ts, fn)
    chosen = sorted(by_bucket.values(), key=lambda x: x[0], reverse=True)[:MAX_FRAMES]
    frames_wanted = [fn for _, fn in sorted(chosen, key=lambda x: x[0])]  # viejo→nuevo

    # 3. ACUMULACIÓN: NCEP solo retiene ~40 min, así que conservamos los frames que
    #    ya tenemos en el CDN dentro de la ventana de 3h y solo añadimos los nuevos.
    existing_keys = cdn_list(CDN_BASE + '/')
    manifest_by_bucket = {}  # bucket -> frame_info (1 por bucket)
    for k in existing_keys:
        if not k.endswith('.png'):
            continue
        m = re.search(r'refl_(\d{14})', k)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        if ts.timestamp() < cutoff:
            continue  # se podará en el paso 7
        b = int(ts.timestamp() // BUCKET_SEC)
        cur = manifest_by_bucket.get(b)
        if not cur or ts.timestamp() > cur['timestamp']:
            manifest_by_bucket[b] = {
                'url': f'{CDN_URL_BASE}/refl_{m.group(1)}.png',
                'timestamp': int(ts.timestamp()),
                'iso': ts.isoformat(),
            }

    # 4. Renderizar SOLO los buckets que NCEP tiene y nosotros aún no.
    for remote_file in frames_wanted:
        ts = parse_timestamp(remote_file)
        if not ts:
            continue
        b = int(ts.timestamp() // BUCKET_SEC)
        if b in manifest_by_bucket:
            continue  # bucket ya cubierto por un frame del CDN

        stem = f"refl_{ts.strftime('%Y%m%d%H%M%S')}"
        grib_path = download_file(remote_file)
        if not grib_path:
            continue
        png_path = WORK_DIR / f'{stem}.png'
        ok = render_to_png(grib_path, png_path)
        try:
            grib_path.unlink()
        except Exception:
            pass
        for idx in WORK_DIR.glob('*.idx'):
            try: idx.unlink()
            except Exception: pass
        if not ok:
            continue
        if cdn_upload(png_path, f'{CDN_BASE}/{stem}.png'):
            log.info(f"  ☁️  uploaded: {stem}")
            manifest_by_bucket[b] = {
                'url': f'{CDN_URL_BASE}/{stem}.png',
                'timestamp': int(ts.timestamp()),
                'iso': ts.isoformat(),
            }
        try:
            png_path.unlink()
        except Exception:
            pass

    # 5. Manifest = 1 frame por bucket, ordenado y capado a los MAX_FRAMES recientes.
    new_frames_manifest = sorted(manifest_by_bucket.values(), key=lambda f: f['timestamp'])[-MAX_FRAMES:]

    # 6. Write manifest.json
    manifest = {
        'product': 'MergedBaseReflectivityQC',
        'elevation_km': 0.5,
        'bounds': BOUNDS,
        'width': OUT_WIDTH,
        'height': OUT_HEIGHT,
        'count': len(new_frames_manifest),
        'frames': new_frames_manifest,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = WORK_DIR / 'manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    if cdn_upload(manifest_path, f'{CDN_BASE}/manifest.json', 'application/json'):
        log.info(f"  📋 manifest updated: {len(new_frames_manifest)} frames")
    manifest_path.unlink()

    # 7. Clean up old frames from CDN (keep only those in current manifest + 2 buffer)
    kept_stems = {Path(f['url']).stem for f in new_frames_manifest}
    for key in existing_keys:
        if not key.endswith('.png'):
            continue
        stem = Path(key).stem
        if stem not in kept_stems:
            full_key = f'{CDN_BASE}/{key}'
            if cdn_delete(full_key):
                log.info(f"  🗑️  deleted old: {stem}")

    log.info(f"═══ Complete in {time.time()-t0:.1f}s ═══")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    args = parser.parse_args()

    try:
        run_pipeline()
    except Exception as e:
        log.error(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
