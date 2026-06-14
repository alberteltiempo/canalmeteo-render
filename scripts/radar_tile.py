#!/usr/bin/env python3
"""
radar_tile_proxy.py — Canal Meteo Radar Tile Cache
===================================================
Downloads RainViewer radar tiles for CONUS and uploads them to
DigitalOcean Spaces CDN for faster, more reliable serving.

Runs every 5 minutes via cron:
  */5 * * * * /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/radar_tile_proxy.py >> /var/log/canalmeteo/radar_proxy.log 2>&1

Strategy:
  - Fetches RainViewer weather-maps.json to get available frames
  - For each frame, downloads all 256px tiles covering CONUS at zooms 2-6
  - Uploads tiles to DO Spaces: data/radar/tiles/{timestamp}/{z}/{x}/{y}.png
  - Uploads manifest: data/radar/manifest.json
  - Cleans up old frames (keeps only current set)

Tile coverage (CONUS bounding box ~[-130, 24] to [-65, 50]):
  Zoom 2:     4 tiles
  Zoom 3:    ~6 tiles
  Zoom 4:   ~16 tiles
  Zoom 5:   ~42 tiles
  Zoom 6:  ~130 tiles
  Total: ~198 tiles per frame × ~13 frames ≈ 2,574 tiles per run
  At ~5KB avg per tile = ~12.5 MB per run (most tiles are transparent/empty)
"""

import json
import time
import os
import sys
import hashlib
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import boto3
from botocore.config import Config

# ─── Configuration ───────────────────────────────────────────
RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"
TILE_SIZE = 256
COLOR_SCHEME = 2      # RainViewer color scheme
SMOOTH = 1            # smoothing
SNOW = 1              # snow coloring

# DO Spaces
SPACES_BUCKET = "canalmeteo-public"
SPACES_REGION = "sfo3"
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"
SPACES_PREFIX = "data/radar/tiles"
MANIFEST_KEY = "data/radar/manifest.json"
CDN_BASE = f"https://{SPACES_BUCKET}.{SPACES_REGION}.digitaloceanspaces.com"

# CONUS bounding box (lng/lat)
CONUS_WEST = -130
CONUS_EAST = -65
CONUS_SOUTH = 24
CONUS_NORTH = 50

# Zoom levels to cache
# Zoom 2-6 covers the broadcast needs (national + regional views)
# RainViewer 256px tiles max at zoom 6
ZOOM_MIN = 2
ZOOM_MAX = 6

# Concurrency
MAX_DOWNLOAD_WORKERS = 20
MAX_UPLOAD_WORKERS = 15
DOWNLOAD_TIMEOUT = 8  # seconds per tile

# Cache directory (local temp)
CACHE_DIR = Path("/tmp/canalmeteo_radar_cache")

# ─── Logging ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("radar_proxy")

# ─── Tile Math ───────────────────────────────────────────────
import math

def lng_to_tile_x(lng, zoom):
    """Convert longitude to tile X coordinate."""
    return int((lng + 180.0) / 360.0 * (1 << zoom))

def lat_to_tile_y(lat, zoom):
    """Convert latitude to tile Y coordinate."""
    lat_rad = math.radians(lat)
    n = 1 << zoom
    return int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)

def get_conus_tiles(zoom):
    """Get list of (z, x, y) tuples covering CONUS at given zoom."""
    x_min = lng_to_tile_x(CONUS_WEST, zoom)
    x_max = lng_to_tile_x(CONUS_EAST, zoom)
    y_min = lat_to_tile_y(CONUS_NORTH, zoom)  # note: y is inverted
    y_max = lat_to_tile_y(CONUS_SOUTH, zoom)
    
    tiles = []
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            tiles.append((zoom, x, y))
    return tiles

def get_all_conus_tiles():
    """Get all tiles for all zoom levels."""
    all_tiles = []
    for z in range(ZOOM_MIN, ZOOM_MAX + 1):
        tiles = get_conus_tiles(z)
        all_tiles.extend(tiles)
        log.info(f"  Zoom {z}: {len(tiles)} tiles")
    return all_tiles


# ─── S3 Client ───────────────────────────────────────────────
def get_s3_client():
    """Create boto3 S3 client for DO Spaces using the do-tor1 profile credentials."""
    # Try AWS_PROFILE-style config first, fall back to env vars
    try:
        session = boto3.Session(profile_name="do-tor1")
        return session.client(
            "s3",
            region_name=SPACES_REGION,
            endpoint_url=SPACES_ENDPOINT,
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                max_pool_connections=MAX_UPLOAD_WORKERS + 5
            )
        )
    except Exception:
        # Fall back to environment variables
        return boto3.client(
            "s3",
            region_name=SPACES_REGION,
            endpoint_url=SPACES_ENDPOINT,
            aws_access_key_id=os.environ.get("DO_SPACES_KEY"),
            aws_secret_access_key=os.environ.get("DO_SPACES_SECRET"),
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                max_pool_connections=MAX_UPLOAD_WORKERS + 5
            )
        )


