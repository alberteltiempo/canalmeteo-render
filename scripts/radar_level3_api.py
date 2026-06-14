#!/usr/bin/env python3
"""
NEXRAD Level 3 API — Canal Meteo TV
Downloads Level 3 products from AWS on-demand, renders PNG tiles,
caches in DO Spaces CDN, serves URLs via HTTP API.

Architecture:
  Tormenta → GET /api/radar?site=KFWS&product=N0Q
    → Check cache (CDN + local)
    → If miss: download L3 from AWS S3 → pyart render → upload CDN
    → Return {url, timestamp, bounds, radar}

Usage:
  systemctl start radar-api
  curl http://localhost:8002/api/radar?site=KFWS&product=N0Q
"""

import os
import io
import time
import json
import logging
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
import re

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.figure import Figure
import pyart
import fsspec
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────
CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_BASE = 'data/nexrad'
CDN_URL_BASE = f'https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CDN_BASE}'

L3_BUCKET = 'unidata-nexrad-level3'

WORK_DIR = Path('/tmp/nexrad_work')
WORK_DIR.mkdir(exist_ok=True)

CACHE_TTL_SECONDS = 180  # 3 minutes — radar updates every ~4-6 min

# ─── Product catalog ──────────────────────────────────────────────
PRODUCTS = {
    'N0Q': {'label': 'Reflectividad', 'field': 'reflectivity', 'vmin': -30, 'vmax': 80,  'unit': 'dBZ', 'cmap': 'nws_ref'},
    'N0U': {'label': 'Velocidad',     'field': 'velocity',     'vmin': -64, 'vmax': 64,  'unit': 'm/s', 'cmap': 'nws_vel'},
    'N0S': {'label': 'Vel. relativa', 'field': 'storm_relative_velocity', 'vmin': -30, 'vmax': 30, 'unit': 'm/s', 'cmap': 'nws_vel'},
    'N0C': {'label': 'Coef. correlación', 'field': 'cross_correlation_ratio', 'vmin': 0.2, 'vmax': 1.05, 'unit': '', 'cmap': 'nws_cc'},
    'N0X': {'label': 'Refl. diferencial', 'field': 'differential_reflectivity', 'vmin': -4, 'vmax': 8, 'unit': 'dB', 'cmap': 'nws_zdr'},
    'NET': {'label': 'Echo Tops',     'field': 'radar_echo_tops', 'vmin': 0, 'vmax': 70, 'unit': 'kft', 'cmap': 'nws_et'},
}

# ─── NWS colormaps (simplified but accurate) ──────────────────────
def make_cmap():
    """Return dict of NWS-standard colormaps for each product."""
    # Reflectivity (NWS standard)
    ref_colors = [
        (-30, '#646464'), (-20, '#787878'), (-10, '#8C8C8C'), (0, '#A0A0A0'),
        (5, '#00ECEC'), (10, '#01A0F6'), (15, '#0000F6'),
        (20, '#00FF00'), (25, '#00C800'), (30, '#009000'),
        (35, '#FFFF00'), (40, '#E7C000'), (45, '#FF9000'),
        (50, '#FF0000'), (55, '#D60000'), (60, '#C00000'),
        (65, '#FF00FF'), (70, '#9955C9'), (75, '#FFFFFF'),
    ]
    # Velocity (red=away, green=toward)
    vel_colors = [
        (-64, '#006400'), (-50, '#00C800'), (-30, '#00FF00'),
        (-15, '#A0F0A0'), (-5, '#E0F0E0'), (0, '#FFFFFF'),
        (5, '#F0E0E0'), (15, '#F0A0A0'), (30, '#FF0000'),
        (50, '#C80000'), (64, '#640000'),
    ]
    # Correlation coefficient
    cc_colors = [
        (0.2, '#000080'), (0.5, '#0000FF'), (0.7, '#00FFFF'),
        (0.85, '#00FF00'), (0.9, '#FFFF00'), (0.95, '#FF8000'),
        (0.97, '#FF0000'), (1.0, '#FFFFFF'), (1.05, '#C0C0C0'),
    ]
    # Differential reflectivity
    zdr_colors = [
        (-4, '#000080'), (-2, '#0000FF'), (-0.5, '#00FFFF'),
        (0, '#00FF00'), (1, '#FFFF00'), (2, '#FF8000'),
        (4, '#FF0000'), (6, '#FF00FF'), (8, '#FFFFFF'),
    ]
    # Echo tops (kft)
    et_colors = [
        (0, '#000080'), (10, '#0000FF'), (20, '#00FFFF'),
        (30, '#00FF00'), (40, '#FFFF00'), (50, '#FF8000'),
        (60, '#FF0000'), (70, '#FF00FF'),
    ]

    cmaps = {}
    for name, stops in [('nws_ref', ref_colors), ('nws_vel', vel_colors),
                        ('nws_cc', cc_colors), ('nws_zdr', zdr_colors),
                        ('nws_et', et_colors)]:
        vals = [s[0] for s in stops]
        cols = [s[1] for s in stops]
        vmin, vmax = vals[0], vals[-1]
        norm_vals = [(v - vmin) / (vmax - vmin) for v in vals]
        cmaps[name] = mcolors.LinearSegmentedColormap.from_list(
            name, list(zip(norm_vals, cols)), N=256)
    return cmaps

