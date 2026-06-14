#!/usr/bin/env python3
"""
===============================================================================
CANAL METEO TV — Records Diarios (Batidos)
===============================================================================
Pipeline horario que detecta records de temperatura (máx/mín), precipitación
y nieve batidos HOY en estaciones ThreadEx, genera PNGs broadcast-style
para redes sociales (nacional + por metro) y envía email si hay records nuevos.

Ubicación:  /opt/canalmeteo/scripts/records_daily_pipeline.py
Venv:       /opt/canalmeteo/venv/
Datos:      /opt/canalmeteo/data/records_daily/
CDN:        canalmeteo-public.sfo3.digitaloceanspaces.com/lynx/records_daily/

Cron:
    # Cada hora — records diarios batidos
    15 * * * * flock -n /tmp/records_daily.lock /opt/canalmeteo/venv/bin/python \\
               /opt/canalmeteo/scripts/records_daily_pipeline.py \\
               >> /var/log/canalmeteo/records_daily.log 2>&1

Uso manual:
    python records_daily_pipeline.py            # Ejecución normal
    python records_daily_pipeline.py --dry-run  # Sin subir ni enviar email
    python records_daily_pipeline.py --force-email  # Forzar envío
    python records_daily_pipeline.py --date 2026-04-15  # Fecha específica
===============================================================================
"""

import os
import sys
import json
import argparse
import logging
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from zoneinfo import ZoneInfo

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR    = Path('/opt/canalmeteo/data/records_daily')
OUTPUT_DIR  = BASE_DIR / 'output'
STATE_FILE  = BASE_DIR / 'state.json'
LOG_DIR     = Path('/var/log/canalmeteo')

# CDN DigitalOcean Spaces
CDN_PROFILE  = 'do-tor1'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
CDN_BUCKET   = 'canalmeteo-public'
CDN_PREFIX   = 'lynx/records_daily'
CDN_BASE_URL = f'https://{CDN_BUCKET}.sfo3.digitaloceanspaces.com/{CDN_PREFIX}'

# ACIS
ACIS_BASE = 'https://data.rcc-acis.org'
ACIS_STNDATA = f'{ACIS_BASE}/StnData'

# Zonas horarias
TZ_ET = ZoneInfo('America/New_York')
TZ_UTC = timezone.utc

# Logger
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('records_daily')

# ═══════════════════════════════════════════════════════════════════════════
# ÁREAS METRO — Las 10 principales del público Hispano US
# ═══════════════════════════════════════════════════════════════════════════
# Cada metro define: nombre en español, bbox [lon_min, lat_min, lon_max, lat_max]
# y lista de estaciones prioritarias para display

METROS = {
    'nyc': {
        'name': 'Nueva York',
        'name_en': 'New York',
        'stations': ['NYC', 'LGA', 'JFK', 'ISP', 'EWR', 'BDR', 'HPN'],
    },
    'la': {
        'name': 'Los Ángeles',
        'name_en': 'Los Angeles',
        'stations': ['LAX', 'BUR', 'LGB', 'SNA', 'ONT', 'RIV', 'SBD'],
    },
    'miami': {
        'name': 'Miami',
        'name_en': 'Miami',
        'stations': ['MIA', 'FLL', 'PBI', 'APF', 'HWO'],
    },
    'chicago': {
        'name': 'Chicago',
        'name_en': 'Chicago',
        'stations': ['ORD', 'MDW', 'RFD', 'MKE', 'GYY'],
    },
    'houston': {
        'name': 'Houston',
        'name_en': 'Houston',
        'stations': ['IAH', 'HOU', 'GLS', 'CLL', 'BPT'],
    },
    'dallas': {
        'name': 'Dallas-Fort Worth',
        'name_en': 'Dallas-Fort Worth',
        'stations': ['DFW', 'DAL', 'FTW', 'ADS', 'GKY'],
    },
    'phoenix': {
        'name': 'Phoenix',
        'name_en': 'Phoenix',
        'stations': ['PHX', 'SDL', 'DVT', 'GYR', 'IWA'],
    },
    'dc': {
        'name': 'Washington DC',
        'name_en': 'Washington DC',
        'stations': ['DCA', 'IAD', 'BWI', 'ADW', 'MTN'],
    },
    'atlanta': {
        'name': 'Atlanta',
        'name_en': 'Atlanta',
        'stations': ['ATL', 'FTY', 'PDK', 'RYY', 'LZU'],
    },
    'boston': {
        'name': 'Boston',
        'name_en': 'Boston',
        'stations': ['BOS', 'BED', 'OWD', 'ORH', 'PVD'],
    },
}

# Nombres amigables para estaciones (display en PNG)
STATION_DISPLAY = {
    'NYC': 'Central Park',      'LGA': 'LaGuardia',       'JFK': 'JFK',
    'ISP': 'Islip, NY',         'EWR': 'Newark, NJ',      'BDR': 'Bridgeport, CT',
    'HPN': 'White Plains',      'LAX': 'LAX',             'BUR': 'Burbank',
    'LGB': 'Long Beach',        'SNA': 'Santa Ana',       'ONT': 'Ontario',
    'RIV': 'Riverside',         'SBD': 'San Bernardino',  'MIA': 'Miami',
    'FLL': 'Fort Lauderdale',   'PBI': 'Palm Beach',      'APF': 'Naples',
    'HWO': 'Hollywood, FL',     'ORD': "O'Hare",          'MDW': 'Midway',
    'RFD': 'Rockford',          'MKE': 'Milwaukee',       'GYY': 'Gary',
    'IAH': 'Houston (IAH)',     'HOU': 'Houston (Hobby)', 'GLS': 'Galveston',
    'CLL': 'College Station',   'BPT': 'Beaumont',        'DFW': 'DFW',
    'DAL': 'Dallas Love',       'FTW': 'Fort Worth',      'ADS': 'Addison',
    'GKY': 'Arlington',         'PHX': 'Phoenix Sky Harbor', 'SDL': 'Scottsdale',
    'DVT': 'Deer Valley',       'GYR': 'Goodyear',        'IWA': 'Mesa',
    'DCA': 'Reagan National',   'IAD': 'Dulles',          'BWI': 'Baltimore',
    'ADW': 'Andrews AFB',       'MTN': 'Martin State',    'ATL': 'Atlanta Hartsfield',
    'FTY': 'Fulton County',     'PDK': 'DeKalb-Peachtree', 'RYY': 'Kennesaw',
    'LZU': 'Lawrenceville',     'BOS': 'Boston Logan',    'BED': 'Hanscom',
    'OWD': 'Norwood',           'ORH': 'Worcester',       'PVD': 'Providence',
}


# ═══════════════════════════════════════════════════════════════════════════
# CONSULTA ACIS
# ═══════════════════════════════════════════════════════════════════════════

