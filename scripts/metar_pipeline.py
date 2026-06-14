#!/usr/bin/env python3
"""
===============================================================================
METAR / Surface Observations Pipeline — Canal Meteo TV
===============================================================================
Descarga observaciones METAR de estaciones ASOS/AWOS de EEUU vía Aviation
Weather Center (aviationweather.gov) y las procesa en un GeoJSON con campos
listos para dataplots en el radar interactivo.

Ubicación:  /opt/canalmeteo/scripts/metar_pipeline.py
Entorno:    /opt/canalmeteo/venv/
Datos:      /opt/canalmeteo/data/metar/
CDN:        canalmeteo-public.sfo3.digitaloceanspaces.com/data/metar/

Cron (cada 10 minutos):
  */10 * * * * /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/metar_pipeline.py

Dependencias:
  pip install requests --break-system-packages
===============================================================================
"""

import requests
import json
import subprocess
import logging
import sys
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

CONFIG = {
    # Aviation Weather Center — bulk METAR CSV (no API key needed)
    'awc_url': 'https://aviationweather.gov/api/data/metar',

    # NWS API for station list by state (fallback)
    'nws_stations_url': 'https://api.weather.gov/stations',

    # Rutas locales
    'data_dir': '/opt/canalmeteo/data/metar',
    'output_json': '/opt/canalmeteo/data/metar/surface_obs.geojson',
    'stations_cache': '/opt/canalmeteo/data/metar/stations.json',

    # AWS/Spaces config
    'aws_profile': 'do-tor1',
    'cdn_bucket': 'canalmeteo-public',
    'cdn_key': 'data/metar/surface_obs.geojson',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',

    # User agent
    'user_agent': 'CanalMeteoTV/1.0 (https://canalmeteo.tv)',

    # Max age for observations (minutes) — discard older than this
    'max_age_minutes': 120,
}

# States to fetch — all CONUS + PR
STATES = [
    'AL','AR','AZ','CA','CO','CT','DE','FL','GA','IA','ID','IL','IN',
    'KS','KY','LA','MA','MD','ME','MI','MN','MO','MS','MT','NC','ND',
    'NE','NH','NJ','NM','NV','NY','OH','OK','OR','PA','RI','SC','SD',
    'TN','TX','UT','VA','VT','WA','WI','WV','WY','PR','DC'
]