# ─── Download tile from RainViewer ───────────────────────────
def download_tile(session, host, path, z, x, y):
    """
    Download a single tile from RainViewer.
    Returns (z, x, y, png_bytes) or (z, x, y, None) on failure.
    """
    url = f"{host}{path}/{TILE_SIZE}/{z}/{x}/{y}/{COLOR_SCHEME}/{SMOOTH}_{SNOW}.png"
    try:
        resp = session.get(url, timeout=DOWNLOAD_TIMEOUT)
        if resp.status_code == 200 and len(resp.content) > 0:
            return (z, x, y, resp.content)
        log.debug(f"Tile {z}/{x}/{y}: HTTP {resp.status_code}, {len(resp.content)} bytes")
        return (z, x, y, None)
    except Exception as e:
        log.debug(f"Tile {z}/{x}/{y} failed: {e}")
        return (z, x, y, None)


# ─── Upload tile to DO Spaces ────────────────────────────────
def upload_tile(s3, timestamp, z, x, y, png_bytes):
    """Upload a single tile PNG to DO Spaces."""
    key = f"{SPACES_PREFIX}/{timestamp}/{z}/{x}/{y}.png"
    try:
        s3.put_object(
            Bucket=SPACES_BUCKET,
            Key=key,
            Body=png_bytes,
            ContentType="image/png",
            ACL="public-read",
            CacheControl="public, max-age=300"  # 5 min cache
        )
        return True
    except Exception as e:
        log.warning(f"Upload failed {key}: {e}")
        return False


# ─── Process one frame ──────────────────────────────────────
def process_frame(s3, http_session, host, frame, conus_tiles):
    """
    Download all CONUS tiles for one radar frame and upload to CDN.
    Returns number of tiles uploaded.
    """
    timestamp = frame["time"]
    path = frame["path"]
    uploaded = 0
    skipped = 0
    failed = 0
    
    # Download tiles in parallel
    results = []
    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
        futures = {
            pool.submit(download_tile, http_session, host, path, z, x, y): (z, x, y)
            for z, x, y in conus_tiles
        }
        for future in as_completed(futures):
            z, x, y, png_bytes = future.result()
            if png_bytes is not None:
                results.append((z, x, y, png_bytes))
            else:
                failed += 1
    
    # Upload non-empty tiles
    # Skip tiles that are fully transparent (very small file = empty tile)
    MIN_TILE_SIZE = 200  # bytes — transparent 256px PNG is ~180 bytes
    
    with ThreadPoolExecutor(max_workers=MAX_UPLOAD_WORKERS) as pool:
        upload_futures = []
        for z, x, y, png_bytes in results:
            if len(png_bytes) < MIN_TILE_SIZE:
                skipped += 1
                continue
            upload_futures.append(
                pool.submit(upload_tile, s3, timestamp, z, x, y, png_bytes)
            )
        for future in as_completed(upload_futures):
            if future.result():
                uploaded += 1
    
    log.info(f"  Frame {timestamp}: {uploaded} uploaded, {skipped} empty, {failed} failed (of {len(conus_tiles)} total)")
    return uploaded


# ─── Cleanup old frames ─────────────────────────────────────
def cleanup_old_frames(s3, current_timestamps):
    """Remove tiles from CDN for frames that are no longer in the RainViewer feed."""
    current_set = {str(ts) for ts in current_timestamps}
    
    try:
        # List all timestamp prefixes in our tile directory
        paginator = s3.get_paginator("list_objects_v2")
        existing_timestamps = set()
        
        for page in paginator.paginate(Bucket=SPACES_BUCKET, Prefix=f"{SPACES_PREFIX}/", Delimiter="/"):
            for prefix in page.get("CommonPrefixes", []):
                # Extract timestamp from prefix like "data/radar/tiles/1234567890/"
                ts = prefix["Prefix"].rstrip("/").split("/")[-1]
                existing_timestamps.add(ts)
        
        stale = existing_timestamps - current_set
        if not stale:
            log.info("No stale frames to clean up")
            return
        
        log.info(f"Cleaning up {len(stale)} stale frame(s)...")
        
        for ts in stale:
            # Delete all objects under this timestamp prefix
            prefix = f"{SPACES_PREFIX}/{ts}/"
            objects_to_delete = []
            
            for page in paginator.paginate(Bucket=SPACES_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    objects_to_delete.append({"Key": obj["Key"]})
            
            # Batch delete (max 1000 per request)
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i:i+1000]
                s3.delete_objects(
                    Bucket=SPACES_BUCKET,
                    Delete={"Objects": batch, "Quiet": True}
                )
            
            log.info(f"  Deleted {len(objects_to_delete)} tiles for frame {ts}")
    
    except Exception as e:
        log.warning(f"Cleanup error: {e}")