def build_threadex_sids() -> list:
    """Lista los ThreadEx SIDs de las estaciones de los metros (para fallback)."""
    sids = set()
    for metro in METROS.values():
        for s in metro['stations']:
            sids.add(f'{s}thr')
    return sorted(sids)


def fetch_records_for_date(target_date: datetime) -> list:
    """
    Consulta ACIS para obtener observados + records del día.
    Dos fases:
      1) MultiStnData con network=9 (ThreadEx) + bbox CONUS → observados del día
      2) Para cada estación con datos, StnData con smry → record del día del año
    Devuelve lista de dicts con datos observados y records climatológicos.
    """
    date_str = target_date.strftime('%Y-%m-%d')
    mmdd = target_date.strftime('%m-%d')

    # ── Fase 1: Observados del día para TODAS las ThreadEx CONUS ──
    log.info(f'Fase 1: Consultando observados {date_str} (ThreadEx CONUS)...')
    observed_stations = fetch_observed_national(date_str)
    log.info(f'  Estaciones con observados: {len(observed_stations)}')

    if not observed_stations:
        log.warning('Sin observados disponibles.')
        return []

    # ── Fase 2: Records climatológicos para estaciones con datos ──
    # Solo consultamos las que tienen observados (ahorra API calls)
    sids_with_data = list(observed_stations.keys())
    log.info(f'Fase 2: Consultando records climatológicos para {len(sids_with_data)} estaciones...')
    records = fetch_climate_records_batch(sids_with_data, target_date)

    # ── Fase 3: Combinar y evaluar ──
    results = []
    for sid, obs in observed_stations.items():
        code = sid.replace('thr', '')
        metro_id = find_metro_for_station(code)
        rec = records.get(sid, {})

        # Nombre display
        display = obs.get('name', STATION_DISPLAY.get(code, code))
        # Limpiar nombre ThreadEx (suelen terminar en ", XX" con el estado)
        if ',' in display:
            parts = display.rsplit(',', 1)
            city = parts[0].strip().title()
            state = parts[1].strip().upper() if len(parts) > 1 else ''
            display = f'{city}, {state}' if state else city

        entry = {
            'station':  code,
            'display':  STATION_DISPLAY.get(code, display),
            'metro_id': metro_id,
            'state':    obs.get('state', ''),
            'lat':      obs.get('lat'),
            'lon':      obs.get('lon'),
            # Temperatura máxima
            'maxt_obs': obs.get('maxt'),
            'maxt_rec': rec.get('maxt_rec'),
            'maxt_rec_year': rec.get('maxt_rec_year'),
            # Temperatura mínima
            'mint_obs': obs.get('mint'),
            'mint_rec': rec.get('mint_rec'),
            'mint_rec_year': rec.get('mint_rec_year'),
            # Precipitación (pulgadas)
            'pcpn_obs': obs.get('pcpn'),
            'pcpn_rec': rec.get('pcpn_rec'),
            'pcpn_rec_year': rec.get('pcpn_rec_year'),
            # Nieve (pulgadas)
            'snow_obs': obs.get('snow'),
            'snow_rec': rec.get('snow_rec'),
            'snow_rec_year': rec.get('snow_rec_year'),
        }

        # Evaluar "batido"
        entry['broken_max']  = is_broken(entry['maxt_obs'], entry['maxt_rec'], direction='above')
        entry['broken_min']  = is_broken(entry['mint_obs'], entry['mint_rec'], direction='below')
        entry['broken_pcpn'] = is_broken(entry['pcpn_obs'], entry['pcpn_rec'], direction='above', min_value=0.01)
        entry['broken_snow'] = is_broken(entry['snow_obs'], entry['snow_rec'], direction='above', min_value=0.1)

        results.append(entry)

    return results


def fetch_observed_national(date_str: str) -> dict:
    """
    Consulta observados del día para estaciones ThreadEx.
    Usa StnData individual en paralelo (ThreadEx SIDs como BHMthr solo
    funcionan con StnData, NO con MultiStnData).
    """
    sids = build_all_threadex_sids()
    log.info(f'  Consultando {len(sids)} estaciones en paralelo (8 workers)...')

    out = {}
    workers = min(8, len(sids))

    def fetch_one_observed(sid):
        """Consulta observado del día para una estación."""
        params = {
            'sid': sid,
            'sdate': date_str,
            'edate': date_str,
            'elems': [
                {'name': 'maxt'},
                {'name': 'mint'},
                {'name': 'pcpn'},
                {'name': 'snow'},
            ],
            'meta': 'name,state,ll'
        }
        try:
            r = requests.post(ACIS_STNDATA,
                              json=params, timeout=20)
            if not r.ok:
                return None
            data = r.json()
            if 'error' in data:
                return None
            meta = data.get('meta', {})
            rows = data.get('data', [])
            if not rows:
                return None
            row = rows[0]  # Solo un día
            maxt = parse_val(row[1])
            mint = parse_val(row[2])
            if maxt is None and mint is None:
                return None
            ll = meta.get('ll', [])
            return {
                'sid': sid,
                'maxt': maxt,
                'mint': mint,
                'pcpn': parse_val(row[3]),
                'snow': parse_val(row[4]) if len(row) > 4 else None,
                'name': meta.get('name', sid),
                'state': meta.get('state', ''),
                'lat': ll[1] if len(ll) >= 2 else None,
                'lon': ll[0] if len(ll) >= 2 else None,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_one_observed, sid): sid for sid in sids}
        done = 0
        for fut in as_completed(futs):
            sid = futs[fut]
            done += 1
            try:
                result = fut.result()
                if result:
                    out[result['sid']] = result
            except Exception:
                pass
            if done % 40 == 0:
                log.info(f'  ... {done}/{len(sids)} consultadas, {len(out)} con datos')

    log.info(f'  Total: {len(out)}/{len(sids)} estaciones con observados')
    return out


def build_all_threadex_sids() -> list:
    """
    Construye la lista completa de ~428 ThreadEx SIDs.
    
    Estrategia (en orden):
    1. Descubrir dinámicamente vía ACIS StnMeta (network=9) — 1 llamada rápida
    2. Importar de records_spc.py o first_100f.py del droplet
    3. Fallback: lista hardcodeada completa
    """
    # ── 1) Descubrir dinámicamente ──
    try:
        r = requests.post(f'{ACIS_BASE}/StnMeta', json={
            'meta': 'name,state,sids,ll',
            'network': '9',
        }, timeout=30)
        if r.ok:
            data = r.json()
            sids = []
            for stn in data.get('meta', []):
                for s in stn.get('sids', []):
                    if s.endswith(' 9'):
                        sid = s.split(' ')[0]
                        sids.append(sid)
                        break
            if len(sids) > 100:
                log.info(f'  ThreadEx descubiertas dinámicamente via StnMeta: {len(sids)}')
                return sids
    except Exception as e:
        log.debug(f'  StnMeta falló: {e}')

    # ── 2) Importar de scripts existentes en el droplet ──
    for script_path in ['/opt/canalmeteo/scripts/records_spc.py',
                        '/opt/canalmeteo/scripts/records_potenciales.py',
                        '/opt/canalmeteo/scripts/first_100f.py']:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location('_stn', script_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, 'THREADEX_STATIONS'):
                    sids = [s[0] for s in mod.THREADEX_STATIONS]
                    if len(sids) > 100:
                        log.info(f'  ThreadEx importadas de {script_path}: {len(sids)}')
                        return sids
        except Exception:
            continue

    # ── 3) Fallback hardcodeado ──
    log.info(f'  Usando lista ThreadEx hardcodeada: {len(THREADEX_ALL_SIDS)} estaciones')
    return THREADEX_ALL_SIDS


