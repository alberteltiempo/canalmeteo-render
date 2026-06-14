#!/usr/bin/env python3
"""
generate_forecast_cities_stub.py
═══════════════════════════════════════════════════════════════════
Genera un forecast-cities.json mínimo válido leyendo weather.json
y agrupando por región según el estado.

NO genera datos perfectos de pronóstico (los campos complejos van vacíos),
pero sí estructura válida para que fetchForecastCitiesData() no devuelva
null y el Promise.all de fetchSegmentData no se rompa.

Output: data/regional/forecast-cities.json en el CDN
═══════════════════════════════════════════════════════════════════
"""

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

CDN_BASE = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com'
SOURCE_URL = f'{CDN_BASE}/data/cities/weather.json'
TARGET_KEY = 'data/regional/forecast-cities.json'
CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'

# Mapping estado → región
STATE_TO_REGION = {
    # Florida
    'Florida': 'florida',
    # Noreste
    'New York': 'noreste',
    'Pennsylvania': 'noreste',
    'New Jersey': 'noreste',
    'Massachusetts': 'noreste',
    'Connecticut': 'noreste',
    'Rhode Island': 'noreste',
    'Maine': 'noreste',
    'New Hampshire': 'noreste',
    'Vermont': 'noreste',
    'Delaware': 'noreste',
    'Maryland': 'noreste',
    # Sureste
    'Virginia': 'sureste',
    'West Virginia': 'sureste',
    'North Carolina': 'sureste',
    'South Carolina': 'sureste',
    'Georgia': 'sureste',
    'Tennessee': 'sureste',
    'Alabama': 'sureste',
    'Mississippi': 'sureste',
    'Kentucky': 'sureste',
    # Grandes Lagos
    'Michigan': 'grandes-lagos',
    'Wisconsin': 'grandes-lagos',
    'Minnesota': 'grandes-lagos',
    'Ohio': 'grandes-lagos',
    'Indiana': 'grandes-lagos',
    'Illinois': 'grandes-lagos',
    # Texas/Sur
    'Texas': 'texas',
    'Oklahoma': 'texas',
    'Louisiana': 'texas',
    'Arkansas': 'texas',
    # Medio Oeste
    'Iowa': 'medio-oeste',
    'Missouri': 'medio-oeste',
    'Kansas': 'medio-oeste',
    'Nebraska': 'medio-oeste',
    'North Dakota': 'medio-oeste',
    'South Dakota': 'medio-oeste',
    # Suroeste
    'Arizona': 'suroeste',
    'New Mexico': 'suroeste',
    'Nevada': 'suroeste',
    'Utah': 'suroeste',
    'Colorado': 'suroeste',
    # Noroeste
    'Washington': 'noroeste',
    'Oregon': 'noroeste',
    'Idaho': 'noroeste',
    'Montana': 'noroeste',
    'Wyoming': 'noroeste',
    'California': 'noroeste',  # No tenemos región California, va al noroeste
    # Skip (no se renderizan en regional)
    'Alaska': None,
    'Hawaii': None,
}

REGION_NAMES = {
    'noreste': 'Noreste',
    'sureste': 'Sureste',
    'florida': 'Florida',
    'grandes-lagos': 'Grandes Lagos',
    'texas': 'Texas y Sur',
    'medio-oeste': 'Medio Oeste',
    'suroeste': 'Suroeste',
    'noroeste': 'Noroeste',
}

# Estados → coordenadas aproximadas (capitales)
STATE_COORDS = {
    'Alabama': (32.36, -86.30),       'Arizona': (33.45, -112.07),
    'Arkansas': (34.74, -92.29),      'California': (38.58, -121.49),
    'Colorado': (39.74, -104.99),     'Connecticut': (41.76, -72.67),
    'Delaware': (39.16, -75.52),      'Florida': (25.76, -80.19),
    'Georgia': (33.75, -84.39),       'Idaho': (43.62, -116.20),
    'Illinois': (39.80, -89.65),      'Indiana': (39.77, -86.16),
    'Iowa': (41.59, -93.62),          'Kansas': (39.05, -95.67),
    'Kentucky': (38.20, -84.87),      'Louisiana': (30.45, -91.19),
    'Maine': (44.31, -69.78),         'Maryland': (38.98, -76.49),
    'Massachusetts': (42.36, -71.06), 'Michigan': (42.73, -84.56),
    'Minnesota': (44.95, -93.10),     'Mississippi': (32.30, -90.18),
    'Missouri': (38.58, -92.17),      'Montana': (46.59, -112.04),
    'Nebraska': (40.81, -96.68),      'Nevada': (39.16, -119.77),
    'New Hampshire': (43.21, -71.54), 'New Jersey': (40.22, -74.77),
    'New Mexico': (35.69, -105.94),   'New York': (42.65, -73.76),
    'North Carolina': (35.78, -78.64),'North Dakota': (46.81, -100.78),
    'Ohio': (39.96, -82.99),          'Oklahoma': (35.49, -97.51),
    'Oregon': (44.94, -123.04),       'Pennsylvania': (40.27, -76.88),
    'Rhode Island': (41.83, -71.41),  'South Carolina': (34.00, -81.04),
    'South Dakota': (44.37, -100.35), 'Tennessee': (36.16, -86.78),
    'Texas': (30.27, -97.74),         'Utah': (40.76, -111.89),
    'Vermont': (44.26, -72.58),       'Virginia': (37.54, -77.43),
    'Washington': (47.04, -122.90),   'West Virginia': (38.34, -81.63),
    'Wisconsin': (43.07, -89.40),     'Wyoming': (41.14, -104.82),
}

