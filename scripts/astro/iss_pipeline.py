#!/opt/canalmeteo/venv/bin/python3
"""
iss_pipeline.py - Canal Meteo TV

Calcula los pases visibles de la ISS para las 30 ciudades hispanas
principales de EE.UU. y Puerto Rico durante las próximas 72 horas.

- Descarga TLE en directo de Celestrak (catalog id 25544)
- Usa skyfield para propagación SGP4 y cálculo de visibilidad
- Filtra solo pases visibles: ISS iluminada + observador en oscuridad civil
- Sube el JSON resultante al CDN de DigitalOcean Spaces

Ejecutar cada 6h con cron:
    0 */6 * * * flock -n /tmp/iss-pipeline.lock timeout 300 /opt/canalmeteo/scripts/astro/iss_pipeline.py >> /var/log/canalmeteo/iss_pipeline.log 2>&1
"""

import json
import math
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from skyfield.api import EarthSatellite, load, wgs84, Loader

# ======== CONFIGURACIÓN ========
TLE_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE'
SKYFIELD_DATA = '/opt/canalmeteo/data/skyfield'
OUTPUT_LOCAL = '/tmp/iss-passes.json'
S3_BUCKET = 'canalmeteo-public'
S3_PATH = 'data/iss/passes-by-city.json'
S3_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'

DURATION_DAYS = 3            # ventana de cálculo: próximas 72h
MIN_ELEVATION = 10           # grados (umbral mínimo para considerar "pase")
TWILIGHT_THRESHOLD = -6      # grados (sol por debajo = crepúsculo civil)