# Lista completa de ~428 estaciones ThreadEx (fallback)
# Fuente: RCC-ACIS network=9, todas las fases ThreadEx hasta 2024
THREADEX_ALL_SIDS = [
    # ALABAMA (4)
    'BHMthr', 'HSVthr', 'MOBthr', 'MGMthr',
    # ALASKA (2)
    'ANCPAthr', 'FAIthr',
    # ARIZONA (3)
    'PHXthr', 'TUSthr', 'FLGthr',
    # ARKANSAS (2)
    'LITthr', 'FSMthr',
    # CALIFORNIA (8)
    'LAXthr', 'SFOthr', 'SACthr', 'SANthr', 'BFLthr', 'FATthr', 'RDDthr', 'SBPthr',
    # COLORADO (4)
    'DENthr', 'COSthr', 'PUBthr', 'GJTthr',
    # CONNECTICUT (2)
    'BDLthr', 'BDRthr',
    # DELAWARE (1)
    'ILGthr',
    # DC (1)
    'DCAthr',
    # FLORIDA (7)
    'JAXthr', 'MIAthr', 'TBWthr', 'MCOthr', 'TLHthr', 'PNSthr', 'EYWthr',
    # GEORGIA (5)
    'ATLthr', 'SAVthr', 'CSGthr', 'AGSthr', 'MCNthr',
    # HAWAII (2)
    'HNLthr', 'ITOthr',
    # IDAHO (4)
    'BOIthr', 'TWFthr', 'PIHthr', 'LWSthr',
    # ILLINOIS (8)
    'ORDthr', 'SPIthr', 'PIAthr', 'MLIthr', 'RFDthr', 'BMIthr', 'DECthr', 'CMIthr',
    # INDIANA (5)
    'INDthr', 'FWAthr', 'EVVthr', 'SBNthr', 'LAFthr',
    # IOWA (6)
    'DSMthr', 'CIDthr', 'DBQthr', 'SUXthr', 'ALOthr', 'MCWthr',
    # KANSAS (6)
    'ICTthr', 'TOPthr', 'DDCthr', 'GCKthr', 'MHKthr', 'SLNthr',
    # KENTUCKY (6)
    'SDFthr', 'LEXthr', 'CVGthr', 'PAHthr', 'BWGthr', 'JSTthr',
    # LOUISIANA (5)
    'MSYthr', 'BTRthr', 'SHVthr', 'LFTthr', 'LCHthr',
    # MAINE (4)
    'PWMthr', 'BHBthr', 'BGRthr', 'CARthr',
    # MARYLAND (2)
    'BWIthr', 'SBYthr',
    # MASSACHUSETTS (4)
    'BOSthr', 'ORHthr', 'BEDthr', 'ACKthr',
    # MICHIGAN (8)
    'DTWthr', 'GRRthr', 'MBSthr', 'TVCthr', 'LNSthr', 'HTLthr', 'FNTthr', 'MKGthr',
    # MINNESOTA (7)
    'MSPthr', 'DLHthr', 'INLthr', 'RSTthr', 'STCthr', 'BJIthr', 'FGFthr',
    # MISSISSIPPI (4)
    'JACKthr', 'GPTthr', 'MEIthr', 'GTRthr',
    # MISSOURI (5)
    'STLthr', 'MCIthr', 'SGFthr', 'COuthr', 'JLNthr',
    # MONTANA (6)
    'GTFthr', 'BILthr', 'HLNthr', 'MSOthr', 'GGWthr', 'MLSthr',
    # NEBRASKA (5)
    'OMAthr', 'LNKthr', 'GRIthr', 'NSTthr', 'LBFthr',
    # NEVADA (4)
    'LASVthr', 'RNOthr', 'ELYthr', 'EKOthr',
    # NEW HAMPSHIRE (2)
    'CONthr', 'MHTthr',
    # NEW JERSEY (3)
    'EWRthr', 'ACYthr', 'TTNthr',
    # NEW MEXICO (3)
    'ABQthr', 'ROWthr', 'LRUthr',
    # NEW YORK (10)
    'NYCthr', 'LGAthr', 'JFKthr', 'BUFthr', 'ALBthr', 'SYRthr', 'ROCthr',
    'BGMthr', 'ISPthr', 'HFDthr',
    # NORTH CAROLINA (7)
    'CLTthr', 'RDUthr', 'GSOthr', 'ILMthr', 'AVLthr', 'FAYthr', 'HSEthr',
    # NORTH DAKOTA (5)
    'FARthr', 'BISthr', 'ISNthr', 'MOTthr', 'DVLthr',
    # OHIO (7)
    'CMHthr', 'CLEthr', 'DAYthr', 'TOLthr', 'CAKthr', 'YNGthr', 'MANthr',
    # OKLAHOMA (4)
    'OKCthr', 'TULthr', 'GAGthr', 'LAWthr',
    # OREGON (5)
    'PDXthr', 'EUGthr', 'MFRthr', 'RDMthr', 'PNDthr',
    # PENNSYLVANIA (8)
    'PHLthr', 'PITthr', 'ABEthr', 'ERIthr', 'AVPthr', 'IPTthr', 'MDTthr', 'UNVthr',
    # PUERTO RICO (2)
    'SJUthr', 'BQNthr',
    # RHODE ISLAND (1)
    'PVDthr',
    # SOUTH CAROLINA (4)
    'CAEthr', 'CHSthr', 'GSPthr', 'FLOthr',
    # SOUTH DAKOTA (5)
    'FSDthr', 'RAPthr', 'ABRthr', 'PIRthr', 'HONthr',
    # TENNESSEE (5)
    'BNAthr', 'MEMthr', 'TYSthr', 'CHAthr', 'TRIthr',
    # TEXAS (16)
    'DFWthr', 'IAHthr', 'HOUthr', 'SATthr', 'AUSthr', 'ELPthr',
    'LBBthr', 'MAFthr', 'ABIthr', 'CRPthr', 'BROthr', 'AMAthr',
    'ACTthr', 'SJTthr', 'GGGthr', 'VCTthr',
    # UTAH (3)
    'SLCthr', 'SGUthr', 'CNYthr',
    # VERMONT (1)
    'BTVthr',
    # VIRGINIA (5)
    'RICthr', 'ORFthr', 'ROAthr', 'IADthr', 'LYHthr',
    # WASHINGTON (4)
    'SEAthr', 'GEGthr', 'ALWthr', 'OLMthr',
    # WEST VIRGINIA (9)
    'CRWthr', 'EKNthr', 'HTSthr', 'HLGthr', 'MGWthr', 'PKBthr',
    'BLFthr', 'CKBthr', 'MRBthr',
    # WISCONSIN (9)
    'GRBthr', 'LSEthr', 'MSNthr', 'MKEthr', 'ASHthr', 'EAUthr',
    'HYRthr', 'AUWthr', 'RHIthr',
    # WYOMING (4)
    'CASPthr', 'CYSthr', 'LNDthr', 'SHRthr',
    # PACIFIC ISLANDS (10)
    'PPGthr', 'YAPthr', 'PNIthr', 'TKKthr', 'GUMthr',
    'MAJthr', 'KWAthr', 'GSNthr', 'RORthr', 'AWKthr',
    # VIRGIN ISLANDS (1)
    'STTthr',
]


