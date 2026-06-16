#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTOFS SST Pipeline — Canal Meteo TV
====================================
Temperatura superficial del mar (SST) del modelo Global RTOFS (HYCOM 1/12°),
recortada a la cuenca tropical de huracanes (Atlántico + Caribe + Golfo + EPAC).

Fuente : NOMADS  rtofs.YYYYMMDD/rtofs_glo_2ds_fNNN_prog.nc  (NetCDF, malla curvilínea)
Salida : data/rtofs/rtofs_sst_fNNN.png  +  rtofs_anom_fNNN.png  +  rtofs_manifest.json
Ciclo  : 1×/día (RTOFS refresca ~16 UTC). Solo ciclo 00z.

Reusa las convenciones de model_pipeline_multi.py:
  - upload() vía aws s3 cp, perfil do-tor1, bucket canalmeteo-public
  - manifest con bounds + hours[{fhour,validTime,validTimeUnix,images}]
  - paletas LinearSegmentedColormap, PNG RGBA 590×260
Diferencias propias de RTOFS:
  - NetCDF (netCDF4 directo, NO xarray por bug de backend)
  - malla curvilínea 2D Latitude/Longitude -> griddata a rejilla regular
  - lon HYCOM en 0..360 desplazado -> normalizar a -180..180
  - SST ya viene en °C (NO Kelvin)
