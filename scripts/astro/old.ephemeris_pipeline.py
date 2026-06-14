#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ephemeris_pipeline.py — Canal Meteo TV
========================================
Bloque 3: Crepúsculos + hora dorada/azul + longitud del día + eventos solares.

Calcula para las principales ciudades de la audiencia hispana en EE.UU.:
  • Amanecer, atardecer, mediodía solar, altitud máxima
  • Crepúsculo civil, náutico, astronómico (mañana y tarde)
  • Hora dorada y hora azul (mañana y tarde)
  • Longitud del día y variación respecto al día anterior
  • Equinoccios y solsticios del año actual y próximo

Output: data/astro/ephemeris-daily.json (CDN público)

Ejecución: una vez al día (cron 00:15)
Tiempo aprox: 30-60 segundos para 12 ciudades × 35 días

Dependencias: skyfield>=1.46, pytz, numpy
Venv: /opt/canalmeteo/venv

Uso:
    python3 ephemeris_pipeline.py              # ejecución completa + upload
    python3 ephemeris_pipeline.py --no-upload  # genera JSON local, no sube
    python3 ephemeris_pipeline.py --days 7     # solo 7 días (debug rápido)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytz
from skyfield import almanac, api

# ===== CONFIGURACIÓN =====
SCRIPT_NAME = 'ephemeris_pipeline'
LOG_DIR = '/var/log/canalmeteo'
LOG_FILE = f'{LOG_DIR}/astro_ephemeris.log'
SKYFIELD_DATA_DIR = '/opt/canalmeteo/data/skyfield'
TMP_OUTPUT = '/tmp/ephemeris-daily.json'

CDN_BUCKET = 'canalmeteo-public'
CDN_KEY = 'data/astro/ephemeris-daily.json'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'

DEFAULT_DAYS = 35

