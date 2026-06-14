#!/usr/bin/env python3
"""
Canal Meteo TV — Severe Warnings Fetcher
Obtiene Tornado Warning + Severe Thunderstorm Warning del NWS,
resuelve geometrías de zonas UGC, y sube JSON a DigitalOcean Spaces.

Cron: */15 * * * * (cada 15 segundos via wrapper, o cada minuto)
"""

import json
import logging
import os
import sys
import time
import subprocess
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
CONFIG = {
    'nws_url': 'https://api.weather.gov/alerts/active',
    'user_agent': 'CanalMeteoTV/2.0 (contacto@canalmeteo.tv)',
    
    # Warning types to fetch
    'events': ['Tornado Warning', 'Severe Thunderstorm Warning'],
    
    # Local paths
    'data_dir': '/opt/canalmeteo/data/radar-warnings',
    'output_file': 'severe_warnings.json',
    
    # DigitalOcean Spaces
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_path': 'radar/severe_warnings.json',
    
    # Zone geometry cache (avoid re-fetching same zones)
    'zone_cache_file': '/opt/canalmeteo/data/radar-warnings/zone_cache.json',
    'zone_cache_max_age': 86400,  # 24 hours
    
    # Concurrency for zone geometry resolution
    'max_workers': 8,
    'zone_timeout': 10,
}

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('severe-warnings')

# ═══════════════════════════════════════════════════════════════
# ZONE GEOMETRY CACHE
# ═══════════════════════════════════════════════════════════════
zone_cache = {}

def load_zone_cache():
    global zone_cache
    cache_file = CONFIG['zone_cache_file']
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            # Purge expired entries
            now = time.time()
            zone_cache = {
                k: v for k, v in data.items()
                if now - v.get('_ts', 0) < CONFIG['zone_cache_max_age']
            }
            log.info(f"📦 Cache de zonas: {len(zone_cache)} entradas válidas")
        except Exception as e:
            log.warning(f"⚠️ Error cargando cache de zonas: {e}")
            zone_cache = {}

def save_zone_cache():
    cache_file = CONFIG['zone_cache_file']
    try:
        with open(cache_file, 'w') as f:
            json.dump(zone_cache, f)
    except Exception as e:
        log.warning(f"⚠️ Error guardando cache de zonas: {e}")

def get_zone_geometry(zone_url):
    """Fetch geometry for a single NWS zone, using cache."""
    if zone_url in zone_cache:
        cached = zone_cache[zone_url]
        return cached.get('geometry')
    
    try:
        resp = requests.get(zone_url, headers={
            'User-Agent': CONFIG['user_agent'],
            'Accept': 'application/geo+json'
        }, timeout=CONFIG['zone_timeout'])
        
        if resp.status_code == 200:
            data = resp.json()
            geom = data.get('geometry')
            if geom:
                zone_cache[zone_url] = {
                    'geometry': geom,
                    '_ts': time.time()
                }
                return geom
    except Exception as e:
        log.debug(f"Error fetching zone {zone_url}: {e}")
    
    return None

def merge_geometries(geometries):
    """Merge multiple geometries into a single MultiPolygon."""
    all_coords = []
    for geom in geometries:
        if not geom:
            continue
        gtype = geom.get('type', '')
        coords = geom.get('coordinates', [])
        if gtype == 'Polygon':
            all_coords.append(coords)
        elif gtype == 'MultiPolygon':
            all_coords.extend(coords)
    
    if not all_coords:
        return None
    if len(all_coords) == 1:
        return {'type': 'Polygon', 'coordinates': all_coords[0]}
    return {'type': 'MultiPolygon', 'coordinates': all_coords}