# Major ASOS/AWOS stations across CONUS (~850 stations)
# Covers all state capitals, major cities, and regional airports
STATIONS_LIST = [
    # Alabama
    'KBHM','KMOB','KHSV','KMGM','KDHN','KANB','KTCL','KMSL',
    # Alaska (skip - outside CONUS)
    # Arizona
    'KPHX','KTUS','KFLG','KYUM','KPRC','KSDL','KGYR','KDVT',
    # Arkansas
    'KLIT','KXNA','KFSM','KJBR','KPBF','KTXK','KHRO',
    # California
    'KLAX','KSFO','KSAN','KSJC','KOAK','KSMF','KBUR','KONT','KSNA',
    'KFAT','KBFL','KSBP','KRDD','KMRY','KPSP','KCRQ','KSBA','KRNM',
    # Colorado
    'KDEN','KCOS','KGJT','KASE','KPUB','KEGE','KALA','KDRO',
    # Connecticut
    'KBDL','KHVN','KGON','KOXC',
    # Delaware
    'KILG','KDOV',
    # Florida
    'KMIA','KFLL','KMCO','KTPA','KJAX','KTLH','KPBI','KRSW','KSFB',
    'KEYW','KGNV','KDAB','KPNS','KMLB','KSRQ','KAPF','KVPS',
    # Georgia
    'KATL','KSAV','KAGS','KMCN','KCSG','KVLD','KABY','KAHN',
    # Hawaii (skip)
    # Idaho
    'KBOI','KIDA','KLWS','KSUN','KTWF',
    # Illinois
    'KORD','KMDW','KSPI','KPIA','KMLI','KBMI','KCMI','KRFD','KDEC',
    # Indiana
    'KIND','KFWA','KSBN','KEVV','KTYQ','KLAF','KGUS',
    # Iowa
    'KDSM','KCID','KDBQ','KSUX','KALO','KMCW',
    # Kansas
    'KICT','KMCI','KTOP','KMHK','KSLN','KGCK','KDDC','KHYS',
    # Kentucky
    'KSDF','KLEX','KCVG','KBWG','KPAH','KOWB',
    # Louisiana
    'KMSY','KBTR','KSHV','KLFT','KLCH','KMLU','KAEX',
    # Maine
    'KPWM','KBGR','KRKD',
    # Maryland
    'KBWI','KDCA','KIAD','KSBY','KHGR',
    # Massachusetts
    'KBOS','KBED','KORH','KACK','KMVY','KHYA','KCEF',
    # Michigan
    'KDTW','KGRR','KLAN','KFNT','KMBS','KAPN','KTVC','KBTL','KMKG',
    # Minnesota
    'KMSP','KDLH','KRST','KSTC','KBRD','KINL','KFAR',
    # Mississippi
    'KJAN','KGPT','KMEI','KTUP','KGLH',
    # Missouri
    'KSTL','KMKC','KSGF','KCOU','KJLN','KCGI',
    # Montana
    'KBZN','KBIL','KMSO','KGPI','KGTF','KHLN',
    # Nebraska
    'KOMA','KLNK','KGRI','KLBF','KEAR',
    # Nevada
    'KLAS','KRNO','KELK',
    # New Hampshire
    'KMHT','KLEB','KPSM',
    # New Jersey
    'KEWR','KTTN','KACY','KTEB',
    # New Mexico
    'KABQ','KROW','KSAF','KLRU','KFMN',
    # New York
    'KJFK','KLGA','KEWR','KBUF','KROC','KSYR','KALB','KISP','KSWF',
    'KELM','KITH','KBGM','KPBG',
    # North Carolina
    'KCLT','KRDU','KGSO','KFAY','KAVL','KILM','KPGV','KINT',
    # North Dakota
    'KFAR','KBIS','KGFK','KMOT','KDIK',
    # Ohio
    'KCLE','KCMH','KCVG','KDAY','KTOL','KYNG','KCAK','KLCK',
    # Oklahoma
    'KOKC','KTUL','KLAW','KEND','KPNC','KSWO',
    # Oregon
    'KPDX','KEUG','KMFR','KRDM','KOTH','KLMT',
    # Pennsylvania
    'KPHL','KPIT','KABE','KAVP','KMDT','KERI','KIPT','KUNV',
    # Rhode Island
    'KPVD','KSFZ',
    # South Carolina
    'KCAE','KCHS','KGSP','KMYR','KFLO',
    # South Dakota
    'KFSD','KRAP','KABR','KPIR',
    # Tennessee
    'KBNA','KMEM','KTYS','KCHA','KTRI',
    # Texas
    'KDFW','KIAH','KHOU','KSAT','KAUS','KELP','KAMA','KLBB',
    'KMAF','KABI','KSPS','KCRP','KBRO','KHRL','KACT','KTYR',
    'KGGG','KSEP','KLRD','KMFE','KGRK',
    # Utah
    'KSLC','KSGN','KCDC','KPVU','KOGD',
    # Vermont
    'KBTV','KMPV',
    # Virginia
    'KRIC','KORF','KROA','KCHO','KLYH','KPHF','KSHR',
    # Washington
    'KSEA','KGEG','KPSC','KBLI','KYKM','KOLM',
    # West Virginia
    'KCRW','KCKB','KMGW',
    # Wisconsin
    'KMKE','KMSN','KGRB','KATW','KCWA','KEAU','KLSE',
    # Wyoming
    'KCPR','KJAC','KCYS','KRKS','KSHR','KCOD',
    # DC
    'KDCA','KIAD',
    # Puerto Rico
    'TJSJ','TJBQ','TJMZ',
]

