#!/usr/bin/env python3
"""
NBM Temperatura (2 m) Pipeline — Canal Meteo TV
─────────────────────────────────────────────────────────────────────
Descarga la temperatura a 2 m del NBM (National Blend of Models, fichero
`core` CONUS) desde el filtro NOMADS de NCEP, le aplica NUESTRA paleta de
temperatura, reproyecta de la rejilla Lambert Conformal a equirectangular con
espaciado Mercator (para casar con el `image source` de Mapbox), y sube un PNG
+ manifest al CDN.

Así la capa de temperatura "ahora" se drapea sobre el mapa base igual que el
satélite GOES y el radar MRMS (mismo método), para la escena "CONDICIONES AHORA".

Salida CDN:
    data/nbm/temp/conus/temp_<YYYYMMDDHHMMSS>.png   (RGBA, bounds del manifest)
    data/nbm/temp/conus/manifest.json               (bounds + 1 frame "ahora")

Uso:
    /opt/canalmeteo/venv/bin/python3 nbm_temp_pipeline.py --once
    /opt/canalmeteo/venv/bin/python3 nbm_temp_pipeline.py --once --date 20260616 --cycle 12

Modelado en goes_ir_pipeline.py (misma estructura de reproyección/CDN).
"""

import os
import sys
import json
import time
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
import numpy as np
import xarray as xr
from pyproj import CRS, Transformer
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─── Config CDN (DigitalOcean Spaces) ──────────────────────────────
CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_BASE = 'data/nbm/temp'
CDN_URL_ROOT = f'https://{CDN_BUCKET}.sfo3.digitaloceanspaces.com/{CDN_BASE}'

WORK_DIR = Path('/tmp/nbm_temp_work')
WORK_DIR.mkdir(exist_ok=True)

# ─── Fuente NBM (NOMADS filter) ────────────────────────────────────
NOMADS_FILTER = 'https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl'
# "ahora" = el lead más corto del ciclo más reciente. El core NBM empieza en f001.
NOW_FH = 1

# ─── Vista de salida (recuadro equirectangular del image source Mapbox) ─
VIEW = {
    'bounds': {'north': 52.0, 'south': 20.0, 'west': -128.0, 'east': -62.0},
    'out_w': 2600, 'out_h': 1500,
}

# ─── Paleta de temperatura (°F → RGB), estilo broadcast ─────────────
# De frío (violeta/azul) a calor (rojo/magenta). Interpolada en una LUT.
PALETTE_F = [
    (-20.0, (120, 80, 170)),
    (0.0, (90, 70, 200)),
    (15.0, (70, 110, 215)),
    (32.0, (75, 150, 225)),   # punto de congelación
    (45.0, (70, 195, 200)),
    (55.0, (95, 205, 120)),
    (65.0, (180, 215, 95)),
    (72.0, (235, 220, 90)),
    (80.0, (240, 165, 70)),
    (90.0, (232, 100, 55)),
    (100.0, (212, 50, 50)),
    (110.0, (175, 40, 95)),
    (120.0, (140, 30, 80)),
]


def k_to_f(k):
    return (k - 273.15) * 9.0 / 5.0 + 32.0


def build_temp_lut(stops):
    """LUT indexada por °F [F_MIN..F_MAX] → RGBA uint8."""
    F_MIN, F_MAX = -30.0, 125.0
    N = 1024
    fs = np.linspace(F_MIN, F_MAX, N)
    sk = sorted(stops, key=lambda s: s[0])
    ks = np.array([s[0] for s in sk])
    r = np.array([s[1][0] for s in sk]); g = np.array([s[1][1] for s in sk]); b = np.array([s[1][2] for s in sk])
    R = np.interp(fs, ks, r); G = np.interp(fs, ks, g); B = np.interp(fs, ks, b)
    A = np.full(N, 255.0)  # opaco; la translucidez se controla en Remotion
    rgba = np.stack([R, G, B, A], axis=1).astype(np.uint8)
    return rgba, F_MIN, F_MAX, N


_LUT, _LUT_FMIN, _LUT_FMAX, _LUT_N = build_temp_lut(PALETTE_F)


def colorize_temp(t_f: np.ndarray, valid: np.ndarray) -> np.ndarray:
    idx = (t_f - _LUT_FMIN) / (_LUT_FMAX - _LUT_FMIN) * (_LUT_N - 1)
    idx = np.clip(np.nan_to_num(idx, nan=0.0), 0, _LUT_N - 1).astype(np.int32)
    out = _LUT[idx]
    out[~valid] = (0, 0, 0, 0)
    return out


# ─── Mercator helpers (alinear con el Mercator de Mapbox) ───────────
def lat_to_merc_y(lat):
    lat = np.clip(lat, -85.051129, 85.051129)
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def merc_y_to_lat(y):
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)


# ─── Máscara tierra/mar (stencil): la temperatura solo se ve en tierra ──
# La rejilla de salida es FIJA → la máscara se calcula una vez y se cachea en
# disco (rápido en sucesivas ejecuciones). Polígonos de tierra Natural Earth 50m.
_LANDMASK = None


