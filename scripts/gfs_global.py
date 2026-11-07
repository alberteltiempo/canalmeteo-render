#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GFS Global Pipeline — Canal Meteo TV
=====================================
GFS 0.25° en cobertura MUNDIAL (Europa, LatAm, todo el mundo), renderizado en
proyección Web Mercator para alinear con Mapbox.

Fuente : NOMADS filter_gfs_0p25.pl (SIN subregión = malla global 721×1440)
Salida : data/gfs_global/gfs_global_{var}_f{NNN}.png + gfs_global_manifest.json
Ciclos : 00/12z (2×/día — suficiente para uso global; CONUS ya cubre 4×/día)

Diferencias vs model_pipeline_multi.py (CONUS):
  - malla lat/lon REGULAR (no Lambert, no curvilínea) -> sin KDTree, remuestreo 1D
  - longitud nativa 0..360 -> rotar a -180..180 (centrar en América/Atlántico)
  - latitud remuestreada a Web Mercator (mismo fix validado en RTOFS)
  - dominio mundial propio (no el CONUS de BASE)
Reutiliza las convenciones: upload aws s3, manifest con bounds, paletas idénticas.

13/09: corre en nimbus-03 (antes nimbus-02). Pintado y subida en paralelo por
variable (CM_HILOS); descargas de NOMADS en serie a propósito (rate-limit).
CM_CDN_SUFIJO=_test publica aparte para probar. Las horas que fallan se
reintentan al final de la pasada.
"""

import os
import sys
import json
import re
import time
import signal
import argparse
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import manifest_relleno   # 15/09: nunca publicar una línea de tiempo más corta
import numpy as np
import cfgrib
import matplotlib
matplotlib.use('Agg')
import matplotlib.colors as mcolors
from PIL import Image

import logging
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('gfs_global')

# =============================================================================
# CONFIG
# =============================================================================
BASE = {
    'aws_profile':  'do-tor1',
    'cdn_bucket':   'canalmeteo-public',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',
    'cdn_base':     'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com',
    'user_agent':   'CanalMeteoTV/1.0',
}

# Pruebas antes de cortar (CM_CDN_SUFIJO=_test) y pintado/subida en paralelo
# (CM_HILOS; 1 = en serie), igual que ecmwf_global.py
SUFIJO = os.environ.get('CM_CDN_SUFIJO', '')
HILOS = max(1, int(os.environ.get('CM_HILOS', '1')))

MODEL_ID = 'gfs_global'
MID = MODEL_ID + SUFIJO          # prefijo en el CDN y carpeta local
DATA_DIR = f'/opt/canalmeteo/data/{MID}'
IMG_DIR  = f'{DATA_DIR}/images'

FILTER = 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl'
FILE_TMPL = 'gfs.t{cc}z.pgrb2.0p25.f{fh:03d}'
DIR_TMPL = '/gfs.{dd}/{cc}/atmos'
CYCLES = [0, 12]                         # 2×/día
# Horas: 0-48 horario, luego cada 3h hasta 120 (5 días). Global no necesita más resolución.
FORECAST_HOURS = list(range(0, 49)) + list(range(51, 121, 3))

# Dominio mundial. Mapbox Web Mercator es útil hasta ~±85°; recortamos a ±80 para
# evitar la singularidad de Mercator en los polos.
DOMAIN = {'lat_min': -80.0, 'lat_max': 80.0, 'lon_min': -180.0, 'lon_max': 180.0}

# Resolución de salida del PNG (equilibrio nitidez/RAM; a escala global sobra)
OUT_W, OUT_H = 2048, 1024

# Grupos a descargar (mismas variables esenciales que CONUS)
# PRATE (tasa instantánea) en vez de APCP: APCP se reinicia cada 6h y no permite
# acumular bien; PRATE es instantáneo y se integra limpio para la lluvia acumulada.
GROUPS = [
    {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
    {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on'},
    {'name': 'sfc', 'params': ('var_GUST=on&var_TCDC=on&var_CAPE=on&var_PRATE=on&var_PRMSL=on&'
                               'var_LAND=on&'
                               'lev_surface=on&lev_mean_sea_level=on&lev_entire_atmosphere=on')},
    # Niveles de presión (el filtro cruza vars×niveles; los mensajes sobrantes se ignoran)
    {'name': 'pl',  'params': ('var_TMP=on&var_UGRD=on&var_VGRD=on&var_HGT=on&var_ABSV=on&'
                               'lev_850_mb=on&lev_500_mb=on&lev_250_mb=on')},
    {'name': 'pl7', 'params': 'var_RH=on&lev_700_mb=on'},
]

# Mapeo nombre cfgrib -> nombre interno (subconjunto de CONUS)
FIELD_MAP = {
    't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
    'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
    'tcc': 'cloudPct', 'cape': 'cape', 'prate': 'prate', 'prmsl': 'pressureMb',
    'lsm': 'landMask',   # LAND 0/1: máscara para las variantes solo-continente
}

# Variantes solo-continente (#24b app): mismo campo y paleta, océano transparente.
# La app las usa en temp_overlay/wind_overlay; Tormenta sigue con las completas
# (el viento sobre el océano importa en cobertura tropical).
LAND_VARIANTS = {'tempF': 'tempFLand', 'wspdMph': 'wspdMphLand'}

# Mapeo (nombre cfgrib, nivel hPa) -> nombre interno crudo (los deriva derive_levels)
PL_FIELD_MAP = {
    ('t', 850): 't850', ('u', 850): 'u850', ('v', 850): 'v850',
    ('u', 250): 'u250', ('v', 250): 'v250',
    ('gh', 500): 'gh500_src', ('t', 500): 't500',
    ('u', 500): 'u500', ('v', 500): 'v500', ('absv', 500): 'absv500',
    ('r', 700): 'r700',
}

# Variables que se renderizan EN CADA HORA (instantáneas)
# 'precipRate' (tasa) sale de prate; 'precipAccum' (acumulado) lo hace el orquestador.
RENDER_LIST = ['tempF', 'dewpF', 'rh', 'wspdMph', 'gustMph',
               'cloudPct', 'cape', 'precipRate', 'pressureMb',
               'temp850C', 'wind850', 'jet250',
               'gh500', 'temp500C', 'wind500', 'vort500', 'rh700',
               'tempAnom']   # 14/09/2026: anomalía vs normales CPC 1991-2020 (clim_global)

# =============================================================================
# CONVERSIONES (idénticas a CONUS)
# =============================================================================
CONVERT = {
    'tempF':      lambda k: (k - 273.15) * 9 / 5 + 32,
    'tempAnom':   lambda f: f,                       # ya en °F (clim_global)
    'dewpF':      lambda k: (k - 273.15) * 9 / 5 + 32,
    'rh':         lambda x: x,
    'wspdMph':    lambda ms: ms * 2.237,
    'gustMph':    lambda ms: ms * 2.237,
    'cloudPct':   lambda x: x,
    'cape':       lambda x: x,
    # PRATE kg/m²/s -> in/h:  *3600 s/h = mm/h, /25.4 = in/h
    'precipRate': lambda kgms: np.where(kgms > 0, kgms * 3600.0 / 25.4, 0),
    # Acumulado ya viene en mm (lo calcula el orquestador) -> in
    'precipAccum': lambda mm: np.where(mm > 0, mm / 25.4, 0),
    'pressureMb': lambda pa: pa / 100.0,
    # Niveles altos: derive_levels ya entrega unidades finales
    'temp850C': lambda x: x, 'wind850': lambda x: x, 'jet250': lambda x: x,
    'gh500': lambda x: x, 'temp500C': lambda x: x, 'wind500': lambda x: x,
    'vort500': lambda x: x, 'rh700': lambda x: x,
}

# =============================================================================
# PALETAS (idénticas a RENDER_VARS de CONUS — para leyenda consistente)
# =============================================================================
import escala_lluvia as _el
RENDER_VARS = {
    'tempAnom': {'label': 'Anomalía temp. (°F)', 'unit': '°F', 'vmin': -25, 'vmax': 25, 'alpha': 0.80,
                 'colors': ['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7',
                            '#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']},
    'tempF':    {'label': 'Temperatura (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 110, 'alpha': 0.70,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a',
                            '#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'dewpF':    {'label': 'Punto de rocío (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 80, 'alpha': 0.70,
                 'colors': ['#4e342e','#6d4c41','#a1887f','#e0e0e0','#a5d6a7','#66bb6a','#2e7d32',
                            '#00e676','#0097a7','#01579b','#4a148c']},
    'rh':       {'label': 'Humedad (%)', 'unit': '%', 'vmin': 0, 'vmax': 100, 'alpha': 0.65,
                 'colors': ['#b71c1c','#e65100','#f57f17','#cddc39','#8bc34a','#43a047','#2e7d32','#1565c0','#0d47a1']},
    'wspdMph':  {'label': 'Viento (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 60, 'alpha': 0.70,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c']},
    'gustMph':  {'label': 'Ráfagas (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 80, 'alpha': 0.70,
                 'colors': ['#e0e0e0','#81d4fa','#29b6f6','#ffeb3b','#ffa726','#ff7043','#e53935','#b71c1c','#4a148c']},
    'cloudPct': {'label': 'Nubes (%)', 'unit': '%', 'vmin': 0, 'vmax': 100, 'alpha': 0.65,
                 'colors': ['#0d47a1','#1565c0','#42a5f5','#90caf9','#e0e0e0','#bdbdbd','#9e9e9e','#757575','#424242']},
    'cape':     {'label': 'CAPE (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 4000, 'alpha': 0.70,
                 'colors': ['#263238','#37474f','#4caf50','#8bc34a','#ffeb3b','#ff9800','#f44336','#d32f2f','#880e4f']},
    'precipRate': {'label': 'Precipitación (in/h)', 'unit': 'in/h', 'vmin': 0, 'vmax': 1.5, 'alpha': 0.75,
                 'colors': ['#263238','#1b5e20','#4caf50','#a5d6a7','#ffeb3b','#ff9800','#f44336','#e040fb']},
    'precipAccum': {'label': 'Lluvia acumulada (in)', 'unit': 'in', 'vmin': 0, 'vmax': 20.0, 'alpha': 0.80,
                 # 22/09: escala común (escala_lluvia), muestreada cada 0.05" para los
                 # renderizadores y leyendas que reparten los colores por igual
                 'colors': _el.colores_lineales(20.0, 0.05),
                 'stops': [x for x in _el.stops_json('in') if x['value'] <= 20.0]},
    'pressureMb': {'label': 'Presión nivel del mar (mb)', 'unit': 'mb', 'vmin': 980, 'vmax': 1050, 'alpha': 0.65,
                 'colors': ['#4a148c','#1565c0','#42a5f5','#81c784','#ffeb3b','#ff9800','#e53935','#880e4f']},
    # Niveles altos (paletas idénticas a ecmwf_global.py / VARS del visor)
    'temp850C': {'label': 'Temp. 850 mb (°C)', 'unit': '°C', 'vmin': -40, 'vmax': 30, 'alpha': 0.70,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#01579b','#0097a7','#00897b','#43a047',
                            '#cddc39','#ffeb3b','#ffa726','#ef5350','#c62828','#880e4f']},
    'jet250':   {'label': 'Jet 250 mb (kt)', 'unit': 'kt', 'vmin': 50, 'vmax': 200, 'alpha': 0.85,
                 'colors': ['#a5d6a7','#cddc39','#ffeb3b','#ffa726','#ef5350','#c62828','#880e4f','#6a1b9a','#311b92']},
    'wind850':  {'label': 'Viento 850 mb (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 70, 'alpha': 0.70,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f']},
    'gh500':    {'label': 'Geopotencial 500 mb (dam)', 'unit': 'dam', 'vmin': 480, 'vmax': 600, 'alpha': 0.70,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#43a047','#cddc39','#ffeb3b','#ffa726','#e53935','#880e4f']},
    'temp500C': {'label': 'Temp. 500 mb (°C)', 'unit': '°C', 'vmin': -45, 'vmax': 5, 'alpha': 0.70,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#01579b','#0097a7','#00897b','#43a047',
                            '#cddc39','#ffeb3b','#ffa726','#ef5350','#c62828','#880e4f']},
    'wind500':  {'label': 'Viento 500 mb (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 120, 'alpha': 0.70,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c']},
    'vort500':  {'label': 'Vorticidad 500 mb (10⁻⁵/s)', 'unit': '1e-5/s', 'vmin': -30, 'vmax': 30, 'alpha': 0.70,
                 'colors': ['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7','#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']},
    'rh700':    {'label': 'Humedad 700 mb (%)', 'unit': '%', 'vmin': 0, 'vmax': 100, 'alpha': 0.65,
                 'colors': ['#b71c1c','#e65100','#f57f17','#cddc39','#8bc34a','#43a047','#2e7d32','#1565c0','#0d47a1']},
}

# =============================================================================
# UPLOAD (idéntico a CONUS)
# =============================================================================
_CDN_LOCK = threading.Lock()


def _cdn():
    with _CDN_LOCK:
        if not hasattr(upload, '_c'):
            import boto3
            upload._c = boto3.Session(profile_name=BASE['aws_profile']).client(
                's3', endpoint_url=BASE['cdn_endpoint'])
    return upload._c


def _borrar(*rutas):
    for r in rutas:
        if r:
            try:
                os.remove(r)
            except OSError:
                pass


def upload(filepath, cdn_key, content_type='image/png'):
    # boto3 en proceso (limpieza de carga 26/07: cientos de spawns del CLI/run)
    try:
        _cdn().upload_file(str(filepath), BASE['cdn_bucket'], cdn_key,
                              ExtraArgs={'ACL': 'public-read',
                                         'ContentType': content_type,
                                         'CacheControl': 'max-age=600'})
        return True
    except Exception as e:
        log.warning(f"    upload falló {cdn_key}: {e}")
        return False

# =============================================================================
# CYCLE DETECTION
# =============================================================================
def detect_cycle():
    """Último ciclo (00/12z) con el f120 ya publicado (valida en la última hora)."""
    now = datetime.now(timezone.utc)
    for back in range(0, 30, 6):
        t = now - timedelta(hours=back)
        cc = max([c for c in CYCLES if c <= t.hour], default=None)
        if cc is None:
            # bajar al ciclo previo del día anterior
            t = t - timedelta(days=1); cc = CYCLES[-1]
        dd = t.strftime('%Y%m%d')
        # validar última hora de pronóstico
        url = (f"{FILTER}?dir=%2F{DIR_TMPL.format(dd=dd, cc=f'{cc:02d}').lstrip('/')}"
               f"&file={FILE_TMPL.format(cc=f'{cc:02d}', fh=FORECAST_HOURS[-1])}"
               f"&var_TMP=on&lev_2_m_above_ground=on")
        try:
            r = subprocess.run(['curl', '-sI', '-o', '/dev/null', '-w', '%{http_code}', url],
                               capture_output=True, text=True, timeout=30)
            if r.stdout.strip() == '200':
                log.info(f"Ciclo GFS global: {dd}/{cc:02d}z")
                return dd, f'{cc:02d}'
        except Exception:
            continue
    return None, None

# =============================================================================
# DESCARGA
# =============================================================================
def download_group(date, cycle, fhour, group):
    os.makedirs(DATA_DIR, exist_ok=True)
    out = f"{DATA_DIR}/{MODEL_ID}_{group['name']}_{date}_{cycle}z_f{fhour:03d}.grib2"
    dir_path = DIR_TMPL.format(dd=date, cc=cycle)
    fname = FILE_TMPL.format(cc=cycle, fh=fhour)
    url = (f"{FILTER}?dir=%2F{dir_path.lstrip('/')}&file={fname}&{group['params']}")
    try:
        r = subprocess.run(['curl', '-sL', '--fail', '-o', out, url],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 500:
            return out
    except Exception as e:
        log.warning(f"    {group['name']}: {e}")
    return None

# =============================================================================
# REMUESTREO A MERCATOR + ROTACIÓN DE LONGITUD
# =============================================================================
_LAT_IDX = None   # índices de fila nativa para cada fila Mercator de salida
_LON_IDX = None   # índices de columna nativa rotada para cada columna de salida

def _merc_lat_grid():
    """Latitudes (grados) de las filas de salida, equiespaciadas en Web Mercator."""
    def my(lat): return np.log(np.tan(np.pi/4 + np.radians(lat)/2))
    yt, yb = my(DOMAIN['lat_max']), my(DOMAIN['lat_min'])
    ym = np.linspace(yt, yb, OUT_H)
    return np.degrees(2*np.arctan(np.exp(ym)) - np.pi/2)

def build_index(nat_lat, nat_lon):
    """Construye índices BILINEALES de remuestreo desde la malla nativa (regular)
    a la rejilla de salida (Mercator en lat, lineal -180..180 en lon).
    Guarda, por cada fila/columna de salida, los dos índices nativos vecinos y el
    peso fraccionario entre ellos, para interpolación bilineal (suaviza el pixelado).
    Cacheado: la malla nativa no cambia entre horas."""
    global _LAT_IDX, _LON_IDX
    if _LAT_IDX is not None:
        return _LAT_IDX, _LON_IDX

    def frac_index(coord_out, coord_nat):
        """Para cada coord de salida devuelve (idx0, idx1, peso) sobre la malla nativa."""
        # np.interp sobre el índice nativo da posición fraccionaria
        n = len(coord_nat)
        # coord_nat debe ser monótona creciente para interp; si decrece, invertir
        if coord_nat[0] > coord_nat[-1]:
            order = np.arange(n)[::-1]
            pos = np.interp(coord_out, coord_nat[::-1], order.astype(float))
        else:
            pos = np.interp(coord_out, coord_nat, np.arange(n, dtype=float))
        i0 = np.floor(pos).astype(int).clip(0, n - 1)
        i1 = (i0 + 1).clip(0, n - 1)
        w = (pos - i0).astype('float32')
        return i0, i1, w

    out_lat = _merc_lat_grid()                       # 80..-80
    out_lon = np.linspace(DOMAIN['lon_min'], DOMAIN['lon_max'], OUT_W)
    out_lon360 = np.where(out_lon < 0, out_lon + 360, out_lon)

    _LAT_IDX = frac_index(out_lat, nat_lat)          # (i0, i1, w) en filas
    _LON_IDX = frac_index(out_lon360, nat_lon)       # (i0, i1, w) en columnas
    return _LAT_IDX, _LON_IDX

def resample(field, nat_lat, nat_lon):
    """Remuestrea un campo nativo (721×1440) a la rejilla de salida Mercator/rotada
    con interpolación BILINEAL (suaviza el pixelado del nearest)."""
    (yi0, yi1, wy), (xi0, xi1, wx) = build_index(nat_lat, nat_lon)
    # Interpolar primero en filas (lat), luego en columnas (lon)
    # f[y, x] tras seleccionar filas vecinas y mezclar
    top = field[yi0]                 # (OUT_H, n_lon_nat)
    bot = field[yi1]
    rows = top * (1 - wy[:, None]) + bot * wy[:, None]   # (OUT_H, n_lon_nat)
    left = rows[:, xi0]              # (OUT_H, OUT_W)
    right = rows[:, xi1]
    out = left * (1 - wx[None, :]) + right * wx[None, :]
    return out.astype('float32')

# =============================================================================
# EXTRACT FIELDS (malla regular — simple)
# =============================================================================
def extract_fields(grib_path):
    """Devuelve {nombre_interno: (array2D, lat1D, lon1D)} para los campos conocidos.
    Cierra cada dataset explícitamente: cfgrib.open_datasets deja handles de
    archivo y buffers que el GC no recoge, causando fuga de RAM hora a hora."""
    found = {}
    datasets = []
    try:
        datasets = cfgrib.open_datasets(grib_path, backend_kwargs={'indexpath': ''})
        for ds in datasets:
            lat = ds.latitude.values
            lon = ds.longitude.values
            # Niveles de presión: isobaricInhPa puede ser dimensión (varios niveles)
            # o coordenada escalar (un solo nivel en el dataset)
            if 'isobaricInhPa' in ds.coords:
                levs = np.atleast_1d(ds.isobaricInhPa.values)
                for cf_name in {k[0] for k in PL_FIELD_MAP}:
                    if cf_name not in ds.data_vars:
                        continue
                    da = ds[cf_name]
                    for lev in levs:
                        internal = PL_FIELD_MAP.get((cf_name, int(lev)))
                        if not internal:
                            continue
                        arr = (da.sel(isobaricInhPa=lev).values
                               if 'isobaricInhPa' in da.dims else da.values)
                        if arr.ndim == 2:
                            found[internal] = (arr.astype('float32').copy(), lat.copy(), lon.copy())
                continue
            for cf_name, internal in FIELD_MAP.items():
                if cf_name in ds.data_vars:
                    arr = ds[cf_name].values
                    if arr.ndim == 2:
                        # .copy() para soltar la referencia al buffer del dataset
                        found[internal] = (arr.astype('float32').copy(), lat.copy(), lon.copy())
    except Exception as e:
        log.warning(f"    extract falló: {e}")
    finally:
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass
    return found

# =============================================================================
# RENDER
# =============================================================================
def render_png(field_resampled, var_name, output_path, land_mask=None):
    if var_name not in RENDER_VARS:
        return False
    rcfg = RENDER_VARS[var_name]
    field = CONVERT[var_name](field_resampled.copy())
    nan = np.isnan(field)
    norm = np.clip((field - rcfg['vmin']) / (rcfg['vmax'] - rcfg['vmin']), 0, 1)
    norm = np.where(nan, 0, norm)
    cmap = mcolors.LinearSegmentedColormap.from_list('c', rcfg['colors'], N=1024)
    rgba = cmap(norm)
    # Precipitación: transparente donde no llueve; resto: alpha del cfg
    if var_name in ('precipRate', 'precipAccum'):
        rgba[:, :, 3] = np.where(field > 0.01, rcfg['alpha'], 0.0)
    elif var_name == 'jet250':
        # Jet: solo visible donde supera 50 kt (como CONUS/ECMWF)
        rgba[:, :, 3] = np.where(field > 50, rcfg['alpha'], 0.0)
    else:
        rgba[:, :, 3] = np.where(nan, 0.0, rcfg['alpha'])
    if land_mask is not None:
        # Variante solo-continente: océano 100% transparente (#24b app)
        rgba[:, :, 3] = np.where(land_mask, rgba[:, :, 3], 0.0)
    Image.fromarray((rgba * 255).astype(np.uint8), 'RGBA').save(output_path, 'PNG', optimize=True)
    return True

# =============================================================================
# DERIVAR wspdMph desde u10/v10
# =============================================================================
def derive_wind(fields):
    if 'u10' in fields and 'v10' in fields:
        u, la, lo = fields['u10']
        v = fields['v10'][0]
        spd = np.sqrt(u**2 + v**2)            # m/s
        fields['wspdMph'] = (spd, la, lo)

def derive_levels(fields):
    """Deriva las variables de niveles altos en unidades finales (paletas del visor)."""
    def get(k):
        return fields[k][0] if k in fields else None
    def put(k, arr, ref):
        fields[k] = (arr.astype('float32'), fields[ref][1], fields[ref][2])
    if get('t850') is not None:
        put('temp850C', get('t850') - 273.15, 't850')
    if get('u850') is not None and get('v850') is not None:
        put('wind850', np.hypot(get('u850'), get('v850')) * 2.237, 'u850')
    if get('u250') is not None and get('v250') is not None:
        put('jet250', np.hypot(get('u250'), get('v250')) * 1.94384, 'u250')   # m/s -> kt
    if get('gh500_src') is not None:
        put('gh500', get('gh500_src') / 10.0, 'gh500_src')                    # gpm -> dam
    if get('t500') is not None:
        put('temp500C', get('t500') - 273.15, 't500')
    if get('u500') is not None and get('v500') is not None:
        put('wind500', np.hypot(get('u500'), get('v500')) * 2.237, 'u500')
    if get('absv500') is not None:
        # GFS publica vorticidad ABSOLUTA; ECMWF (y la paleta) usan RELATIVA:
        # restar Coriolis f = 2·Ω·sin(lat) y pasar a 10⁻⁵/s
        arr, la, _ = fields['absv500']
        f_cor = 2.0 * 7.2921e-5 * np.sin(np.radians(la))[:, None]
        put('vort500', (arr - f_cor) * 1e5, 'absv500')
    if get('r700') is not None:
        put('rh700', np.clip(get('r700'), 0, 100), 'r700')

# =============================================================================
# MANIFEST
# =============================================================================
def build_manifest(date, cycle, manifest_hours):
    return {
        'model': 'GFS Global', 'version': 'global-v1',
        'cycle': f"{date}/{cycle}z",
        'projection': 'EPSG:3857',
        'generated': datetime.now(timezone.utc).isoformat(),
        'bounds': {'north': DOMAIN['lat_max'], 'south': DOMAIN['lat_min'],
                   'east': DOMAIN['lon_max'], 'west': DOMAIN['lon_min']},
        'variables': {k: {'label': v['label'], 'unit': v['unit'],
                          'vmin': v['vmin'], 'vmax': v['vmax'], 'colors': v['colors'],
                          **({'stops': v['stops']} if v.get('stops') else {})}
                      for k, v in RENDER_VARS.items()},
        'hours': manifest_hours,
    }

# =============================================================================
# PROCESAR UNA SOLA HORA (modo hijo — se ejecuta en subproceso y muere al acabar)
# =============================================================================
HOURS_DIR = f'{DATA_DIR}/_hours_staging'

def process_single_hour(date, cycle, fh):
    """Procesa UNA hora de pronóstico y escribe su entrada de manifest a disco.
    Diseñado para correr como subproceso aislado: al terminar, el proceso muere
    y libera toda la memoria (incluida cualquier fuga de cfgrib)."""
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(HOURS_DIR, exist_ok=True)
    cycle_dt = datetime.strptime(f"{date}{cycle}", '%Y%m%d%H').replace(tzinfo=timezone.utc)
    t0 = time.time()

    fields = {}
    ok_groups = 0
    for g in GROUPS:
        gp = download_group(date, cycle, fh, g)
        if not gp:
            continue
        ok_groups += 1
        for k, val in extract_fields(gp).items():
            fields[k] = val
        try:
            os.remove(gp)
        except OSError:
            pass
    if ok_groups == 0:
        log.warning(f"f{fh:03d}: sin datos")
        return 1

    derive_wind(fields)
    derive_levels(fields)
    # Renombrar prate -> precipRate para el render de tasa instantánea
    if 'prate' in fields:
        fields['precipRate'] = fields['prate']
    valid_dt = cycle_dt + timedelta(hours=fh)
    # Anomalía de temperatura vs normales CPC 1991-2020 (solo tierra), 14/09/2026
    if 'tempF' in fields:
        try:
            import clim_global
            arr, la, lo = fields['tempF']
            anom = clim_global.anomalia((arr - 273.15) * 9 / 5 + 32, la, lo, valid_dt)
            if anom is not None:
                fields['tempAnom'] = (anom, la, lo)
        except Exception as e:
            log.warning(f"    tempAnom f{fh:03d}: {e}")
    # Máscara tierra/mar en la rejilla de salida (LAND es 0/1; el resample
    # bilinear difumina la costa: >=0.5 la mantiene pegada a la línea real)
    land_res = None
    if 'landMask' in fields:
        arr, la, lo = fields['landMask']
        land_res = resample(arr, la, lo) >= 0.5
    _cdn()   # cliente S3 creado antes de repartir hilos

    def hacer_var(var):
        urls = {}
        try:
            arr, nat_lat, nat_lon = fields[var]
            res = resample(arr, nat_lat, nat_lon)
            png = f"{IMG_DIR}/{MODEL_ID}_{var}_f{fh:03d}.png"
            if render_png(res, var, png):
                key = f"data/{MID}/{MID}_{var}_f{fh:03d}.png"
                if upload(png, key):
                    urls[var] = f"{BASE['cdn_base']}/{key}"
                _borrar(png)
            # Variante solo-continente (#24b app)
            vkey = LAND_VARIANTS.get(var)
            if vkey and land_res is not None:
                png_l = f"{IMG_DIR}/{MODEL_ID}_{vkey}_f{fh:03d}.png"
                if render_png(res, var, png_l, land_mask=land_res):
                    key_l = f"data/{MID}/{MID}_{vkey}_f{fh:03d}.png"
                    if upload(png_l, key_l):
                        urls[vkey] = f"{BASE['cdn_base']}/{key_l}"
                    _borrar(png_l)
        except Exception as e:
            log.warning(f"    {var} f{fh:03d}: {e}")
        return urls

    hour_imgs = {}
    with ThreadPoolExecutor(max_workers=HILOS) as pool:
        for urls in pool.map(hacer_var, [v for v in RENDER_LIST if v in fields]):
            hour_imgs.update(urls)

    # Guardar PRATE resampleado (en mm/h) para que el orquestador integre el acumulado.
    # PRATE kg/m²/s * 3600 = mm/h sobre la rejilla de salida ya proyectada.
    if 'prate' in fields:
        arr, nat_lat, nat_lon = fields['prate']
        rate_mmh = resample(arr, nat_lat, nat_lon) * 3600.0
        np.save(f"{HOURS_DIR}/prate_{fh:03d}.npy", rate_mmh.astype('float32'))

    # 05/10: bajas y altas cerradas del campo de presión, un JSON por paso. El
    # visor las rotula y las mueve con la línea de tiempo.
    if 'prmsl' in fields:
        try:
            import centros_presion
            arr, nat_lat, nat_lon = fields['prmsl']
            c = centros_presion.detectar(arr, nat_lat, nat_lon)
            if c:
                cl = f"{IMG_DIR}/{MODEL_ID}_centros_f{fh:03d}.json"
                with open(cl, 'w') as f:
                    json.dump({'model': MID, 'fhour': fh, 'centros': c}, f,
                              separators=(',', ':'))
                k = f"data/{MID}/{MID}_centros_f{fh:03d}.json"
                if upload(cl, k, 'application/json'):
                    hour_imgs['centros'] = f"{BASE['cdn_base']}/{k}"
                _borrar(cl)
        except Exception as e:
            log.warning(f"    centros f{fh:03d}: {e}")

    if not hour_imgs:
        return 1
    entry = {'fhour': fh, 'validTime': valid_dt.isoformat(),
             'validTimeUnix': int(valid_dt.timestamp()), 'images': hour_imgs}
    with open(f"{HOURS_DIR}/hour_{fh:03d}.json", 'w') as f:
        json.dump(entry, f)
    log.info(f"f{fh:03d}: {len(hour_imgs)} PNGs · {time.time()-t0:.0f}s")
    return 0

# =============================================================================
# MANIFEST INCREMENTAL
# El manifest se fusiona desde los hour_NNN.json y se sube tras CADA hora
# (patrón RTOFS): si el timeout del cron mata el proceso a medias, el CDN
# declara el ciclo nuevo con las horas ya subidas en vez de quedarse con el
# manifest del ciclo viejo apuntando a PNGs ya sobrescritos.
# =============================================================================
def merge_and_upload_manifest(date, cycle, accum_imgs=None):
    manifest_hours = []
    for fn in sorted(os.listdir(HOURS_DIR)):
        if fn.startswith('hour_') and fn.endswith('.json'):
            try:
                with open(f"{HOURS_DIR}/{fn}") as f:
                    manifest_hours.append(json.load(f))
            except Exception:
                pass
    manifest_hours.sort(key=lambda h: h['fhour'])
    if accum_imgs:
        for h in manifest_hours:
            if h['fhour'] in accum_imgs:
                h['images']['precipAccum'] = accum_imgs[h['fhour']]
    if not manifest_hours:
        return []
    manifest = build_manifest(date, cycle, manifest_hours)
    mpath = f"{DATA_DIR}/{MODEL_ID}_manifest.json"
    os.makedirs(DATA_DIR, exist_ok=True)
    manifest = manifest_relleno.componer(manifest, mpath, FORECAST_HOURS[-1])   # 15/09: no acortar
    if manifest is None:
        return manifest_hours
    # 04/10: este publicador NO pasaba por el emparejador, así que sus 32
    # rejillas nunca llegaban al manifiesto (el Studio lo veía en 0 de 19).
    # Se usa MODEL_ID y no MID para que un ciclo *_test también empareje.
    try:
        import frames_grid
        frames_grid.anotar(manifest, MODEL_ID)
    except Exception as e:
        print(f'  ⚠️ frames_grid: {e}')
    with open(mpath, 'w') as f:
        json.dump(manifest, f, ensure_ascii=False)
    upload(mpath, f"data/{MID}/{MID}_manifest.json", 'application/json; charset=utf-8')
    return manifest_hours


# =============================================================================
# MAIN
# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date'); ap.add_argument('--cycle')
    ap.add_argument('--detect-cycle', action='store_true')
    ap.add_argument('--single-hour', type=int, default=None,
                    help='procesar SOLO esta hora de pronóstico (modo hijo)')
    ap.add_argument('--max-hours', type=int, default=None, help='limitar nº de horas (prueba)')
    ap.add_argument('--force', action='store_true',
                    help='re-renderizar aunque el ciclo ya esté completo en el manifest local')
    args = ap.parse_args()

    if args.detect_cycle:
        d, c = detect_cycle()
        print(f"{d}/{c}" if d else '')
        return 0 if d else 1

    # MODO HIJO: una sola hora, aislada
    if args.single_hour is not None:
        if not (args.date and args.cycle):
            log.error("--single-hour requiere --date y --cycle")
            return 1
        return process_single_hour(args.date, args.cycle, args.single_hour)

    # MODO ORQUESTADOR: lanza un subproceso por hora
    t_start = time.time()
    if args.date and args.cycle:
        date, cycle = args.date, args.cycle
    else:
        date, cycle = detect_cycle()
    if not date:
        log.error("Sin ciclo GFS global disponible")
        return 1

    # Skip si el ciclo ya está completo (el cron corre 4×/día pero GFS global solo
    # usa 00/12z: sin esto se re-renderizaba el mismo ciclo dos veces al día)
    if not args.force:
        try:
            with open(f"{DATA_DIR}/{MODEL_ID}_manifest.json") as f:
                prev = json.load(f)
            pub = re.sub(r'\D', '', str(prev.get('run') or prev.get('cycle') or ''))[:10]
            if pub and pub > f"{date}{cycle}":
                log.info(f"Ciclo {date}/{cycle}z anterior al publicado ({pub}) — nada que hacer")
                return 0
            if (prev.get('cycle') == f"{date}/{cycle}z"
                    and len(manifest_relleno.horas_propias(prev)) >= len(FORECAST_HOURS) - 2   # tolera 2 horas fallidas
                    and RENDER_LIST[-1] in prev['hours'][0].get('images', {})):
                log.info(f"Ciclo {date}/{cycle}z ya completo — nada que hacer (usa --force)")
                return 0
        except Exception:
            pass

    # Limpiar JSONs de horas de corridas previas
    import shutil
    if os.path.isdir(HOURS_DIR):
        shutil.rmtree(HOURS_DIR)
    os.makedirs(HOURS_DIR, exist_ok=True)

    hours = FORECAST_HOURS[:args.max_hours] if args.max_hours else FORECAST_HOURS
    log.info(f"GFS Global {date}/{cycle}z — {len(hours)} horas (subprocess-per-hour)")

    # Si el timeout del cron nos manda SIGTERM, dejar rastro en el log y subir
    # el manifest con lo procesado hasta ahora antes de morir.
    def _on_sigterm(signum, frame):
        log.warning("SIGTERM recibido (¿timeout del cron?) — subiendo manifest parcial y saliendo")
        try:
            merge_and_upload_manifest(date, cycle)
        except Exception as e:
            log.warning(f"manifest de emergencia falló: {e}")
        sys.exit(1)
    signal.signal(signal.SIGTERM, _on_sigterm)

    py = sys.executable
    n_ok = 0

    def correr_hora(fh):
        nonlocal n_ok
        cmd = [py, os.path.abspath(__file__), '--single-hour', str(fh),
               '--date', date, '--cycle', cycle]
        try:
            r = subprocess.run(cmd, timeout=420)
            if r.returncode == 0:
                n_ok += 1
                merge_and_upload_manifest(date, cycle)
                return True
        except subprocess.TimeoutExpired:
            log.warning(f"    f{fh:03d}: timeout, saltando")
        except Exception as e:
            log.warning(f"    f{fh:03d}: error subproceso: {e}")
        return False

    fallidas = []
    for i, fh in enumerate(hours, 1):
        log.info(f"--- f{fh:03d} ({i}/{len(hours)}) ---")
        if not correr_hora(fh):
            fallidas.append(fh)

    # Segunda vuelta para las horas que fallaron (NOMADS corta a rachas). El
    # acumulado se integra después, así que las recuperadas entran en orden.
    if fallidas:
        log.info(f"Reintento de {len(fallidas)} horas fallidas: {fallidas}")
        time.sleep(60)
        for fh in fallidas:
            log.info(f"--- f{fh:03d} (reintento) ---")
            correr_hora(fh)

    # =========================================================================
    # ACUMULADO DE LLUVIA (para huracanes): integrar PRATE hora a hora.
    # precipAccum(f_N) = suma de tasa(mm/h) * horas_intervalo desde f000 hasta f_N.
    # Crece monótono: al mover la barra de tiempo se ve la lluvia total acumulándose.
    # =========================================================================
    log.info("Integrando lluvia acumulada desde PRATE...")
    # Recoger las horas que tienen prate guardado, en orden
    prate_files = sorted(f for f in os.listdir(HOURS_DIR)
                         if f.startswith('prate_') and f.endswith('.npy'))
    accum = None
    prev_fh = 0
    accum_imgs = {}   # fh -> url del PNG acumulado
    for pf in prate_files:
        fh = int(pf[6:9])
        try:
            rate = np.load(f"{HOURS_DIR}/{pf}")          # mm/h en rejilla de salida
        except Exception:
            continue
        dt_h = fh - prev_fh                               # horas del intervalo (1, o 3 en pasos largos)
        prev_fh = fh
        if accum is None:
            accum = np.zeros_like(rate)
        # Lluvia del intervalo = tasa media * horas (aprox: tasa del frame * dt)
        accum = accum + np.clip(rate, 0, None) * dt_h
        # Renderizar el acumulado de esta hora (ya está en la rejilla de salida)
        png = f"{IMG_DIR}/{MODEL_ID}_precipAccum_f{fh:03d}.png"
        if render_png(accum.copy(), 'precipAccum', png):
            key = f"data/{MID}/{MID}_precipAccum_f{fh:03d}.png"
            if upload(png, key):
                accum_imgs[fh] = f"{BASE['cdn_base']}/{key}"
            try:
                os.remove(png)
            except OSError:
                pass
        del rate

    # Manifest final: fusiona los hour_NNN.json e inyecta el acumulado
    manifest_hours = merge_and_upload_manifest(date, cycle, accum_imgs)

    # Limpiar staging (npy + json de horas) para no acumular en disco
    try:
        shutil.rmtree(HOURS_DIR)
    except Exception:
        pass

    log.info(f"✅ GFS Global: {len(manifest_hours)}/{len(hours)} horas en {time.time()-t_start:.0f}s")
    return 0 if manifest_hours else 1


if __name__ == '__main__':
    sys.exit(main())