# 30 ciudades con mayor concentración de población hispana en EE.UU.
CITIES = [
    # Texas
    {'id': 'houston-tx',       'name': 'Houston',       'state': 'TX', 'lat': 29.7604,  'lon': -95.3698,  'tz': 'America/Chicago'},
    {'id': 'san-antonio-tx',   'name': 'San Antonio',   'state': 'TX', 'lat': 29.4241,  'lon': -98.4936,  'tz': 'America/Chicago'},
    {'id': 'dallas-tx',        'name': 'Dallas',        'state': 'TX', 'lat': 32.7767,  'lon': -96.7970,  'tz': 'America/Chicago'},
    {'id': 'el-paso-tx',       'name': 'El Paso',       'state': 'TX', 'lat': 31.7619,  'lon': -106.4850, 'tz': 'America/Denver'},
    {'id': 'austin-tx',        'name': 'Austin',        'state': 'TX', 'lat': 30.2672,  'lon': -97.7431,  'tz': 'America/Chicago'},
    {'id': 'fort-worth-tx',    'name': 'Fort Worth',    'state': 'TX', 'lat': 32.7555,  'lon': -97.3308,  'tz': 'America/Chicago'},
    # California
    {'id': 'los-angeles-ca',   'name': 'Los Angeles',   'state': 'CA', 'lat': 34.0522,  'lon': -118.2437, 'tz': 'America/Los_Angeles'},
    {'id': 'san-diego-ca',     'name': 'San Diego',     'state': 'CA', 'lat': 32.7157,  'lon': -117.1611, 'tz': 'America/Los_Angeles'},
    {'id': 'san-jose-ca',      'name': 'San Jose',      'state': 'CA', 'lat': 37.3382,  'lon': -121.8863, 'tz': 'America/Los_Angeles'},
    {'id': 'fresno-ca',        'name': 'Fresno',        'state': 'CA', 'lat': 36.7378,  'lon': -119.7871, 'tz': 'America/Los_Angeles'},
    {'id': 'sacramento-ca',    'name': 'Sacramento',    'state': 'CA', 'lat': 38.5816,  'lon': -121.4944, 'tz': 'America/Los_Angeles'},
    # Florida
    {'id': 'miami-fl',         'name': 'Miami',         'state': 'FL', 'lat': 25.7617,  'lon': -80.1918,  'tz': 'America/New_York'},
    {'id': 'orlando-fl',       'name': 'Orlando',       'state': 'FL', 'lat': 28.5383,  'lon': -81.3792,  'tz': 'America/New_York'},
    {'id': 'tampa-fl',         'name': 'Tampa',         'state': 'FL', 'lat': 27.9506,  'lon': -82.4572,  'tz': 'America/New_York'},
    {'id': 'jacksonville-fl',  'name': 'Jacksonville',  'state': 'FL', 'lat': 30.3322,  'lon': -81.6557,  'tz': 'America/New_York'},
    # Northeast
    {'id': 'new-york-ny',      'name': 'New York',      'state': 'NY', 'lat': 40.7128,  'lon': -74.0060,  'tz': 'America/New_York'},
    {'id': 'newark-nj',        'name': 'Newark',        'state': 'NJ', 'lat': 40.7357,  'lon': -74.1724,  'tz': 'America/New_York'},
    {'id': 'philadelphia-pa',  'name': 'Philadelphia',  'state': 'PA', 'lat': 39.9526,  'lon': -75.1652,  'tz': 'America/New_York'},
    {'id': 'boston-ma',        'name': 'Boston',        'state': 'MA', 'lat': 42.3601,  'lon': -71.0589,  'tz': 'America/New_York'},
    # Sur / sureste
    {'id': 'atlanta-ga',       'name': 'Atlanta',       'state': 'GA', 'lat': 33.7490,  'lon': -84.3880,  'tz': 'America/New_York'},
    {'id': 'charlotte-nc',     'name': 'Charlotte',     'state': 'NC', 'lat': 35.2271,  'lon': -80.8431,  'tz': 'America/New_York'},
    # Suroeste
    {'id': 'phoenix-az',       'name': 'Phoenix',       'state': 'AZ', 'lat': 33.4484,  'lon': -112.0740, 'tz': 'America/Phoenix'},
    {'id': 'tucson-az',        'name': 'Tucson',        'state': 'AZ', 'lat': 32.2226,  'lon': -110.9747, 'tz': 'America/Phoenix'},
    {'id': 'albuquerque-nm',   'name': 'Albuquerque',   'state': 'NM', 'lat': 35.0844,  'lon': -106.6504, 'tz': 'America/Denver'},
    {'id': 'denver-co',        'name': 'Denver',        'state': 'CO', 'lat': 39.7392,  'lon': -104.9903, 'tz': 'America/Denver'},
    {'id': 'las-vegas-nv',     'name': 'Las Vegas',     'state': 'NV', 'lat': 36.1699,  'lon': -115.1398, 'tz': 'America/Los_Angeles'},
    # Medio oeste
    {'id': 'chicago-il',       'name': 'Chicago',       'state': 'IL', 'lat': 41.8781,  'lon': -87.6298,  'tz': 'America/Chicago'},
    {'id': 'kansas-city-mo',   'name': 'Kansas City',   'state': 'MO', 'lat': 39.0997,  'lon': -94.5786,  'tz': 'America/Chicago'},
    # Puerto Rico
    {'id': 'san-juan-pr',      'name': 'San Juan',      'state': 'PR', 'lat': 18.4655,  'lon': -66.1057,  'tz': 'America/Puerto_Rico'},
    {'id': 'ponce-pr',         'name': 'Ponce',         'state': 'PR', 'lat': 18.0111,  'lon': -66.6141,  'tz': 'America/Puerto_Rico'},
]