"""

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

import numpy as np
import netCDF4
from scipy.interpolate import griddata
import matplotlib
matplotlib.use('Agg')
import matplotlib.colors as mcolors
from PIL import Image

# Logging mínimo coherente con el resto de pipelines
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('rtofs')

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

MODEL_ID = 'rtofs'
DATA_DIR = f'/opt/canalmeteo/data/{MODEL_ID}'
IMG_DIR  = f'{DATA_DIR}/images'

# BBox cuenca tropical de huracanes (validado: 4.8% de la malla global, ~711K pts)
BBOX = {'lat_min': 0.0, 'lat_max': 45.0, 'lon_min': -100.0, 'lon_max': -10.0}

# Rejilla regular de salida (resolución del PNG en grados ~0.08° nativo de RTOFS)
# 90° lon x 45° lat a ~0.08° => mantener proporción del overlay
OUT_W, OUT_H = 1126, 632   # coincide con el shape del subset validado

# Horas de pronóstico a procesar (RTOFS publica f000..f192 cada hora; usamos saltos)
# Para huracanes: nowcast + cada 24h hasta 8 días.
FORECAST_HOURS = [0, 24, 48, 72, 96, 120, 144, 168, 192]

# Coral Reef Watch — anomalía de SST diaria global (5km, NetCDF en su CDN/OPeNDAP)
# Producto operativo: ct5km_ssta (sea surface temperature anomaly)
CRW_BASE = 'https://www.star.nesdis.noaa.gov/pub/sod/mecb/crw/data/5km/v3.1_op/nc/v1.0/daily/ssta'

NOMADS_BASE = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtofs/prod'

# =============================================================================
# PALETAS  (formato idéntico a RENDER_VARS del pipeline principal)
# =============================================================================
RENDER_VARS = {
    'sstF': {
        'label': 'Temperatura del mar (°F)', 'unit': '°F',
        'vmin': 60, 'vmax': 90,   # rango útil tropical (15.5–32 °C)
        # Azul frío -> verde -> amarillo -> naranja -> rojo (umbral huracán ~26.5°C/80°F)
        'colors': ['#08306b', '#2171b5', '#41b6c4', '#7fcdbb', '#c7e9b4',
                   '#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'],
        'alpha': 0.82,
    },
    'sstAnom': {
        'label': 'Anomalía SST (°C)', 'unit': '°C',
        'vmin': -5, 'vmax': 5,    # divergente centrado en 0
        'colors': ['#053061', '#2166ac', '#4393c3', '#92c5de', '#d1e5f0',
                   '#f7f7f7',
                   '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f'],
        'alpha': 0.80,
    },
}

CONVERT = {
    'sstF':    lambda c: c * 9.0 / 5.0 + 32.0,   # °C -> °F
    'sstAnom': lambda a: a,                        # ya viene en °C
}


# =============================================================================
# UPLOAD  (idéntico a model_pipeline_multi.py)
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
# DETECTAR CICLO DISPONIBLE
# =============================================================================
def detect_cycle():
    """Encuentra el rtofs.YYYYMMDD más reciente que tenga el f000_prog.
    RTOFS refresca ~16 UTC; antes de eso el día actual no existe -> usa ayer."""
    now = datetime.now(timezone.utc)
    for delta in (0, 1, 2):
        d = (now - timedelta(days=delta)).strftime('%Y%m%d')
        url = f"{NOMADS_BASE}/rtofs.{d}/rtofs_glo_2ds_f000_prog.nc"
        try:
            r = subprocess.run(['curl', '-sIL', '-o', '/dev/null',
                                '-w', '%{http_code}', url],
                               capture_output=True, text=True, timeout=30)
            if r.stdout.strip() == '200':
                log.info(f"Ciclo RTOFS detectado: {d}")
                return d
        except Exception:
            continue
    log.error("No se encontró ningún ciclo RTOFS disponible")
    return None


# =============================================================================
# DESCARGA + LECTURA DE UN prog
# =============================================================================
def download_prog(date, fhour):
    os.makedirs(DATA_DIR, exist_ok=True)
    fname = f"rtofs_glo_2ds_f{fhour:03d}_prog.nc"
    url = f"{NOMADS_BASE}/rtofs.{date}/{fname}"
    local = f"{DATA_DIR}/{fname}"
    r = subprocess.run(['curl', '-sL', '--fail', '-o', local, url],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(local):
        return None
    # Validar firma HDF5 (\211HDF)
    with open(local, 'rb') as fh:
        if fh.read(4) != b'\x89HDF':
            log.warning(f"    f{fhour:03d}: archivo no es HDF5 válido")
            os.remove(local)
            return None
    return local


# Cache del recorte: índices del bbox (no cambian entre horas, malla fija)
_SUBSET_CACHE = {}

def read_sst_subset(local_path):
    """Lee SST del prog, normaliza lon, recorta bbox, devuelve (sst, lat, lon) recortados."""
    ds = netCDF4.Dataset(local_path)
    lat = ds.variables['Latitude'][:]
    lon = ds.variables['Longitude'][:]
    sst = np.ma.filled(ds.variables['sst'][:].squeeze().astype('float32'), np.nan)
    ds.close()

    # Normalizar lon HYCOM (0..360 desplazado) a -180..180
    lon180 = ((lon + 180) % 360) - 180

    key = (lat.shape, float(np.nanmin(lat)))
    if key not in _SUBSET_CACHE:
        m = ((lat >= BBOX['lat_min']) & (lat <= BBOX['lat_max']) &
             (lon180 >= BBOX['lon_min']) & (lon180 <= BBOX['lon_max']))
        ys, xs = np.where(m)
        _SUBSET_CACHE[key] = (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1)
    y0, y1, x0, x1 = _SUBSET_CACHE[key]

    return (sst[y0:y1, x0:x1],
            lat[y0:y1, x0:x1],
            lon180[y0:y1, x0:x1])


# =============================================================================
# REGRID curvilíneo -> regular  (una rejilla regular fija para el overlay)
# =============================================================================
_REGULAR_GRID = None

def _merc_y(lat_deg):
    """Coordenada Y de Web Mercator (EPSG:3857) normalizada, para una latitud en grados."""
    lat = np.radians(lat_deg)
    return np.log(np.tan(np.pi / 4 + lat / 2))

def get_regular_grid():
    """Rejilla de salida del PNG. La longitud es lineal (Mercator es lineal en X),
    pero la LATITUD se espacia según Web Mercator: Mapbox coloca la imagen con
    'coordinates' (4 esquinas) y la reproyecta a Mercator, así que las filas de
    píxel deben corresponder a latitudes Mercator-equiespaciadas, no lineales.
    Sin esto, la tierra se desplaza hacia el norte a latitudes altas."""
    global _REGULAR_GRID
    if _REGULAR_GRID is None:
        gx = np.linspace(BBOX['lon_min'], BBOX['lon_max'], OUT_W)
        # Y equiespaciado en espacio Mercator entre north y south, luego de vuelta a grados
        y_top = _merc_y(BBOX['lat_max'])
        y_bot = _merc_y(BBOX['lat_min'])
        y_merc = np.linspace(y_top, y_bot, OUT_H)        # norte arriba, lineal en Mercator
        gy = np.degrees(2 * np.arctan(np.exp(y_merc)) - np.pi / 2)  # Mercator inverso -> grados
        _REGULAR_GRID = np.meshgrid(gx, gy)
    return _REGULAR_GRID


def regrid_to_regular(field, lat, lon):
    """griddata de malla curvilínea a rejilla regular, recortando a océano.

    griddata(linear) rellena los huecos de tierra interpolando desde el mar
    vecino, lo que pinta el continente. Para evitarlo interpolamos también una
    máscara binaria (1=dato válido/océano, 0=tierra) por NEAREST sobre TODOS
    los puntos nativos; donde el punto nativo más cercano es tierra, forzamos
    NaN. Así el overlay queda solo sobre agua, con borde de costa limpio.
    """
    grid_lon, grid_lat = get_regular_grid()

    valid = ~np.isnan(field)
    if valid.sum() == 0:
        return np.full((OUT_H, OUT_W), np.nan, dtype='float32')

    # 1) Interpolar SST solo desde puntos de océano (linear, suave)
    pts_ocean = np.column_stack([lon[valid].ravel(), lat[valid].ravel()])
    vals_ocean = field[valid].ravel()
    out = griddata(pts_ocean, vals_ocean, (grid_lon, grid_lat), method='linear')

    # 2) Máscara océano/tierra por NEAREST usando TODOS los puntos nativos del bbox.
    #    El punto nativo más cercano a cada celda regular define si es mar (1) o tierra (0).
    pts_all = np.column_stack([lon.ravel(), lat.ravel()])
    mask_all = valid.ravel().astype('float32')   # 1 océano, 0 tierra
    nearest = griddata(pts_all, mask_all, (grid_lon, grid_lat), method='nearest')

    # 3) Donde el vecino nativo es tierra -> transparente
    out = np.where(nearest < 0.5, np.nan, out)
    return out.astype('float32')


# =============================================================================
# RENDER PNG  (mismo enfoque que render_png del pipeline principal)
# =============================================================================
def render_png(field_regular, var_name, output_path):
    if var_name not in RENDER_VARS:
        return False
    rcfg = RENDER_VARS[var_name]
    convert_fn = CONVERT[var_name]

    field = convert_fn(field_regular.copy())
    nan_mask = np.isnan(field)

    norm = np.clip((field - rcfg['vmin']) / (rcfg['vmax'] - rcfg['vmin']), 0, 1)
    norm = np.where(nan_mask, 0, norm)
    cmap = mcolors.LinearSegmentedColormap.from_list('c', rcfg['colors'], N=256)
    rgba = cmap(norm)

    # Transparente sobre tierra/NaN; opacidad de océano según paleta
    rgba[:, :, 3] = np.where(nan_mask, 0.0, rcfg['alpha'])

    img = Image.fromarray((rgba * 255).astype(np.uint8), 'RGBA')
    img.save(output_path, 'PNG', optimize=True)
    return True


# =============================================================================
# ANOMALÍA — Coral Reef Watch (opcional, no bloquea si falla)
# =============================================================================
def _crw_latest_url(date):
    """Lista el directorio CRW del año y devuelve (url, fname) del .nc REAL más
    reciente (excluye .md5 — CRW publica el checksum ~1 día antes que los datos).
    Prueba el año de 'date' y, si no hay, el año anterior (borde de enero)."""
    import re
    years = [date[:4]]
    if date[4:8] <= '0103':           # primeros días de enero: mirar año previo
        years.append(str(int(date[:4]) - 1))
    for yr in years:
        idx = f"{CRW_BASE}/{yr}/"
        try:
            html = subprocess.run(['curl', '-sL', idx],
                                  capture_output=True, text=True, timeout=60).stdout
        except Exception:
            continue
        # filtrar líneas .md5 ANTES de extraer (el .nc va embebido en .nc.md5)
        ncs = sorted(set(re.findall(r'ct5km_ssta_v3\.1_\d{8}\.nc',
                     '\n'.join(l for l in html.splitlines() if '.md5' not in l))))
        if ncs:
            return f"{idx}{ncs[-1]}", ncs[-1]
    return None, None


def fetch_crw_anomaly(date):
    """Descarga la anomalía SST de CRW más reciente disponible y la recorta al bbox.
    Devuelve campo regular o None si no disponible."""
    url, fname = _crw_latest_url(date)
    if not url:
        log.info("    CRW: no se encontró ningún .nc en el directorio")
        return None
    local = f"{DATA_DIR}/{fname}"
    log.info(f"    CRW anomalía: usando {fname}")
    try:
        r = subprocess.run(['curl', '-sL', '--fail', '-o', local, url],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.exists(local):
            log.info("    CRW anomalía no disponible (descarga falló)")
            return None
        ds = netCDF4.Dataset(local)
        # CRW es malla regular lat/lon 1D
        clat = ds.variables['lat'][:]
        clon = ds.variables['lon'][:]
        anom = np.ma.filled(ds.variables['sea_surface_temperature_anomaly'][:].squeeze().astype('float32'), np.nan)
        ds.close()
        os.remove(local)
        # Recortar al bbox e interpolar a la rejilla del overlay
        ila = np.where((clat >= BBOX['lat_min']) & (clat <= BBOX['lat_max']))[0]
        ilo = np.where((clon >= BBOX['lon_min']) & (clon <= BBOX['lon_max']))[0]
        sub = anom[np.ix_(ila, ilo)]
        sla, slo = clat[ila], clon[ilo]
        grid_lon, grid_lat = get_regular_grid()
        mlon, mlat = np.meshgrid(slo, sla)
        valid = ~np.isnan(sub)
        if valid.sum() == 0:
            return None
        # Interpolar anomalía solo desde océano (linear)
        out = griddata(np.column_stack([mlon[valid], mlat[valid]]), sub[valid],
                       (grid_lon, grid_lat), method='linear')
        # Máscara océano/tierra por NEAREST sobre todos los puntos nativos -> recorta tierra
        nearest = griddata(np.column_stack([mlon.ravel(), mlat.ravel()]),
                           valid.ravel().astype('float32'),
                           (grid_lon, grid_lat), method='nearest')
        out = np.where(nearest < 0.5, np.nan, out)
        return out.astype('float32')
    except Exception as e:
        log.info(f"    CRW anomalía falló: {e}")
        return None


# =============================================================================
# MANIFEST  (mismo formato que _build_manifest, con bounds propios)
# =============================================================================
def build_manifest(date, manifest_hours):
    return {
        'model': 'RTOFS', 'version': 'ocean-v1',
        'cycle': f"{date}/00z",
        'generated': datetime.now(timezone.utc).isoformat(),
        'bounds': {'north': BBOX['lat_max'], 'south': BBOX['lat_min'],
                   'east': BBOX['lon_max'], 'west': BBOX['lon_min']},
        'variables': {k: {'label': v['label'], 'unit': v['unit'],
                          'vmin': v['vmin'], 'vmax': v['vmax'],
                          'colors': v['colors']}
                      for k, v in RENDER_VARS.items()},
        'hours': manifest_hours,
    }


# =============================================================================
# MAIN
# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', help='YYYYMMDD (default: autodetect)')
    ap.add_argument('--detect-cycle', action='store_true')
    ap.add_argument('--keep-nc', action='store_true', help='no borrar los .nc descargados')
    args = ap.parse_args()

    if args.detect_cycle:
        d = detect_cycle()
        print(d if d else '')
        return 0 if d else 1

    os.makedirs(IMG_DIR, exist_ok=True)
    t_start = time.time()

    date = args.date or detect_cycle()
    if not date:
        log.error("Sin ciclo RTOFS disponible — abortando")
        return 1

    # Anomalía CRW (una sola, corresponde al día — no por hora de pronóstico)
    log.info("Descargando anomalía Coral Reef Watch...")
    anom_regular = fetch_crw_anomaly(date)

    manifest_hours = []
    cycle_dt = datetime.strptime(date, '%Y%m%d').replace(tzinfo=timezone.utc)

    n_ok = 0
    for i, fh in enumerate(FORECAST_HOURS, 1):
        t0 = time.time()
        log.info(f"--- f{fh:03d} ({i}/{len(FORECAST_HOURS)}) ---")
        local = download_prog(date, fh)
        if not local:
            log.warning(f"    f{fh:03d}: descarga falló, saltando")
            continue

        try:
            sst, lat, lon = read_sst_subset(local)
            sst_reg = regrid_to_regular(sst, lat, lon)
        except Exception as e:
            log.warning(f"    f{fh:03d}: lectura/regrid falló: {e}")
            if not args.keep_nc and os.path.exists(local):
                os.remove(local)
            continue

        valid_dt = cycle_dt + timedelta(hours=fh)
        hour_imgs = {}

        # SST en °F
        png = f"{IMG_DIR}/{MODEL_ID}_sstF_f{fh:03d}.png"
        if render_png(sst_reg, 'sstF', png):
            key = f"data/{MODEL_ID}/{MODEL_ID}_sstF_f{fh:03d}.png"
            if upload(png, key):
                hour_imgs['sstF'] = f"{BASE['cdn_base']}/{key}"

        # Anomalía: solo en f000 (es del día, no del pronóstico)
        if fh == 0 and anom_regular is not None:
            apng = f"{IMG_DIR}/{MODEL_ID}_sstAnom_f000.png"
            if render_png(anom_regular, 'sstAnom', apng):
                key = f"data/{MODEL_ID}/{MODEL_ID}_sstAnom_f000.png"
                if upload(apng, key):
                    hour_imgs['sstAnom'] = f"{BASE['cdn_base']}/{key}"

        if hour_imgs:
            manifest_hours.append({
                'fhour': fh,
                'validTime': valid_dt.isoformat(),
                'validTimeUnix': int(valid_dt.timestamp()),
                'images': hour_imgs,
            })
            n_ok += 1

        if not args.keep_nc and os.path.exists(local):
            os.remove(local)
        log.info(f"    f{fh:03d}: {len(hour_imgs)} PNGs · {time.time()-t0:.0f}s")

    # Manifest
    manifest = build_manifest(date, manifest_hours)
    mpath = f"{DATA_DIR}/{MODEL_ID}_manifest.json"
    with open(mpath, 'w') as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    upload(mpath, f"data/{MODEL_ID}/{MODEL_ID}_manifest.json", 'application/json')

    log.info(f"✅ RTOFS: {n_ok}/{len(FORECAST_HOURS)} horas en {time.time()-t_start:.0f}s")
    return 0 if n_ok > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
