#!/usr/bin/env python3
"""
Canal Meteo TV - Space Weather Data Fetcher v2
Fetches solar wind, magnetometer, KP, flare events, NOAA scales, solar imagery
Uploads to DigitalOcean Spaces CDN via AWS CLI (profile do-tor1)

Cron: */2 * * * * /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/fetch_space_weather.py
"""

import json
import os
import subprocess
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Configuration ──────────────────────────────────────────────────
AWS_PROFILE = 'do-tor1'
AWS_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
S3_BUCKET = 'canalmeteo-public'
CDN_PREFIX = 'space-weather'
DATA_DIR = '/opt/canalmeteo/data/space-weather'

SWPC_BASE = 'https://services.swpc.noaa.gov'
TIMEOUT = 15
UA = 'CanalMeteoTV/2.0 (space-weather)'

# ── JSON Data Sources ──────────────────────────────────────────────
JSON_SOURCES = {
    # Solar wind plasma — multiple time ranges for range selector
    'plasma-2-hour':  f'{SWPC_BASE}/products/solar-wind/plasma-2-hour.json',
    'plasma-6-hour':  f'{SWPC_BASE}/products/solar-wind/plasma-6-hour.json',
    'plasma-1-day':   f'{SWPC_BASE}/products/solar-wind/plasma-1-day.json',

    # Solar wind magnetometer (Bz, Bt) — multiple time ranges
    'mag-2-hour':     f'{SWPC_BASE}/products/solar-wind/mag-2-hour.json',
    'mag-6-hour':     f'{SWPC_BASE}/products/solar-wind/mag-6-hour.json',
    'mag-1-day':      f'{SWPC_BASE}/products/solar-wind/mag-1-day.json',

    # Ephemerides (DSCOVR position/distance)
    'ephemerides':    f'{SWPC_BASE}/products/solar-wind/ephemerides.json',

    # KP Index (observed + forecast)
    'planetary-k-index':          f'{SWPC_BASE}/products/noaa-planetary-k-index.json',
    'planetary-k-index-forecast': f'{SWPC_BASE}/products/noaa-planetary-k-index-forecast.json',

    # GOES Magnetometer (primary=GOES-19, secondary=GOES-18)
    'goes-mag-primary-6h':   f'{SWPC_BASE}/json/goes/primary/magnetometers-6-hour.json',
    'goes-mag-secondary-6h': f'{SWPC_BASE}/json/goes/secondary/magnetometers-6-hour.json',
    'goes-mag-primary-1d':   f'{SWPC_BASE}/json/goes/primary/magnetometers-1-day.json',
    'goes-mag-secondary-1d': f'{SWPC_BASE}/json/goes/secondary/magnetometers-1-day.json',

    # Solar flare probabilities
    'solar-probabilities':   f'{SWPC_BASE}/json/solar_probabilities.json',

    # GOES X-ray flux (for flare detection chart)
    'goes-xray-flux-6h':    f'{SWPC_BASE}/json/goes/primary/xrays-6-hour.json',
    'goes-xray-flux-1d':    f'{SWPC_BASE}/json/goes/primary/xrays-1-day.json',
}

# Hemispheric power (text format, needs parsing)
HEMI_POWER_URL = f'{SWPC_BASE}/text/aurora-nowcast-hemi-power.txt'

# Edited events (large file ~1MB, we filter to recent XRA flares only)
EDITED_EVENTS_URL = f'{SWPC_BASE}/json/edited_events.json'

# ── Solar Imagery ──────────────────────────────────────────────────
SUVI_CHANNELS = {
    'goes-suvi-094': f'{SWPC_BASE}/images/animations/suvi/primary/094/latest.png',
    'goes-suvi-131': f'{SWPC_BASE}/images/animations/suvi/primary/131/latest.png',
    'goes-suvi-171': f'{SWPC_BASE}/images/animations/suvi/primary/171/latest.png',
    'goes-suvi-195': f'{SWPC_BASE}/images/animations/suvi/primary/195/latest.png',
    'goes-suvi-284': f'{SWPC_BASE}/images/animations/suvi/primary/284/latest.png',
    'goes-suvi-304': f'{SWPC_BASE}/images/animations/suvi/primary/304/latest.png',
}