def log(msg):
    """Imprime con timestamp."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{now}] {msg}', flush=True)


def fetch_tle():
    """Descarga TLE de la ISS desde Celestrak."""
    log(f'Descargando TLE desde {TLE_URL}…')
    resp = requests.get(TLE_URL, timeout=30,
                        headers={'User-Agent': 'CanalMeteoTV/1.0'})
    resp.raise_for_status()
    lines = [l for l in resp.text.strip().split('\n') if l.strip()]
    if len(lines) < 3:
        raise ValueError(f'TLE incompleto ({len(lines)} líneas)')
    name = lines[0].strip()
    line1 = lines[1].strip()
    line2 = lines[2].strip()
    epoch = line1[18:32].strip()
    log(f'TLE OK: {name}, época {epoch}')
    return name, line1, line2


def estimate_magnitude(elev_deg, range_km):
    """Estima magnitud aparente de la ISS.

    Modelo simplificado basado en distancia, calibrado contra heavens-above.com:
        m = -1.8 + 5·log10(range/1000)
    No incluye ángulo de fase Sol-ISS-Observador (que añadiría ±0.5 mag).

    Valores típicos:
        range ~400 km (cenit):     m ≈ -3.8
        range ~600 km (alt 50°):   m ≈ -2.9
        range ~1000 km (alt 25°):  m ≈ -1.8
        range ~2000 km (horizonte):m ≈ -0.3
    """
    if range_km <= 0:
        return 0.0
    return round(-1.8 + 5 * math.log10(range_km / 1000.0), 2)


def validate_and_describe_pass(sat, observer, eph, t_rise, t_culm, t_set, sun_func):
    """Convierte un trío rise/culminate/set en un dict de pase, o None si no es visible."""
    difference = sat - observer

    # Estado en culminación
    topo_culm = difference.at(t_culm)
    alt_culm, az_culm, dist_culm = topo_culm.altaz()

    # ISS iluminada en culminación?
    if not sat.at(t_culm).is_sunlit(eph):
        return None

    # Observador en oscuridad (sol < -6°) en culminación?
    sun_alt = sun_func(t_culm)
    if sun_alt >= TWILIGHT_THRESHOLD:
        return None

    # Posiciones de rise y set
    topo_rise = difference.at(t_rise)
    alt_rise, az_rise, _ = topo_rise.altaz()
    topo_set = difference.at(t_set)
    alt_set, az_set, _ = topo_set.altaz()

    duration_sec = (t_set - t_rise) * 86400  # diferencia en días → seg

    max_elev = round(alt_culm.degrees, 1)
    magnitude = estimate_magnitude(max_elev, dist_culm.km)

    if max_elev >= 60:
        quality = 'excellent'
    elif max_elev >= 30:
        quality = 'good'
    else:
        quality = 'fair'

    is_spectacular = bool(magnitude <= -3.0 and max_elev >= 45)

    return {
        'start_utc':     t_rise.utc_datetime().isoformat(),
        'culm_utc':      t_culm.utc_datetime().isoformat(),
        'end_utc':       t_set.utc_datetime().isoformat(),
        'duration_sec':  round(duration_sec, 1),
        'start_az':      round(az_rise.degrees, 1),
        'max_elev':      max_elev,
        'max_az':        round(az_culm.degrees, 1),
        'end_az':        round(az_set.degrees, 1),
        'range_km':      round(dist_culm.km, 1),
        'magnitude':     magnitude,
        'quality':       quality,
        'is_spectacular': is_spectacular
    }


def compute_passes_for_city(sat, eph, ts, city, t0, t1):
    """Calcula pases visibles para una ciudad."""
    observer = wgs84.latlon(city['lat'], city['lon'])

    # Función para obtener altitud del sol en cualquier instante
    sun = eph['sun']
    earth = eph['earth']
    obs_geo = earth + observer
    def sun_alt(t):
        apparent = obs_geo.at(t).observe(sun).apparent()
        alt, _, _ = apparent.altaz()
        return alt.degrees

    t_events, events = sat.find_events(observer, t0, t1, altitude_degrees=MIN_ELEVATION)

    passes = []
    current = {}
    for t, event in zip(t_events, events):
        if event == 0:    # rise
            current = {'rise': t}
        elif event == 1:  # culminate
            if 'rise' in current:
                current['culm'] = t
        elif event == 2:  # set
            if 'rise' in current and 'culm' in current:
                pass_info = validate_and_describe_pass(
                    sat, observer, eph,
                    current['rise'], current['culm'], t,
                    sun_alt
                )
                if pass_info:
                    passes.append(pass_info)
            current = {}

    return passes


def upload_to_cdn(local_path):
    """Sube el JSON al CDN de DO Spaces usando aws cli."""
    cmd = [
        'aws', 's3', 'cp', local_path, f's3://{S3_BUCKET}/{S3_PATH}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=300',
        '--endpoint-url', S3_ENDPOINT
    ]
    log(f'Subiendo a s3://{S3_BUCKET}/{S3_PATH}…')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f'ERROR subiendo al CDN: {result.stderr.strip()}')
        return False
    log(f'CDN OK: https://{S3_BUCKET}.sfo3.cdn.digitaloceanspaces.com/{S3_PATH}')
    return True


def main():
    try:
        name, line1, line2 = fetch_tle()
    except Exception as e:
        log(f'ERROR descargando TLE: {e}')
        sys.exit(1)

    # Cargar Skyfield (de421.bsp se descarga la primera vez ~17MB)
    Path(SKYFIELD_DATA).mkdir(parents=True, exist_ok=True)
    loader = Loader(SKYFIELD_DATA, verbose=False)
    ts = loader.timescale()
    eph = loader('de421.bsp')

    sat = EarthSatellite(line1, line2, name, ts)

    now_utc = datetime.now(timezone.utc)
    t0 = ts.from_datetime(now_utc)
    t1 = ts.from_datetime(now_utc + timedelta(days=DURATION_DAYS))

    output = {
        'generated_utc': now_utc.isoformat(),
        'duration_days': DURATION_DAYS,
        'tle': {
            'name': name,
            'epoch': line1[18:32].strip(),
            'line1': line1,
            'line2': line2
        },
        'cities': {}
    }

    total_passes = 0
    total_spectacular = 0

    for i, city in enumerate(CITIES, 1):
        try:
            passes = compute_passes_for_city(sat, eph, ts, city, t0, t1)
            spectacular = sum(1 for p in passes if p['is_spectacular'])
            output['cities'][city['id']] = {
                'name':  city['name'],
                'state': city['state'],
                'lat':   city['lat'],
                'lon':   city['lon'],
                'tz':    city['tz'],
                'passes': passes
            }
            log(f'{i:2}/{len(CITIES)} {city["name"]:<18} {city["state"]}: {len(passes)} pases ({spectacular} espectaculares)')
            total_passes += len(passes)
            total_spectacular += spectacular
        except Exception as e:
            log(f'{i:2}/{len(CITIES)} {city["name"]:<18} {city["state"]}: ERROR {e}')
            output['cities'][city['id']] = {
                'name':  city['name'],
                'state': city['state'],
                'lat':   city['lat'],
                'lon':   city['lon'],
                'tz':    city['tz'],
                'passes': [],
                'error': str(e)
            }

    log(f'Total: {total_passes} pases ({total_spectacular} espectaculares) en {len(CITIES)} ciudades')

    # Guardar local
    Path(OUTPUT_LOCAL).parent.mkdir(parents=True, exist_ok=True)
    # Handler para tipos numpy (skyfield los usa internamente)
    def _np_to_native(o):
        if hasattr(o, 'item'):  # numpy scalars exponen .item()
            return o.item()
        raise TypeError(f'No serializable: {type(o).__name__}')
    with open(OUTPUT_LOCAL, 'w') as f:
        json.dump(output, f, separators=(',', ':'), default=_np_to_native)
    size_kb = Path(OUTPUT_LOCAL).stat().st_size / 1024
    log(f'JSON generado: {OUTPUT_LOCAL} ({size_kb:.1f} KB)')

    # Subir
    if not upload_to_cdn(OUTPUT_LOCAL):
        sys.exit(2)

    log('Pipeline ISS completado')


if __name__ == '__main__':
    main()