def get_land_mask():
    global _LANDMASK
    if _LANDMASK is not None:
        return _LANDMASK
    W, H = VIEW['out_w'], VIEW['out_h']
    bn = VIEW['bounds']
    cache = Path(f'/opt/canalmeteo/data/nbm_temp_landmask_{W}x{H}.npy')
    if cache.exists():
        _LANDMASK = np.load(cache)
        return _LANDMASK
    import cartopy.io.shapereader as shpreader
    from shapely.ops import unary_union
    from shapely import contains_xy
    my = np.linspace(lat_to_merc_y(bn['north']), lat_to_merc_y(bn['south']), H)
    lats = merc_y_to_lat(my)
    lons = np.linspace(bn['west'], bn['east'], W)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    shp = shpreader.natural_earth(resolution='50m', category='physical', name='land')
    land = unary_union(list(shpreader.Reader(shp).geometries()))
    mask = contains_xy(land, lon_grid, lat_grid)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, mask)
        log.info(f"  máscara tierra/mar calculada y cacheada ({mask.sum()} px tierra)")
    except Exception as e:
        log.warning(f"  no se pudo cachear la máscara: {e}")
    _LANDMASK = mask
    return mask


# ─── Reproyección Lambert → equirectangular (LUT de índices) ────────
def build_reproj_lut(ds):
    """Índices (row,col) del grid Lambert fuente para cada píxel de salida."""
    a = ds['t2m']
    g = a.attrs
    latin1 = float(g['GRIB_Latin1InDegrees'])
    latin2 = float(g['GRIB_Latin2InDegrees'])
    lad = float(g['GRIB_LaDInDegrees'])
    lov = float(g['GRIB_LoVInDegrees'])
    lov = lov - 360.0 if lov > 180.0 else lov
    dx = float(g['GRIB_DxInMetres'])
    dy = float(g['GRIB_DyInMetres'])

    lcc = CRS.from_proj4(
        f"+proj=lcc +lat_1={latin1} +lat_2={latin2} +lat_0={lad} +lon_0={lov} "
        f"+x_0=0 +y_0=0 +R=6371200 +units=m +no_defs"
    )
    tf = Transformer.from_crs("EPSG:4326", lcc, always_xy=True)

    lat2d = ds['latitude'].values
    lon2d = ds['longitude'].values
    # lon NBM viene en 0..360 → a -180..180 para el transform
    lon00 = lon2d[0, 0] - 360.0 if lon2d[0, 0] > 180.0 else lon2d[0, 0]
    x0, y0 = tf.transform(lon00, lat2d[0, 0])  # primer punto del grid (esquina SW)
    src_h, src_w = a.shape

    bn = VIEW['bounds']
    W, H = VIEW['out_w'], VIEW['out_h']
    my = np.linspace(lat_to_merc_y(bn['north']), lat_to_merc_y(bn['south']), H)
    lats = merc_y_to_lat(my)
    lons = np.linspace(bn['west'], bn['east'], W)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    X, Y = tf.transform(lon_grid.ravel(), lat_grid.ravel())
    X = X.reshape(H, W); Y = Y.reshape(H, W)
    col = np.round((X - x0) / dx).astype(np.int32)
    row = np.round((Y - y0) / dy).astype(np.int32)
    valid = np.isfinite(X) & np.isfinite(Y) & (row >= 0) & (row < src_h) & (col >= 0) & (col < src_w)
    col = np.clip(col, 0, src_w - 1)
    row = np.clip(row, 0, src_h - 1)
    return row, col, valid


# ─── Descarga NBM (NOMADS filter) ──────────────────────────────────
def nbm_url(date_str, cycle, fh):
    params = {
        'file': f'blend.t{cycle:02d}z.core.f{fh:03d}.co.grib2',
        'dir': f'/blend.{date_str}/{cycle:02d}/core',
        'var_TMP': 'on',
        'lev_2_m_above_ground': 'on',
    }
    return NOMADS_FILTER, params


def download_nbm(date_str, cycle, fh, dst):
    url, params = nbm_url(date_str, cycle, fh)
    try:
        r = requests.get(url, params=params, timeout=180)
        if r.status_code == 200 and len(r.content) > 100000 and r.content[:4] == b'GRIB':
            dst.write_bytes(r.content)
            return True
        log.warning(f"  descarga NBM no válida (status {r.status_code}, {len(r.content)} bytes)")
        return False
    except Exception as e:
        log.error(f"  download error: {e}")
        return False


def detect_cycle():
    """Ciclo NBM más reciente con f001 disponible (prueba hacia atrás)."""
    now = datetime.now(timezone.utc)
    for back in range(0, 8):
        t = now - timedelta(hours=back)
        date_str = t.strftime('%Y%m%d')
        cycle = t.hour
        url, params = nbm_url(date_str, cycle, NOW_FH)
        try:
            r = requests.head(url, params=params, timeout=30)
            # El filtro responde 200 aunque construya el subset; comprobamos con GET corto.
            g = requests.get(url, params=params, timeout=120)
            if g.status_code == 200 and g.content[:4] == b'GRIB':
                tmp = WORK_DIR / f'nbm_{date_str}_{cycle:02d}.grib2'
                tmp.write_bytes(g.content)
                return date_str, cycle, tmp
        except Exception:
            continue
    return None, None, None