STATE_ES = {
    'Alabama': 'Alabama', 'Arizona': 'Arizona', 'Arkansas': 'Arkansas',
    'California': 'California', 'Colorado': 'Colorado', 'Connecticut': 'Connecticut',
    'Delaware': 'Delaware', 'Florida': 'Florida', 'Georgia': 'Georgia',
    'Idaho': 'Idaho', 'Illinois': 'Illinois', 'Indiana': 'Indiana',
    'Iowa': 'Iowa', 'Kansas': 'Kansas', 'Kentucky': 'Kentucky',
    'Louisiana': 'Luisiana', 'Maine': 'Maine', 'Maryland': 'Maryland',
    'Massachusetts': 'Massachusetts', 'Michigan': 'Michigan',
    'Minnesota': 'Minnesota', 'Mississippi': 'Misisipi',
    'Missouri': 'Misuri', 'Montana': 'Montana', 'Nebraska': 'Nebraska',
    'Nevada': 'Nevada', 'New Hampshire': 'New Hampshire',
    'New Jersey': 'Nueva Jersey', 'New Mexico': 'Nuevo México',
    'New York': 'Nueva York', 'North Carolina': 'Carolina del Norte',
    'North Dakota': 'Dakota del Norte', 'Ohio': 'Ohio',
    'Oklahoma': 'Oklahoma', 'Oregon': 'Oregón', 'Pennsylvania': 'Pensilvania',
    'Rhode Island': 'Rhode Island', 'South Carolina': 'Carolina del Sur',
    'South Dakota': 'Dakota del Sur', 'Tennessee': 'Tennessee',
    'Texas': 'Texas', 'Utah': 'Utah', 'Vermont': 'Vermont',
    'Virginia': 'Virginia', 'Washington': 'Washington',
    'West Virginia': 'Virginia Occidental', 'Wisconsin': 'Wisconsin',
    'Wyoming': 'Wyoming',
}


def slugify(text: str) -> str:
    """Genera ID URL-safe."""
    return text.lower().replace(' ', '-').replace('.', '').replace(',', '')


def transform_city(c: dict) -> dict:
    """Convierte un city del weather.json a la estructura ForecastCity."""
    city_name = c.get('city', '')
    state = c.get('state', '')
    lat, lon = STATE_COORDS.get(state, (0, 0))

    # Convertir forecast5 → ForecastDay[]
    days = []
    for day in c.get('forecast5', []):
        days.append({
            'date': day.get('date', ''),
            'day_label_es': day.get('label', ''),
            'day_long_es': day.get('label', ''),
            'max_f': day.get('tempMax'),
            'min_f': day.get('tempMin'),
            'feels_max_f': None,
            'feels_min_f': None,
            'precip_in': 0,
            'pop_pct': 0,
            'wind_max_mph': None,
            'gust_max_mph': None,
            'cloud_avg_pct': None,
            'rh_avg_pct': None,
            'cape_max': None,
            'condition_id': day.get('condition', '').lower().replace(' ', '_'),
            'condition_es': day.get('conditionEs', ''),
            'icon': day.get('icon', ''),
        })

    return {
        'id': slugify(f"{city_name}-{state}"),
        'name': city_name,
        'name_es': city_name,
        'state': state,
        'state_es': STATE_ES.get(state, state),
        'lat': lat,
        'lon': lon,
        'tz': c.get('tz', 'America/New_York'),
        'days': days,
    }


def main():
    print("=== Generando forecast-cities.json ===")

    # 1) Descargar weather.json
    print(f"  Fetching {SOURCE_URL}...")
    with urllib.request.urlopen(SOURCE_URL) as r:
        source = json.load(r)

    cities_raw = source.get('data', [])
    print(f"  {len(cities_raw)} ciudades en weather.json")

    # 2) Agrupar por región
    regions = {rid: {'name_es': name, 'cities': []} for rid, name in REGION_NAMES.items()}
    skipped = 0

    for c in cities_raw:
        state = c.get('state', '')
        # Solo capitales (10 latino son duplicados de capitales)
        if c.get('region') != 'capital':
            continue

        region_id = STATE_TO_REGION.get(state)
        if region_id is None:
            skipped += 1
            continue

        if region_id not in regions:
            print(f"  WARN: región desconocida '{region_id}' para {state}")
            continue

        try:
            city_obj = transform_city(c)
            regions[region_id]['cities'].append(city_obj)
        except Exception as e:
            print(f"  ERROR transformando {c.get('city')}: {e}")

    # 3) Resumen
    print(f"\n  Distribución por región:")
    for rid, r in regions.items():
        print(f"    {rid:15s}: {len(r['cities']):2d} ciudades")
    print(f"  Skipped: {skipped}")

    # 4) Construir output
    output = {
        'version': '1.0',
        'generated': datetime.now(timezone.utc).isoformat(),
        'model': 'weather.json-aggregated',
        'cycle': source.get('generated', ''),
        'regions': regions,
    }

    # 5) Guardar local
    tmp_path = '/tmp/forecast-cities.json'
    with open(tmp_path, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved {tmp_path} ({len(json.dumps(output))//1024} KB)")

    # 6) Subir CDN
    print(f"  Uploading to s3://{CDN_BUCKET}/{TARGET_KEY}...")
    cmd = [
        'aws', 's3', 'cp', tmp_path,
        f's3://{CDN_BUCKET}/{TARGET_KEY}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'public, max-age=300',
        '--endpoint-url', CDN_ENDPOINT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  ❌ Upload failed: {result.stderr[:200]}")
        return 1

    print(f"  ✅ Uploaded")
    print(f"\n  URL: {CDN_BASE}/{TARGET_KEY}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
