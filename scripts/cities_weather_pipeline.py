#!/usr/bin/env python3
"""
Canal Meteo - Cities Weather Pipeline

Llama a weather-api.php?all=1 cada hora y sube el resultado al CDN.
El layout principal (canalmeteo-layout.html) lee desde el CDN, evitando
que cada visita ejecute las 60 llamadas a NWS en serie en GoDaddy.

Ubicación:  /opt/canalmeteo/scripts/cities_weather_pipeline.py
Cron:       0 * * * * (cada hora)
Lock:       /tmp/cities_weather.lock
Log:        /var/log/canalmeteo/cities_weather.log

Uso:
    python3 cities_weather_pipeline.py          # Una sola ejecución
    python3 cities_weather_pipeline.py --debug  # Verbose

Salida CDN:
    https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/cities/weather.json
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════
CONFIG = {
    'weather_api_url': 'https://canalmeteo.tv/widget/weather-api.php?all=1',
    'fetch_timeout_sec': 180,        # PHP puede tardar mucho la primera vez
    'output_local': '/opt/canalmeteo/data/cities_weather.json',
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_path': os.environ.get('CDN_PREFIX', '') + 'data/cities/weather.json',
    'public_url': 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/' + os.environ.get('CDN_PREFIX', '') + 'data/cities/weather.json',
    'expected_min_count': 50,        # Mínimo aceptable de ciudades en respuesta
    'user_agent': 'CanalMeteoCitiesPipeline/1.0',
}

# ═══════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════
def setup_logging(debug=False):
    log_dir = Path('/var/log/canalmeteo')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'cities_weather.log'

    handlers = [logging.FileHandler(str(log_file), encoding='utf-8')]
    if debug or sys.stderr.isatty():
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers,
    )

# ═══════════════════════════════════════════════════════════════════
# FETCH
# ═══════════════════════════════════════════════════════════════════
def fetch_weather():
    """Llama a weather-api.php?all=1 y devuelve el dict parseado."""
    url = CONFIG['weather_api_url']
    timeout = CONFIG['fetch_timeout_sec']
    logging.info(f'Fetching {url} (timeout={timeout}s)')
    started = time.time()
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={'User-Agent': CONFIG['user_agent']},
        )
        elapsed = time.time() - started
        logging.info(f'HTTP {r.status_code} en {elapsed:.1f}s ({len(r.content)} bytes)')
        r.raise_for_status()
        data = r.json()
        return data
    except requests.exceptions.Timeout:
        logging.error(f'Timeout tras {timeout}s')
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f'Request error: {e}')
        return None
    except json.JSONDecodeError as e:
        logging.error(f'JSON decode error: {e}')
        return None

def validate_weather_data(data):
    """Verifica que el JSON tiene la estructura esperada."""
    if not isinstance(data, dict):
        logging.error('Response no es un dict')
        return False
    if not data.get('success'):
        logging.error(f'success=False: {data.get("error", "(no error msg)")}')
        return False
    cities = data.get('data', [])
    count = len(cities)
    if count < CONFIG['expected_min_count']:
        logging.warning(f'Solo {count} ciudades, esperaba al menos {CONFIG["expected_min_count"]}')
        # No es fatal, continuamos
    logging.info(f'Validación OK: {count} ciudades')
    # Sample first city for sanity check
    if cities:
        first = cities[0]
        logging.info(f'Primera ciudad: {first.get("city")}, {first.get("state")} → temp={first.get("temp")} cond={first.get("conditionEs")}')
    return True

# ═══════════════════════════════════════════════════════════════════
# ENRICH (añadimos metadata útil para el cliente)
# ═══════════════════════════════════════════════════════════════════
def enrich(data):
    """Añade metadata al JSON antes de subir al CDN."""
    data['_pipeline'] = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': CONFIG['weather_api_url'],
        'pipeline': 'cities_weather_pipeline.py',
    }
    # Crear lookup map por "City|State" para acceso O(1) en JS
    if 'data' in data and isinstance(data['data'], list):
        lookup = {}
        for c in data['data']:
            key = f"{c.get('city')}|{c.get('state')}"
            lookup[key] = c
        data['by_key'] = lookup
    return data

# ═══════════════════════════════════════════════════════════════════
# SAVE LOCAL & UPLOAD CDN
# ═══════════════════════════════════════════════════════════════════
def save_local(data, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    size = p.stat().st_size
    logging.info(f'Guardado local: {p} ({size:,} bytes)')
    return p

def upload_to_cdn(local_path):
    s3_uri = f"s3://{CONFIG['s3_bucket']}/{CONFIG['s3_path']}"
    cmd = [
        'aws', '--profile', CONFIG['aws_profile'],
        '--endpoint-url', CONFIG['aws_endpoint'],
        's3', 'cp', str(local_path), s3_uri,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'public, max-age=600',
    ]
    logging.info(f'Subiendo a {s3_uri}')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logging.error(f'aws s3 cp failed: {result.stderr}')
            return False
        logging.info(f'Upload OK → {CONFIG["public_url"]}')
        return True
    except subprocess.TimeoutExpired:
        logging.error('aws s3 cp timeout')
        return False
    except Exception as e:
        logging.error(f'aws s3 cp exception: {e}')
        return False

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    debug = '--debug' in sys.argv
    setup_logging(debug=debug)

    logging.info('=' * 60)
    logging.info('Cities Weather Pipeline — start')

    data = fetch_weather()
    if data is None:
        logging.error('Fetch falló, abortando')
        sys.exit(1)

    if not validate_weather_data(data):
        logging.error('Validación falló, abortando')
        sys.exit(2)

    data = enrich(data)
    local = save_local(data, CONFIG['output_local'])

    if not upload_to_cdn(local):
        logging.error('Upload CDN falló')
        sys.exit(3)

    logging.info('Pipeline OK')
    logging.info('=' * 60)

if __name__ == '__main__':
    main()
