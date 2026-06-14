#!/usr/bin/env python3
"""
faa_airports_pipeline.py
Canal Meteo TV — FAA Airport Status pipeline

Uses the FAA NAS Status public XML feed (single endpoint, all airports at once).
Replaces the deprecated soa.smext.faa.gov/asws per-airport JSON API.

Endpoint: https://nasstatus.faa.gov/api/airport-status-information
Output:   canalmeteo-public/data/faa/airports.json
Cron:     */5 * * * *   (cada 5 min — los ground stops cambian rápido)

Ubicación:  /opt/canalmeteo/scripts/faa_airports_pipeline.py
"""

import json
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

# ───────────────────────── CONFIG ─────────────────────────
FAA_XML_ENDPOINT = 'https://nasstatus.faa.gov/api/airport-status-information'
OUTPUT_KEY = 'data/faa/airports.json'
CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
REQUEST_TIMEOUT = 15

# Airport dictionary: IATA → (name_es, city_es, state)
AIRPORT_NAMES = {
    # Northeast
    'JFK': ('John F. Kennedy', 'Nueva York', 'NY'),
    'LGA': ('LaGuardia', 'Nueva York', 'NY'),
    'EWR': ('Newark Liberty', 'Newark', 'NJ'),
    'BOS': ('Logan', 'Boston', 'MA'),
    'PHL': ('Filadelfia', 'Filadelfia', 'PA'),
    'DCA': ('Reagan Nacional', 'Washington', 'DC'),
    'IAD': ('Dulles', 'Washington', 'DC'),
    'BWI': ('Baltimore/Washington', 'Baltimore', 'MD'),
    'PIT': ('Pittsburgh', 'Pittsburgh', 'PA'),
    'BUF': ('Buffalo Niagara', 'Buffalo', 'NY'),
    'ALB': ('Albany', 'Albany', 'NY'),
    'PVD': ('T. F. Green', 'Providence', 'RI'),
    'BDL': ('Bradley', 'Hartford', 'CT'),
    # Southeast
    'ATL': ('Hartsfield-Jackson', 'Atlanta', 'GA'),
    'MIA': ('Miami', 'Miami', 'FL'),
    'FLL': ('Fort Lauderdale', 'Fort Lauderdale', 'FL'),
    'MCO': ('Orlando', 'Orlando', 'FL'),
    'TPA': ('Tampa', 'Tampa', 'FL'),
    'JAX': ('Jacksonville', 'Jacksonville', 'FL'),
    'RSW': ('Suroeste de Florida', 'Fort Myers', 'FL'),
    'PBI': ('Palm Beach', 'West Palm Beach', 'FL'),
    'CLT': ('Charlotte Douglas', 'Charlotte', 'NC'),
    'RDU': ('Raleigh-Durham', 'Raleigh', 'NC'),
    'GSO': ('Piedmont Triad', 'Greensboro', 'NC'),
    'CHS': ('Charleston', 'Charleston', 'SC'),
    'CAE': ('Columbia', 'Columbia', 'SC'),
    'SAV': ('Savannah', 'Savannah', 'GA'),
    # Midwest
    'ORD': ("O'Hare", 'Chicago', 'IL'),
    'MDW': ('Midway', 'Chicago', 'IL'),
    'DTW': ('Detroit Metro', 'Detroit', 'MI'),
    'MSP': ('Minneapolis-Saint Paul', 'Mineápolis', 'MN'),
    'STL': ('San Luis', 'San Luis', 'MO'),
    'MCI': ('Kansas City', 'Kansas City', 'MO'),
    'CLE': ('Cleveland Hopkins', 'Cleveland', 'OH'),
    'CVG': ('Cincinnati/Norte Kentucky', 'Cincinnati', 'OH'),
    'CMH': ('John Glenn Columbus', 'Columbus', 'OH'),
    'DAY': ('Dayton', 'Dayton', 'OH'),
    'IND': ('Indianápolis', 'Indianápolis', 'IN'),
    'MKE': ('General Mitchell', 'Milwaukee', 'WI'),
    'GRR': ('Gerald R. Ford', 'Grand Rapids', 'MI'),
    'OMA': ('Eppley', 'Omaha', 'NE'),
    # South central
    'DFW': ('Dallas-Fort Worth', 'Dallas', 'TX'),
    'DAL': ('Dallas Love Field', 'Dallas', 'TX'),
    'IAH': ('George Bush Intercontinental', 'Houston', 'TX'),
    'HOU': ('William P. Hobby', 'Houston', 'TX'),
    'AUS': ('Austin-Bergstrom', 'Austin', 'TX'),
    'SAT': ('San Antonio', 'San Antonio', 'TX'),
    'ELP': ('El Paso', 'El Paso', 'TX'),
    'MSY': ('Louis Armstrong', 'Nueva Orleans', 'LA'),
    'MEM': ('Memphis', 'Memphis', 'TN'),
    'BNA': ('Nashville', 'Nashville', 'TN'),
    'BHM': ('Birmingham', 'Birmingham', 'AL'),
    'OKC': ('Will Rogers', 'Oklahoma City', 'OK'),
    'TUL': ('Tulsa', 'Tulsa', 'OK'),
    'LIT': ('Clinton Little Rock', 'Little Rock', 'AR'),
    # Mountain
    'DEN': ('Denver', 'Denver', 'CO'),
    'COS': ('Colorado Springs', 'Colorado Springs', 'CO'),
    'SLC': ('Salt Lake City', 'Salt Lake City', 'UT'),
    'PHX': ('Sky Harbor', 'Phoenix', 'AZ'),
    'LAS': ('Harry Reid', 'Las Vegas', 'NV'),
    'RNO': ('Reno-Tahoe', 'Reno', 'NV'),
    'ABQ': ('Albuquerque', 'Albuquerque', 'NM'),
    'TUS': ('Tucson', 'Tucson', 'AZ'),
    'BOI': ('Boise', 'Boise', 'ID'),
    # West Coast
    'LAX': ('Los Ángeles', 'Los Ángeles', 'CA'),
    'SFO': ('San Francisco', 'San Francisco', 'CA'),
    'SAN': ('San Diego', 'San Diego', 'CA'),
    'SEA': ('Seattle-Tacoma', 'Seattle', 'WA'),
    'PDX': ('Portland', 'Portland', 'OR'),
    'SJC': ('San José Mineta', 'San José', 'CA'),
    'OAK': ('Oakland', 'Oakland', 'CA'),
    'SMF': ('Sacramento', 'Sacramento', 'CA'),
    'SNA': ('John Wayne', 'Santa Ana', 'CA'),
    'ONT': ('Ontario', 'Ontario', 'CA'),
    'BUR': ('Hollywood Burbank', 'Burbank', 'CA'),
    'LGB': ('Long Beach', 'Long Beach', 'CA'),
    # Alaska + Hawaii
    'ANC': ('Ted Stevens', 'Anchorage', 'AK'),
    'FAI': ('Fairbanks', 'Fairbanks', 'AK'),
    'HNL': ('Daniel K. Inouye', 'Honolulu', 'HI'),
    'OGG': ('Kahului', 'Kahului', 'HI'),
    'KOA': ('Kona', 'Kailua-Kona', 'HI'),
    'LIH': ('Lihue', 'Lihue (Kauai)', 'HI'),
    # Puerto Rico / USVI
    'SJU': ('Luis Muñoz Marín', 'San Juan', 'PR'),
    'BQN': ('Rafael Hernández', 'Aguadilla', 'PR'),
    'PSE': ('Mercedita', 'Ponce', 'PR'),
    'STT': ('Cyril E. King', 'Saint Thomas', 'VI'),
    'STX': ('Henry E. Rohlsen', 'Saint Croix', 'VI'),
    'TISX': ('Henry E. Rohlsen', 'Saint Croix', 'VI'),
}


