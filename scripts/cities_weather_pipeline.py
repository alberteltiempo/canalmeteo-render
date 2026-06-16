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
    's3_path': 'data/cities/weather.json',
    'public_url': 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/cities/weather.json',
    'expected_min_count': 50,        # Mínimo aceptable de ciudades en respuesta
    'user_agent': 'CanalMeteoCitiesPipeline/1.0',
    # Auto-flush del CDN tras subir, para que los datos nuevos se vean
    # enseguida (el endpoint tiene TTL 3600 = hasta 1 h de retraso).
    'cdn_endpoint_id': '11ee90e9-1e11-4380-ba2e-d40795722664',
    'doctl_bin': '/snap/bin/doctl',  # ruta absoluta: cron no tiene PATH de snap
}

# ═══════════════════════════════════════════════════════════════════
# COORDENADAS DE LAS 60 CIUDADES
# (10 latinas + 50 capitales de estado)
# Clave: "Ciudad|Estado" coincidiendo con weather-api.php
# Valor: (latitud, longitud)
# ═══════════════════════════════════════════════════════════════════
CITY_COORDS = {
    # Ciudades principales latinas
    "Miami|Florida": (25.7617, -80.1918),
    "Los Angeles|California": (34.0522, -118.2437),
    "Houston|Texas": (29.7604, -95.3698),
    "New York|New York": (40.7128, -74.0060),
    "Chicago|Illinois": (41.8781, -87.6298),
    "San Antonio|Texas": (29.4252, -98.4946),
    "Dallas|Texas": (32.7767, -96.7970),
    "Orlando|Florida": (28.5384, -81.3789),
    "Las Vegas|Nevada": (36.1699, -115.1398),
    "San Diego|California": (32.7157, -117.1611),
    # Capitales de los 50 estados
    "Montgomery|Alabama": (32.3792, -86.3077),
    "Juneau|Alaska": (58.3019, -134.4197),
    "Phoenix|Arizona": (33.4484, -112.0740),
    "Little Rock|Arkansas": (34.7465, -92.2896),
    "Sacramento|California": (38.5816, -121.4944),
    "Denver|Colorado": (39.7392, -104.9903),
    "Hartford|Connecticut": (41.7658, -72.6734),
    "Dover|Delaware": (39.1582, -75.5244),
    "Tallahassee|Florida": (30.4383, -84.2807),
    "Atlanta|Georgia": (33.7490, -84.3880),
    "Honolulu|Hawaii": (21.3099, -157.8581),
    "Boise|Idaho": (43.6150, -116.2023),
    "Springfield|Illinois": (39.7817, -89.6501),
    "Indianapolis|Indiana": (39.7684, -86.1581),
    "Des Moines|Iowa": (41.5868, -93.6250),
    "Topeka|Kansas": (39.0473, -95.6752),
    "Frankfort|Kentucky": (38.2009, -84.8733),
    "Baton Rouge|Louisiana": (30.4515, -91.1871),
    "Augusta|Maine": (44.3106, -69.7795),
    "Annapolis|Maryland": (38.9784, -76.4922),
    "Boston|Massachusetts": (42.3601, -71.0589),
    "Lansing|Michigan": (42.7325, -84.5555),
    "Saint Paul|Minnesota": (44.9537, -93.0900),
    "Jackson|Mississippi": (32.2988, -90.1848),
    "Jefferson City|Missouri": (38.5767, -92.1735),
    "Helena|Montana": (46.5891, -112.0391),
    "Lincoln|Nebraska": (40.8136, -96.7026),
    "Carson City|Nevada": (39.1638, -119.7674),
    "Concord|New Hampshire": (43.2081, -71.5376),
    "Trenton|New Jersey": (40.2206, -74.7597),
    "Santa Fe|New Mexico": (35.6870, -105.9378),
    "Albany|New York": (42.6526, -73.7562),
    "Raleigh|North Carolina": (35.7796, -78.6382),
    "Bismarck|North Dakota": (46.8083, -100.7837),
    "Columbus|Ohio": (39.9612, -82.9988),
    "Oklahoma City|Oklahoma": (35.4676, -97.5164),
    "Salem|Oregon": (44.9429, -123.0351),
    "Harrisburg|Pennsylvania": (40.2732, -76.8867),
    "Providence|Rhode Island": (41.8240, -71.4128),
    "Columbia|South Carolina": (34.0007, -81.0348),
    "Pierre|South Dakota": (44.3683, -100.3510),
    "Nashville|Tennessee": (36.1627, -86.7816),
    "Austin|Texas": (30.2672, -97.7431),
    "Salt Lake City|Utah": (40.7608, -111.8910),
    "Montpelier|Vermont": (44.2601, -72.5754),
    "Richmond|Virginia": (37.5407, -77.4360),
    "Olympia|Washington": (47.0379, -122.9007),
    "Charleston|West Virginia": (38.3498, -81.6326),
    "Madison|Wisconsin": (43.0731, -89.4012),
    "Cheyenne|Wyoming": (41.1400, -104.8202),
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
    # Añadir lat/lon a cada ciudad + crear lookup map por "City|State"
    if 'data' in data and isinstance(data['data'], list):
        lookup = {}
        ciudades_con_coords = 0
        ciudades_sin_coords = []
        for c in data['data']:
            key = f"{c.get('city')}|{c.get('state')}"
            # Añadir lat/lon desde diccionario CITY_COORDS
            coords = CITY_COORDS.get(key)
            if coords:
                c['lat'] = coords[0]
                c['lon'] = coords[1]
                ciudades_con_coords += 1
            else:
                ciudades_sin_coords.append(key)
            lookup[key] = c
        data['by_key'] = lookup
        logging.info(f'Coordenadas añadidas a {ciudades_con_coords}/{len(data["data"])} ciudades')
        if ciudades_sin_coords:
            logging.warning(f'Sin coordenadas: {ciudades_sin_coords}')
    return data


# ═══════════════════════════════════════════════════════════════════
# HOURLY12 (Open-Meteo batch: 12 h de temp + prob. de lluvia + ícono)
# ═══════════════════════════════════════════════════════════════════
# Mapa de códigos WMO (weather_code de Open-Meteo) → emoji, usando la
# misma paleta que el upstream (weather-api.php): ☀️ 🌤️ ⛅ ☁️ 🌦️ ⛈️ 🌫️
# (+ 🌧️ 🌨️ 🌙 para casos que el upstream no cubre).
WMO_EMOJI = {
    0: '☀️',                                   # despejado
    1: '🌤️',                                   # mayormente despejado
    2: '⛅',                                    # parcialmente nublado
    3: '☁️',                                    # nublado
    45: '🌫️', 48: '🌫️',                        # niebla
    51: '🌦️', 53: '🌦️', 55: '🌦️',             # llovizna
    56: '🌧️', 57: '🌧️',                        # llovizna helada
    61: '🌦️', 63: '🌧️', 65: '🌧️',             # lluvia
    66: '🌧️', 67: '🌧️',                        # lluvia helada
    71: '🌨️', 73: '🌨️', 75: '🌨️', 77: '🌨️',   # nieve
    80: '🌦️', 81: '🌧️', 82: '🌧️',             # chubascos
    85: '🌨️', 86: '🌨️',                        # chubascos de nieve
    95: '⛈️', 96: '⛈️', 99: '⛈️',              # tormenta
}


def wmo_to_emoji(code, is_day=1):
    """Convierte un código WMO en emoji. De noche, despejado/mayormente
    despejado muestran luna en vez de sol."""
    if code in (0, 1) and not is_day:
        return '🌙'
    return WMO_EMOJI.get(code, '☀️')


def add_hourly12(data):
    """Añade hourly12 a cada ciudad con coordenadas, en una sola
    llamada batch a Open-Meteo. No fatal: si falla, el JSON se
    publica igual sin el campo (el frontend tiene fallback)."""
    try:
        cities = [c for c in data.get('data', [])
                  if isinstance(c.get('lat'), (int, float))
                  and isinstance(c.get('lon'), (int, float))]
        if not cities:
            logging.warning('hourly12: ninguna ciudad con coordenadas')
            return
        lats = ','.join(f"{c['lat']:.4f}" for c in cities)
        lons = ','.join(f"{c['lon']:.4f}" for c in cities)
        url = ('https://api.open-meteo.com/v1/forecast'
               f'?latitude={lats}&longitude={lons}'
               '&hourly=temperature_2m,precipitation_probability,'
               'weather_code,is_day'
               '&temperature_unit=fahrenheit&timezone=auto&forecast_hours=12')
        started = time.time()
        r = requests.get(url, timeout=30,
                         headers={'User-Agent': CONFIG['user_agent']})
        r.raise_for_status()
        res = r.json()
        if isinstance(res, dict):
            res = [res]
        ok = 0
        for c, loc in zip(cities, res):
            h = loc.get('hourly') or {}
            tiempos = h.get('time') or []
            temps = h.get('temperature_2m') or []
            pops = h.get('precipitation_probability') or []
            codes = h.get('weather_code') or []
            isdays = h.get('is_day') or []
            filas = []
            for i, t in enumerate(tiempos[:12]):
                try:
                    hora = int(t[11:13])
                except (ValueError, IndexError):
                    continue
                temp = temps[i] if i < len(temps) else None
                if temp is None:
                    continue
                ampm = 'am' if hora < 12 else 'pm'
                h12 = hora % 12 or 12
                fila = {
                    'time': 'Ahora' if i == 0 else f'{h12}{ampm}',
                    'temp': round(temp),
                }
                pop = pops[i] if i < len(pops) else None
                if pop is not None:
                    fila['pop'] = int(pop)
                code = codes[i] if i < len(codes) else None
                if code is not None:
                    is_day = isdays[i] if i < len(isdays) else 1
                    fila['icon'] = wmo_to_emoji(int(code), int(is_day))
                filas.append(fila)
            if len(filas) >= 2:
                c['hourly12'] = filas
                # Mitigación Roku/Firestick: esos clientes leen el campo
                # legacy `hourly` (sin icon/pop, con horas basura). Lo
                # reescribimos con las primeras 4 horas de hourly12 para
                # que muestren el ícono y la condición correctos.
                c['hourly'] = [dict(f) for f in filas[:4]]
                ok += 1
        logging.info(f'hourly12 añadido a {ok}/{len(cities)} ciudades '
                     f'(Open-Meteo, {time.time() - started:.1f}s)')
    except Exception as e:
        logging.warning(f'hourly12 omitido (Open-Meteo falló): {e}')


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
        flush_cdn()
        return True
    except subprocess.TimeoutExpired:
        logging.error('aws s3 cp timeout')
        return False
    except Exception as e:
        logging.error(f'aws s3 cp exception: {e}')
        return False


def flush_cdn():
    """Purga la caché del CDN para el archivo recién subido, así los
    datos nuevos se ven enseguida en vez de esperar el TTL (~1 h).
    No fatal: si falla, el archivo ya está subido y el CDN se refresca
    solo al expirar el TTL."""
    endpoint = CONFIG.get('cdn_endpoint_id')
    if not endpoint:
        return
    cmd = [
        CONFIG['doctl_bin'], 'compute', 'cdn', 'flush', endpoint,
        '--files', CONFIG['s3_path'],
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logging.warning(f'CDN flush falló (no fatal): {result.stderr.strip()}')
        else:
            logging.info(f'CDN flush OK → {CONFIG["s3_path"]}')
    except Exception as e:
        logging.warning(f'CDN flush omitido (no fatal): {e}')

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    debug = '--debug' in sys.argv
    setup_logging(debug=debug)

    logging.info('=' * 60)
    logging.info('Pipeline cities_weather INICIADO')

    # 1. Descargar
    data = fetch_weather()
    if not data:
        logging.error('Sin datos, abortando')
        return 1

    # 2. Validar
    if not validate_weather_data(data):
        logging.error('Validación fallida, abortando')
        return 1

    # 3. Enriquecer (añadir coordenadas + metadata)
    data = enrich(data)

    # 3b. hourly12: 12 h de temp + prob. de lluvia (Open-Meteo, no fatal)
    add_hourly12(data)

    # 4. Guardar local
    local_path = save_local(data, CONFIG['output_local'])

    # 5. Subir al CDN (a menos que --no-upload)
    if '--no-upload' in sys.argv:
        logging.info('Modo --no-upload: omitido')
    else:
        if not upload_to_cdn(local_path):
            logging.error('Upload fallido')
            return 1

    logging.info('Pipeline COMPLETADO')
    return 0


if __name__ == '__main__':
    sys.exit(main())