# Ciudades clave de la audiencia hispana en EE.UU. + PR
# Cubren las mayores concentraciones de hispanohablantes y diferentes zonas horarias.
CITIES = [
    # ===== 50 CAPITALES ESTATALES =====
    {"id": "montgomery",      "name": "Montgomery, AL",      "state": "Alabama",        "lat": 32.3792, "lon":  -86.3077, "tz": "America/Chicago"},
    {"id": "juneau",          "name": "Juneau, AK",          "state": "Alaska",         "lat": 58.3019, "lon": -134.4197, "tz": "America/Juneau"},
    {"id": "phoenix",         "name": "Phoenix, AZ",         "state": "Arizona",        "lat": 33.4484, "lon": -112.0740, "tz": "America/Phoenix"},
    {"id": "little_rock",     "name": "Little Rock, AR",     "state": "Arkansas",       "lat": 34.7465, "lon":  -92.2896, "tz": "America/Chicago"},
    {"id": "sacramento",      "name": "Sacramento, CA",      "state": "California",     "lat": 38.5816, "lon": -121.4944, "tz": "America/Los_Angeles"},
    {"id": "denver",          "name": "Denver, CO",          "state": "Colorado",       "lat": 39.7392, "lon": -104.9903, "tz": "America/Denver"},
    {"id": "hartford",        "name": "Hartford, CT",        "state": "Connecticut",    "lat": 41.7637, "lon":  -72.6851, "tz": "America/New_York"},
    {"id": "dover",           "name": "Dover, DE",           "state": "Delaware",       "lat": 39.1582, "lon":  -75.5244, "tz": "America/New_York"},
    {"id": "tallahassee",     "name": "Tallahassee, FL",     "state": "Florida",        "lat": 30.4383, "lon":  -84.2807, "tz": "America/New_York"},
    {"id": "atlanta",         "name": "Atlanta, GA",         "state": "Georgia",        "lat": 33.7490, "lon":  -84.3880, "tz": "America/New_York"},
    {"id": "honolulu",        "name": "Honolulu, HI",        "state": "Hawaii",         "lat": 21.3099, "lon": -157.8581, "tz": "Pacific/Honolulu"},
    {"id": "boise",           "name": "Boise, ID",           "state": "Idaho",          "lat": 43.6150, "lon": -116.2023, "tz": "America/Boise"},
    {"id": "springfield_il",  "name": "Springfield, IL",     "state": "Illinois",       "lat": 39.7817, "lon":  -89.6501, "tz": "America/Chicago"},
    {"id": "indianapolis",    "name": "Indianapolis, IN",    "state": "Indiana",        "lat": 39.7684, "lon":  -86.1581, "tz": "America/Indiana/Indianapolis"},
    {"id": "des_moines",      "name": "Des Moines, IA",      "state": "Iowa",           "lat": 41.5868, "lon":  -93.6250, "tz": "America/Chicago"},
    {"id": "topeka",          "name": "Topeka, KS",          "state": "Kansas",         "lat": 39.0473, "lon":  -95.6752, "tz": "America/Chicago"},
    {"id": "frankfort",       "name": "Frankfort, KY",       "state": "Kentucky",       "lat": 38.2009, "lon":  -84.8733, "tz": "America/Kentucky/Louisville"},
    {"id": "baton_rouge",     "name": "Baton Rouge, LA",     "state": "Louisiana",      "lat": 30.4515, "lon":  -91.1871, "tz": "America/Chicago"},
    {"id": "augusta",         "name": "Augusta, ME",         "state": "Maine",          "lat": 44.3107, "lon":  -69.7795, "tz": "America/New_York"},
    {"id": "annapolis",       "name": "Annapolis, MD",       "state": "Maryland",       "lat": 38.9784, "lon":  -76.4922, "tz": "America/New_York"},
    {"id": "boston",          "name": "Boston, MA",          "state": "Massachusetts",  "lat": 42.3601, "lon":  -71.0589, "tz": "America/New_York"},
    {"id": "lansing",         "name": "Lansing, MI",         "state": "Michigan",       "lat": 42.7325, "lon":  -84.5555, "tz": "America/Detroit"},
    {"id": "saint_paul",      "name": "Saint Paul, MN",      "state": "Minnesota",      "lat": 44.9537, "lon":  -93.0900, "tz": "America/Chicago"},
    {"id": "jackson",         "name": "Jackson, MS",         "state": "Mississippi",    "lat": 32.2988, "lon":  -90.1848, "tz": "America/Chicago"},
    {"id": "jefferson_city",  "name": "Jefferson City, MO",  "state": "Missouri",       "lat": 38.5767, "lon":  -92.1735, "tz": "America/Chicago"},
    {"id": "helena",          "name": "Helena, MT",          "state": "Montana",        "lat": 46.5891, "lon": -112.0391, "tz": "America/Denver"},
    {"id": "lincoln",         "name": "Lincoln, NE",         "state": "Nebraska",       "lat": 40.8136, "lon":  -96.7026, "tz": "America/Chicago"},
    {"id": "carson_city",     "name": "Carson City, NV",     "state": "Nevada",         "lat": 39.1638, "lon": -119.7674, "tz": "America/Los_Angeles"},
    {"id": "concord",         "name": "Concord, NH",         "state": "New Hampshire",  "lat": 43.2081, "lon":  -71.5376, "tz": "America/New_York"},
    {"id": "trenton",         "name": "Trenton, NJ",         "state": "New Jersey",     "lat": 40.2206, "lon":  -74.7597, "tz": "America/New_York"},
    {"id": "santa_fe",        "name": "Santa Fe, NM",        "state": "New Mexico",     "lat": 35.6870, "lon": -105.9378, "tz": "America/Denver"},
    {"id": "albany",          "name": "Albany, NY",          "state": "New York",       "lat": 42.6526, "lon":  -73.7562, "tz": "America/New_York"},
    {"id": "raleigh",         "name": "Raleigh, NC",         "state": "North Carolina", "lat": 35.7796, "lon":  -78.6382, "tz": "America/New_York"},
    {"id": "bismarck",        "name": "Bismarck, ND",        "state": "North Dakota",   "lat": 46.8083, "lon": -100.7837, "tz": "America/Chicago"},
    {"id": "columbus_oh",     "name": "Columbus, OH",        "state": "Ohio",           "lat": 39.9612, "lon":  -82.9988, "tz": "America/New_York"},
    {"id": "oklahoma_city",   "name": "Oklahoma City, OK",   "state": "Oklahoma",       "lat": 35.4676, "lon":  -97.5164, "tz": "America/Chicago"},
    {"id": "salem_or",        "name": "Salem, OR",           "state": "Oregon",         "lat": 44.9429, "lon": -123.0351, "tz": "America/Los_Angeles"},
    {"id": "harrisburg",      "name": "Harrisburg, PA",      "state": "Pennsylvania",   "lat": 40.2732, "lon":  -76.8867, "tz": "America/New_York"},
    {"id": "providence",      "name": "Providence, RI",      "state": "Rhode Island",   "lat": 41.8240, "lon":  -71.4128, "tz": "America/New_York"},
    {"id": "columbia",        "name": "Columbia, SC",        "state": "South Carolina", "lat": 34.0007, "lon":  -81.0348, "tz": "America/New_York"},
    {"id": "pierre",          "name": "Pierre, SD",          "state": "South Dakota",   "lat": 44.3683, "lon": -100.3510, "tz": "America/Chicago"},
    {"id": "nashville",       "name": "Nashville, TN",       "state": "Tennessee",      "lat": 36.1627, "lon":  -86.7816, "tz": "America/Chicago"},
    {"id": "austin",          "name": "Austin, TX",          "state": "Texas",          "lat": 30.2672, "lon":  -97.7431, "tz": "America/Chicago"},
    {"id": "salt_lake_city",  "name": "Salt Lake City, UT",  "state": "Utah",           "lat": 40.7608, "lon": -111.8910, "tz": "America/Denver"},
    {"id": "montpelier",      "name": "Montpelier, VT",      "state": "Vermont",        "lat": 44.2601, "lon":  -72.5754, "tz": "America/New_York"},
    {"id": "richmond",        "name": "Richmond, VA",        "state": "Virginia",       "lat": 37.5407, "lon":  -77.4360, "tz": "America/New_York"},
    {"id": "olympia",         "name": "Olympia, WA",         "state": "Washington",     "lat": 47.0379, "lon": -122.9007, "tz": "America/Los_Angeles"},
    {"id": "charleston_wv",   "name": "Charleston, WV",      "state": "West Virginia",  "lat": 38.3498, "lon":  -81.6326, "tz": "America/New_York"},
    {"id": "madison",         "name": "Madison, WI",         "state": "Wisconsin",      "lat": 43.0731, "lon":  -89.4012, "tz": "America/Chicago"},
    {"id": "cheyenne",        "name": "Cheyenne, WY",        "state": "Wyoming",        "lat": 41.1400, "lon": -104.8202, "tz": "America/Denver"},

    # ===== WASHINGTON DC =====
    {"id": "washington_dc",   "name": "Washington, DC",      "state": "District of Columbia", "lat": 38.9072, "lon": -77.0369, "tz": "America/New_York"},

    # ===== TEXAS — núcleo hispano (11) =====
    {"id": "houston",         "name": "Houston, TX",         "state": "Texas",          "lat": 29.7604, "lon":  -95.3698, "tz": "America/Chicago"},
    {"id": "dallas",          "name": "Dallas, TX",          "state": "Texas",          "lat": 32.7767, "lon":  -96.7970, "tz": "America/Chicago"},
    {"id": "san_antonio",     "name": "San Antonio, TX",     "state": "Texas",          "lat": 29.4241, "lon":  -98.4936, "tz": "America/Chicago"},
    {"id": "fort_worth",      "name": "Fort Worth, TX",      "state": "Texas",          "lat": 32.7555, "lon":  -97.3308, "tz": "America/Chicago"},
    {"id": "el_paso",         "name": "El Paso, TX",         "state": "Texas",          "lat": 31.7619, "lon": -106.4850, "tz": "America/Denver"},
    {"id": "corpus_christi",  "name": "Corpus Christi, TX",  "state": "Texas",          "lat": 27.8006, "lon":  -97.3964, "tz": "America/Chicago"},
    {"id": "mcallen",         "name": "McAllen, TX",         "state": "Texas",          "lat": 26.2034, "lon":  -98.2300, "tz": "America/Chicago"},
    {"id": "brownsville",     "name": "Brownsville, TX",     "state": "Texas",          "lat": 25.9018, "lon":  -97.4975, "tz": "America/Chicago"},
    {"id": "laredo",          "name": "Laredo, TX",          "state": "Texas",          "lat": 27.5036, "lon":  -99.5076, "tz": "America/Chicago"},
    {"id": "lubbock",         "name": "Lubbock, TX",         "state": "Texas",          "lat": 33.5779, "lon": -101.8552, "tz": "America/Chicago"},
    {"id": "amarillo",        "name": "Amarillo, TX",        "state": "Texas",          "lat": 35.2220, "lon": -101.8313, "tz": "America/Chicago"},

    # ===== FLORIDA — núcleo hispano (6) =====
    {"id": "miami",           "name": "Miami, FL",           "state": "Florida",        "lat": 25.7617, "lon":  -80.1918, "tz": "America/New_York"},
    {"id": "orlando",         "name": "Orlando, FL",         "state": "Florida",        "lat": 28.5384, "lon":  -81.3789, "tz": "America/New_York"},
    {"id": "tampa",           "name": "Tampa, FL",           "state": "Florida",        "lat": 27.9506, "lon":  -82.4572, "tz": "America/New_York"},
    {"id": "jacksonville",    "name": "Jacksonville, FL",    "state": "Florida",        "lat": 30.3322, "lon":  -81.6557, "tz": "America/New_York"},
    {"id": "hialeah",         "name": "Hialeah, FL",         "state": "Florida",        "lat": 25.8576, "lon":  -80.2781, "tz": "America/New_York"},
    {"id": "fort_lauderdale", "name": "Fort Lauderdale, FL", "state": "Florida",        "lat": 26.1224, "lon":  -80.1373, "tz": "America/New_York"},

    # ===== CALIFORNIA — núcleo hispano (10) =====
    {"id": "los_angeles",     "name": "Los Angeles, CA",     "state": "California",     "lat": 34.0522, "lon": -118.2437, "tz": "America/Los_Angeles"},
    {"id": "san_diego",       "name": "San Diego, CA",       "state": "California",     "lat": 32.7157, "lon": -117.1611, "tz": "America/Los_Angeles"},
    {"id": "san_jose",        "name": "San Jose, CA",        "state": "California",     "lat": 37.3382, "lon": -121.8863, "tz": "America/Los_Angeles"},
    {"id": "san_francisco",   "name": "San Francisco, CA",   "state": "California",     "lat": 37.7749, "lon": -122.4194, "tz": "America/Los_Angeles"},
    {"id": "fresno",          "name": "Fresno, CA",          "state": "California",     "lat": 36.7378, "lon": -119.7871, "tz": "America/Los_Angeles"},
    {"id": "long_beach",      "name": "Long Beach, CA",      "state": "California",     "lat": 33.7701, "lon": -118.1937, "tz": "America/Los_Angeles"},
    {"id": "bakersfield",     "name": "Bakersfield, CA",     "state": "California",     "lat": 35.3733, "lon": -119.0187, "tz": "America/Los_Angeles"},
    {"id": "anaheim",         "name": "Anaheim, CA",         "state": "California",     "lat": 33.8366, "lon": -117.9143, "tz": "America/Los_Angeles"},
    {"id": "santa_ana",       "name": "Santa Ana, CA",       "state": "California",     "lat": 33.7455, "lon": -117.8678, "tz": "America/Los_Angeles"},
    {"id": "riverside",       "name": "Riverside, CA",       "state": "California",     "lat": 33.9806, "lon": -117.3755, "tz": "America/Los_Angeles"},

    # ===== NORESTE — alta densidad hispana (5) =====
    {"id": "new_york",        "name": "New York, NY",        "state": "New York",       "lat": 40.7128, "lon":  -74.0060, "tz": "America/New_York"},
    {"id": "newark",          "name": "Newark, NJ",          "state": "New Jersey",     "lat": 40.7357, "lon":  -74.1724, "tz": "America/New_York"},
    {"id": "jersey_city",     "name": "Jersey City, NJ",     "state": "New Jersey",     "lat": 40.7178, "lon":  -74.0431, "tz": "America/New_York"},
    {"id": "paterson",        "name": "Paterson, NJ",        "state": "New Jersey",     "lat": 40.9168, "lon":  -74.1718, "tz": "America/New_York"},
    {"id": "philadelphia",    "name": "Philadelphia, PA",    "state": "Pennsylvania",   "lat": 39.9526, "lon":  -75.1652, "tz": "America/New_York"},

    # ===== GRANDES CIUDADES (otras) (12) =====
    {"id": "chicago",         "name": "Chicago, IL",         "state": "Illinois",       "lat": 41.8781, "lon":  -87.6298, "tz": "America/Chicago"},
    {"id": "detroit",         "name": "Detroit, MI",         "state": "Michigan",       "lat": 42.3314, "lon":  -83.0458, "tz": "America/Detroit"},
    {"id": "milwaukee",       "name": "Milwaukee, WI",       "state": "Wisconsin",      "lat": 43.0389, "lon":  -87.9065, "tz": "America/Chicago"},
    {"id": "memphis",         "name": "Memphis, TN",         "state": "Tennessee",      "lat": 35.1495, "lon":  -90.0490, "tz": "America/Chicago"},
    {"id": "new_orleans",     "name": "New Orleans, LA",     "state": "Louisiana",      "lat": 29.9511, "lon":  -90.0715, "tz": "America/Chicago"},
    {"id": "birmingham",      "name": "Birmingham, AL",      "state": "Alabama",        "lat": 33.5186, "lon":  -86.8104, "tz": "America/Chicago"},
    {"id": "charlotte",       "name": "Charlotte, NC",       "state": "North Carolina", "lat": 35.2271, "lon":  -80.8431, "tz": "America/New_York"},
    {"id": "baltimore",       "name": "Baltimore, MD",       "state": "Maryland",       "lat": 39.2904, "lon":  -76.6122, "tz": "America/New_York"},
    {"id": "las_vegas",       "name": "Las Vegas, NV",       "state": "Nevada",         "lat": 36.1699, "lon": -115.1398, "tz": "America/Los_Angeles"},
    {"id": "albuquerque",     "name": "Albuquerque, NM",     "state": "New Mexico",     "lat": 35.0844, "lon": -106.6504, "tz": "America/Denver"},
    {"id": "tucson",          "name": "Tucson, AZ",          "state": "Arizona",        "lat": 32.2226, "lon": -110.9747, "tz": "America/Phoenix"},
    {"id": "anchorage",       "name": "Anchorage, AK",       "state": "Alaska",         "lat": 61.2181, "lon": -149.9003, "tz": "America/Anchorage"},

    # ===== NOROESTE PACÍFICO (2) =====
    {"id": "seattle",         "name": "Seattle, WA",         "state": "Washington",     "lat": 47.6062, "lon": -122.3321, "tz": "America/Los_Angeles"},
    {"id": "portland_or",     "name": "Portland, OR",        "state": "Oregon",         "lat": 45.5152, "lon": -122.6784, "tz": "America/Los_Angeles"},

    # ===== PUERTO RICO (3) =====
    {"id": "san_juan",        "name": "San Juan, PR",        "state": "Puerto Rico",    "lat": 18.4655, "lon":  -66.1057, "tz": "America/Puerto_Rico"},
    {"id": "ponce",           "name": "Ponce, PR",           "state": "Puerto Rico",    "lat": 18.0111, "lon":  -66.6140, "tz": "America/Puerto_Rico"},
    {"id": "mayaguez",        "name": "Mayagüez, PR",        "state": "Puerto Rico",    "lat": 18.2013, "lon":  -67.1397, "tz": "America/Puerto_Rico"},
]