# Translation of FAA reasons — partial matching (more specific first)
REASON_TRANSLATIONS = [
    ('THUNDERSTORM', 'Tormentas eléctricas'),
    ('TSRA', 'Tormentas eléctricas'),
    ('TORNADOE', 'Tornados'),
    ('TORNADO', 'Tornados'),
    ('LOW CEILING', 'Techo bajo de nubes'),
    ('LOW CLOUD', 'Nubosidad baja'),
    ('SNOW', 'Nieve'),
    ('ICE', 'Hielo'),
    ('FREEZING', 'Precipitación helada'),
    ('FOG', 'Niebla'),
    ('VIS', 'Baja visibilidad'),
    ('WIND', 'Vientos fuertes'),
    ('VOLUME', 'Volumen de tráfico aéreo'),
    ('RUNWAY', 'Cierre de pista'),
    ('TAXIWAY', 'Cierre de calle de rodaje'),
    ('EQUIPMENT', 'Problema de equipamiento'),
    ('STAFFING', 'Falta de controladores aéreos'),
    ('CONSTRUCTION', 'Obras en pista'),
    ('WEATHER', 'Condiciones meteorológicas'),
    ('WX', 'Condiciones meteorológicas'),
    ('OTHER', 'Otros motivos'),
]


def translate_reason(reason):
    if not reason:
        return ''
    r = reason.upper().strip()
    for key, val in REASON_TRANSLATIONS:
        if key in r:
            return val
    return reason.strip()


