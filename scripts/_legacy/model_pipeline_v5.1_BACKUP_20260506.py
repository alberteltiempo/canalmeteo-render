#!/usr/bin/env python3
"""
===============================================================================
Multi-Model Raster Pipeline — Canal Meteo TV  (v5.2 — HRRR_EXT añadido)
===============================================================================
Supports: NBM, GFS, HRRR, HRRR_EXT
Usage:
  python model_pipeline.py              # defaults to NBM
  python model_pipeline.py --model gfs
  python model_pipeline.py --model hrrr      # 0-18h cada hora
  python model_pipeline.py --model hrrr_ext  # 0-48h en ciclos 00/06/12/18z

Cron:
  20 * * * *      .../model_pipeline.py --model nbm
  35 * * * *      .../model_pipeline.py --model hrrr
  45 0,6,12,18 * * * .../model_pipeline.py --model gfs
  55 0,6,12,18 * * * .../model_pipeline.py --model hrrr_ext

NUEVOS PRODUCTOS (v5):
  GFS:
    - reflectivity (REFC composite simulado, hires)
    - jet250       (corriente en chorro a 250 mb, mph)
    - temp850C     (temperatura a 850 mb, °C)
    - wind850      (viento a 850 mb, mph)
    - pressureMb   (PRMSL — ya existía pero ahora se renderiza también como ISOBARAS)
  NBM:
    - tempAnom     (anomalía de temperatura vs NCEI 1991-2020)
  GFS:
    - tempAnom     (anomalía de temperatura vs NCEI 1991-2020)

Requiere para anomalía:
  - /opt/canalmeteo/data/climatology/tavg_normals_1991_2020.nc
  - Generado con: python download_climatology.py
===============================================================================
"""
import requests, json, subprocess, logging, sys, os, time, warnings, argparse
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
warnings.filterwarnings('ignore')

try:
    import cfgrib
    from PIL import Image
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
except ImportError as e:
    print(f"ERROR: {e}"); sys.exit(1)

# =============================================================================
# COMMON CONFIG
# =============================================================================
BASE = {
    'aws_profile': 'do-tor1',
    'cdn_bucket': 'canalmeteo-public',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',
    'cdn_base': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com',
    'user_agent': 'CanalMeteoTV/1.0',
    'lat_min': 24.0, 'lat_max': 50.0,
    'lon_min': -125.0, 'lon_max': -66.0,
    'img_width': 590, 'img_height': 260,
    'img_width_hires': 3600, 'img_height_hires': 2120,
    'climatology_path': '/opt/canalmeteo/data/climatology/tavg_normals_1991_2020.nc',
}

# Variables que se renderizan a alta resolución
HIRES_VARS = {'reflectivity', 'refd1km', 'ptypeRefl'}

# Variables que se renderizan como contornos (no relleno)
CONTOUR_VARS = {'pressureMb_iso'}

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================
MODELS = {
    'nbm': {
        'name': 'NBM',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl',
        'file_tmpl': 'blend.t{cc}z.core.f{fh:03d}.co.grib2',
        'dir_tmpl': '/blend.{dd}/{cc}/core',
        'cycles': list(range(24)),
        'forecast_hours': list(range(1, 49)) + [51, 54, 57, 60],
        'lon_360': True,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&var_APTMP=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_WIND=on&var_GUST=on&var_WDIR=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&lev_surface=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh', 'aptmp': 'feelsF',
            'si10': 'wspdMph', 'i10fg': 'gustMph', 'wdir10': 'wdir',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
        },
        # NBM no tiene PRMSL ni REFC en el filter — anomalía sí, calculada vs t2m
        'compute_anomaly_from': 't2m',
    },
    'gfs': {
        'name': 'GFS',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl',
        'file_tmpl': 'gfs.t{cc}z.pgrb2.0p25.f{fh:03d}',
        'dir_tmpl': '/gfs.{dd}/{cc}/atmos',
        'cycles': [0, 6, 12, 18],
        'forecast_hours': list(range(0, 49)) + list(range(51, 121, 3)),
        'lon_360': False,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&var_GUST=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&var_PRMSL=on&'
                                       'var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&'
                                       'lev_surface=on&lev_mean_sea_level=on'},
            {'name': 'refl', 'params': 'var_REFD=on&all_lev=on'},
            # NUEVOS:
            {'name': 'refc',  'params': 'var_REFC=on&lev_entire_atmosphere=on'},
            {'name': '250mb', 'params': 'var_UGRD=on&var_VGRD=on&lev_250_mb=on'},
            {'name': '850mb', 'params': 'var_TMP=on&var_UGRD=on&var_VGRD=on&lev_850_mb=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
            'u10': 'u10', 'v10': 'v10', 'i10fg': 'gustMph',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            'prmsl': 'pressureMb',
            'refd': 'refd1km',
            'refc': 'reflectivity',     # NUEVO
            'crain': 'crain', 'csnow': 'csnow', 'cfrzr': 'cfrzr', 'cicep': 'cicep',
            # Claves de niveles isobáricos (renombradas en extract_fields según level)
            'u250': 'u250', 'v250': 'v250',
            't850': 'temp850C', 'u850': 'u850', 'v850': 'v850',
        },
        # Para 250mb/850mb los keys de cfgrib pueden colisionar con superficie;
        # se manejan en extract_fields() con detección por typeOfLevel.
        'compute_anomaly_from': 't2m',
        'render_isobars': True,
        'render_jet': True,
        'render_850': True,
    },
    'hrrr': {
        'name': 'HRRR',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl',
        'file_tmpl': 'hrrr.t{cc}z.wrfsfcf{fh:02d}.grib2',
        'dir_tmpl': '/hrrr.{dd}/conus',
        'cycles': list(range(24)),
        'forecast_hours': list(range(0, 19)),
        'forecast_hours_extended': list(range(0, 49)),
        'lon_360': False,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&var_GUST=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&'
                                       'var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&lev_surface=on'},
            {'name': 'refc', 'params': 'var_REFC=on&lev_entire_atmosphere=on'},
            {'name': 'refd', 'params': 'var_REFD=on&lev_1000_m_above_ground=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
            'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            'refc': 'reflectivity', 'refd': 'refd1km',
            'crain': 'crain', 'csnow': 'csnow', 'cfrzr': 'cfrzr', 'cicep': 'cicep',
        },
    },
    'hrrr_ext': {
        # HRRR Extendido — mismos productos que HRRR pero hasta 48h.
        # NOAA solo publica las horas extendidas (19-48) en los ciclos
        # principales: 00z, 06z, 12z, 18z. Los demás ciclos solo llegan a 18h.
        'name': 'HRRR_EXT',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl',
        'file_tmpl': 'hrrr.t{cc}z.wrfsfcf{fh:02d}.grib2',
        'dir_tmpl': '/hrrr.{dd}/conus',
        'cycles': [0, 6, 12, 18],            # SOLO ciclos principales
        'forecast_hours': list(range(0, 49)),  # SIEMPRE 0-48 horas
        'lon_360': False,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&var_GUST=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&'
                                       'var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&lev_surface=on'},
            {'name': 'refc', 'params': 'var_REFC=on&lev_entire_atmosphere=on'},
            {'name': 'refd', 'params': 'var_REFD=on&lev_1000_m_above_ground=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
            'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            'refc': 'reflectivity', 'refd': 'refd1km',
            'crain': 'crain', 'csnow': 'csnow', 'cfrzr': 'cfrzr', 'cicep': 'cicep',
        },
    },
}