def fetch_climate_records_batch(sids: list, target_date: datetime) -> dict:
    """
    Consulta records climatológicos día-del-año para cada estación en paralelo.
    Usa 10 workers para mantener la velocidad sin saturar ACIS.
    """
    out = {}
    # Limitar workers a 8 para no saturar ACIS
    workers = min(8, len(sids))
    if workers == 0:
        return out

    log.info(f'  Lanzando {workers} workers para {len(sids)} estaciones...')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_climate_record_one, sid, target_date): sid for sid in sids}
        done = 0
        for fut in as_completed(futs):
            sid = futs[fut]
            done += 1
            try:
                result = fut.result()
                if result:
                    out[sid] = result
            except Exception as e:
                log.warning(f'  Record {sid}: {e}')
            if done % 50 == 0:
                log.info(f'  ... {done}/{len(sids)} estaciones procesadas')
    log.info(f'  Records climatológicos obtenidos: {len(out)}/{len(sids)}')
    return out


def fetch_climate_record_one(sid: str, target_date: datetime) -> dict:
    """
    Obtiene los valores récord día-del-año para una estación.

    Estrategia: consultar SOLO los datos de ese día-del-año (mm-dd) a lo largo
    de todo el período de registro, y calcular extremos localmente.
    Esto es más rápido que descargar TODO el POR ya que ACIS devuelve solo ~130 filas.
    """
    mmdd = target_date.strftime('%m-%d')
    year = target_date.year

    # Usar un rango de ~150 años (más que suficiente para cualquier ThreadEx)
    # con sdate/edate en formato 'YYYY-MM-DD' donde MM-DD = target day
    # Para obtener solo ese día de cada año, usamos duración annual
    params = {
        'sid': sid,
        'sdate': '1850-01-01',
        'edate': f'{year - 1}-12-31',
        'elems': [
            {'name': 'maxt'},
            {'name': 'mint'},
            {'name': 'pcpn'},
            {'name': 'snow'},
        ]
    }

    try:
        r = requests.post(ACIS_STNDATA, json=params, timeout=90)
        if not r.ok:
            return None
        data = r.json()
        if 'error' in data:
            return None

        # Filtrar para el día específico del año
        max_vals, min_vals, pcp_vals, snw_vals = [], [], [], []
        for row in data.get('data', []):
            date_s = row[0]
            if date_s[5:10] != mmdd:
                continue
            year_s = date_s[:4]
            mx = parse_val(row[1])
            mn = parse_val(row[2])
            pc = parse_val(row[3])
            sn = parse_val(row[4]) if len(row) > 4 else None
            if mx is not None:
                max_vals.append((mx, year_s))
            if mn is not None:
                min_vals.append((mn, year_s))
            if pc is not None:
                pcp_vals.append((pc, year_s))
            if sn is not None:
                snw_vals.append((sn, year_s))

        mx_v, mx_y = (max(max_vals, key=lambda x: x[0]) if max_vals else (None, None))
        mn_v, mn_y = (min(min_vals, key=lambda x: x[0]) if min_vals else (None, None))
        pc_v, pc_y = (max(pcp_vals, key=lambda x: x[0]) if pcp_vals else (None, None))
        sn_v, sn_y = (max(snw_vals, key=lambda x: x[0]) if snw_vals else (None, None))

        return {
            'maxt_rec': mx_v, 'maxt_rec_year': mx_y,
            'mint_rec': mn_v, 'mint_rec_year': mn_y,
            'pcpn_rec': pc_v, 'pcpn_rec_year': pc_y,
            'snow_rec': sn_v, 'snow_rec_year': sn_y,
        }
    except requests.exceptions.Timeout:
        log.warning(f'  Timeout para {sid}')
        return None
    except Exception as e:
        return None


def parse_val(v):
    """Parsea un valor de ACIS ('M', 'T', float string, etc)."""
    if v in ('M', 'T', '', None):
        return 0.01 if v == 'T' else None  # Trace → 0.01
    try:
        return float(v)
    except Exception:
        return None


def is_broken(obs, rec, direction='above', min_value=None) -> bool:
    """¿El observado ha batido el récord?"""
    if obs is None or rec is None:
        return False
    if min_value is not None and obs < min_value:
        return False
    if direction == 'above':
        return obs > rec
    return obs < rec


def find_metro_for_station(code: str) -> str | None:
    for mid, m in METROS.items():
        if code in m['stations']:
            return mid
    return None


# ═══════════════════════════════════════════════════════════════════════════
# ESTADO (records ya notificados)
# ═══════════════════════════════════════════════════════════════════════════

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {'date': '', 'notified': []}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {'date': '', 'notified': []}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_id(entry: dict, kind: str) -> str:
    """ID único para tracking de un récord (estación + fecha + tipo)."""
    return f'{entry["station"]}_{kind}'


def detect_new_records(results: list, state: dict, target_date_str: str) -> tuple[list, list]:
    """
    Devuelve (nuevos_records, todos_los_records_batidos_hoy).
    Si la fecha cambió, reinicia el estado.
    """
    if state.get('date') != target_date_str:
        state['date'] = target_date_str
        state['notified'] = []

    already = set(state.get('notified', []))
    new_records = []
    all_broken = []

    for e in results:
        for kind, key in [('max', 'broken_max'), ('min', 'broken_min'),
                          ('pcpn', 'broken_pcpn'), ('snow', 'broken_snow')]:
            if e.get(key):
                rid = record_id(e, kind)
                all_broken.append({'entry': e, 'kind': kind, 'rid': rid})
                if rid not in already:
                    new_records.append({'entry': e, 'kind': kind, 'rid': rid})

    return new_records, all_broken


# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# RENDERIZADO PNG — BROADCAST STYLE
# ═══════════════════════════════════════════════════════════════════════════

# Fondos temáticos por tipo de record
THEMES = {
    'max': {
        'name': 'MÁXIMAS BATIDAS',
        'grad_top':    (140, 20, 10),
        'grad_mid':    (180, 60, 20),
        'grad_bottom': (40, 8, 8),
        'accent':      '#FF4136',
        'glow':        (255, 80, 40, 25),
        'row_bg':      (60, 15, 12, 160),
    },
    'min': {
        'name': 'MÍNIMAS BATIDAS',
        'grad_top':    (10, 40, 100),
        'grad_mid':    (20, 80, 160),
        'grad_bottom': (5, 12, 35),
        'accent':      '#4FC3F7',
        'glow':        (60, 160, 255, 25),
        'row_bg':      (10, 25, 55, 160),
    },
    'pcpn': {
        'name': 'LLUVIA RÉCORD',
        'grad_top':    (8, 60, 60),
        'grad_mid':    (15, 100, 80),
        'grad_bottom': (5, 20, 25),
        'accent':      '#26A69A',
        'glow':        (40, 180, 160, 20),
        'row_bg':      (10, 35, 35, 160),
    },
    'snow': {
        'name': 'NIEVE RÉCORD',
        'grad_top':    (50, 30, 80),
        'grad_mid':    (90, 50, 140),
        'grad_bottom': (15, 10, 30),
        'accent':      '#CE93D8',
        'glow':        (180, 100, 220, 20),
        'row_bg':      (30, 15, 45, 160),
    },
    'metro': {
        'name': '',
        'grad_top':    (20, 45, 65),
        'grad_mid':    (35, 65, 90),
        'grad_bottom': (10, 18, 28),
        'accent':      '#F39C12',
        'glow':        (243, 156, 18, 15),
        'row_bg':      (15, 30, 45, 160),
    },
}

# Formatos de salida
FORMATS = {
    'feed':  (1080, 1350),
    'story': (1080, 1920),
}

# Logo
LOGO_SEARCH_PATHS = [
    '/home/claude/records_daily/assets/logo-canalmeteo-30.png',
    '/opt/canalmeteo/assets/logo-canalmeteo-30.png',
    '/opt/canalmeteo/assets/Canal_Meteo_Flat_30.png',
]

_logo_cache = None


def load_logo(height=55):
    """Carga y cachea el logo de Canal Meteo. Lo descarga del CDN si no existe localmente."""
    global _logo_cache
    if _logo_cache is not None:
        return _logo_cache
    from PIL import Image as PILImage

    # Intentar cargar de rutas locales
    for p in LOGO_SEARCH_PATHS:
        try:
            img = PILImage.open(p).convert('RGBA')
            aspect = img.width / img.height
            img = img.resize((int(height * aspect), height), PILImage.LANCZOS)
            _logo_cache = img
            return img
        except Exception:
            continue

    # Auto-descargar si no existe
    logo_url = 'https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png'
    dl_path = Path('/opt/canalmeteo/assets/logo-canalmeteo-30.png')
    try:
        dl_path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(logo_url, timeout=15)
        if r.ok:
            dl_path.write_bytes(r.content)
            img = PILImage.open(dl_path).convert('RGBA')
            aspect = img.width / img.height
            img = img.resize((int(height * aspect), height), PILImage.LANCZOS)
            _logo_cache = img
            log.info(f'Logo descargado de {logo_url}')
            return img
    except Exception as e:
        log.warning(f'No se pudo descargar logo: {e}')

    _logo_cache = False
    return False


