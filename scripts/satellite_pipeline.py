#!/usr/bin/env python3
"""
Satellite imagery pipeline for Canal Meteo TV — Tormenta
Downloads GOES-East/West CONUS imagery from NOAA STAR CDN,
reprojects from geostationary to equirectangular lat/lon,
crops info bar, uploads to Canal Meteo CDN.

Cron: */5 * * * * /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/satellite_pipeline.py >> /var/log/canalmeteo/satellite.log 2>&1
"""

import requests
import subprocess
import logging
import time
import json
import numpy as np
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone, timedelta
from pyproj import Transformer
from scipy.ndimage import map_coordinates

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_BASE = 'data/satellite'

# Output bounds (lat/lon for Mapbox image source coordinates)
OUT_BOUNDS = { 'north': 50.0, 'south': 24.0, 'west': -125.0, 'east': -66.0 }
OUT_WIDTH = 2400
OUT_HEIGHT = 1200

# Generate output grid in Mercator Y spacing
# Mapbox image source stretches the image linearly in screen space (Mercator)
# So if we output in equirectangular (linear lat), it gets distorted
# Solution: space output latitudes in Mercator Y, so Mapbox's linear stretch = correct
import math
def lat_to_merc_y(lat):
    return math.log(math.tan(math.pi/4 + math.radians(lat)/2))
def merc_y_to_lat(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi/2)

MERC_Y_N = lat_to_merc_y(OUT_BOUNDS['north'])
MERC_Y_S = lat_to_merc_y(OUT_BOUNDS['south'])
# Output latitudes: evenly spaced in Mercator Y, converted back to lat
OUT_LATS_MERCATOR = np.array([
    merc_y_to_lat(MERC_Y_N + (MERC_Y_S - MERC_Y_N) * i / (OUT_HEIGHT - 1))
    for i in range(OUT_HEIGHT)
])

# GOES satellite parameters
GOES_PARAMS = {
    'GOES19': {  # GOES-East at 75.0W (from NetCDF)
        'lon_0': -75.0, 'h': 35786023.0,
        'a': 6378137.0, 'b': 6356752.31414, 'sweep': 'x',
    },
    'GOES18': {  # GOES-West at 137.2W
        'lon_0': -137.2, 'h': 35786023.0,
        'a': 6378137.0, 'b': 6356752.31414, 'sweep': 'x',
    },
}