SOHO_IMAGES = {
    'soho-lasco-c2': 'https://soho.nascom.nasa.gov/data/realtime/c2/1024/latest.jpg',
    'soho-lasco-c3': 'https://soho.nascom.nasa.gov/data/realtime/c3/1024/latest.jpg',
    'soho-eit-171':  'https://soho.nascom.nasa.gov/data/realtime/eit_171/1024/latest.jpg',
    'soho-eit-195':  'https://soho.nascom.nasa.gov/data/realtime/eit_195/1024/latest.jpg',
    'soho-eit-284':  'https://soho.nascom.nasa.gov/data/realtime/eit_284/1024/latest.jpg',
    'soho-eit-304':  'https://soho.nascom.nasa.gov/data/realtime/eit_304/1024/latest.jpg',
    'soho-hmi-mag':  'https://soho.nascom.nasa.gov/data/realtime/hmi_mag/1024/latest.jpg',
}

SDO_AIA_IMAGES = {
    'sdo-aia-094': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0094.jpg',
    'sdo-aia-131': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0131.jpg',
    'sdo-aia-171': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0171.jpg',
    'sdo-aia-193': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0193.jpg',
    'sdo-aia-211': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0211.jpg',
    'sdo-aia-304': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0304.jpg',
    'sdo-aia-335': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0335.jpg',
    'sdo-aia-1600': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_1600.jpg',
    'sdo-aia-1700': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_1700.jpg',
    'sdo-hmi-int':  'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_HMIIC.jpg',
    'sdo-hmi-mag':  'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_HMIBC.jpg',
}