# =============================================================================
# Alaska + Hawaii (parques NPS Canal Meteo)
# Añadidas para cobertura de Denali (PAFA, PATK, PANC) y Hawaii Volcanoes (PHTO, PHKO)
# =============================================================================
STATIONS_LIST += [
    # Alaska — principales aeropuertos
    'PANC',  # Anchorage Ted Stevens Intl
    'PAFA',  # Fairbanks Intl
    'PAJN',  # Juneau Intl
    'PADQ',  # Kodiak
    'PAEN',  # Kenai Muni
    'PATK',  # Talkeetna (cerca Denali NP)
    'PAFB',  # Eielson AFB (cerca Fairbanks)
    'PABE',  # Bethel
    'PASN',  # St. Paul Island
    'PABR',  # Barrow / Utqiagvik
    # Hawaii — principales aeropuertos
    'PHNL',  # Honolulu Intl (Oahu)
    'PHTO',  # Hilo Intl (Big Island, cerca Volcanoes NP)
    'PHKO',  # Kona Intl (Big Island)
    'PHOG',  # Kahului (Maui)
    'PHLI',  # Lihue (Kauai)
    'PHMK',  # Molokai
]

# Remove duplicates
STATIONS_LIST = list(dict.fromkeys(STATIONS_LIST))

# Flight category thresholds
def flight_category(vis_mi, ceil_ft):
    """Determine flight category: VFR, MVFR, IFR, LIFR"""
    if vis_mi is None: vis_mi = 99
    if ceil_ft is None: ceil_ft = 99999
    if vis_mi < 1 or ceil_ft < 500: return 'LIFR'
    if vis_mi < 3 or ceil_ft < 1000: return 'IFR'
    if vis_mi <= 5 or ceil_ft <= 3000: return 'MVFR'
    return 'VFR'

FC_COLORS = {
    'VFR': '#00c853',
    'MVFR': '#2196f3',
    'IFR': '#f44336',
    'LIFR': '#e040fb'
}

# Weather condition translations
WX_TRANSLATIONS = {
    'RA': 'Lluvia', 'SN': 'Nieve', 'TS': 'Tormenta', 'FG': 'Niebla',
    'BR': 'Neblina', 'HZ': 'Calima', 'DZ': 'Llovizna', 'SH': 'Chubasco',
    'GR': 'Granizo', 'PL': 'Hielo', 'FZ': 'Helada', 'FZRA': 'Lluvia helada',
    'FZFG': 'Niebla helada', 'TSRA': 'Tormenta con lluvia',
    'TSSN': 'Tormenta con nieve', '+RA': 'Lluvia fuerte',
    '+SN': 'Nieve fuerte', '+TS': 'Tormenta fuerte',
    '-RA': 'Lluvia ligera', '-SN': 'Nieve ligera',
    'BLSN': 'Ventisca', 'FC': 'Nube embudo', 'VA': 'Ceniza volcánica',
    'DU': 'Polvo', 'SA': 'Arena', 'FU': 'Humo', 'SQ': 'Turbonada',
}