# ─── Upload manifest ────────────────────────────────────────
def upload_manifest(s3, host, frames):
    """
    Upload manifest.json — tells the frontend which frames are cached
    and provides both CDN and fallback RainViewer URLs.
    """
    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "cdn_base": CDN_BASE,
        "tile_path_template": f"{SPACES_PREFIX}/{{time}}/{{z}}/{{x}}/{{y}}.png",
        "fallback_host": host,
        "tile_size": TILE_SIZE,
        "color_scheme": COLOR_SCHEME,
        "frames": [
            {
                "time": f["time"],
                "path": f["path"],
                "cdn_url": f"{CDN_BASE}/{SPACES_PREFIX}/{f['time']}/{{z}}/{{x}}/{{y}}.png",
                "fallback_url": f"{host}{f['path']}/{TILE_SIZE}/{{z}}/{{x}}/{{y}}/{COLOR_SCHEME}/{SMOOTH}_{SNOW}.png"
            }
            for f in frames
        ]
    }
    
    try:
        s3.put_object(
            Bucket=SPACES_BUCKET,
            Key=MANIFEST_KEY,
            Body=json.dumps(manifest, indent=2),
            ContentType="application/json",
            ACL="public-read",
            CacheControl="public, max-age=120"  # 2 min cache for manifest
        )
        log.info(f"✅ Manifest uploaded: {len(frames)} frames")
    except Exception as e:
        log.error(f"Failed to upload manifest: {e}")


# ─── Main ────────────────────────────────────────────────────
def main():
    start_time = time.time()
    
    # --verbose flag for debugging
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    log.info("=" * 60)
    log.info("Canal Meteo Radar Tile Proxy — Starting")
    
    # 1. Fetch RainViewer API
    try:
        resp = requests.get(RAINVIEWER_API, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error(f"Failed to fetch RainViewer API: {e}")
        sys.exit(1)
    
    host = data.get("host", "https://tilecache.rainviewer.com")
    past_frames = data.get("radar", {}).get("past", [])
    
    if not past_frames:
        log.error("No radar frames available")
        sys.exit(1)
    
    log.info(f"RainViewer: {len(past_frames)} frames, host: {host}")
    
    # 2. Diagnostic: test a single tile download before bulk processing
    test_frame = past_frames[0]
    test_url = f"{host}{test_frame['path']}/{TILE_SIZE}/3/1/2/{COLOR_SCHEME}/{SMOOTH}_{SNOW}.png"
    log.info(f"Test tile URL: {test_url}")
    try:
        test_resp = requests.get(test_url, timeout=10)
        log.info(f"Test tile: HTTP {test_resp.status_code}, {len(test_resp.content)} bytes, Content-Type: {test_resp.headers.get('Content-Type', 'unknown')}")
        if test_resp.status_code != 200:
            log.warning(f"Test tile response body: {test_resp.text[:200]}")
    except Exception as e:
        log.error(f"Test tile failed: {e}")
    
    # 3. Calculate CONUS tiles
    log.info("Calculating CONUS tile coverage:")
    conus_tiles = get_all_conus_tiles()
    log.info(f"Total tiles per frame: {len(conus_tiles)}")
    log.info(f"Total tiles to process: {len(conus_tiles) * len(past_frames)}")
    
    # 3. Initialize clients
    s3 = get_s3_client()
    http_session = requests.Session()
    http_session.headers.update({"User-Agent": "CanalMeteoTV/1.0"})
    # Match pool size to download workers to avoid "Connection pool is full" warnings
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_DOWNLOAD_WORKERS,
        pool_maxsize=MAX_DOWNLOAD_WORKERS,
        max_retries=2
    )
    http_session.mount("https://", adapter)
    http_session.mount("http://", adapter)
    
    # 4. Process each frame
    total_uploaded = 0
    for i, frame in enumerate(past_frames):
        log.info(f"Processing frame {i+1}/{len(past_frames)} (ts={frame['time']})...")
        count = process_frame(s3, http_session, host, frame, conus_tiles)
        total_uploaded += count
    
    # 5. Upload manifest
    upload_manifest(s3, host, past_frames)
    
    # 6. Cleanup old frames
    current_timestamps = [str(f["time"]) for f in past_frames]
    cleanup_old_frames(s3, current_timestamps)
    
    elapsed = time.time() - start_time
    log.info(f"✅ Done: {total_uploaded} tiles uploaded in {elapsed:.1f}s")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