# Umbrales de altitud del sol (grados) para cada evento del día
THRESHOLDS = {
    'astron':  -18.0,    # crepúsculo astronómico
    'naut':    -12.0,    # crepúsculo náutico
    'civil':    -6.0,    # crepúsculo civil
    'blue':     -4.0,    # límite entre hora azul y hora dorada
    'horizon':  -0.833,  # amanecer/atardecer estándar (incl. refracción atmosférica)
    'golden':    6.0,    # fin de hora dorada matutina / inicio vespertina
}

# Muestreo: 2 minutos = 720 muestras por día. Precisión de cruces ~30s tras interpolación.
SAMPLE_STEP_MINUTES = 2
SAMPLES_PER_DAY = 24 * 60 // SAMPLE_STEP_MINUTES  # = 720


# ===== COLORES ANSI =====
class C:
    GRN = '\033[92m'; CYAN = '\033[96m'; YEL = '\033[93m'; RED = '\033[91m'
    BLU = '\033[94m'; DIM = '\033[2m'; RST = '\033[0m'; BOLD = '\033[1m'


def progress_bar(current, total, label='', start_time=None, width=36):
    """Barra de progreso estilo Canal Meteo: █░ con porcentaje y ETA."""
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = '█' * filled + '░' * (width - filled)
    eta = ''
    if start_time and current > 0:
        elapsed = time.time() - start_time
        rate = current / elapsed
        remaining = (total - current) / rate if rate > 0 else 0
        eta = f' · ETA {remaining:4.0f}s'
    label_trunc = (label[:28] + '…') if len(label) > 29 else label.ljust(29)
    print(
        f'\r{C.CYAN}[{bar}]{C.RST} {pct*100:5.1f}% · '
        f'{current:>4}/{total:<4} · {label_trunc}{eta}    ',
        end='', flush=True
    )
    if current == total:
        print()