# Sky cover translations
SKY_TRANSLATIONS = {
    'SKC': 'Despejado', 'CLR': 'Despejado', 'FEW': 'Pocas nubes',
    'SCT': 'Parcialmente nublado', 'BKN': 'Mayormente nublado',
    'OVC': 'Nublado', 'VV': 'Cielo oscurecido'
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# =============================================================================
# FUNCIONES
# =============================================================================

def c_to_f(c):
    """Celsius to Fahrenheit"""
    if c is None: return None
    return round(c * 9/5 + 32, 1)

def mps_to_mph(mps):
    """m/s to mph"""
    if mps is None: return None
    return round(mps * 2.237, 1)

def mps_to_kts(mps):
    """m/s to knots"""
    if mps is None: return None
    return round(mps * 1.944, 1)

def m_to_mi(m):
    """meters to statute miles"""
    if m is None: return None
    return round(m / 1609.34, 1)

def m_to_ft(m):
    """meters to feet"""
    if m is None: return None
    return round(m * 3.281)

def pa_to_inhg(pa):
    """Pascals to inches of mercury"""
    if pa is None: return None
    return round(pa / 3386.39, 2)

def pa_to_mb(pa):
    """Pascals to millibars"""
    if pa is None: return None
    return round(pa / 100, 1)

def heat_index(t_f, rh):
    """Calculate heat index in °F (if T >= 80°F)"""
    if t_f is None or rh is None or t_f < 80: return None
    hi = (-42.379 + 2.04901523*t_f + 10.14333127*rh
          - 0.22475541*t_f*rh - 0.00683783*t_f**2
          - 0.05481717*rh**2 + 0.00122874*t_f**2*rh
          + 0.00085282*t_f*rh**2 - 0.00000199*t_f**2*rh**2)
    return round(hi, 1)

def wind_chill(t_f, wind_mph):
    """Calculate wind chill in °F (if T <= 50°F and wind >= 3mph)"""
    if t_f is None or wind_mph is None or t_f > 50 or wind_mph < 3: return None
    wc = (35.74 + 0.6215*t_f - 35.75*wind_mph**0.16
          + 0.4275*t_f*wind_mph**0.16)
    return round(wc, 1)

def relative_humidity(t_c, td_c):
    """Calculate RH% from temperature and dewpoint (both in Celsius)"""
    if t_c is None or td_c is None: return None
    try:
        e_td = 6.112 * math.exp((17.67 * td_c) / (td_c + 243.5))
        e_t = 6.112 * math.exp((17.67 * t_c) / (t_c + 243.5))
        rh = (e_td / e_t) * 100
        return round(min(100, max(0, rh)))
    except:
        return None

def translate_wx(wx_string):
    """Translate present weather string to Spanish"""
    if not wx_string: return ''
    for code, es in sorted(WX_TRANSLATIONS.items(), key=lambda x: -len(x[0])):
        wx_string = wx_string.replace(code, es)
    return wx_string.strip()

def translate_sky(cover):
    """Translate sky cover abbreviation"""
    return SKY_TRANSLATIONS.get(cover, cover)


def fetch_metar_awc():
    """
    Fetch recent METAR data from Aviation Weather Center (AWC).
    Uses station IDs in batches of 100 (bbox requires undocumented params).
    """
    log.info("Fetching METAR from Aviation Weather Center...")

    all_obs = []
    batch_size = 100

    for i in range(0, len(STATIONS_LIST), batch_size):
        batch = STATIONS_LIST[i:i+batch_size]
        ids_str = ','.join(batch)
        try:
            url = f"https://aviationweather.gov/api/data/metar?ids={ids_str}&format=json&hours=2"
            r = requests.get(url, headers={'User-Agent': CONFIG['user_agent']}, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                all_obs.extend(data)
            batch_num = i // batch_size + 1
            total_batches = (len(STATIONS_LIST) + batch_size - 1) // batch_size
            log.info(f"  Batch {batch_num}/{total_batches}: {len(data)} obs")
        except Exception as e:
            log.warning(f"  Batch {i//batch_size+1} failed: {e}")
            continue

    log.info(f"AWC total: {len(all_obs)} observations")
    return all_obs


def fetch_metar_nws():
    """
    Fallback: fetch from NWS API station by station.
    Much slower but more reliable. Only used if AWC fails.
    """
    log.info("Fetching METAR from NWS API (fallback)...")
    observations = []

    for state in STATES:
        try:
            url = f"{CONFIG['nws_stations_url']}?state={state}&limit=500"
            r = requests.get(url, headers={
                'User-Agent': CONFIG['user_agent'],
                'Accept': 'application/geo+json'
            }, timeout=30)
            if r.status_code != 200: continue
            stations = r.json().get('features', [])

            for stn in stations[:50]:  # Limit per state
                stn_id = stn['properties'].get('stationIdentifier', '')
                if not stn_id: continue
                try:
                    obs_url = f"https://api.weather.gov/stations/{stn_id}/observations/latest"
                    obs_r = requests.get(obs_url, headers={
                        'User-Agent': CONFIG['user_agent'],
                        'Accept': 'application/geo+json'
                    }, timeout=15)
                    if obs_r.status_code == 200:
                        observations.append(obs_r.json())
                except:
                    continue
        except:
            continue

    log.info(f"NWS API returned {len(observations)} observations")
    return observations


def process_awc_obs(raw_list):
    """Process AWC JSON observations into standardized GeoJSON features.
    
    AWC fields (from actual API response):
      icaoId, receiptTime, obsTime (epoch), reportTime, temp (°C), dewp (°C),
      wdir, wspd (kts), wgst (kts), visib ("10+" or number), altim (hPa),
      slp (hPa), wxString, precip, pcp3hr, pcp6hr, pcp24hr, metarType,
      rawOb, lat, lon, elev, name, cover (SKC/CLR/FEW/SCT/BKN/OVC),
      clouds [{cover, base}], fltCat (VFR/MVFR/IFR/LIFR)
    """
    features = []
    now = datetime.now(timezone.utc)
    max_age = timedelta(minutes=CONFIG['max_age_minutes'])

    for obs in raw_list:
        try:
            lat = obs.get('lat')
            lon = obs.get('lon')
            if lat is None or lon is None: continue

            # Parse time — obsTime is epoch seconds
            ob_epoch = obs.get('obsTime')
            if ob_epoch is None: continue
            try:
                if isinstance(ob_epoch, (int, float)):
                    ot = datetime.fromtimestamp(ob_epoch, tz=timezone.utc)
                else:
                    ot = datetime.fromisoformat(str(ob_epoch).replace('Z', '+00:00'))
            except:
                continue

            if (now - ot) > max_age: continue
            ob_time_str = ot.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Temperature (AWC gives °C)
            t_c = obs.get('temp')
            td_c = obs.get('dewp')
            t_f = c_to_f(t_c)
            td_f = c_to_f(td_c)
            rh = relative_humidity(t_c, td_c)

            # Wind (AWC gives knots)
            wdir = obs.get('wdir')
            wspd_kts = obs.get('wspd')
            wgst_kts = obs.get('wgst')
            wspd_mph = round(wspd_kts * 1.151, 1) if wspd_kts is not None else None
            wgst_mph = round(wgst_kts * 1.151, 1) if wgst_kts is not None else None

            # Visibility — "10+", "6+", or numeric
            vis_raw = obs.get('visib')
            if isinstance(vis_raw, str):
                clean = vis_raw.replace('+', '')
                vis_mi = float(clean) if clean.replace('.', '').isdigit() else None
            elif vis_raw is not None:
                vis_mi = float(vis_raw)
            else:
                vis_mi = None

            # Pressure (AWC gives hPa for altim and slp)
            altim_hpa = obs.get('altim')
            slp_hpa = obs.get('slp')
            altim_inhg = round(altim_hpa * 0.02953, 2) if altim_hpa else None
            slp_mb = round(slp_hpa, 1) if slp_hpa else None

            # Clouds — AWC provides 'cover' (highest) and 'clouds' array
            sky_cover = obs.get('cover', '')
            clouds = obs.get('clouds', [])
            ceil_ft = None
            for c in clouds:
                if c.get('cover') in ('BKN', 'OVC', 'VV'):
                    ceil_ft = c.get('base')  # AWC gives feet AGL
                    break

            # Weather string
            wx_string = obs.get('wxString', '') or ''

            # Flight category — AWC pre-computes this!
            fc = obs.get('fltCat', '')
            if not fc:
                fc = flight_category(vis_mi, ceil_ft)

            # Heat index / Wind chill
            hi = heat_index(t_f, rh) if t_f and rh else None
            wc = wind_chill(t_f, wspd_mph) if t_f and wspd_mph else None
            feels_like = wc if wc is not None else (hi if hi is not None else t_f)

            # Precip
            precip_1h = obs.get('precip')
            precip_3h = obs.get('pcp3hr')
            precip_6h = obs.get('pcp6hr')
            precip_24h = obs.get('pcp24hr')

            station_id = obs.get('icaoId', '')
            station_name = obs.get('name', station_id)

            feature = {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [round(lon, 4), round(lat, 4)]},
                'properties': {
                    'id': station_id,
                    'name': station_name,
                    'obsTime': ob_time_str,
                    'obsAge': round((now - ot).total_seconds() / 60),

                    'tempF': t_f,
                    'dewpF': td_f,
                    'feelsF': feels_like,
                    'rh': rh,

                    'wdir': wdir,
                    'wspdKts': wspd_kts,
                    'wspdMph': wspd_mph,
                    'wgstKts': wgst_kts,
                    'wgstMph': wgst_mph,

                    'altimInHg': altim_inhg,
                    'slpMb': slp_mb,

                    'visMi': vis_mi,

                    'skyCover': sky_cover,
                    'skyEs': translate_sky(sky_cover),
                    'ceilFt': ceil_ft,

                    'wxString': wx_string,
                    'wxEs': translate_wx(wx_string),

                    'flightCat': fc,
                    'fcColor': FC_COLORS.get(fc, '#999'),

                    'precip1h': precip_1h,
                    'precip3h': precip_3h,
                    'precip6h': precip_6h,
                    'precip24h': precip_24h,

                    'rawOb': obs.get('rawOb', ''),
                }
            }
            features.append(feature)
        except Exception as e:
            continue

    return features


def upload_to_cdn(filepath):
    """Upload GeoJSON to DigitalOcean Spaces via AWS CLI."""
    cmd = [
        'aws', 's3', 'cp', filepath,
        f"s3://{CONFIG['cdn_bucket']}/{CONFIG['cdn_key']}",
        '--profile', CONFIG['aws_profile'],
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=300',
        '--endpoint-url', CONFIG['cdn_endpoint']
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            log.info(f"✅ Uploaded to CDN: {CONFIG['cdn_key']}")
            return True
        else:
            log.error(f"❌ Upload failed: {result.stderr}")
            return False
    except Exception as e:
        log.error(f"❌ Upload error: {e}")
        return False


def main():
    log.info("=" * 60)
    log.info("METAR Pipeline — Canal Meteo TV")
    log.info("=" * 60)

    # Create data directory
    Path(CONFIG['data_dir']).mkdir(parents=True, exist_ok=True)

    # Fetch observations
    raw = fetch_metar_awc()
    if not raw:
        log.warning("AWC failed, trying NWS API fallback...")
        raw = fetch_metar_nws()

    if not raw:
        log.error("No observations available from any source")
        return

    # Process into GeoJSON features
    features = process_awc_obs(raw)
    log.info(f"Processed {len(features)} valid observations")

    if not features:
        log.warning("No valid features after processing")
        return

    # Build GeoJSON
    geojson = {
        'type': 'FeatureCollection',
        'properties': {
            'generated': datetime.now(timezone.utc).isoformat(),
            'generated_ts': int(datetime.now(timezone.utc).timestamp()),
            'count': len(features),
            'source': 'AWC/METAR'
        },
        'features': features
    }

    # Save locally
    output_path = CONFIG['output_json']
    with open(output_path, 'w') as f:
        json.dump(geojson, f, separators=(',', ':'))
    file_size = Path(output_path).stat().st_size
    log.info(f"Saved: {output_path} ({file_size / 1024:.1f} KB)")

    # Upload to CDN
    upload_to_cdn(output_path)

    log.info(f"✅ Pipeline complete: {len(features)} stations")


if __name__ == '__main__':
    main()
