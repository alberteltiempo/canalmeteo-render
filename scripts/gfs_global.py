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
"""

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

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
    'cdn_base':     'https://canalmeteo-public.sfo3.digitaloceanspaces.com',
    'user_agent':   'CanalMeteoTV/1.0',
}

MODEL_ID = 'gfs_global'
DATA_DIR = f'/opt/canalmeteo/data/{MODEL_ID}'
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
                               'lev_surface=on&lev_mean_sea_level=on&lev_entire_atmosphere=on')},
]

# Mapeo nombre cfgrib -> nombre interno (subconjunto de CONUS)
FIELD_MAP = {
    't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
    'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
    'tcc': 'cloudPct', 'cape': 'cape', 'prate': 'prate', 'prmsl': 'pressureMb',
}

# Variables que se renderizan EN CADA HORA (instantáneas)
# 'precipRate' (tasa) sale de prate; 'precipAccum' (acumulado) lo hace el orquestador.
RENDER_LIST = ['tempF', 'dewpF', 'rh', 'wspdMph', 'gustMph',
               'cloudPct', 'cape', 'precipRate', 'pressureMb']

# =============================================================================
# CONVERSIONES (idénticas a CONUS)
# =============================================================================
CONVERT = {
    'tempF':      lambda k: (k - 273.15) * 9 / 5 + 32,
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
}

# =============================================================================
# PALETAS (idénticas a RENDER_VARS de CONUS — para leyenda consistente)
# =============================================================================
RENDER_VARS = {
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
    'precipAccum': {'label': 'Lluvia acumulada (in)', 'unit': 'in', 'vmin': 0, 'vmax': 20, 'alpha': 0.80,
                 # escala alta para huracanes: verde->amarillo->naranja->rojo->morado (>15in extremo)
                 'colors': ['#1b5e20','#43a047','#a5d6a7','#fff59d','#ffeb3b','#ffa726','#fb8c00',
                            '#f4511e','#e53935','#b71c1c','#8e24aa','#6a1b9a','#4a148c']},
    'pressureMb': {'label': 'Presión nivel del mar (mb)', 'unit': 'mb', 'vmin': 980, 'vmax': 1050, 'alpha': 0.65,
                 'colors': ['#4a148c','#1565c0','#42a5f5','#81c784','#ffeb3b','#ff9800','#e53935','#880e4f']},
}

# =============================================================================
# UPLOAD (idéntico a CONUS)
# =============================================================================
def upload(filepath, cdn_key, content_type='image/png'):
    cmd = ['aws', 's3', 'cp', filepath, f"s3://{BASE['cdn_bucket']}/{cdn_key}",
           '--profile', BASE['aws_profile'], '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=600',
           '--endpoint-url', BASE['cdn_endpoint']]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120).returncode == 0
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
def render_png(field_resampled, var_name, output_path):
    if var_name not in RENDER_VARS:
        return False
    rcfg = RENDER_VARS[var_name]
    field = CONVERT[var_name](field_resampled.copy())
    nan = np.isnan(field)
    norm = np.clip((field - rcfg['vmin']) / (rcfg['vmax'] - rcfg['vmin']), 0, 1)
    norm = np.where(nan, 0, norm)
    cmap = mcolors.LinearSegmentedColormap.from_list('c', rcfg['colors'], N=256)
    rgba = cmap(norm)
    # Precipitación: transparente donde no llueve; resto: alpha del cfg
    if var_name in ('precipRate', 'precipAccum'):
        rgba[:, :, 3] = np.where(field > 0.01, rcfg['alpha'], 0.0)
    else:
        rgba[:, :, 3] = np.where(nan, 0.0, rcfg['alpha'])
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

# =============================================================================
# MANIFEST
# =============================================================================
def build_manifest(date, cycle, manifest_hours):
    return {
        'model': 'GFS Global', 'version': 'global-v1',
        'cycle': f"{date}/{cycle}z",
        'generated': datetime.now(timezone.utc).isoformat(),
        'bounds': {'north': DOMAIN['lat_max'], 'south': DOMAIN['lat_min'],
                   'east': DOMAIN['lon_max'], 'west': DOMAIN['lon_min']},
        'variables': {k: {'label': v['label'], 'unit': v['unit'],
                          'vmin': v['vmin'], 'vmax': v['vmax'], 'colors': v['colors']}
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
    # Renombrar prate -> precipRate para el render de tasa instantánea
    if 'prate' in fields:
        fields['precipRate'] = fields['prate']
    valid_dt = cycle_dt + timedelta(hours=fh)
    hour_imgs = {}
    for var in RENDER_LIST:
        if var not in fields:
            continue
        arr, nat_lat, nat_lon = fields[var]
        res = resample(arr, nat_lat, nat_lon)
        png = f"{IMG_DIR}/{MODEL_ID}_{var}_f{fh:03d}.png"
        if render_png(res, var, png):
            key = f"data/{MODEL_ID}/{MODEL_ID}_{var}_f{fh:03d}.png"
            if upload(png, key):
                hour_imgs[var] = f"{BASE['cdn_base']}/{key}"
            try:
                os.remove(png)
            except OSError:
                pass

    # Guardar PRATE resampleado (en mm/h) para que el orquestador integre el acumulado.
    # PRATE kg/m²/s * 3600 = mm/h sobre la rejilla de salida ya proyectada.
    if 'prate' in fields:
        arr, nat_lat, nat_lon = fields['prate']
        rate_mmh = resample(arr, nat_lat, nat_lon) * 3600.0
        np.save(f"{HOURS_DIR}/prate_{fh:03d}.npy", rate_mmh.astype('float32'))

    if not hour_imgs:
        return 1
    entry = {'fhour': fh, 'validTime': valid_dt.isoformat(),
             'validTimeUnix': int(valid_dt.timestamp()), 'images': hour_imgs}
    with open(f"{HOURS_DIR}/hour_{fh:03d}.json", 'w') as f:
        json.dump(entry, f)
    log.info(f"f{fh:03d}: {len(hour_imgs)} PNGs · {time.time()-t0:.0f}s")
    return 0

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

    # Limpiar JSONs de horas de corridas previas
    import shutil
    if os.path.isdir(HOURS_DIR):
        shutil.rmtree(HOURS_DIR)
    os.makedirs(HOURS_DIR, exist_ok=True)

    hours = FORECAST_HOURS[:args.max_hours] if args.max_hours else FORECAST_HOURS
    log.info(f"GFS Global {date}/{cycle}z — {len(hours)} horas (subprocess-per-hour)")

    py = sys.executable
    n_ok = 0
    for i, fh in enumerate(hours, 1):
        log.info(f"--- f{fh:03d} ({i}/{len(hours)}) ---")
        cmd = [py, os.path.abspath(__file__), '--single-hour', str(fh),
               '--date', date, '--cycle', cycle]
        try:
            r = subprocess.run(cmd, timeout=300)
            if r.returncode == 0:
                n_ok += 1
        except subprocess.TimeoutExpired:
            log.warning(f"    f{fh:03d}: timeout, saltando")
        except Exception as e:
            log.warning(f"    f{fh:03d}: error subproceso: {e}")

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
            key = f"data/{MODEL_ID}/{MODEL_ID}_precipAccum_f{fh:03d}.png"
            if upload(png, key):
                accum_imgs[fh] = f"{BASE['cdn_base']}/{key}"
            try:
                os.remove(png)
            except OSError:
                pass
        del rate

    # Fusionar manifest desde los JSONs de cada hora
    manifest_hours = []
    for fn in sorted(os.listdir(HOURS_DIR)):
        if fn.startswith('hour_') and fn.endswith('.json'):
            try:
                with open(f"{HOURS_DIR}/{fn}") as f:
                    manifest_hours.append(json.load(f))
            except Exception:
                pass
    manifest_hours.sort(key=lambda h: h['fhour'])
    # Inyectar la imagen de acumulado en la entrada de cada hora
    for h in manifest_hours:
        if h['fhour'] in accum_imgs:
            h['images']['precipAccum'] = accum_imgs[h['fhour']]

    manifest = build_manifest(date, cycle, manifest_hours)
    mpath = f"{DATA_DIR}/{MODEL_ID}_manifest.json"
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(mpath, 'w') as f:
        json.dump(manifest, f, ensure_ascii=False)
    upload(mpath, f"data/{MODEL_ID}/{MODEL_ID}_manifest.json", 'application/json')

    # Limpiar staging (npy + json de horas) para no acumular en disco
    try:
        shutil.rmtree(HOURS_DIR)
    except Exception:
        pass

    log.info(f"✅ GFS Global: {len(manifest_hours)}/{len(hours)} horas en {time.time()-t_start:.0f}s")
    return 0 if manifest_hours else 1


if __name__ == '__main__':
    sys.exit(main())