# ===== LOGGING =====
def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stderr),
        ]
    )


# ===== CÁLCULO ASTRONÓMICO =====
def compute_day_ephemeris(observer, sun, ts, tz, date_local):
    """
    Calcula todos los eventos solares de un día para una ubicación.

    Estrategia: una sola observación vectorizada con muestras cada 2 min,
    luego se detectan los cruces de los 6 umbrales por interpolación lineal.

    Devuelve: (dict eventos, datetime mediodía local, float altitud máx grados)
    """
    # Ventana: desde 00:00 local hasta 24:00 local
    start_local = tz.localize(datetime.combine(date_local, datetime.min.time()))
    times_local = [start_local + timedelta(minutes=SAMPLE_STEP_MINUTES * i)
                   for i in range(SAMPLES_PER_DAY + 1)]
    times_utc = [t.astimezone(timezone.utc) for t in times_local]
    t_vec = ts.from_datetimes(times_utc)

    # Altitud del sol vectorizada (una sola llamada a Skyfield)
    alts = observer.at(t_vec).observe(sun).apparent().altaz()[0].degrees
    alts = np.asarray(alts)

    events = {}

    # Detectar cruces para cada umbral
    for key, deg in THRESHOLDS.items():
        # Cruce ascendente: alts[i] < deg <= alts[i+1]
        rising = np.where((alts[:-1] < deg) & (alts[1:] >= deg))[0]
        if len(rising) > 0:
            i = rising[0]
            frac = (deg - alts[i]) / (alts[i+1] - alts[i])
            events[f'{key}_dawn'] = times_local[i] + timedelta(minutes=SAMPLE_STEP_MINUTES * frac)

        # Cruce descendente: alts[i] >= deg > alts[i+1]
        setting = np.where((alts[:-1] >= deg) & (alts[1:] < deg))[0]
        if len(setting) > 0:
            i = setting[0]
            frac = (alts[i] - deg) / (alts[i] - alts[i+1])
            events[f'{key}_dusk'] = times_local[i] + timedelta(minutes=SAMPLE_STEP_MINUTES * frac)

    # Mediodía solar (máximo de altitud)
    max_idx = int(np.argmax(alts))
    solar_noon = times_local[max_idx]
    max_altitude = float(alts[max_idx])

    return events, solar_noon, max_altitude