# =============================================================================
# CONVERTERS (grib field values → display units)
# =============================================================================
CONVERTERS = {
    'tempF':      lambda k: (k - 273.15) * 9/5 + 32,
    'dewpF':      lambda k: (k - 273.15) * 9/5 + 32,
    'feelsF':     lambda k: (k - 273.15) * 9/5 + 32,
    'rh':         lambda x: x,
    'wspdMph':    lambda ms: ms * 2.237,
    'gustMph':    lambda ms: ms * 2.237,
    'wdir':       lambda x: x,
    'visMi':      lambda m: m / 1609.34,
    'cloudPct':   lambda x: x,
    'cape':       lambda x: x,
    'precipIn':   lambda kg: np.where(kg > 0, kg / 25.4, 0),
    'reflectivity': lambda x: x,
    'refd1km':    lambda x: x,
    'pressureMb': lambda pa: pa / 100.0,
    'crain':      lambda x: x,
    'csnow':      lambda x: x,
    'cfrzr':      lambda x: x,
    'cicep':      lambda x: x,
    'u10':        lambda x: x,
    'v10':        lambda x: x,
    # NUEVOS
    'tempAnom':   lambda f_diff: f_diff,           # ya viene en °F (calculado)
    'temp850C':   lambda k: k - 273.15,            # K → °C
    'jet250':     lambda ms: ms * 1.94384,         # m/s → knots (más estándar para jet)
    'wind850':    lambda ms: ms * 2.237,           # m/s → mph
    'u250':       lambda x: x, 'v250': lambda x: x,
    'u850':       lambda x: x, 'v850': lambda x: x,
}