def render_all_pngs(all_broken: list, target_date: datetime) -> dict:
    """Genera todos los PNGs en ambos formatos (feed 1080x1350 + story 1080x1920)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = {}
    subtitle = format_date_es(target_date)

    # ── Nacionales (separados por tipo) ──
    for kind in ('max', 'min', 'pcpn', 'snow'):
        rows = [b for b in all_broken if b['kind'] == kind]
        if not rows:
            continue
        rows.sort(key=lambda b: record_margin(b), reverse=True)
        rows = rows[:15]
        theme = THEMES[kind]
        for fmt_name, (W, H) in FORMATS.items():
            path = OUTPUT_DIR / f'records_nacional_{kind}_{fmt_name}.png'
            render_panel(rows, path, W, H, title=theme['name'],
                         subtitle=subtitle, theme=theme, kind=kind)
            generated[f'nacional_{kind}_{fmt_name}'] = path
        log.info(f'  ✅ records_nacional_{kind} (feed + story)')

    # ── Metros ──
    for mid, meta in METROS.items():
        metro_rows = [b for b in all_broken if b['entry'].get('metro_id') == mid]
        if not metro_rows:
            continue
        combined = combine_by_station(metro_rows)
        theme = THEMES['metro']
        for fmt_name, (W, H) in FORMATS.items():
            path = OUTPUT_DIR / f'records_metro_{mid}_{fmt_name}.png'
            render_panel(combined, path, W, H, title=meta['name'].upper(),
                         subtitle=subtitle, theme=theme, kind='metro')
            generated[f'metro_{mid}_{fmt_name}'] = path
        log.info(f'  ✅ records_metro_{mid} (feed + story)')

    return generated


def record_margin(b: dict) -> float:
    e, k = b['entry'], b['kind']
    if k == 'max':  return (e['maxt_obs'] or 0) - (e['maxt_rec'] or 0)
    if k == 'min':  return (e['mint_rec'] or 0) - (e['mint_obs'] or 0)
    if k == 'pcpn': return (e['pcpn_obs'] or 0) - (e['pcpn_rec'] or 0)
    if k == 'snow': return (e['snow_obs'] or 0) - (e['snow_rec'] or 0)
    return 0


def combine_by_station(rows: list) -> list:
    by_station = {}
    for b in rows:
        code = b['entry']['station']
        by_station.setdefault(code, []).append(b)
    combined = []
    for code, items in by_station.items():
        combined.append({
            'entry': items[0]['entry'],
            'kinds': [x['kind'] for x in items],
        })
    combined.sort(key=lambda c: (-len(c['kinds']), c['entry']['display']))
    return combined


def render_panel(rows, out_path: Path, W: int, H: int,
                 title: str, subtitle: str, theme: dict, kind: str):
    """Renderiza un PNG broadcast-style con fondo temático."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    gt, gm, gb = theme['grad_top'], theme['grad_mid'], theme['grad_bottom']
    accent_rgb = hex_to_rgb(theme['accent'])

    # ── Fondo: gradiente tricolor ──
    for y in range(H):
        t = y / H
        if t < 0.3:
            p = t / 0.3
            c = tuple(int(gt[i] + (gm[i] - gt[i]) * p) for i in range(3))
        else:
            p = (t - 0.3) / 0.7
            c = tuple(int(gm[i] + (gb[i] - gm[i]) * p) for i in range(3))
        draw.line([(0, y), (W, y)], fill=c + (255,))

    # ── Glow radial esquina superior-derecha ──
    glow = theme['glow']
    glow_layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    cx, cy = int(W * 0.75), 0
    max_r = int(W * 0.55)
    for radius in range(max_r, 0, -5):
        alpha = int(glow[3] * (1 - radius / max_r) ** 2)
        if alpha < 1:
            continue
        glow_draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(glow[0], glow[1], glow[2], alpha)
        )
    img = Image.alpha_composite(img, glow_layer)
    draw = ImageDraw.Draw(img)

    # ── Textura diagonal sutil ──
    texture = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    tex_draw = ImageDraw.Draw(texture)
    for i in range(-H, W + H, 28):
        tex_draw.line([(i, 0), (i + H, H)], fill=(255, 255, 255, 3), width=1)
    img = Image.alpha_composite(img, texture)
    draw = ImageDraw.Draw(img)

    # ── Franja acento superior ──
    for x in range(W):
        t = x / W
        c = tuple(int(accent_rgb[i] * (0.4 + t * 0.6)) for i in range(3))
        draw.line([(x, 0), (x, 6)], fill=c + (255,))

    # ── Fuentes ──
    def lf(name_list, size):
        for p in name_list:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    bp = ['/opt/canalmeteo/fonts/Outfit-ExtraBold.ttf',
          '/opt/canalmeteo/fonts/Outfit-Bold.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
    rp = ['/opt/canalmeteo/fonts/Outfit-Regular.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    mp = ['/opt/canalmeteo/fonts/JetBrainsMono-Bold.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf']

    f_handle = lf(rp, 22)
    f_city   = lf(bp, 28)
    f_value  = lf(mp, 40)
    f_label  = lf(bp, 16)
    f_small  = lf(rp, 15)
    f_footer = lf(rp, 18)
    f_count  = lf(bp, 72)
    f_count_lbl = lf(rp, 20)

    # ── Logo ──
    logo = load_logo(height=55)
    logo_x, logo_y = 55, 40

    if logo:
        img.paste(logo, (logo_x, logo_y), logo)
        draw = ImageDraw.Draw(img)
        text_x = logo_x + logo.width + 14
    else:
        draw.rectangle([(logo_x, logo_y), (logo_x + 6, logo_y + 36)],
                       fill=accent_rgb + (255,))
        text_x = logo_x + 20

    draw.text((text_x, logo_y + 8), '@alberteltiempo',
              fill=(255, 255, 255, 160), font=f_handle)

    # Fecha derecha
    draw.text((W - 55, logo_y + 8), subtitle,
              fill=accent_rgb + (220,), font=f_handle, anchor='rt')
    draw.text((W - 55, logo_y + 36), 'canalmeteo.tv',
              fill=(255, 255, 255, 120), font=f_handle, anchor='rt')

    # ── Título ──
    title_y = 140
    title_size = 62
    while title_size > 32:
        f_title = lf(bp, title_size)
        bbox = draw.textbbox((0, 0), title, font=f_title)
        if bbox[2] - bbox[0] <= W - 110:
            break
        title_size -= 3
    draw.text((55, title_y), title, fill=(255, 255, 255, 255), font=f_title)

    # ── Counter grande ──
    n_records = len(rows)
    pill_y = title_y + title_size + 30
    draw.text((55, pill_y), str(n_records),
              fill=accent_rgb + (255,), font=f_count)
    cnt_bbox = draw.textbbox((55, pill_y), str(n_records), font=f_count)
    pill_label = 'récords batidos hoy' if kind != 'metro' else 'estaciones con récords'
    draw.text((cnt_bbox[2] + 16, pill_y + 30), pill_label,
              fill=(255, 255, 255, 150), font=f_count_lbl)

    # ── Separador ──
    sep_y = pill_y + 95
    draw.line([(55, sep_y), (W - 55, sep_y)], fill=accent_rgb + (80,), width=2)

    # ── Filas ──
    rows_y_start = sep_y + 20
    rows_y_end = H - 75
    avail = rows_y_end - rows_y_start

    if kind == 'metro':
        _draw_metro_rows(draw, img, rows, rows_y_start, avail, W, theme, f_city, f_value, f_label, f_small)
    else:
        _draw_national_rows(draw, img, rows, rows_y_start, avail, W, kind, theme, f_city, f_value, f_label, f_small)

    # ── Footer ──
    fy = H - 50
    draw.line([(55, fy - 10), (W - 55, fy - 10)], fill=(255, 255, 255, 30), width=1)
    draw.text((55, fy), 'Fuente: RCC-ACIS · ThreadEx · NWS',
              fill=(255, 255, 255, 80), font=f_footer)
    draw.text((W - 55, fy), 'canalmeteo.tv',
              fill=(255, 255, 255, 80), font=f_footer, anchor='rs')

    img.convert('RGB').save(out_path, 'PNG', optimize=True)


def _draw_row_bg(draw, img, x1, y, x2, row_h, row_bg, accent_rgb):
    """Dibuja fondo semitransparente + borde acento para una fila."""
    from PIL import Image as PILImage
    w = x2 - x1
    overlay = PILImage.new('RGBA', (w, row_h), tuple(row_bg))
    img.paste(PILImage.alpha_composite(
        PILImage.new('RGBA', overlay.size, (0, 0, 0, 0)), overlay
    ), (x1, y), overlay)
    draw_fresh = ImageDraw_from(img)
    draw_fresh.rectangle([(x1, y), (x1 + 7, y + row_h)], fill=accent_rgb + (255,))
    return draw_fresh


def _draw_national_rows(draw, img, rows, y_start, avail, W, kind, theme,
                        f_city, f_value, f_label, f_small):
    """Filas nacionales: Ciudad | RÉCORD | BATIDO | OBSERVADO."""
    from PIL import Image as PILImage, ImageDraw
    accent_rgb = hex_to_rgb(theme['accent'])
    row_bg = theme['row_bg']
    n = len(rows)
    row_h = min(85, max(50, (avail - 30) // max(1, n) - 6))
    gap = 6

    x_city   = 75
    x_rec_v  = int(W * 0.52)
    x_status = int(W * 0.66)
    x_obs_v  = int(W * 0.88)

    # Headers
    draw.text((x_city, y_start), 'CIUDAD', fill=(255, 255, 255, 100), font=f_label)
    draw.text((x_rec_v, y_start), 'RÉCORD', fill=(255, 255, 255, 100), font=f_label, anchor='mt')
    draw.text((x_status, y_start), 'ESTADO', fill=(255, 255, 255, 100), font=f_label, anchor='mt')
    draw.text((x_obs_v, y_start), 'OBSERVADO', fill=(255, 255, 255, 100), font=f_label, anchor='mt')
    y = y_start + 28

    unit = '°F' if kind in ('max', 'min') else '"'

    for b in rows:
        if y + row_h > y_start + avail:
            break
        e = b['entry']
        obs = get_obs(e, kind)
        rec = get_rec(e, kind)
        rec_year = get_rec_year(e, kind)

        # Fondo fila semitransparente
        overlay = PILImage.new('RGBA', (W - 100, row_h), tuple(row_bg))
        img.paste(PILImage.alpha_composite(
            PILImage.new('RGBA', overlay.size, (0, 0, 0, 0)), overlay
        ), (50, y), overlay)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(50, y), (57, y + row_h)], fill=accent_rgb + (255,))

        mid_y = y + row_h // 2
        draw.text((x_city, mid_y - 16), e['display'],
                  fill=(255, 255, 255, 255), font=f_city)
        if rec_year and row_h >= 60:
            draw.text((x_city, mid_y + 12), f'Récord desde {rec_year}',
                      fill=(255, 255, 255, 70), font=f_small)

        draw.text((x_rec_v, mid_y), format_value(rec, unit),
                  fill=(200, 210, 225, 200), font=f_value, anchor='mm')
        draw.text((x_status, mid_y), 'BATIDO',
                  fill=accent_rgb + (255,), font=f_city, anchor='mm')
        draw.text((x_obs_v, mid_y), format_value(obs, unit),
                  fill=(255, 214, 10, 255), font=f_value, anchor='mm')

        y += row_h + gap


def _draw_metro_rows(draw, img, rows, y_start, avail, W, theme,
                     f_city, f_value, f_label, f_small):
    """Filas metro — combinadas por estación."""
    from PIL import Image as PILImage, ImageDraw
    accent_rgb = hex_to_rgb(theme['accent'])
    row_bg = theme['row_bg']
    n = len(rows)
    row_h = min(95, max(60, (avail - 10) // max(1, n) - 8))
    gap = 8

    label_map = {'max': 'MÁX', 'min': 'MÍN', 'pcpn': 'LLUVIA', 'snow': 'NIEVE'}
    color_map = {
        'max':  (231, 76, 60),
        'min':  (79, 195, 247),
        'pcpn': (38, 166, 154),
        'snow': (206, 147, 216),
    }

    y = y_start
    for c in rows:
        if y + row_h > y_start + avail:
            break
        e = c['entry']
        kinds = c['kinds']

        overlay = PILImage.new('RGBA', (W - 100, row_h), tuple(row_bg))
        img.paste(PILImage.alpha_composite(
            PILImage.new('RGBA', overlay.size, (0, 0, 0, 0)), overlay
        ), (50, y), overlay)
        draw = ImageDraw.Draw(img)
        draw.rectangle([(50, y), (57, y + row_h)], fill=accent_rgb + (255,))

        draw.text((75, y + 10), e['display'],
                  fill=(255, 255, 255, 255), font=f_city)

        x = 75
        chip_y = y + row_h - 28
        for k in kinds:
            obs = get_obs(e, k)
            rec = get_rec(e, k)
            u = '°F' if k in ('max', 'min') else '"'
            col = color_map[k]

            lt = f'{label_map[k]}:'
            draw.text((x, chip_y), lt, fill=col + (255,), font=f_label)
            bbox = draw.textbbox((x, chip_y), lt, font=f_label)
            x = bbox[2] + 6

            ot = format_value(obs, u)
            draw.text((x, chip_y), ot, fill=(255, 214, 10, 255), font=f_label)
            bbox = draw.textbbox((x, chip_y), ot, font=f_label)
            x = bbox[2] + 6

            rt = f'(récord {format_value(rec, u)})'
            draw.text((x, chip_y), rt, fill=(255, 255, 255, 90), font=f_small)
            bbox = draw.textbbox((x, chip_y), rt, font=f_small)
            x = bbox[2] + 18

        y += row_h + gap


def get_obs(e, kind):
    return {'max': e['maxt_obs'], 'min': e['mint_obs'],
            'pcpn': e['pcpn_obs'], 'snow': e['snow_obs']}[kind]

def get_rec(e, kind):
    return {'max': e['maxt_rec'], 'min': e['mint_rec'],
            'pcpn': e['pcpn_rec'], 'snow': e['snow_rec']}[kind]

def get_rec_year(e, kind):
    return {'max': e['maxt_rec_year'], 'min': e['mint_rec_year'],
            'pcpn': e['pcpn_rec_year'], 'snow': e['snow_rec_year']}[kind]

def format_value(v, unit):
    if v is None:
        return '—'
    if unit == '°F':
        return f'{v:.0f}°'
    return f'{v:.2f}{unit}'

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def format_date_es(d: datetime) -> str:
    meses = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
             'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE']
    return f'{d.day} DE {meses[d.month - 1]} DE {d.year}'



# ═══════════════════════════════════════════════════════════════════════════
# EMAIL
# ═══════════════════════════════════════════════════════════════════════════

def send_email(pngs: dict, new_records: list, all_broken: list, target_date: datetime):
    """Envía email con SendGrid (mismo patrón que terremoto-mag7.py)."""
    import base64
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail, Attachment, FileContent, FileName, FileType, Disposition
        )
    except ImportError:
        log.error('sendgrid no instalado. pip install sendgrid')
        return False

    api_key = os.environ.get('SENDGRID_API_KEY')
    from_email = os.environ.get('FROM_EMAIL', 'alertas@canalmeteo.tv')
    to_emails = [x.strip() for x in os.environ.get('TO_EMAILS', '').split(',') if x.strip()]

    if not api_key or not to_emails:
        log.warning('SendGrid no configurado — define SENDGRID_API_KEY y TO_EMAILS en .env_records')
        return False

    date_es = target_date.strftime('%d/%m/%Y')
    n_new = len(new_records)
    n_total = len(all_broken)

    html = build_email_html(new_records, all_broken, pngs, target_date)

    message = Mail(
        from_email=from_email,
        to_emails=to_emails,
        subject=f'🌡️ Canal Meteo — {n_new} récord(s) nuevo(s) · {date_es}',
        html_content=html
    )

    # Adjuntar PNGs (solo los feed, no duplicar con story)
    for name, path in pngs.items():
        if '_story' in name:
            continue  # Solo adjuntar feed para no sobrecargar el email
        try:
            with open(path, 'rb') as fh:
                encoded = base64.b64encode(fh.read()).decode()
            attachment = Attachment(
                FileContent(encoded),
                FileName(path.name),
                FileType('image/png'),
                Disposition('attachment')
            )
            message.attachment = attachment
        except Exception as e:
            log.warning(f'  No se pudo adjuntar {path.name}: {e}')

    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        log.info(f'  ✉️  Email enviado via SendGrid a {len(to_emails)} destinatario(s). Status: {response.status_code}')
        return True
    except Exception as e:
        log.error(f'Error enviando email SendGrid: {e}')
        return False


def build_email_html(new_records, all_broken, pngs, target_date):
    date_es = target_date.strftime('%d de %B de %Y')
    new_list_html = ''
    for r in new_records[:20]:
        e = r['entry']
        k = r['kind']
        obs = get_obs(e, k)
        rec = get_rec(e, k)
        unit = '°F' if k in ('max', 'min') else '"'
        kind_es = {'max': 'Máx.', 'min': 'Mín.', 'pcpn': 'Lluvia', 'snow': 'Nieve'}[k]
        new_list_html += f'''
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e0e4ec">{e["display"]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e0e4ec;color:#457a99"><b>{kind_es}</b></td>
          <td style="padding:8px 12px;border-bottom:1px solid #e0e4ec"><b>{format_value(obs, unit)}</b></td>
          <td style="padding:8px 12px;border-bottom:1px solid #e0e4ec;color:#7d8597">récord anterior: {format_value(rec, unit)}</td>
        </tr>
        '''

    files_list = ''.join(f'<li>{p.name}</li>' for p in pngs.values())

    return f'''
    <!DOCTYPE html>
    <html>
    <body style="margin:0;padding:0;background:#f4f6fa;font-family:-apple-system,system-ui,sans-serif">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fa;padding:24px 0">
        <tr><td align="center">
          <table width="640" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden">
            <tr><td style="background:linear-gradient(135deg,#457a99,#22445b);padding:32px 40px;color:#fff">
              <div style="font-size:12px;letter-spacing:1.5px;opacity:0.8">CANAL METEO TV</div>
              <h1 style="margin:8px 0 4px;font-size:26px">Récords batidos · {date_es}</h1>
              <div style="opacity:0.85">{len(new_records)} récord(s) nuevo(s) · {len(all_broken)} total hoy</div>
            </td></tr>
            <tr><td style="padding:24px 40px">
              <h3 style="margin:0 0 12px;color:#22445b">📸 Imágenes generadas</h3>
              <ul style="color:#546680">{files_list}</ul>
              <p style="color:#546680;font-size:14px">Las imágenes están adjuntas a este correo. También disponibles en el CDN: <br>
              <code style="background:#f4f6fa;padding:4px 8px;border-radius:4px;font-size:12px">{CDN_BASE_URL}/</code></p>
            </td></tr>
            <tr><td style="padding:0 40px 24px">
              <h3 style="margin:0 0 12px;color:#22445b">🆕 Récords nuevos esta hora</h3>
              <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;border-collapse:collapse">
                {new_list_html}
              </table>
            </td></tr>
            <tr><td style="background:#f4f6fa;padding:16px 40px;color:#7d8597;font-size:12px;text-align:center">
              Canal Meteo TV · Pipeline automatizado · canalmeteo.tv
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    '''


# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD CDN
# ═══════════════════════════════════════════════════════════════════════════

def upload_to_cdn(pngs: dict, json_summary: dict, target_date: datetime):
    """Sube PNGs y JSON resumen a DO Spaces."""
    date_str = target_date.strftime('%Y-%m-%d')
    # Subir PNGs
    for name, path in pngs.items():
        key = f'{CDN_PREFIX}/{date_str}/{path.name}'
        # También el latest
        key_latest = f'{CDN_PREFIX}/latest/{path.name}'
        for k in [key, key_latest]:
            cmd = ['aws', 's3', 'cp', str(path), f's3://{CDN_BUCKET}/{k}',
                   '--profile', CDN_PROFILE, '--acl', 'public-read',
                   '--content-type', 'image/png', '--endpoint-url', CDN_ENDPOINT,
                   '--cache-control', 'max-age=300']
            subprocess.run(cmd, check=False, capture_output=True)

    # JSON resumen
    json_path = OUTPUT_DIR / 'records_daily.json'
    json_path.write_text(json.dumps(json_summary, indent=2, default=str))
    for k in [f'{CDN_PREFIX}/{date_str}/records_daily.json',
              f'{CDN_PREFIX}/latest/records_daily.json']:
        subprocess.run(['aws', 's3', 'cp', str(json_path), f's3://{CDN_BUCKET}/{k}',
                        '--profile', CDN_PROFILE, '--acl', 'public-read',
                        '--content-type', 'application/json',
                        '--endpoint-url', CDN_ENDPOINT,
                        '--cache-control', 'max-age=300'],
                       check=False, capture_output=True)
    log.info(f'  ☁️  Subido al CDN: {CDN_BASE_URL}/latest/')


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true', help='No subir al CDN ni enviar email')
    p.add_argument('--force-email', action='store_true', help='Forzar envío aunque no haya records nuevos')
    p.add_argument('--date', help='Fecha YYYY-MM-DD (default: hoy ET)')
    args = p.parse_args()

    # Fecha objetivo
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').replace(tzinfo=TZ_ET)
    else:
        target_date = datetime.now(TZ_ET)
    date_str = target_date.strftime('%Y-%m-%d')

    log.info('=' * 70)
    log.info(f'Canal Meteo TV — Records Diarios · {date_str}')
    log.info('=' * 70)

    BASE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Consultar observados + records
    results = fetch_records_for_date(target_date)
    log.info(f'Estaciones procesadas: {len(results)}')

    # 2. Detectar nuevos
    state = load_state()
    new_records, all_broken = detect_new_records(results, state, date_str)
    log.info(f'Records batidos HOY: {len(all_broken)} · Nuevos esta ejecución: {len(new_records)}')

    if not all_broken:
        log.info('Sin records batidos. Termino.')
        return 0

    # 3. Generar PNGs
    log.info('Generando PNGs...')
    pngs = render_all_pngs(all_broken, target_date)
    log.info(f'PNGs generados: {len(pngs)}')

    # 4. Resumen JSON
    summary = {
        'date': date_str,
        'generated_at': datetime.now(TZ_UTC).isoformat(),
        'total_broken': len(all_broken),
        'new_this_run': len(new_records),
        'records': [
            {
                'station': b['entry']['station'],
                'display': b['entry']['display'],
                'metro_id': b['entry'].get('metro_id'),
                'kind': b['kind'],
                'obs': get_obs(b['entry'], b['kind']),
                'rec': get_rec(b['entry'], b['kind']),
                'rec_year': get_rec_year(b['entry'], b['kind']),
            }
            for b in all_broken
        ],
    }

    # 5. Upload + email
    if not args.dry_run:
        upload_to_cdn(pngs, summary, target_date)

        should_email = bool(new_records) or args.force_email
        if should_email:
            if send_email(pngs, new_records, all_broken, target_date):
                for r in new_records:
                    state['notified'].append(r['rid'])
                save_state(state)
        else:
            log.info('Sin records nuevos desde última ejecución. Email omitido.')

    log.info('✅ Completado')
    return 0


if __name__ == '__main__':
    sys.exit(main())