def fmt_time(dt):
    """Formato HH:MM, o None si dt es None."""
    return dt.strftime('%H:%M') if dt else None


def build_day_summary(date_local, events, solar_noon, max_altitude, prev_day_length_min=None):
    """Construye el dict de salida para un día (campos cortos para reducir JSON)."""
    sr = events.get('horizon_dawn')
    ss = events.get('horizon_dusk')

    day_length_min = None
    if sr and ss:
        day_length_min = round((ss - sr).total_seconds() / 60)

    dl_delta = None
    if day_length_min is not None and prev_day_length_min is not None:
        dl_delta = day_length_min - prev_day_length_min

    return {
        'd':        date_local.isoformat(),
        'sr':       fmt_time(sr),                          # sunrise
        'ss':       fmt_time(ss),                          # sunset
        'sn':       fmt_time(solar_noon),                  # solar noon
        'sa':       round(max_altitude, 1),                # solar altitude (max)
        'dl':       day_length_min,                        # day length (min)
        'dl_delta': dl_delta,                              # delta vs día anterior
        'cd':       fmt_time(events.get('civil_dawn')),    # civil dawn
        'cu':       fmt_time(events.get('civil_dusk')),    # civil dusk
        'nd':       fmt_time(events.get('naut_dawn')),     # nautical dawn
        'nu':       fmt_time(events.get('naut_dusk')),     # nautical dusk
        'ad':       fmt_time(events.get('astron_dawn')),   # astronomical dawn
        'au':       fmt_time(events.get('astron_dusk')),   # astronomical dusk
        # Hora dorada: del horizonte (sr/ss) hasta +6°
        'gms':      fmt_time(sr),                          # golden morning start
        'gme':      fmt_time(events.get('golden_dawn')),   # golden morning end
        'ges':      fmt_time(events.get('golden_dusk')),   # golden evening start
        'gee':      fmt_time(ss),                          # golden evening end
        # Hora azul: entre crepúsculo civil (-6°) y -4°
        'bms':      fmt_time(events.get('civil_dawn')),    # blue morning start
        'bme':      fmt_time(events.get('blue_dawn')),     # blue morning end
        'bes':      fmt_time(events.get('blue_dusk')),     # blue evening start
        'bee':      fmt_time(events.get('civil_dusk')),    # blue evening end
    }