# =============================================================================
# RENDER VARS (paletas de color para PNG)
# =============================================================================
RENDER_VARS = {
    'tempF':    {'label': 'Temperatura (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 110,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a',
                            '#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'dewpF':    {'label': 'Punto de rocío (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 80,
                 'colors': ['#4e342e','#6d4c41','#a1887f','#e0e0e0','#a5d6a7','#66bb6a','#2e7d32',
                            '#00e676','#0097a7','#01579b','#4a148c']},
    'feelsF':   {'label': 'Sensación (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 120,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a',
                            '#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'rh':       {'label': 'Humedad (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                 'colors': ['#b71c1c','#e65100','#f57f17','#cddc39','#8bc34a','#43a047','#2e7d32','#1565c0','#0d47a1']},
    'wspdMph':  {'label': 'Viento (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 60,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c']},
    'gustMph':  {'label': 'Ráfagas (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 80,
                 'colors': ['#e0e0e0','#81d4fa','#29b6f6','#ffeb3b','#ffa726','#ff7043','#e53935','#b71c1c','#4a148c']},
    'visMi':    {'label': 'Visibilidad (mi)', 'unit': 'mi', 'vmin': 0, 'vmax': 15,
                 'colors': ['#b71c1c','#e53935','#ff7043','#ffa726','#ffeb3b','#e0e0e0','#90caf9']},
    'cloudPct': {'label': 'Nubes (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                 'colors': ['#0d47a1','#1565c0','#42a5f5','#90caf9','#e0e0e0','#bdbdbd','#9e9e9e','#757575','#424242']},
    'cape':     {'label': 'CAPE (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 4000,
                 'colors': ['#263238','#37474f','#4caf50','#8bc34a','#ffeb3b','#ff9800','#f44336','#d32f2f','#880e4f']},
    'precipIn': {'label': 'Precipitación (in)', 'unit': 'in', 'vmin': 0, 'vmax': 2,
                 'colors': ['#263238','#1b5e20','#4caf50','#a5d6a7','#ffeb3b','#ff9800','#f44336','#e040fb']},
    'reflectivity': {'label': 'Radar simulado (dBZ)', 'unit': 'dBZ', 'vmin': 0, 'vmax': 80,
                 'colors': 'nws_refl', 'discrete': True},
    'refd1km':  {'label': 'Radar 1km base (dBZ)', 'unit': 'dBZ', 'vmin': 0, 'vmax': 80,
                 'colors': 'nws_refl', 'discrete': True},
    'ptypeRefl': {'label': 'Tipo precip + radar', 'unit': 'dBZ', 'vmin': 0, 'vmax': 75,
                 'colors': ['#00000000','#02fd02','#01c501','#008e00','#fdf802','#fd9500','#fd0000',
                            '#81d4fa','#039be5','#01579b','#f48fb1','#e91e63','#880e4f','#7c4dff','#6200ea','#fdfdfd']},
    'pressureMb': {'label': 'Presión nivel del mar (mb)', 'unit': 'mb', 'vmin': 980, 'vmax': 1050,
                 'colors': ['#4a148c','#1565c0','#42a5f5','#81c784','#ffeb3b','#ff9800','#e53935','#880e4f']},
    # === NUEVOS ===
    'tempAnom': {'label': 'Anomalía temp. (°F)', 'unit': '°F', 'vmin': -25, 'vmax': 25,
                 # Paleta divergente azul → blanco → rojo (frío vs cálido)
                 'colors': ['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7',
                            '#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']},
    'temp850C': {'label': 'Temperatura 850 mb (°C)', 'unit': '°C', 'vmin': -40, 'vmax': 30,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#01579b','#0097a7','#00897b','#43a047',
                            '#cddc39','#ffeb3b','#ffa726','#ef5350','#c62828','#880e4f']},
    'jet250':   {'label': 'Corriente en chorro 250 mb (kt)', 'unit': 'kt', 'vmin': 50, 'vmax': 200,
                 # Verde claro → amarillo → naranja → rojo → magenta para >150 kt
                 'colors': ['#00000000','#a5d6a7','#cddc39','#ffeb3b','#ffa726','#ef5350',
                            '#c62828','#880e4f','#6a1b9a','#311b92']},
    'wind850':  {'label': 'Viento 850 mb (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 70,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f']},
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


# =============================================================================
# CYCLE DETECTION
# =============================================================================
def find_latest_cycle(model_cfg):
    """Find latest available cycle for this model."""
    now = datetime.now(timezone.utc)
    # HRRR_EXT solo tiene 4 ciclos/día (cada 6h), igual que GFS
    if model_cfg['name'] in ('GFS', 'HRRR_EXT'):
        max_lookback = 24
    else:
        max_lookback = 12
    seen_cycles = set()

    for hb in range(0, max_lookback):
        t = now - timedelta(hours=hb)
        cc_int = t.hour
        valid_cycles = sorted(model_cfg['cycles'])
        cc_int = max([c for c in valid_cycles if c <= cc_int], default=valid_cycles[-1])
        cc = f"{cc_int:02d}"
        dd = t.strftime('%Y%m%d')

        cycle_key = f"{dd}/{cc}"
        if cycle_key in seen_cycles:
            continue
        seen_cycles.add(cycle_key)

        dir_path = model_cfg['dir_tmpl'].format(dd=dd, cc=cc)
        fh = model_cfg['forecast_hours'][0]
        fname = model_cfg['file_tmpl'].format(cc=cc, fh=fh)
        lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
        test_group = model_cfg['groups'][0]
        url = (f"{model_cfg['filter']}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
               f"{test_group['params']}&subregion=&toplat=26&leftlon={lw}&rightlon={lw+2}&bottomlat=24")
        try:
            r = requests.get(url, timeout=20, headers={'User-Agent': BASE['user_agent']})
            if r.status_code == 200 and len(r.content) > 100:
                log.info(f"Cycle: {dd}/{cc}z")
                return dd, cc
        except Exception:
            pass
    return None, None


# =============================================================================
# DOWNLOAD GROUP
# =============================================================================
def download_group(model_cfg, date, cycle, fhour, group):
    """Download one filtered GRIB2."""
    data_dir = f"/opt/canalmeteo/data/{model_cfg['name'].lower()}"
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    outpath = os.path.join(data_dir,
        f"{model_cfg['name'].lower()}_{group['name']}_f{fhour:03d}.grib2")

    lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
    le = BASE['lon_max'] + (360 if model_cfg['lon_360'] else 0)
    dir_path = model_cfg['dir_tmpl'].format(dd=date, cc=cycle)
    fname = model_cfg['file_tmpl'].format(cc=cycle, fh=fhour)

    url = (f"{model_cfg['filter']}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
           f"{group['params']}&subregion=&toplat={BASE['lat_max']}&leftlon={lw}&"
           f"rightlon={le}&bottomlat={BASE['lat_min']}")
    try:
        r = requests.get(url, timeout=90, headers={'User-Agent': BASE['user_agent']})
        if r.status_code == 200 and len(r.content) > 500:
            with open(outpath, 'wb') as f:
                f.write(r.content)
            return outpath, len(r.content), group['name']
    except Exception as e:
        log.warning(f"    {group['name']}: {e}")
    return None, 0, group['name']


# =============================================================================
# EXTRACT FIELDS — versión consciente del nivel
# =============================================================================
def extract_fields(grib_path, field_map, group_name=None):
    """Extract known fields from GRIB2.
    Para grupos de niveles isobáricos (250mb, 850mb), renombra los campos
    para evitar colisión con campos de superficie del mismo nombre (UGRD/VGRD/TMP).
    """
    found = {}
    try:
        for ds in cfgrib.open_datasets(grib_path):
            # Detectar el nivel del dataset
            type_of_level = None
            level_value = None
            try:
                if 'isobaricInhPa' in ds.coords:
                    type_of_level = 'isobaricInhPa'
                    level_value = float(ds['isobaricInhPa'].values) \
                        if ds['isobaricInhPa'].ndim == 0 \
                        else float(ds['isobaricInhPa'].values[0])
            except Exception:
                pass

            for fname in ds.data_vars:
                data = ds[fname].values
                if data.ndim == 3:
                    data = data[0]

                # Campos isobáricos: renombrar según nivel (250mb / 850mb)
                key = fname
                if type_of_level == 'isobaricInhPa' and level_value is not None:
                    if abs(level_value - 250) < 1:
                        if fname == 'u': key = 'u250'
                        elif fname == 'v': key = 'v250'
                    elif abs(level_value - 850) < 1:
                        if fname == 't': key = 't850'
                        elif fname == 'u': key = 'u850'
                        elif fname == 'v': key = 'v850'

                if key in field_map and key not in found:
                    found[key] = (data, ds.latitude.values, ds.longitude.values)
    except Exception as e:
        log.warning(f"    cfgrib ({group_name}): {e}")
    return found


# =============================================================================
# NWS RADAR REFLECTIVITY COLOR TABLE
# =============================================================================
NWS_REFL_TABLE = [
    (15, (  1, 159, 244)), (20, (  3,   0, 244)), (25, (  2, 253,   2)),
    (30, (  1, 197,   1)), (35, (  0, 142,   0)), (40, (253, 248,   2)),
    (45, (229, 188,   0)), (50, (253, 149,   0)), (55, (253,   0,   0)),
    (60, (212,   0,   0)), (65, (188,   0,   0)), (70, (248,   0, 253)),
    (75, (152,  84, 198)), (80, (253, 253, 253)),
]

def render_nws_refl(field):
    """Render radar field using exact NWS discrete color bins."""
    h, w = field.shape
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    for i, (threshold, (r, g, b)) in enumerate(NWS_REFL_TABLE):
        if i < len(NWS_REFL_TABLE) - 1:
            next_threshold = NWS_REFL_TABLE[i + 1][0]
            mask = (field >= threshold) & (field < next_threshold)
        else:
            mask = field >= threshold
        rgba[mask, 0] = r / 255.0
        rgba[mask, 1] = g / 255.0
        rgba[mask, 2] = b / 255.0
        rgba[mask, 3] = 0.92
    return rgba


# =============================================================================
# REPROJECTION (cached KDTree)
# =============================================================================
_kdtree_cache = {}
# ═══════════════════════════════════════════════════════════════════
# KDTree disk cache — persiste indices entre runs (Apr 30 2026)
# ═══════════════════════════════════════════════════════════════════
_KDTREE_CACHE_DIR = "/opt/canalmeteo/data/cache/kdtree"

def _kdtree_cache_path(model_name, src_shape, target_h, target_w, sample_hash):
    """Ruta del archivo cache para esta configuración."""
    import os
    os.makedirs(_KDTREE_CACHE_DIR, exist_ok=True)
    fname = f"{model_name}_{src_shape[0]}x{src_shape[1]}_to_{target_h}x{target_w}_{sample_hash}.pkl"
    return os.path.join(_KDTREE_CACHE_DIR, fname)

def _kdtree_grid_hash(lats_2d, lons_2d):
    """Hash corto de las coords para detectar cambios de grid (raros)."""
    import hashlib
    sample = lats_2d.ravel()[:8].tobytes() + lons_2d.ravel()[:8].tobytes()
    return hashlib.md5(sample).hexdigest()[:8]

def load_kdtree_indices(model_name, src_shape, target_h, target_w, sample_hash):
    """Carga indices desde disco. Devuelve None si no existe."""
    import os, pickle
    path = _kdtree_cache_path(model_name, src_shape, target_h, target_w, sample_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            indices = pickle.load(f)
        log.info(f"    Loaded KDTree indices from cache: {os.path.basename(path)}")
        return indices
    except Exception as e:
        log.warning(f"    Failed to load KDTree cache: {e} — rebuilding")
        return None

def save_kdtree_indices(model_name, src_shape, target_h, target_w, sample_hash, indices):
    """Guarda indices a disco."""
    import os, pickle
    path = _kdtree_cache_path(model_name, src_shape, target_h, target_w, sample_hash)
    try:
        with open(path, "wb") as f:
            pickle.dump(indices, f, protocol=4)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        log.info(f"    Saved KDTree indices to cache: {os.path.basename(path)} ({size_mb:.1f} MB)")
    except Exception as e:
        log.warning(f"    Failed to save KDTree cache: {e}")



def reproject_cached(data, lats_2d, lons_2d, target_h, target_w):
    """Cached version — reuses KDTree across variables for same grid shape."""
    global _kdtree_cache
    from scipy.spatial import cKDTree

    cache_key = (lats_2d.shape, target_h, target_w)
    if cache_key not in _kdtree_cache:
        # Try loading from disk first (Apr 30 2026 disk cache)
        model_for_cache = globals().get('_current_model_name', 'unknown')
        sample_hash = _kdtree_grid_hash(lats_2d, lons_2d)
        indices = load_kdtree_indices(
            model_for_cache, lats_2d.shape, target_h, target_w, sample_hash,
        )

        if indices is None:
            # Build from scratch
            lons_fixed = np.where(lons_2d > 180, lons_2d - 360, lons_2d)
            lat_reg = np.linspace(BASE['lat_max'], BASE['lat_min'], target_h)
            lon_reg = np.linspace(BASE['lon_min'], BASE['lon_max'], target_w)
            lon_grid, lat_grid = np.meshgrid(lon_reg, lat_reg)

            src_points = np.column_stack([lats_2d.ravel(), lons_fixed.ravel()])
            tree = cKDTree(src_points)
            tgt_points = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
            _, indices = tree.query(tgt_points)
            log.info(f"    Built KDTree for {lats_2d.shape} -> {target_h}x{target_w}")

            # Persist to disk for future runs
            save_kdtree_indices(
                model_for_cache, lats_2d.shape, target_h, target_w, sample_hash, indices,
            )

        _kdtree_cache[cache_key] = indices

    indices = _kdtree_cache[cache_key]
    return data.ravel()[indices].reshape(target_h, target_w)


# =============================================================================
# CLIMATOLOGY (NCEI 1991-2020) — para anomalía
# =============================================================================
_climatology_cache = None

def load_climatology():
    """Carga el cubo NetCDF (365, H, W) de Tavg en °F una sola vez."""
    global _climatology_cache
    if _climatology_cache is not None:
        return _climatology_cache
    path = BASE['climatology_path']
    if not os.path.exists(path):
        log.warning(f"    Climatología no encontrada: {path} — anomalía deshabilitada")
        _climatology_cache = False
        return False
    try:
        import xarray as xr
        ds = xr.open_dataset(path)
        var = list(ds.data_vars)[0]
        arr = ds[var].values  # shape (365, H, W)
        _climatology_cache = arr.astype(np.float32)
        log.info(f"    Climatología cargada: {arr.shape}")
        return _climatology_cache
    except Exception as e:
        log.warning(f"    No se pudo cargar climatología: {e}")
        _climatology_cache = False
        return False


def compute_temp_anomaly(t_field_F, lats, lons, valid_dt):
    """Calcula T_modelo (°F) - T_climatología(día_del_año).
    t_field_F: array 2D ya convertido a °F
    valid_dt: datetime UTC del valid time
    Retorna array 2D de anomalía en °F, o None si la climatología no está disponible."""
    clim = load_climatology()
    if clim is False or clim is None:
        return None
    doy = valid_dt.timetuple().tm_yday - 1  # 0-indexed
    if doy >= clim.shape[0]:
        doy = clim.shape[0] - 1
    clim_field = clim[doy]  # (H_clim, W_clim) — ya regrillado a img_height x img_width

    # El campo t puede venir a tamaño nativo o reproyectado.
    # Lo reescalamos a img_height × img_width (resolución de la climatología).
    target_h, target_w = clim_field.shape
    if t_field_F.shape != clim_field.shape:
        if lats.ndim == 2:
            t_resized = reproject_cached(t_field_F, lats, lons, target_h, target_w)
        else:
            # Grid regular → resize bilineal vía PIL
            from PIL import Image as PILImage
            img = PILImage.fromarray(t_field_F.astype(np.float32), mode='F')
            t_resized = np.array(img.resize((target_w, target_h), PILImage.BILINEAR))
    else:
        t_resized = t_field_F

    return t_resized - clim_field


# =============================================================================
# RENDER PNG (relleno por celda)
# =============================================================================
def render_png(data, lats, lons, var_name, convert_fn, output_path, needs_reproject=False):
    """Render field as PNG using fast PIL resize."""
    if var_name not in RENDER_VARS:
        return False
    rcfg = RENDER_VARS[var_name]

    field = convert_fn(data.copy())
    field = np.where(np.isnan(field), rcfg['vmin'], field)

    # ── REPROJECT Lambert Conformal (2D coords) to regular lat/lon grid ──
    if needs_reproject and lats.ndim == 2:
        if var_name in HIRES_VARS:
            field = reproject_cached(field, lats, lons,
                                     BASE['img_height_hires'], BASE['img_width_hires'])
        else:
            field = reproject_cached(field, lats, lons,
                                     BASE['img_height'], BASE['img_width'])

    # ── ANTI-PIXELADO PARA RADAR ──
    # Para reflectividad en grid regular (ej. GFS 0.25° → 25km de píxel nativo),
    # el render directo a 3600x2120 muestra cuadrados visibles. Suavizamos solo
    # los píxeles con eco real para evitar halos donde no debería haberlos.
    if var_name in {'reflectivity', 'refd1km'}:
        try:
            from scipy.ndimage import gaussian_filter, zoom
            # Si el campo NO fue reproyectado (grid regular nativo), ampliarlo
            # con interpolación bilineal antes de pasar al colormap discreto NWS.
            if not (needs_reproject and lats.ndim == 2):
                # Ampliar al tamaño hires con factor de zoom
                target_h, target_w = BASE['img_height_hires'], BASE['img_width_hires']
                zh = target_h / field.shape[0]
                zw = target_w / field.shape[1]
                # Máscara de ecos válidos (>5 dBZ) — interpolada también
                mask = (field > 5).astype(np.float32)
                # Suavizar el campo antes de ampliar (sigma pequeño en grid nativo)
                field_smooth = gaussian_filter(field, sigma=0.7)
                # Ampliar por interpolación bilineal (orden 1)
                field = zoom(field_smooth, (zh, zw), order=1)
                # Ampliar máscara con orden 0 (nearest) para preservar bordes
                mask = zoom(mask, (zh, zw), order=1)
                # Aplicar máscara: donde no había eco, forzar a 0
                field = np.where(mask > 0.3, field, 0)
            else:
                # Ya reproyectado a hires: solo suavizado leve
                field = gaussian_filter(field, sigma=1.0)
        except Exception as e:
            log.warning(f"    Suavizado radar falló: {e}")

    # ── Discrete NWS colormap para radar ──
    if rcfg.get('discrete') and rcfg['colors'] == 'nws_refl':
        rgba = render_nws_refl(field)
        out_w, out_h = BASE['img_width_hires'], BASE['img_height_hires']
    else:
        norm = np.clip((field - rcfg['vmin']) / (rcfg['vmax'] - rcfg['vmin']), 0, 1)
        cmap = mcolors.LinearSegmentedColormap.from_list('c', rcfg['colors'], N=256)
        rgba = cmap(norm)

        if var_name in HIRES_VARS:
            rgba[:, :, 3] = np.where(field > 15, 0.92, 0.0)
            out_w, out_h = BASE['img_width_hires'], BASE['img_height_hires']
        elif var_name == 'jet250':
            # Jet: solo visible donde supera 50 kt
            rgba[:, :, 3] = np.where(field > 50, 0.85, 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name == 'tempAnom':
            # Anomalía: 80% opaco, escala divergente
            rgba[:, :, 3] = 0.80
            out_w, out_h = BASE['img_width'], BASE['img_height']
        else:
            rgba[:, :, 3] = 0.70
            out_w, out_h = BASE['img_width'], BASE['img_height']

    img_full = Image.fromarray((rgba * 255).astype(np.uint8), 'RGBA')
    # Si el campo ya fue ampliado a hires (grid regular suavizado), no resize
    if (needs_reproject and lats.ndim == 2) or \
       (var_name in {'reflectivity', 'refd1km'} and field.shape[0] == BASE['img_height_hires']):
        img_out = img_full
    else:
        img_out = img_full.resize((out_w, out_h), Image.BILINEAR)
    img_out.save(output_path, 'PNG', optimize=True)
    return True


# =============================================================================
# RENDER ISOBARS (contornos de presión MSLP)
# =============================================================================
def render_isobars(prmsl_pa, lats, lons, output_path, needs_reproject=False):
    """Renderiza isobaras como líneas de contorno PNG transparente.
    Líneas cada 4 mb, etiquetadas, color rojo para >1016 mb (alta) y azul <1012 mb (baja).
    """
    field = prmsl_pa / 100.0  # Pa → mb
    field = np.where(np.isnan(field), 1013.25, field)

    if needs_reproject and lats.ndim == 2:
        field = reproject_cached(field, lats, lons, BASE['img_height'], BASE['img_width'])

    # Suavizado leve para mejor estética de contornos
    try:
        from scipy.ndimage import gaussian_filter
        field = gaussian_filter(field, sigma=1.5)
    except Exception:
        pass

    out_w, out_h = BASE['img_width'], BASE['img_height']
    fig = plt.figure(figsize=(out_w / 100, out_h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, field.shape[1])
    ax.set_ylim(field.shape[0], 0)
    ax.axis('off')
    fig.patch.set_alpha(0)

    levels_low  = np.arange(960, 1013, 4)
    levels_high = np.arange(1016, 1056, 4)
    levels_mid  = [1012, 1013, 1014, 1015]

    # Rojo: alta (≥1016)
    cs_high = ax.contour(field, levels=levels_high, colors='#c62828', linewidths=1.0)
    ax.clabel(cs_high, inline=True, fontsize=7, fmt='%d', colors='#c62828')
    # Azul: baja (≤1012)
    cs_low = ax.contour(field, levels=levels_low, colors='#1565c0', linewidths=1.0)
    ax.clabel(cs_low, inline=True, fontsize=7, fmt='%d', colors='#1565c0')
    # Gris: rango medio
    cs_mid = ax.contour(field, levels=levels_mid, colors='#616161', linewidths=0.7,
                        linestyles='dashed')

    fig.savefig(output_path, dpi=100, transparent=True, bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    return True


# =============================================================================
# UPLOAD
# =============================================================================
def upload(filepath, cdn_key, content_type='image/png'):
    cmd = ['aws', 's3', 'cp', filepath, f"s3://{BASE['cdn_bucket']}/{cdn_key}",
           '--profile', BASE['aws_profile'], '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=600',
           '--endpoint-url', BASE['cdn_endpoint']]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    except Exception:
        return False


# =============================================================================
# PROCESS HOUR
# =============================================================================
def process_hour(model_cfg, date, cycle, fhour, cycle_dt):
    """Process one forecast hour."""
    t0 = time.time()
    model_id = model_cfg['name'].lower()
    valid_dt = cycle_dt + timedelta(hours=fhour)
    hour_imgs = {}
    hour_points = {}
    img_dir = f"/opt/canalmeteo/data/{model_id}/images"
    Path(img_dir).mkdir(parents=True, exist_ok=True)

    # ── DOWNLOAD all groups ──
    all_fields = {}
    total_bytes = 0
    for group in model_cfg['groups']:
        grib_path, nbytes, gname = download_group(model_cfg, date, cycle, fhour, group)
        total_bytes += nbytes
        if grib_path:
            fields = extract_fields(grib_path, model_cfg['fields'], group_name=gname)
            all_fields.update(fields)
            try: os.remove(grib_path)
            except Exception: pass

    if not all_fields:
        return None

    log.info(f"    Downloaded: {total_bytes//1024} KB · Fields: {list(all_fields.keys())}")

    # ── DERIVED: viento de superficie (10m) desde UGRD/VGRD ──
    if 'u10' in all_fields and 'v10' in all_fields:
        u_data, u_lats, u_lons = all_fields['u10']
        v_data, _, _ = all_fields['v10']
        wspd = np.sqrt(u_data**2 + v_data**2)
        wdir = (270 - np.degrees(np.arctan2(v_data, u_data))) % 360
        all_fields['_wspd'] = (wspd, u_lats, u_lons)
        all_fields['_wdir'] = (wdir, u_lats, u_lons)
        model_cfg['fields']['_wspd'] = 'wspdMph'
        model_cfg['fields']['_wdir'] = 'wdir'

    # ── DERIVED: jet 250 mb (magnitud del viento) ──
    if 'u250' in all_fields and 'v250' in all_fields:
        u, lt, ln = all_fields['u250']
        v, _, _ = all_fields['v250']
        jet = np.sqrt(u**2 + v**2)
        all_fields['_jet250'] = (jet, lt, ln)
        model_cfg['fields']['_jet250'] = 'jet250'

    # ── DERIVED: viento 850 mb (magnitud) ──
    if 'u850' in all_fields and 'v850' in all_fields:
        u, lt, ln = all_fields['u850']
        v, _, _ = all_fields['v850']
        w850 = np.sqrt(u**2 + v**2)
        all_fields['_wind850'] = (w850, lt, ln)
        model_cfg['fields']['_wind850'] = 'wind850'

    # ── DERIVED: temperatura 850 mb (renombre directo) ──
    if 't850' in all_fields:
        model_cfg['fields']['t850'] = 'temp850C'

    # ── DERIVED: anomalía de temperatura ──
    anom_src = model_cfg.get('compute_anomaly_from')
    if anom_src and anom_src in all_fields:
        t_data, t_lats, t_lons = all_fields[anom_src]
        # Convertir a °F primero
        t_F = (t_data - 273.15) * 9/5 + 32
        # Reproyectar si Lambert
        if t_lats.ndim == 2:
            t_F_reg = reproject_cached(t_F, t_lats, t_lons,
                                       BASE['img_height'], BASE['img_width'])
            anom = compute_temp_anomaly(t_F_reg, t_lats, t_lons, valid_dt)
        else:
            anom = compute_temp_anomaly(t_F, t_lats, t_lons, valid_dt)
        if anom is not None:
            # Las coords ya son grid regular del tamaño de la climatología
            lat_reg = np.linspace(BASE['lat_max'], BASE['lat_min'], anom.shape[0])
            lon_reg = np.linspace(BASE['lon_min'], BASE['lon_max'], anom.shape[1])
            all_fields['_tempAnom'] = (anom, lat_reg, lon_reg)
            model_cfg['fields']['_tempAnom'] = 'tempAnom'

    # ── PROCESS each field (PNG + GeoJSON points) ──
    for grib_field, (data, lats, lons) in all_fields.items():
        if grib_field not in model_cfg['fields']:
            continue
        var_name = model_cfg['fields'][grib_field]
        if var_name not in CONVERTERS:
            continue
        convert_fn = CONVERTERS[var_name]

        # GeoJSON points (solo para variables 2D nativas, no derivadas globales)
        gjstep = 20
        if lats.ndim == 2 and var_name not in {'tempAnom', 'jet250', 'wind850', 'temp850C'}:
            for iy in range(0, lats.shape[0], gjstep):
                for ix in range(0, lats.shape[1], gjstep):
                    la, lo = float(lats[iy, ix]), float(lons[iy, ix])
                    if lo > 180: lo -= 360
                    if la < BASE['lat_min'] or la > BASE['lat_max']: continue
                    if lo < BASE['lon_min'] or lo > BASE['lon_max']: continue
                    val = float(data[iy, ix])
                    if np.isnan(val): continue
                    cv = convert_fn(val)
                    if hasattr(cv, '__len__'): cv = float(cv)
                    key = (round(la, 2), round(lo, 2))
                    if key not in hour_points: hour_points[key] = {}
                    hour_points[key][var_name] = round(float(cv), 1)

        # Render PNG
        needs_reproj = (lats.ndim == 2) or (model_cfg['name'] in ('HRRR', 'HRRR_EXT'))
        png_path = os.path.join(img_dir, f"{model_id}_{var_name}_f{fhour:03d}.png")
        if render_png(data, lats, lons, var_name, convert_fn, png_path,
                      needs_reproject=needs_reproj):
            cdn_key = f"data/{model_id}/{model_id}_{var_name}_f{fhour:03d}.png"
            if upload(png_path, cdn_key):
                hour_imgs[var_name] = f"{BASE['cdn_base']}/{cdn_key}"

    # ── ISOBARAS (contornos de PRMSL) ──
    if model_cfg.get('render_isobars') and 'prmsl' in all_fields:
        try:
            p_data, p_lats, p_lons = all_fields['prmsl']
            iso_path = os.path.join(img_dir, f"{model_id}_isobaras_f{fhour:03d}.png")
            if render_isobars(p_data, p_lats, p_lons, iso_path,
                              needs_reproject=(p_lats.ndim == 2)):
                cdn_key = f"data/{model_id}/{model_id}_isobaras_f{fhour:03d}.png"
                if upload(iso_path, cdn_key):
                    hour_imgs['isobaras'] = f"{BASE['cdn_base']}/{cdn_key}"
                    log.info(f"    ✅ isobaras")
        except Exception as e:
            log.warning(f"    isobaras error: {e}")

    # ── PRECIP TYPE composite (existente) ──
    refl_data = None; refl_lats = refl_lons = None
    for rkey in ['refd1km', 'reflectivity']:
        gf = [k for k, v in model_cfg['fields'].items() if v == rkey]
        for gk in gf:
            if gk in all_fields:
                refl_data, refl_lats, refl_lons = all_fields[gk]
                break
        if refl_data is not None: break

    has_ptype = all(k in all_fields for k in ['crain', 'csnow', 'cfrzr', 'cicep']
                    if k in model_cfg['fields'].keys())

    if refl_data is not None and has_ptype:
        try:
            cr = all_fields.get('crain', (np.zeros_like(refl_data),))[0]
            cs = all_fields.get('csnow', (np.zeros_like(refl_data),))[0]
            cf = all_fields.get('cfrzr', (np.zeros_like(refl_data),))[0]
            ci = all_fields.get('cicep', (np.zeros_like(refl_data),))[0]

            if refl_lats.ndim == 2:
                th, tw = BASE['img_height_hires'], BASE['img_width_hires']
                refl_data = reproject_cached(refl_data, refl_lats, refl_lons, th, tw)
                cr = reproject_cached(cr, refl_lats, refl_lons, th, tw)
                cs = reproject_cached(cs, refl_lats, refl_lons, th, tw)
                cf = reproject_cached(cf, refl_lats, refl_lons, th, tw)
                ci = reproject_cached(ci, refl_lats, refl_lons, th, tw)

            refl_norm = np.clip(refl_data / 75.0, 0, 1)
            h, w = refl_data.shape[:2]
            mask_valid = refl_data > 5

            cmap = mcolors.LinearSegmentedColormap.from_list('radar',
                ['#00000000','#04e9e7','#019ff4','#0300f4','#02fd02','#01c501','#008e00',
                 '#fdf802','#e5bc00','#fd9500','#fd0000','#d40000','#bc0000','#f800fd','#9854c6','#fdfdfd'], N=256)
            cmap_snow = mcolors.LinearSegmentedColormap.from_list('snow',
                ['#00000000','#b3e5fc','#81d4fa','#4fc3f7','#29b6f6','#039be5','#0277bd',
                 '#01579b','#e1bee7','#ce93d8','#ab47bc','#8e24aa','#6a1b9a','#4a148c','#e0e0e0','#ffffff'], N=256)
            cmap_frzr = mcolors.LinearSegmentedColormap.from_list('frzr',
                ['#00000000','#fce4ec','#f8bbd0','#f48fb1','#f06292','#ec407a','#e91e63',
                 '#d81b60','#c2185b','#ad1457','#880e4f','#ff6f00','#ff8f00','#ffa000','#ffb300','#ffffff'], N=256)
            cmap_ice = mcolors.LinearSegmentedColormap.from_list('ice',
                ['#00000000','#e8eaf6','#c5cae9','#9fa8da','#7986cb','#5c6bc0','#3f51b5',
                 '#3949ab','#303f9f','#283593','#1a237e','#b388ff','#7c4dff','#651fff','#6200ea','#ffffff'], N=256)

            rgba_rain = cmap(refl_norm)
            rgba_snow = cmap_snow(refl_norm)
            rgba_frzr = cmap_frzr(refl_norm)
            rgba_ice  = cmap_ice(refl_norm)

            final = np.copy(rgba_rain)
            snow_mask = (cs > 0.5) & mask_valid
            frzr_mask = (cf > 0.5) & mask_valid
            ice_mask  = (ci > 0.5) & mask_valid
            final[snow_mask] = rgba_snow[snow_mask]
            final[frzr_mask] = rgba_frzr[frzr_mask]
            final[ice_mask]  = rgba_ice[ice_mask]
            final[:, :, 3] = np.where(mask_valid, 0.92, 0)

            img_full = Image.fromarray((final * 255).astype(np.uint8), 'RGBA')
            if refl_lats.ndim == 2:
                img_out = img_full
            else:
                img_out = img_full.resize((BASE['img_width_hires'],
                                           BASE['img_height_hires']), Image.BILINEAR)
            ptype_path = os.path.join(img_dir, f"{model_id}_ptypeRefl_f{fhour:03d}.png")
            img_out.save(ptype_path, 'PNG', optimize=True)
            cdn_key = f"data/{model_id}/{model_id}_ptypeRefl_f{fhour:03d}.png"
            if upload(ptype_path, cdn_key):
                hour_imgs['ptypeRefl'] = f"{BASE['cdn_base']}/{cdn_key}"
                log.info(f"    ✅ ptypeRefl")
        except Exception as e:
            log.warning(f"    ptypeRefl error: {e}")

    elapsed = time.time() - t0
    log.info(f"    f{fhour:03d}: {len(hour_imgs)} PNGs · {elapsed:.0f}s")

    if hour_imgs:
        return {'fhour': fhour, 'validTime': valid_dt.isoformat(),
                'validTimeUnix': int(valid_dt.timestamp()), 'images': hour_imgs}
    return None


# =============================================================================
# MAIN
# =============================================================================
def acquire_internal_lock(model_id):
    """Lock interno (independiente del de flock) para detectar ejecuciones simultáneas
    aunque el lock externo no esté activo."""
    import fcntl
    lock_path = f"/tmp/canalmeteo_model_{model_id}.lock"
    try:
        lock_file = open(lock_path, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(f"{os.getpid()}\n")
        lock_file.flush()
        return lock_file
    except (IOError, OSError):
        log.error(f"⛔ Otro proceso ya está ejecutando model_pipeline para {model_id}")
        log.error(f"   Lock: {lock_path}")
        log.error(f"   Si estás seguro de que no hay otro proceso, borra el archivo.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='nbm', choices=['nbm', 'gfs', 'hrrr', 'hrrr_ext'])
    args = parser.parse_args()

    model_cfg = MODELS[args.model]
    # Para que el KDTree disk cache sepa qué modelo está corriendo
    global _current_model_name
    _current_model_name = model_cfg['name']
    model_id = model_cfg['name'].lower()

    # Lock interno — previene 2 instancias del mismo modelo aunque el lock
    # externo de cron (flock) esté libre. Crítico tras incidente del 26-abr.
    _lock_handle = acquire_internal_lock(model_id)

    t_start = time.time()
    log.info("=" * 50)
    log.info(f"Model Pipeline v5 — {model_cfg['name']} — Canal Meteo TV")
    log.info("=" * 50)

    date, cycle = find_latest_cycle(model_cfg)
    if not date:
        log.error("No cycle available"); return

    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    manifest_hours = []

    forecast_hours = model_cfg['forecast_hours']
    # NOTA: Antes existía una lógica que extendía automáticamente HRRR a 48h
    # en ciclos principales. Ahora eso es responsabilidad del modelo 'hrrr_ext'
    # separado. HRRR mantiene siempre 0-18h en todos los ciclos.

    # Pre-cargar climatología una vez (si existe)
    load_climatology()

    for i, fh in enumerate(forecast_hours):
        log.info(f"--- f{fh:03d} ({i+1}/{len(forecast_hours)}) ---")
        try:
            result = process_hour(model_cfg, date, cycle, fh, cycle_dt)
            if result:
                manifest_hours.append(result)
        except Exception as e:
            log.error(f"  ❌ f{fh:03d} falló: {e} — continuando con la siguiente hora")
            import traceback
            log.debug(traceback.format_exc())

        # Free memory
        import gc, glob
        for g in glob.glob(f"/opt/canalmeteo/data/{model_id}/*.grib2"):
            try: os.remove(g)
            except Exception: pass
        for g in glob.glob(f"/opt/canalmeteo/data/{model_id}/*.idx"):
            try: os.remove(g)
            except Exception: pass

        # Liberar KDTree cache si crece demasiado (evita OOM en runs largos)
        global _kdtree_cache
        if len(_kdtree_cache) > 6:
            _kdtree_cache.clear()
        gc.collect()

        # Partial manifest cada 12 horas
        if manifest_hours and (i + 1) % 12 == 0:
            partial_manifest = {
                'model': model_cfg['name'], 'version': 'raster-v5',
                'cycle': f"{date}/{cycle}z",
                'generated': datetime.now(timezone.utc).isoformat(),
                'bounds': {'north': BASE['lat_max'], 'south': BASE['lat_min'],
                           'east': BASE['lon_max'], 'west': BASE['lon_min']},
                'variables': {k: {'label': v['label'], 'unit': v['unit'],
                                  'vmin': v['vmin'], 'vmax': v['vmax']}
                             for k, v in RENDER_VARS.items()},
                'hours': manifest_hours
            }
            mpath = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
            with open(mpath, 'w') as f: json.dump(partial_manifest, f)
            upload(mpath, f"data/{model_id}/{model_id}_manifest.json", 'application/json')
            log.info(f"  📤 Partial manifest: {len(manifest_hours)} hours")

        time.sleep(1)

    if manifest_hours:
        manifest = {
            'model': model_cfg['name'], 'version': 'raster-v5',
            'cycle': f"{date}/{cycle}z",
            'generated': datetime.now(timezone.utc).isoformat(),
            'bounds': {'north': BASE['lat_max'], 'south': BASE['lat_min'],
                       'east': BASE['lon_max'], 'west': BASE['lon_min']},
            'variables': {k: {'label': v['label'], 'unit': v['unit'],
                              'vmin': v['vmin'], 'vmax': v['vmax'],
                              'colors': v['colors']}
                         for k, v in RENDER_VARS.items()},
            'hours': manifest_hours,
        }
        tmp = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
        with open(tmp, 'w') as f:
            json.dump(manifest, f, separators=(',', ':'))
        if upload(tmp, f"data/{model_id}/{model_id}_manifest.json", 'application/json'):
            log.info(f"✅ Manifest uploaded")

    total = sum(len(h['images']) for h in manifest_hours)
    log.info(f"✅ {model_cfg['name']}: {total} images, {len(manifest_hours)} hours "
             f"in {time.time() - t_start:.0f}s")


if __name__ == '__main__':
    main()