# ── Upload via AWS CLI ─────────────────────────────────────────────
def upload_to_spaces(local_path, s3_key, content_type='application/json', cache_control='max-age=60, public'):
    s3_dest = f"s3://{S3_BUCKET}/{s3_key}"
    cmd = [
        'aws', 's3', 'cp', local_path, s3_dest,
        '--endpoint-url', AWS_ENDPOINT,
        '--profile', AWS_PROFILE,
        '--content-type', content_type,
        '--cache-control', cache_control,
        '--acl', 'public-read',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return True
        else:
            print(f"  [ERROR] Upload {s3_key}: {result.stderr.strip()}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  [ERROR] Upload {s3_key}: {e}", file=sys.stderr)
        return False


def save_and_upload_json(name, data):
    """Save JSON locally, then upload to Spaces."""
    local_path = os.path.join(DATA_DIR, f'{name}.json')
    with open(local_path, 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    s3_key = f'{CDN_PREFIX}/data/{name}.json'
    return upload_to_spaces(local_path, s3_key)


# ── Fetch functions ────────────────────────────────────────────────
def fetch_json(name, url):
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={
            'User-Agent': UA, 'Accept': 'application/json',
        })
        r.raise_for_status()
        return name, r.json()
    except Exception as e:
        print(f"  [WARN] Failed to fetch {name}: {e}", file=sys.stderr)
        return name, None


def fetch_hemispheric_power():
    """Fetch hemispheric power text and parse to JSON."""
    try:
        r = requests.get(HEMI_POWER_URL, timeout=TIMEOUT, headers={'User-Agent': UA})
        r.raise_for_status()
        data = []
        for line in r.text.strip().split('\n'):
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 4:
                try:
                    data.append({
                        'time_tag': parts[0].replace('_', 'T') + ':00Z',
                        'hpi_north': float(parts[2]),
                        'hpi_south': float(parts[3]),
                    })
                except ValueError:
                    continue
        return data
    except Exception as e:
        print(f"  [WARN] Failed to fetch hemispheric power: {e}", file=sys.stderr)
        return None


def fetch_recent_flares():
    """Fetch edited_events.json and extract recent XRA (X-ray) flare events.
    Fields: type='XRA', particulars1='C1.1'/'M2.7'/'X1.0', region=AR number, location=solar coords
    """
    try:
        r = requests.get(EDITED_EVENTS_URL, timeout=30, headers={
            'User-Agent': UA, 'Accept': 'application/json',
        })
        r.raise_for_status()
        events = r.json()

        # Filter: only XRA events from last 7 days, class C1.0+
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S')
        flares = []
        for ev in events:
            if ev.get('type') != 'XRA':
                continue
            begin = ev.get('begin_datetime', '')
            if begin < cutoff:
                continue
            classtype = ev.get('particulars1', '')
            # Only include C1.0+ flares (skip A and B class)
            if not classtype or classtype[0] not in ('C', 'M', 'X'):
                continue
            # Calculate duration in minutes
            duration = None
            try:
                b = datetime.fromisoformat(ev['begin_datetime'])
                e = datetime.fromisoformat(ev['end_datetime'])
                duration = int((e - b).total_seconds() / 60)
            except Exception:
                pass

            flares.append({
                'begin': ev.get('begin_datetime', ''),
                'max': ev.get('max_datetime', ''),
                'end': ev.get('end_datetime', ''),
                'classtype': classtype,
                'region': ev.get('region'),
                'location': ev.get('location', ''),
                'observatory': ev.get('observatory', ''),
                'duration_min': duration,
            })

        # Sort by begin time descending (most recent first)
        flares.sort(key=lambda x: x['begin'], reverse=True)
        return flares[:20]
    except Exception as e:
        print(f"  [WARN] Failed to fetch edited events: {e}", file=sys.stderr)
        return None


def fetch_image(name, url):
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': UA})
        r.raise_for_status()
        return name, r.content
    except Exception as e:
        print(f"  [WARN] Failed to fetch image {name}: {e}", file=sys.stderr)
        return name, None


# ── Main ───────────────────────────────────────────────────────────
def main():
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f"[{ts}] Starting space weather data fetch v2...")

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'images'), exist_ok=True)

    results = {'json': 0, 'images': 0, 'errors': 0}

    # ── 1. Fetch all JSON data in parallel ─────────────────────────
    print(f"  Fetching {len(JSON_SOURCES)} JSON data sources...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_json, name, url): name
            for name, url in JSON_SOURCES.items()
        }
        for future in as_completed(futures):
            name, data = future.result()
            if data is not None:
                if save_and_upload_json(name, data):
                    results['json'] += 1
                    print(f"    ✓ {name}")
                else:
                    results['errors'] += 1
            else:
                results['errors'] += 1

    # ── 2. Hemispheric power (text → JSON) ─────────────────────────
    print("  Fetching hemispheric power...")
    hemi_data = fetch_hemispheric_power()
    if hemi_data:
        if save_and_upload_json('hemispheric-power', hemi_data):
            results['json'] += 1
            print(f"    ✓ hemispheric-power ({len(hemi_data)} entries)")
        else:
            results['errors'] += 1

    # ── 3. Recent solar flares (filtered from edited_events) ───────
    print("  Fetching recent solar flares...")
    flares = fetch_recent_flares()
    if flares is not None:
        if save_and_upload_json('recent-flares', flares):
            results['json'] += 1
            print(f"    ✓ recent-flares ({len(flares)} flares)")
        else:
            results['errors'] += 1

    # ── 4. Metadata ────────────────────────────────────────────────
    save_and_upload_json('metadata', {'updated': ts, 'version': 2})

    # ── 5. Fetch SUVI + SOHO images ────────────────────────────────
    reliable_images = {}
    reliable_images.update(SUVI_CHANNELS)
    reliable_images.update(SOHO_IMAGES)

    print(f"  Fetching {len(reliable_images)} solar images...")
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_image, name, url): name
            for name, url in reliable_images.items()
        }
        for future in as_completed(futures):
            name, img_data = future.result()
            if img_data is not None:
                ext = 'jpg' if name.startswith('soho-') else 'png'
                ct = 'image/jpeg' if ext == 'jpg' else 'image/png'
                img_path = os.path.join(DATA_DIR, 'images', f'{name}.{ext}')
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                s3_key = f'{CDN_PREFIX}/images/{name}.{ext}'
                if upload_to_spaces(img_path, s3_key, ct, 'max-age=120, public'):
                    results['images'] += 1
                    print(f"    ✓ {name}")
                else:
                    results['errors'] += 1
            else:
                results['errors'] += 1

    # ── 6. SDO/AIA images (may fail DNS) ───────────────────────────
    print(f"  Attempting {len(SDO_AIA_IMAGES)} SDO/AIA images...")
    sdo_ok = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_image, name, url): name
            for name, url in SDO_AIA_IMAGES.items()
        }
        for future in as_completed(futures):
            name, img_data = future.result()
            if img_data is not None:
                img_path = os.path.join(DATA_DIR, 'images', f'{name}.jpg')
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                s3_key = f'{CDN_PREFIX}/images/{name}.jpg'
                if upload_to_spaces(img_path, s3_key, 'image/jpeg', 'max-age=120, public'):
                    sdo_ok += 1
                    print(f"    ✓ {name}")

    if sdo_ok == 0:
        print("    ⚠ SDO/AIA: DNS not resolving. Frontend uses direct fallback URLs.")

    print(f"\n  Summary: {results['json']} JSON, {results['images']} SUVI/SOHO, {sdo_ok} SDO, {results['errors']} errors")
    return 0 if results['errors'] < 5 else 1


if __name__ == '__main__':
    sys.exit(main())