def compute_year_events(year, ts, eph):
    """Equinoccios y solsticios del año (4 eventos)."""
    t0 = ts.utc(year, 1, 1)
    t1 = ts.utc(year + 1, 1, 1)
    times, events = almanac.find_discrete(t0, t1, almanac.seasons(eph))

    # Skyfield convención: 0=vernal eq, 1=summer solst, 2=autumnal eq, 3=winter solst
    types = ['equinox_spring', 'solstice_summer', 'equinox_autumn', 'solstice_winter']
    names_es = [
        'Equinoccio de primavera',
        'Solsticio de verano',
        'Equinoccio de otoño',
        'Solsticio de invierno',
    ]
    names_en = [
        'Spring equinox',
        'Summer solstice',
        'Autumn equinox',
        'Winter solstice',
    ]

    out = []
    for t, e in zip(times, events):
        out.append({
            'type':     types[e],
            'name_es':  names_es[e],
            'name_en':  names_en[e],
            'datetime_utc': t.utc_datetime().isoformat(),
        })
    return out


# ===== UPLOAD CDN =====
def upload_to_cdn(local_path, cdn_key, gzip_encoded=False):
    """Sube archivo al CDN usando AWS CLI con perfil do-tor1.
    Si gzip_encoded=True, marca el archivo con Content-Encoding: gzip
    (el navegador lo descomprimirá transparentemente con fetch()).
    """
    cmd = [
        'aws', 's3', 'cp', local_path,
        f's3://{CDN_BUCKET}/{cdn_key}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=3600',
        '--endpoint-url', CDN_ENDPOINT,
    ]
    if gzip_encoded:
        cmd.extend(['--content-encoding', 'gzip'])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f'AWS CLI falló (rc={result.returncode}): {result.stderr.strip()}')
    return f'https://{CDN_BUCKET}.sfo3.cdn.digitaloceanspaces.com/{cdn_key}'