# ═══════════════════════════════════════════════════════════════
# FETCH WARNINGS
# ═══════════════════════════════════════════════════════════════
def fetch_warnings():
    """Fetch all active severe warnings from NWS."""
    headers = {
        'User-Agent': CONFIG['user_agent'],
        'Accept': 'application/geo+json'
    }
    
    all_features = []
    
    for event in CONFIG['events']:
        try:
            log.info(f"📡 Consultando NWS: {event}...")
            resp = requests.get(
                CONFIG['nws_url'],
                params={
                    'status': 'actual',
                    'message_type': 'alert',
                    'event': event
                },
                headers=headers,
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            features = data.get('features', [])
            log.info(f"   → {len(features)} {event}(s) activo(s)")
            
            for f in features:
                f['_warningType'] = 'tornado' if 'Tornado' in event else 'severe'
                all_features.append(f)
                
        except requests.exceptions.RequestException as e:
            log.error(f"❌ Error consultando NWS para {event}: {e}")
    
    return all_features

# ═══════════════════════════════════════════════════════════════
# RESOLVE GEOMETRIES
# ═══════════════════════════════════════════════════════════════
def resolve_all_geometries(features):
    """Resolve geometry for all features, using zone lookup if needed."""
    resolved = []
    needs_zone = []
    
    for f in features:
        if f.get('geometry'):
            resolved.append(f)
        else:
            needs_zone.append(f)
    
    log.info(f"📍 Con geometría directa: {len(resolved)} | Necesitan resolución: {len(needs_zone)}")
    
    if not needs_zone:
        return resolved
    
    # Collect all unique zone URLs
    all_zone_urls = set()
    for f in needs_zone:
        zones = f.get('properties', {}).get('affectedZones', [])
        all_zone_urls.update(zones)
    
    log.info(f"🗺️ Resolviendo {len(all_zone_urls)} zonas únicas...")
    
    # Fetch all zone geometries in parallel
    with ThreadPoolExecutor(max_workers=CONFIG['max_workers']) as executor:
        future_to_url = {
            executor.submit(get_zone_geometry, url): url
            for url in all_zone_urls
        }
        
        zone_geometries = {}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                geom = future.result()
                if geom:
                    zone_geometries[url] = geom
            except Exception as e:
                log.debug(f"Error resolving {url}: {e}")
    
    log.info(f"   → Resueltas: {len(zone_geometries)} / {len(all_zone_urls)} zonas")
    
    # Now assign geometries to features
    for f in needs_zone:
        zones = f.get('properties', {}).get('affectedZones', [])
        geoms = [zone_geometries[z] for z in zones if z in zone_geometries]
        
        if geoms:
            merged = merge_geometries(geoms)
            if merged:
                f['geometry'] = merged
                resolved.append(f)
    
    return resolved

# ═══════════════════════════════════════════════════════════════
# BUILD OUTPUT JSON
# ═══════════════════════════════════════════════════════════════
def build_output(features):
    """Build the final JSON output."""
    warnings = []
    
    for f in features:
        props = f.get('properties', {})
        warnings.append({
            'id': props.get('id', ''),
            'warningType': f.get('_warningType', 'severe'),
            'event': props.get('event', ''),
            'areaDesc': props.get('areaDesc', ''),
            'severity': props.get('severity', ''),
            'urgency': props.get('urgency', ''),
            'onset': props.get('onset', ''),
            'expires': props.get('expires', ''),
            'headline': props.get('headline', ''),
            'description': props.get('description', '')[:500],  # truncate
            'senderName': props.get('senderName', ''),
            'geometry': f.get('geometry')
        })
    
    # Sort: tornado first, then severe
    warnings.sort(key=lambda w: (0 if w['warningType'] == 'tornado' else 1))
    
    output = {
        'generated': datetime.now(timezone.utc).isoformat(),
        'generated_ts': int(time.time()),
        'tornado_count': sum(1 for w in warnings if w['warningType'] == 'tornado'),
        'severe_count': sum(1 for w in warnings if w['warningType'] == 'severe'),
        'total': len(warnings),
        'warnings': warnings
    }
    
    return output

# ═══════════════════════════════════════════════════════════════
# UPLOAD TO SPACES
# ═══════════════════════════════════════════════════════════════
def upload_to_spaces(local_path):
    """Upload JSON to DigitalOcean Spaces."""
    s3_dest = f"s3://{CONFIG['s3_bucket']}/{CONFIG['s3_path']}"
    
    cmd = [
        'aws', 's3', 'cp', local_path, s3_dest,
        '--endpoint-url', CONFIG['aws_endpoint'],
        '--profile', CONFIG['aws_profile'],
        '--content-type', 'application/json',
        '--cache-control', 'max-age=10, public',
        '--acl', 'public-read'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            log.info(f"☁️ Subido a Spaces: {CONFIG['s3_path']}")
            return True
        else:
            log.error(f"❌ Error subiendo a Spaces: {result.stderr}")
            return False
    except Exception as e:
        log.error(f"❌ Error en upload: {e}")
        return False

# ═══════════════════════════════════════════════════════════════
# ALSO UPLOAD RAINVIEWER DATA
# ═══════════════════════════════════════════════════════════════
def fetch_and_upload_rainviewer():
    """Fetch RainViewer API data and upload to Spaces for faster client access."""
    try:
        resp = requests.get(
            'https://api.rainviewer.com/public/weather-maps.json',
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        
        local_path = os.path.join(CONFIG['data_dir'], 'rainviewer.json')
        with open(local_path, 'w') as f:
            json.dump(data, f)
        
        s3_dest = f"s3://{CONFIG['s3_bucket']}/radar/rainviewer.json"
        cmd = [
            'aws', 's3', 'cp', local_path, s3_dest,
            '--endpoint-url', CONFIG['aws_endpoint'],
            '--profile', CONFIG['aws_profile'],
            '--content-type', 'application/json',
            '--cache-control', 'max-age=60, public',
            '--acl', 'public-read'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            log.info(f"📡 RainViewer data subido a Spaces")
        else:
            log.warning(f"⚠️ Error subiendo RainViewer: {result.stderr}")
            
    except Exception as e:
        log.warning(f"⚠️ Error fetching RainViewer: {e}")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    start = time.time()
    log.info("🌪️ Canal Meteo TV — Severe Warnings Fetcher")
    
    # Ensure directories
    os.makedirs(CONFIG['data_dir'], exist_ok=True)
    
    # Load zone cache
    load_zone_cache()
    
    # Fetch warnings
    features = fetch_warnings()
    
    # Resolve geometries
    resolved = resolve_all_geometries(features)
    log.info(f"✅ Total avisos con geometría: {len(resolved)}")
    
    # Build output
    output = build_output(resolved)
    
    # Save locally
    local_path = os.path.join(CONFIG['data_dir'], CONFIG['output_file'])
    with open(local_path, 'w') as f:
        json.dump(output, f, ensure_ascii=False)
    log.info(f"💾 Guardado local: {local_path}")
    
    # Upload to Spaces
    upload_to_spaces(local_path)
    
    # Also upload RainViewer data
    fetch_and_upload_rainviewer()
    
    # Save zone cache
    save_zone_cache()
    
    elapsed = time.time() - start
    log.info(f"⏱️ Completado en {elapsed:.1f}s | "
             f"🌪️ {output['tornado_count']} tornado | "
             f"⛈️ {output['severe_count']} severe | "
             f"📊 Total: {output['total']}")

if __name__ == '__main__':
    main()