# ─── CDN (DigitalOcean) ────────────────────────────────────────────
def cdn_cmd(args):
    return subprocess.run(
        ['aws'] + args + ['--profile', AWS_PROFILE, '--endpoint-url', CDN_ENDPOINT],
        capture_output=True, text=True, timeout=120,
    )


def cdn_upload(local_path, cdn_key, content_type):
    r = cdn_cmd(['s3', 'cp', str(local_path), f's3://{CDN_BUCKET}/{cdn_key}',
                 '--acl', 'public-read', '--content-type', content_type,
                 '--cache-control', 'max-age=300', '--quiet'])
    return r.returncode == 0


def cdn_list(prefix):
    r = cdn_cmd(['s3', 'ls', f's3://{CDN_BUCKET}/{prefix}'])
    return [l.split()[-1] for l in r.stdout.splitlines() if l.split()]


def cdn_delete(cdn_key):
    return cdn_cmd(['s3', 'rm', f's3://{CDN_BUCKET}/{cdn_key}', '--quiet']).returncode == 0


# ─── Render de la capa de temperatura ──────────────────────────────
def render_temp(grib_path: Path, png_path: Path) -> bool:
    try:
        ds = xr.open_dataset(grib_path, engine='cfgrib', backend_kwargs={'indexpath': ''})
        row, col, valid = build_reproj_lut(ds)
        t_k = ds['t2m'].values.astype('float32')
        sampled = t_k[row, col]
        # Stencil: solo tierra (la temperatura no se ve en el mar).
        land = get_land_mask()
        valid_data = valid & np.isfinite(sampled) & land
        rgba = colorize_temp(k_to_f(sampled), valid_data)
        Image.fromarray(rgba, mode='RGBA').save(png_path, 'PNG', optimize=True, compress_level=6)
        ds.close()
        return True
    except Exception as e:
        log.error(f"  render error: {e}")
        import traceback; traceback.print_exc()
        return False


def process(date_str=None, cycle=None):
    base = f"{CDN_BASE}/conus"
    if date_str and cycle is not None:
        grib = WORK_DIR / f'nbm_{date_str}_{cycle:02d}.grib2'
        if not download_nbm(date_str, int(cycle), NOW_FH, grib):
            log.error("  no se pudo descargar el ciclo indicado")
            return 0
    else:
        date_str, cycle, grib = detect_cycle()
        if not grib:
            log.error("  no se encontró ciclo NBM con f001 disponible")
            return 0
    log.info(f"── NBM temp · ciclo {date_str}/{cycle:02d}z f{NOW_FH:03d} ──")

    # Hora válida del frame (ciclo + lead).
    cyc_dt = datetime.strptime(f"{date_str}{int(cycle):02d}", '%Y%m%d%H').replace(tzinfo=timezone.utc)
    valid_dt = cyc_dt + timedelta(hours=NOW_FH)
    stem = f"temp_{valid_dt.strftime('%Y%m%d%H%M%S')}"

    png = WORK_DIR / f'{stem}.png'
    ok = render_temp(grib, png)
    try: grib.unlink()
    except Exception: pass
    if not ok:
        return 0

    if not cdn_upload(png, f'{base}/{stem}.png', 'image/png'):
        log.error("  fallo subiendo el PNG")
        return 0
    log.info(f"  ☁️  {stem}.png")

    manifest = {
        'model': 'NBM', 'product': 'core', 'var': 't2m', 'units': 'F',
        'cycle': f"{date_str}{int(cycle):02d}", 'fh': NOW_FH,
        'bounds': VIEW['bounds'], 'width': VIEW['out_w'], 'height': VIEW['out_h'],
        'frames': [{
            'url': f'{CDN_URL_ROOT}/conus/{stem}.png',
            'timestamp': int(valid_dt.timestamp()),
            'iso': valid_dt.isoformat(),
        }],
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    mpath = WORK_DIR / 'manifest.json'
    mpath.write_text(json.dumps(manifest, indent=2))
    cdn_upload(mpath, f'{base}/manifest.json', 'application/json')
    mpath.unlink()

    # Limpieza: borra PNG antiguos del CDN que no sean el actual.
    for k in cdn_list(base + '/'):
        if k.endswith('.png') and Path(k).stem != stem:
            cdn_delete(f'{base}/{k}')
    try: png.unlink()
    except Exception: pass
    log.info("  manifest actualizado")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--date', default=None, help='YYYYMMDD (opcional, fuerza ciclo)')
    ap.add_argument('--cycle', default=None, help='HH del ciclo (opcional)')
    args = ap.parse_args()

    t0 = time.time()
    log.info("═══ NBM temp pipeline ═══")
    n = process(args.date, args.cycle)
    log.info(f"═══ Completado en {time.time()-t0:.1f}s · {n} frame(s) ═══")


if __name__ == '__main__':
    main()