CMAPS = make_cmap()

# ─── S3 filesystem ─────────────────────────────────────────────────
fs = fsspec.filesystem("s3", anon=True)

# In-memory cache of recent responses (site+product → result)
_memcache = {}


def list_latest_l3(site: str, product: str, max_files: int = 5):
    """List latest Level 3 files for site+product in last hour."""
    now = datetime.now(timezone.utc)
    # Try current and previous hour to handle hour boundaries
    files_all = []
    for hours_back in range(2):
        dt = now - timedelta(hours=hours_back)
        # Bucket path: SITE/SITE_PRODUCT_YYYY_MM_DD_HH
        prefix = f'{L3_BUCKET}/{site}_{product}_{dt.strftime("%Y_%m_%d_%H")}'
        try:
            found = fs.glob(f's3://{prefix}*')
            files_all.extend(found)
        except Exception as e:
            log.warning(f"  S3 glob error: {e}")
    # Sort by filename (contains timestamp)
    files_all.sort(reverse=True)
    return files_all[:max_files]


def parse_timestamp_from_filename(filename: str) -> Optional[datetime]:
    """Extract timestamp from L3 filename: KFWS_N0Q_2026_04_14_17_23_45"""
    m = re.search(r'(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})', filename)
    if not m:
        return None
    return datetime(*[int(g) for g in m.groups()], tzinfo=timezone.utc)


def get_cache_key(site: str, product: str, timestamp: datetime) -> str:
    """Stable cache key for CDN upload."""
    ts = timestamp.strftime('%Y%m%d%H%M%S')
    return f'{site}_{product}_{ts}'