PRODUCTS = {
    'goes-east-geocolor': { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/GEOCOLOR/2500x1500.jpg', 'sat': 'GOES19' },
    'goes-east-ir':       { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/13/2500x1500.jpg', 'sat': 'GOES19' },
    'goes-east-vis':      { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/02/2500x1500.jpg', 'sat': 'GOES19' },
    'goes-east-wv':       { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/09/2500x1500.jpg', 'sat': 'GOES19' },
    'goes-west-geocolor': { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES18/ABI/CONUS/GEOCOLOR/2500x1500.jpg', 'sat': 'GOES18' },
    'goes-west-ir':       { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES18/ABI/CONUS/13/2500x1500.jpg', 'sat': 'GOES18' },
    'goes-west-vis':      { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES18/ABI/CONUS/02/2500x1500.jpg', 'sat': 'GOES18' },
    'goes-west-wv':       { 'url': 'https://cdn.star.nesdis.noaa.gov/GOES18/ABI/CONUS/09/2500x1500.jpg', 'sat': 'GOES18' },
}

CROP_BOTTOM_RATIO = 0.053
_reproj_cache = {}


def build_reproj_lut(sat_key, src_h, src_w):
    """Build lookup table using pyproj to map output lat/lon to source geostationary pixels.
    
    Strategy: 
    1. For each output pixel, compute its geostationary x,y in meters
    2. Use calibration to map geostationary x,y to source image pixels
    3. The calibration uses known lat/lon points to determine the linear mapping
       from geostationary meters to image pixel coordinates
    """
    cache_key = (sat_key, src_h, src_w)
    if cache_key in _reproj_cache:
        return _reproj_cache[cache_key]

    log.info(f"  Building LUT for {sat_key} ({src_w}x{src_h} -> {OUT_WIDTH}x{OUT_HEIGHT})")
    t0 = time.time()
    params = GOES_PARAMS[sat_key]

    # Transformer: lon/lat -> geostationary x,y (meters)
    proj_str = (f"+proj=geos +lon_0={params['lon_0']} +h={params['h']} "
                f"+a={params['a']} +b={params['b']} +sweep={params['sweep']} +units=m")
    transformer = Transformer.from_crs("EPSG:4326", proj_str, always_xy=True)

    # Step 1: Determine the geostationary extent of the source image
    # Use known reference points to calibrate the image pixel ↔ geostationary mapping
    # The CONUS sector has known scan angles from the PUG
    # Center of CONUS sector: 30.08N, 87.1W (PUG Table 5.1.2.7-5 for operational GOES-East)
    # We compute geos coords for the PUG scan angle corners and map to pixels
    
    H = params['h']
    
    # Use Band-specific scan angles from actual NetCDF metadata
    # Band 13/IR (2km): x=-0.101332..0.038612, y=0.044268..0.128212 (2500x1500)
    # Band 02/Vis (0.5km->2500): x=-0.101353..0.038633, y=0.044247..0.128233 (10000->2500)
    # GeoColor/B09 use Band 13 grid (2km)
    # When STAR renders 2500x1500 from Band 02, they downsample 10000->2500
    # The half-pixel offset matters: use Band 02 angles for vis, Band 13 for rest
    
    # Determine which scan angles to use based on image dimensions
    if src_w == 2500 and src_h == 1500:
        # Standard 2km grid (Band 13, GeoColor, WV, etc.)
        scan_x_min, scan_x_max = -0.101332, 0.038612
        scan_y_min, scan_y_max = 0.044268, 0.128212
    else:
        # Non-standard size - use Band 13 angles as default
        scan_x_min, scan_x_max = -0.101332, 0.038612
        scan_y_min, scan_y_max = 0.044268, 0.128212
    
    # Convert scan angles to geostationary meters
    geos_x_min = scan_x_min * H
    geos_x_max = scan_x_max * H
    geos_y_min = scan_y_min * H  # bottom of image (south)
    geos_y_max = scan_y_max * H  # top of image (north)
    
    # Linear mapping: geos meters -> source image pixels
    # Image pixel (0,0) = top-left = (geos_x_min, geos_y_max)
    # Image pixel (src_w, src_h) = bottom-right = (geos_x_max, geos_y_min)
    px_per_geos_x = src_w / (geos_x_max - geos_x_min)
    px_per_geos_y = src_h / (geos_y_max - geos_y_min)

    # Step 2: For each output pixel, compute geostationary coords and map to source pixel
    out_lons = np.linspace(OUT_BOUNDS['west'], OUT_BOUNDS['east'], OUT_WIDTH)
    out_lats = OUT_LATS_MERCATOR  # Mercator-spaced latitudes for correct Mapbox display
    lon_grid, lat_grid = np.meshgrid(out_lons, out_lats)

    gx, gy = transformer.transform(lon_grid.ravel(), lat_grid.ravel())
    gx = np.array(gx).reshape(OUT_HEIGHT, OUT_WIDTH)
    gy = np.array(gy).reshape(OUT_HEIGHT, OUT_WIDTH)

    # Map geostationary meters to source image pixels
    src_col = (gx - geos_x_min) * px_per_geos_x
    src_row = (geos_y_max - gy) * px_per_geos_y  # y is inverted (north=top)

    # Valid mask
    valid = (np.isfinite(gx) & np.isfinite(gy) &
             (src_col >= 0) & (src_col < src_w) &
             (src_row >= 0) & (src_row < src_h))

    src_col = np.where(valid, src_col, 0).astype(np.float32)
    src_row = np.where(valid, src_row, 0).astype(np.float32)

    _reproj_cache[cache_key] = (src_row, src_col, valid)
    log.info(f"  LUT ready: {valid.sum()}/{valid.size} valid px ({time.time()-t0:.1f}s)")
    return src_row, src_col, valid


def reproject_image(arr, sat_key):
    """Reproject image array from geostationary to equirectangular."""
    src_h, src_w = arr.shape[:2]
    n_ch = arr.shape[2] if arr.ndim == 3 else 1
    src_row, src_col, valid = build_reproj_lut(sat_key, src_h, src_w)

    if n_ch == 1:
        out = map_coordinates(arr, [src_row, src_col], order=1, mode='constant', cval=0)
        return np.where(valid, out, 0).astype(np.uint8), valid

    out = np.zeros((OUT_HEIGHT, OUT_WIDTH, n_ch), dtype=np.uint8)
    for c in range(n_ch):
        ch = map_coordinates(arr[:, :, c], [src_row, src_col], order=1, mode='constant', cval=0)
        out[:, :, c] = np.where(valid, ch, 0).astype(np.uint8)
    return out, valid


def upload(filepath, cdn_key, content_type='image/jpeg'):
    cmd = ['aws', 's3', 'cp', filepath, f's3://{CDN_BUCKET}/{cdn_key}',
           '--profile', AWS_PROFILE, '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=60',
           '--endpoint-url', CDN_ENDPOINT]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    except:
        return False


def process_product(key, cfg, timestamp):
    """Download, reproject, and upload one satellite product with timestamp."""
    try:
        r = requests.get(cfg['url'], timeout=30,
                         headers={'User-Agent': 'CanalMeteoTV/1.0 (contacto@canalmeteo.tv)'})
        if r.status_code != 200:
            log.warning(f"  {key}: HTTP {r.status_code}")
            return False

        img = Image.open(BytesIO(r.content))

        # Do NOT crop - the full 2500x1500 image matches the CONUS sector grid exactly
        arr = np.array(img)

        # Reproject
        reprojected, valid = reproject_image(arr, cfg['sat'])

        # Save with timestamp
        out_path = f'/tmp/sat_{key}_{timestamp}.jpg'
        Image.fromarray(reprojected).save(out_path, 'JPEG', quality=88)

        # Upload timestamped version
        cdn_key = f'{CDN_BASE}/{key}_{timestamp}.jpg'
        if upload(out_path, cdn_key):
            # Also upload as "latest" for simple loading
            cdn_latest = f'{CDN_BASE}/{key}.jpg'
            upload(out_path, cdn_latest)
            log.info(f"  ✅ {key}_{timestamp}")
            return True
        log.warning(f"  ❌ {key}: upload failed")
        return False

    except Exception as e:
        log.warning(f"  {key}: {e}")
        import traceback; traceback.print_exc()
        return False


def cleanup_old_frames(product_keys, max_age_hours=6):
    """Remove frames older than max_age_hours from CDN."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    cutoff_ts = cutoff.strftime('%Y%m%d%H%M')

    for key in product_keys:
        # List objects in CDN with this prefix
        list_cmd = ['aws', 's3', 'ls',
                    f's3://{CDN_BUCKET}/{CDN_BASE}/{key}_',
                    '--profile', AWS_PROFILE,
                    '--endpoint-url', CDN_ENDPOINT]
        try:
            result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                continue
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                # Extract filename from ls output
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                fname = parts[-1]
                # Extract timestamp from filename: goes-east-ir_202604130500.jpg
                import re
                m = re.search(r'_(\d{12})\.jpg$', fname)
                if m:
                    file_ts = m.group(1)
                    if file_ts < cutoff_ts:
                        del_key = f'{CDN_BASE}/{fname}'
                        del_cmd = ['aws', 's3', 'rm', f's3://{CDN_BUCKET}/{del_key}',
                                   '--profile', AWS_PROFILE,
                                   '--endpoint-url', CDN_ENDPOINT]
                        subprocess.run(del_cmd, capture_output=True, text=True, timeout=15)
                        log.info(f"  🗑️ Deleted old: {fname}")
        except Exception as e:
            log.warning(f"  Cleanup {key}: {e}")


def build_manifest(product_keys):
    """Build manifest with list of available timestamped frames per product."""
    now = datetime.now(timezone.utc)
    manifest = {
        'generated': now.isoformat(),
        'bounds': OUT_BOUNDS,
        'products': {},
    }

    for key in product_keys:
        list_cmd = ['aws', 's3', 'ls',
                    f's3://{CDN_BUCKET}/{CDN_BASE}/{key}_',
                    '--profile', AWS_PROFILE,
                    '--endpoint-url', CDN_ENDPOINT]
        try:
            result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                continue
            frames = []
            import re
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                fname = parts[-1]
                m = re.search(r'_(\d{12})\.jpg$', fname)
                if m:
                    ts = m.group(1)
                    # Convert to unix timestamp
                    dt = datetime.strptime(ts, '%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                    frames.append({
                        'time': int(dt.timestamp()),
                        'ts': ts,
                        'url': f'https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CDN_BASE}/{fname}',
                    })

            # Sort by time, newest last
            frames.sort(key=lambda f: f['time'])
            manifest['products'][key] = frames
        except Exception as e:
            log.warning(f"  Manifest {key}: {e}")

    return manifest


def main():
    t0 = time.time()
    log.info("=== Satellite Pipeline ===")

    now = datetime.now(timezone.utc)
    timestamp = now.strftime('%Y%m%d%H%M')

    success = 0
    for key, cfg in PRODUCTS.items():
        if process_product(key, cfg, timestamp):
            success += 1

    # Cleanup old frames (> 6 hours)
    log.info("Cleaning old frames...")
    cleanup_old_frames(list(PRODUCTS.keys()), max_age_hours=6)

    # Build and upload manifest with all available frames
    log.info("Building manifest...")
    manifest = build_manifest(list(PRODUCTS.keys()))
    manifest_path = '/tmp/sat_manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f)
    upload(manifest_path, f'{CDN_BASE}/manifest.json', 'application/json')

    total_frames = sum(len(v) for v in manifest.get('products', {}).values())
    log.info(f"Done: {success}/{len(PRODUCTS)} new, {total_frames} total frames, {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