def get_airport_info(iata):
    if iata in AIRPORT_NAMES:
        return AIRPORT_NAMES[iata]
    return iata, '', ''


def text_or(elem, tag, default=''):
    """Safely get child text from XML element."""
    if elem is None:
        return default
    child = elem.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return default


def fetch_xml():
    r = requests.get(
        FAA_XML_ENDPOINT,
        headers={
            'User-Agent': 'CanalMeteo/1.0 (canalmeteo.tv)',
            'Accept': 'application/xml, text/xml, */*',
        },
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.content


def classify_delay_type(name):
    n = (name or '').lower()
    if 'ground stop' in n:
        return 'ground_stop'
    if 'ground delay' in n:
        return 'ground_delay'
    if 'arrive' in n and 'depart' in n:
        return 'arrive_depart_delay'
    if 'depart' in n:
        return 'depart_delay'
    if 'arriv' in n:
        return 'arrive_delay'
    if 'deicing' in n or 'de-icing' in n:
        return 'deicing'
    if 'closure' in n:
        return 'closure'
    return (name or 'other').lower().replace(' ', '_').replace('/', '_')


def type_code_to_es(code):
    return {
        'ground_stop': 'Parada en tierra',
        'ground_delay': 'Demora en tierra',
        'depart_delay': 'Demora en salida',
        'arrive_delay': 'Demora en llegada',
        'arrive_depart_delay': 'Demoras de llegada y salida',
        'deicing': 'Descongelado',
        'closure': 'Cierre',
    }.get(code, code)


def parse_xml(xml_bytes):
    """
    FAA XML structure (from https://nasstatus.faa.gov/api/airport-status-information):

    <AIRPORT_STATUS_INFORMATION>
      <Update_Time>Fri Apr 18 22:00:00 2026 GMT</Update_Time>
      <Delay_type>
        <name>Ground Stop Programs</name>
        <Airport>
          <ARPT>IAH</ARPT>
          <Reason>WX / Thunderstorms</Reason>
          <Endtime>Apr 18 at 22:59 UTC</Endtime>
        </Airport>
        ...
      </Delay_type>
      <Delay_type>
        <name>Ground Delay Programs</name>
        <Airport>
          <ARPT>SFO</ARPT>
          <Reason>WX / Low Ceilings</Reason>
          <Avg>45 minutes</Avg>
          <Trend>Steady</Trend>
        </Airport>
      </Delay_type>
      <Delay_type>
        <name>Arrive Depart Delay</name>
        <Airport>...</Airport>
      </Delay_type>
      <Airport_Closures>
        <Airport>
          <ARPT>TISX</ARPT>
          <Reason>...</Reason>
          <Start>...</Start>
          <Reopen>...</Reopen>
        </Airport>
      </Airport_Closures>
    </AIRPORT_STATUS_INFORMATION>
    """
    root = ET.fromstring(xml_bytes)
    update_time = text_or(root, 'Update_Time')
    events_by_airport = {}

    # Delay_type blocks
    for delay_type in root.findall('Delay_type'):
        type_name = text_or(delay_type, 'name')
        type_code = classify_delay_type(type_name)

        for airport_el in delay_type.findall('.//Airport'):
            iata = text_or(airport_el, 'ARPT').upper()
            if not iata:
                continue

            reason = text_or(airport_el, 'Reason')
            event = {
                'tipo': type_code,
                'tipo_es': type_code_to_es(type_code),
                'reason': reason,
                'reason_es': translate_reason(reason),
            }

            if type_code == 'ground_stop':
                event['end_time'] = text_or(airport_el, 'Endtime')
            elif type_code == 'ground_delay':
                event['avg_time'] = text_or(airport_el, 'Avg')
                event['trend'] = text_or(airport_el, 'Trend')
            elif type_code in ('depart_delay', 'arrive_delay', 'arrive_depart_delay'):
                event['min_time'] = text_or(airport_el, 'Min')
                event['max_time'] = text_or(airport_el, 'Max')
                event['trend'] = text_or(airport_el, 'Trend')
            elif type_code == 'deicing':
                event['avg_time'] = text_or(airport_el, 'Avg')
                event['min_time'] = text_or(airport_el, 'Min')
                event['max_time'] = text_or(airport_el, 'Max')

            events_by_airport.setdefault(iata, []).append(event)

    # Airport_Closures (separate section)
    closures_root = root.find('Airport_Closures')
    if closures_root is not None:
        for airport_el in closures_root.findall('.//Airport'):
            iata = text_or(airport_el, 'ARPT').upper()
            if not iata:
                continue

            reason = text_or(airport_el, 'Reason')
            event = {
                'tipo': 'closure',
                'tipo_es': 'Cierre',
                'reason': reason,
                'reason_es': translate_reason(reason),
                'begin_time': text_or(airport_el, 'Start'),
                'end_time': text_or(airport_el, 'Reopen'),
            }
            events_by_airport.setdefault(iata, []).append(event)

    return update_time, events_by_airport


def build_affected_list(events_by_airport):
    priority = {
        'ground_stop': 0,
        'closure': 1,
        'ground_delay': 2,
        'arrive_depart_delay': 3,
        'depart_delay': 4,
        'arrive_delay': 5,
        'deicing': 6,
    }

    affected = []
    for iata, events in events_by_airport.items():
        if not events:
            continue
        events.sort(key=lambda e: priority.get(e['tipo'], 99))
        main = events[0]

        name, city, state = get_airport_info(iata)
        affected.append({
            'iata': iata,
            'icao': f'K{iata}' if len(iata) == 3 else iata,
            'name': name,
            'name_es': name,
            'city': city,
            'state': state,
            'main_event': main['tipo'],
            'main_event_es': main['tipo_es'],
            'events': events,
        })

    affected.sort(key=lambda a: priority.get(a['main_event'], 99))
    return affected


def upload_to_cdn(data):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        tmp_path = f.name

    cmd = [
        'aws', 's3', 'cp', tmp_path,
        f's3://{CDN_BUCKET}/{OUTPUT_KEY}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=60',
        '--endpoint-url', CDN_ENDPOINT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    Path(tmp_path).unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"❌ CDN upload failed:\n{result.stderr}")
        return False
    print(f"✅ Uploaded to {CDN_BUCKET}/{OUTPUT_KEY}")
    return True


def main():
    start = time.time()
    print(f"🛫 FAA Airport Status Pipeline — {datetime.now(timezone.utc).isoformat()}")
    print(f"   Fetching {FAA_XML_ENDPOINT}")

    try:
        xml_bytes = fetch_xml()
    except Exception as e:
        print(f"❌ Failed to fetch FAA feed: {e}")
        return 1

    try:
        update_time, events_by_airport = parse_xml(xml_bytes)
    except ET.ParseError as e:
        print(f"❌ XML parse error: {e}")
        # Debug: print first 500 chars
        try:
            print(f"   First bytes: {xml_bytes[:500]}")
        except Exception:
            pass
        return 1
    except Exception as e:
        print(f"❌ Failed to parse feed: {e}")
        return 1

    affected = build_affected_list(events_by_airport)

    counts = {
        'ground_stop': 0, 'closure': 0, 'ground_delay': 0,
        'arrive_depart_delay': 0, 'depart_delay': 0, 'arrive_delay': 0, 'deicing': 0
    }
    for a in affected:
        counts[a['main_event']] = counts.get(a['main_event'], 0) + 1

    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'faa_update_time': update_time,
        'total_affected': len(affected),
        'counts': counts,
        'airports': affected,
    }

    print(f"\n📊 Summary:")
    print(f"   FAA update time: {update_time}")
    print(f"   Total affected airports: {len(affected)}")
    for code, n in counts.items():
        if n > 0:
            print(f"   • {type_code_to_es(code)}: {n}")

    if affected:
        print(f"\n⚠️  Top affected airports:")
        for a in affected[:10]:
            evt = a['events'][0]
            detail = evt.get('reason_es', '')
            name_str = a['name_es'][:30]
            print(f"   {a['iata']:<4} {name_str:<32} · {a['main_event_es']}"
                  f"{' · ' + detail if detail else ''}")

    upload_to_cdn(output)

    elapsed = time.time() - start
    print(f"\n✓ Done in {elapsed:.1f}s")
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