def cdn_upload(local_path: str, cdn_key: str, content_type: str = 'image/png') -> bool:
    """Upload file to DigitalOcean Spaces CDN."""
    cmd = ['aws', 's3', 'cp', local_path, f's3://{CDN_BUCKET}/{cdn_key}',
           '--profile', AWS_PROFILE, '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=300',
           '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception as e:
        log.warning(f"  CDN upload failed: {e}")
        return False


def cdn_exists(cdn_key: str) -> bool:
    """Check if file already in CDN."""
    cmd = ['aws', 's3api', 'head-object',
           '--bucket', CDN_BUCKET, '--key', cdn_key,
           '--profile', AWS_PROFILE,
           '--endpoint-url', CDN_ENDPOINT]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except:
        return False


def render_l3_to_png(s3_path: str, product: str) -> tuple:
    """
    Download L3 from S3, render to PNG with transparency.
    Returns (local_png_path, bounds_dict) or (None, None) on error.
    """
    try:
        t0 = time.time()
        pcfg = PRODUCTS[product]

        # Download file
        local_file = WORK_DIR / Path(s3_path).name
        with fs.open(s3_path, 'rb') as src, open(local_file, 'wb') as dst:
            dst.write(src.read())
        t_dl = time.time() - t0

        # Parse with pyart
        radar = pyart.io.read_nexrad_level3(str(local_file))
        t_parse = time.time() - t0 - t_dl

        # Identify field
        field_name = list(radar.fields.keys())[0]
        data = radar.fields[field_name]['data']
        log.info(f"    field={field_name} shape={data.shape} range=[{data.min():.1f}, {data.max():.1f}]")

        # Get radar location + max range
        radar_lon = float(radar.longitude['data'][0])
        radar_lat = float(radar.latitude['data'][0])
        max_range_km = float(radar.range['data'].max() / 1000.0)

        # Calculate bounds (geographic extent) — approx using lat/lon delta
        # Earth radius ~6371 km, 1° lat = 111.32 km, 1° lon = 111.32 * cos(lat) km
        lat_deg_per_km = 1.0 / 111.32
        lon_deg_per_km = 1.0 / (111.32 * np.cos(np.radians(radar_lat)))
        half_lat = max_range_km * lat_deg_per_km
        half_lon = max_range_km * lon_deg_per_km

        bounds = {
            'north': radar_lat + half_lat,
            'south': radar_lat - half_lat,
            'east': radar_lon + half_lon,
            'west': radar_lon - half_lon,
            'radar_lat': radar_lat,
            'radar_lon': radar_lon,
            'range_km': max_range_km,
        }

        # Render PPI (Plan Position Indicator) to transparent PNG
        fig = Figure(figsize=(10, 10), dpi=200, facecolor='none')
        ax = fig.add_subplot(111, facecolor='none')
        ax.set_aspect('equal')

        # Get azimuth + range grid
        display = pyart.graph.RadarDisplay(radar)
        cmap = CMAPS.get(pcfg['cmap'], 'viridis')

        display.plot_ppi(
            field_name, sweep=0, ax=ax, fig=fig,
            vmin=pcfg['vmin'], vmax=pcfg['vmax'],
            cmap=cmap,
            colorbar_flag=False, title_flag=False,
            axislabels_flag=False,
        )

        ax.set_xticks([])
        ax.set_yticks([])
        ax.axis('off')
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Save as transparent PNG
        png_path = WORK_DIR / f'{local_file.stem}.png'
        fig.savefig(png_path, transparent=True, bbox_inches='tight',
                    pad_inches=0, dpi=200)
        plt.close(fig)

        # Clean up source L3 file
        try:
            local_file.unlink()
        except:
            pass

        t_total = time.time() - t0
        log.info(f"    rendered in {t_total:.1f}s (dl={t_dl:.1f}s parse={t_parse:.1f}s)")
        return str(png_path), bounds

    except Exception as e:
        log.error(f"  render error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def process_radar_request(site: str, product: str, frames: int = 1):
    """
    Main processing: find latest L3 files, render, upload, return URLs.
    Returns list of {url, timestamp, bounds} for up to `frames` frames.
    """
    site = site.upper()
    product = product.upper()

    if product not in PRODUCTS:
        raise HTTPException(400, f'Unknown product: {product}. Valid: {list(PRODUCTS.keys())}')

    # Memcache check (skip re-processing within TTL)
    mem_key = f'{site}_{product}_{frames}'
    now_ts = time.time()
    if mem_key in _memcache:
        cached = _memcache[mem_key]
        if now_ts - cached['cached_at'] < CACHE_TTL_SECONDS:
            log.info(f"  🎯 memcache hit: {site} {product}")
            return cached['data']

    # List latest L3 files
    log.info(f"  Listing L3 for {site} {product}...")
    files = list_latest_l3(site, product, max_files=frames)
    if not files:
        raise HTTPException(404, f'No L3 data found for {site}/{product} in last hour')

    # Process each frame
    results = []
    for s3_path in files:
        fname = Path(s3_path).name
        timestamp = parse_timestamp_from_filename(fname)
        if not timestamp:
            continue

        cache_key = get_cache_key(site, product, timestamp)
        cdn_png_key = f'{CDN_BASE}/{cache_key}.png'
        cdn_json_key = f'{CDN_BASE}/{cache_key}.json'
        cdn_url = f'{CDN_URL_BASE}/{cache_key}.png'

        # Check if already in CDN
        if cdn_exists(cdn_png_key):
            log.info(f"  ✓ CDN cached: {cache_key}")
            # Fetch bounds JSON if cached
            bounds_url = f'{CDN_URL_BASE}/{cache_key}.json'
            try:
                import requests
                r = requests.get(bounds_url, timeout=5)
                bounds = r.json() if r.ok else None
            except:
                bounds = None
            if bounds:
                results.append({
                    'url': cdn_url,
                    'timestamp': int(timestamp.timestamp()),
                    'iso': timestamp.isoformat(),
                    'bounds': bounds,
                })
                continue

        # Not cached — download + render + upload
        log.info(f"  ⚙️ Processing: {fname}")
        png_path, bounds = render_l3_to_png(f's3://{s3_path}', product)
        if not png_path or not bounds:
            continue

        # Upload PNG
        if cdn_upload(png_path, cdn_png_key):
            log.info(f"  ☁️ Uploaded: {cdn_url}")

            # Also upload bounds JSON for future cache hits
            bounds_path = png_path.replace('.png', '.json')
            with open(bounds_path, 'w') as f:
                json.dump(bounds, f)
            cdn_upload(bounds_path, cdn_json_key, 'application/json')

            results.append({
                'url': cdn_url,
                'timestamp': int(timestamp.timestamp()),
                'iso': timestamp.isoformat(),
                'bounds': bounds,
            })

            # Clean up local
            try:
                Path(png_path).unlink()
                Path(bounds_path).unlink()
            except:
                pass

    # Sort by timestamp (oldest first for animation)
    results.sort(key=lambda r: r['timestamp'])

    # Store in memcache
    _memcache[mem_key] = {'cached_at': now_ts, 'data': results}

    return results


# ─── FastAPI app ───────────────────────────────────────────────────
app = FastAPI(title="Canal Meteo Radar API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "Canal Meteo Radar API",
            "products": list(PRODUCTS.keys()),
            "usage": "/api/radar?site=KFWS&product=N0Q&frames=1"}


@app.get("/api/radar")
def get_radar(
    site: str = Query(..., description="4-letter radar site (e.g. KFWS)"),
    product: str = Query(..., description="Product code (N0Q, N0U, N0C, N0X, N0S, NET)"),
    frames: int = Query(1, ge=1, le=10, description="Number of frames (1-10)"),
):
    """Get latest radar data URL(s) for a site+product."""
    try:
        t0 = time.time()
        results = process_radar_request(site, product, frames)
        elapsed = time.time() - t0

        return {
            'site': site.upper(),
            'product': product.upper(),
            'label': PRODUCTS[product.upper()]['label'],
            'unit': PRODUCTS[product.upper()]['unit'],
            'vmin': PRODUCTS[product.upper()]['vmin'],
            'vmax': PRODUCTS[product.upper()]['vmax'],
            'count': len(results),
            'frames': results,
            'elapsed_s': round(elapsed, 2),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Request failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f'Processing error: {str(e)}')


@app.get("/api/radar/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8002, log_level='info')