def compress_gzip(src_path, dst_path):
    """Comprime un archivo con gzip nivel 6 (buen balance ratio/tiempo)."""
    import gzip
    with open(src_path, 'rb') as f_in, gzip.open(dst_path, 'wb', compresslevel=6) as f_out:
        while True:
            chunk = f_in.read(65536)
            if not chunk:
                break
            f_out.write(chunk)
    return os.path.getsize(dst_path)


# ===== MAIN =====
def main():
    parser = argparse.ArgumentParser(
        description='Pipeline de efemérides solares — Canal Meteo TV (Bloque 3)'
    )
    parser.add_argument('--no-upload', action='store_true', help='No subir al CDN (debug)')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS,
                        help=f'Días a calcular (default {DEFAULT_DAYS})')
    parser.add_argument('--out', default=TMP_OUTPUT, help='Archivo JSON de salida')
    args = parser.parse_args()

    setup_logging()
    t_start = time.time()

    print(f'\n{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════╗')
    print(f'║   CANAL METEO TV — EPHEMERIS PIPELINE (BLOQUE 3) ║')
    print(f'╚══════════════════════════════════════════════════╝{C.RST}\n')

    print(f'{C.DIM}Configuración:{C.RST}')
    print(f'  • Ciudades:   {len(CITIES)}')
    print(f'  • Días:       {args.days}')
    print(f'  • Output:     {args.out}')
    print(f'  • Upload CDN: {"NO" if args.no_upload else "SÍ"}\n')

    # Cargar efemérides JPL DE421 (válido 1900-2050, ~17 MB, se descarga la primera vez)
    print(f'{C.YEL}● Cargando efemérides JPL DE421...{C.RST}')
    os.makedirs(SKYFIELD_DATA_DIR, exist_ok=True)
    load = api.Loader(SKYFIELD_DATA_DIR, verbose=False)
    ts = load.timescale()
    eph = load('de421.bsp')
    earth = eph['earth']
    sun = eph['sun']
    print(f'{C.GRN}  ✓ Cargadas desde {SKYFIELD_DATA_DIR}{C.RST}\n')

    # Fechas a calcular: empezamos el día de hoy (UTC) y avanzamos N días
    today = datetime.now(timezone.utc).date()
    dates = [today + timedelta(days=i) for i in range(args.days)]

    # Estructura de salida
    out = {
        'generated_at':  datetime.now(timezone.utc).isoformat(),
        'valid_from':    dates[0].isoformat(),
        'valid_until':   dates[-1].isoformat(),
        'days_count':    args.days,
        'sample_step_minutes': SAMPLE_STEP_MINUTES,
        'cities':        [],
    }

    # Procesar cada ciudad × día
    total_ops = len(CITIES) * args.days
    op_count = 0
    pipeline_start = time.time()

    print(f'{C.YEL}● Calculando para {len(CITIES)} ciudades × {args.days} días = {total_ops} operaciones{C.RST}')

    for city in CITIES:
        city_t0 = time.time()
        tz = pytz.timezone(city['tz'])
        topos = api.wgs84.latlon(city['lat'], city['lon'])
        observer = earth + topos

        city_data = {
            'id':   city['id'],
            'name': city['name'],
            'lat':  city['lat'],
            'lon':  city['lon'],
            'tz':   city['tz'],
            'days': [],
        }

        prev_dl = None
        for date_local in dates:
            try:
                events, solar_noon, max_alt = compute_day_ephemeris(
                    observer, sun, ts, tz, date_local
                )
                day_summary = build_day_summary(
                    date_local, events, solar_noon, max_alt, prev_dl
                )
                city_data['days'].append(day_summary)
                prev_dl = day_summary['dl']
            except Exception as e:
                logging.error(f"Error en {city['id']} {date_local}: {e}")
                city_data['days'].append({'d': date_local.isoformat(), 'error': str(e)})

            op_count += 1
            progress_bar(op_count, total_ops, label=city['name'], start_time=pipeline_start)

        out['cities'].append(city_data)
        logging.info(f"{city['id']:<14} procesado en {time.time()-city_t0:.1f}s")

    # Equinoccios y solsticios del año actual y próximo
    print(f'\n{C.YEL}● Calculando equinoccios y solsticios...{C.RST}')
    current_year = today.year
    out['year_events'] = {
        str(current_year):     compute_year_events(current_year, ts, eph),
        str(current_year + 1): compute_year_events(current_year + 1, ts, eph),
    }
    n_events = len(out['year_events'][str(current_year)])
    print(f'{C.GRN}  ✓ {n_events} eventos en {current_year}, {n_events} en {current_year+1}{C.RST}')

    # Guardar JSON (compacto, sin pretty-printing)
    print(f'\n{C.YEL}● Guardando JSON...{C.RST}')
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(args.out) / 1024
    print(f'{C.GRN}  ✓ {args.out} ({size_kb:.1f} KB){C.RST}')

    # Subir al CDN comprimido con gzip (el navegador descomprime transparente)
    if not args.no_upload:
        print(f'\n{C.YEL}● Comprimiendo con gzip antes de subir...{C.RST}')
        gz_path = args.out + '.gz'
        size_gz = compress_gzip(args.out, gz_path)
        ratio = (size_gz / os.path.getsize(args.out)) * 100
        print(f'{C.GRN}  ✓ {size_gz/1024:.1f} KB ({ratio:.0f}% del original){C.RST}')

        print(f'\n{C.YEL}● Subiendo al CDN (Content-Encoding: gzip)...{C.RST}')
        try:
            cdn_url = upload_to_cdn(gz_path, CDN_KEY, gzip_encoded=True)
            print(f'{C.GRN}  ✓ {cdn_url}{C.RST}')
            logging.info(f'CDN OK: {cdn_url} ({size_gz/1024:.1f} KB gz)')
            os.unlink(gz_path)  # limpiar tmp
        except Exception as e:
            print(f'{C.RED}  ✗ Error: {e}{C.RST}')
            logging.error(f'Error subiendo a CDN: {e}')
            sys.exit(1)

    # Resumen
    total_elapsed = time.time() - t_start
    print(f'\n{C.BOLD}{C.GRN}═══════════════════════════════════════════════════')
    print(f'  ✓ COMPLETADO en {total_elapsed:.1f}s')
    print(f'  ✓ {len(CITIES)} ciudades · {args.days} días · {size_kb:.1f} KB')
    print(f'═══════════════════════════════════════════════════{C.RST}\n')
    logging.info(f'Pipeline completado en {total_elapsed:.1f}s')


if __name__ == '__main__':
    main()
