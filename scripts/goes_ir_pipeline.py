#!/usr/bin/env python3
"""
GOES IR (banda 13) Pipeline — Canal Meteo TV
─────────────────────────────────────────────────────────────────────
Descarga la imaginería cruda ABI-L2 "Cloud & Moisture" banda 13 (ventana IR
limpia, 10.3 µm) de GOES-19 (Este + sector CONUS) y GOES-18 (Oeste) desde el
bucket público de AWS Open Data (acceso anónimo), aplica NUESTRA paleta (estilo
windy) con TRANSPARENCIA en el cielo despejado/caliente, reproyecta de la
proyección geoestacionaria a equirectangular con espaciado Mercator (para que
case con el `image source` de Mapbox), y sube PNG transparentes + manifest al CDN.

Así el satélite se drapea sobre el mapa base igual que el radar MRMS, con
transparencia real y la paleta que queramos (como Baron/WSI/windy). El geocolor
no permite esto porque ya viene pintado.

Vistas:
  - este  : GOES-19 full disk (ABI-L2-CMIPF)  → data/goes_ir/este/
  - oeste : GOES-18 full disk (ABI-L2-CMIPF)  → data/goes_ir/oeste/
  - conus : GOES-19 sector CONUS (ABI-L2-CMIPC, 5 min, alta resolución) → data/goes_ir/conus/

Uso:
  /opt/canalmeteo/venv/bin/python3 goes_ir_pipeline.py --once
  /opt/canalmeteo/venv/bin/python3 goes_ir_pipeline.py --once --views conus
"""

import os
# Los NetCDF de GOES son HDF5; sin esto netCDF4 falla con "HDF error -101" por el
# bloqueo de archivos. DEBE fijarse antes de importar xarray/netCDF4.
os.environ.setdefault('HDF5_USE_FILE_LOCKING', 'FALSE')

import sys
import json
import time
import logging
import argparse
import subprocess
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

# IMPORTANTE: netCDF4 ANTES que pyproj. pyproj trae su propia pila de librerías
# nativas (PROJ/GDAL) que, si se cargan antes que HDF5, rompen la apertura de los
# NetCDF de GOES con "HDF error -101". Importar netCDF4 aquí inicializa HDF5 primero.
import netCDF4  # noqa: F401  (efecto de orden de carga, no se usa directamente)
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
CDN_BASE = 'data/goes_ir'
CDN_URL_ROOT = f'https://{CDN_BUCKET}.sfo3.digitaloceanspaces.com/{CDN_BASE}'

WORK_DIR = Path('/tmp/goes_ir_work')
WORK_DIR.mkdir(exist_ok=True)

# ─── Vistas a procesar ─────────────────────────────────────────────
# bounds = recuadro equirectangular de salida (coords del image source Mapbox).
# span_min = ventana temporal a cubrir (≥3 h). bucket_sec = cadencia (1 frame por
# bucket, estable para el cache). max_frames = tope de frames en el manifest.
VIEWS = {
    'este': {
        'aws_bucket': 'noaa-goes19',
        'product': 'ABI-L2-CMIPF',  # full disk (cada 10 min)
        'sat': 'GOES19',
        'bounds': {'north': 62.0, 'south': -62.0, 'west': -130.0, 'east': -10.0},
        'out_w': 2400, 'out_h': 2400,
        'span_min': 195, 'bucket_sec': 900, 'max_frames': 14,
    },
    'oeste': {
        'aws_bucket': 'noaa-goes18',
        'product': 'ABI-L2-CMIPF',  # full disk (cada 10 min)
        'sat': 'GOES18',
        'bounds': {'north': 62.0, 'south': -62.0, 'west': -180.0, 'east': -70.0},
        'out_w': 2400, 'out_h': 2400,
        'span_min': 195, 'bucket_sec': 900, 'max_frames': 14,
    },
    'conus': {
        'aws_bucket': 'noaa-goes19',
        'product': 'ABI-L2-CMIPC',  # sector CONUS (5 min, alta resolución)
        'sat': 'GOES19',
        'bounds': {'north': 52.0, 'south': 20.0, 'west': -128.0, 'east': -62.0},
        'out_w': 2800, 'out_h': 1500,
        'span_min': 195, 'bucket_sec': 600, 'max_frames': 19,
    },
}

# ─── Paletas IR (temperatura de brillo K → color RGB) ───────────────
# Temperaturas de cálidas (arriba) a frías (abajo).
#
# WINDY (colorida): nubes bajas gris-blanco; topes fríos azul→cian→verde→
# amarillo→rojo→magenta. GUARDADA para otros productos (no se usa en tiempo_CONUS).
PALETTE_WINDY = [
    (300.0, (255, 255, 255)),
    (283.0, (245, 248, 250)),
    (273.0, (235, 240, 245)),
    (263.0, (215, 224, 232)),
    (253.0, (188, 202, 215)),
    (243.0, (150, 178, 210)),
    (233.0, (95, 150, 215)),
    (223.0, (60, 120, 210)),
    (213.0, (40, 200, 190)),
    (203.0, (120, 220, 80)),
    (198.0, (245, 235, 70)),
    (193.0, (248, 150, 40)),
    (188.0, (230, 45, 40)),
    (183.0, (200, 30, 125)),
    (170.0, (255, 255, 255)),
]

# WHITE (solo blancos): nubes en blanco/gris claro; la profundidad/altura de la
# nube se transmite SOLO con la opacidad (más frío = más opaco y más brillante).
# Es la paleta ACTIVA de tiempo_CONUS (los colores se perdían sobre el mapa).
PALETTE_WHITE = [
    (300.0, (255, 255, 255)),
    (283.0, (220, 224, 228)),   # nube baja muy tenue, gris claro
    (273.0, (228, 231, 235)),
    (253.0, (238, 240, 243)),
    (233.0, (247, 248, 250)),
    (213.0, (255, 255, 255)),   # topes fríos: blanco puro
    (170.0, (255, 255, 255)),
]

# Paleta activa para este producto.
ACTIVE_PALETTE = PALETTE_WHITE


def _alpha_ramp(temps):
    """Opacidad por temperatura: despejado transparente; nube translúcida; topes
    fríos casi opacos. Común a todas las paletas."""
    A = np.zeros_like(temps)
    A[temps >= 283.0] = 0.0
    m1 = (temps < 283.0) & (temps >= 273.0)
    A[m1] = (283.0 - temps[m1]) / 10.0 * 0.50           # 0 → 0.50
    m2 = (temps < 273.0) & (temps >= 235.0)
    A[m2] = 0.50 + (273.0 - temps[m2]) / 38.0 * 0.45    # 0.50 → 0.95
    A[temps < 235.0] = 0.98
    return A


def build_ir_lut(stops):
    """LUT indexada por temperatura [T_MIN..T_MAX] → RGBA uint8 para una paleta."""
    T_MAX, T_MIN = 310.0, 170.0
    N = 1024
    temps = np.linspace(T_MAX, T_MIN, N)  # cálido→frío
    sk = sorted(stops, key=lambda s: s[0])
    ks = np.array([s[0] for s in sk])
    r = np.array([s[1][0] for s in sk]); g = np.array([s[1][1] for s in sk]); b = np.array([s[1][2] for s in sk])
    R = np.interp(temps, ks, r); G = np.interp(temps, ks, g); B = np.interp(temps, ks, b)
    A = _alpha_ramp(temps)
    rgba = np.stack([R, G, B, A * 255.0], axis=1).astype(np.uint8)
    return rgba, T_MAX, T_MIN, N


_IR_LUT, _LUT_TMAX, _LUT_TMIN, _LUT_N = build_ir_lut(ACTIVE_PALETTE)


def colorize_ir(tb_kelvin: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Mapea temperatura de brillo (K) → RGBA uint8 con la paleta windy."""
    idx = (( _LUT_TMAX - tb_kelvin) / (_LUT_TMAX - _LUT_TMIN) * (_LUT_N - 1))
    idx = np.clip(np.nan_to_num(idx, nan=0.0), 0, _LUT_N - 1).astype(np.int32)
    out = _IR_LUT[idx]                      # (H,W,4)
    out[~valid] = (0, 0, 0, 0)              # fuera de cobertura → transparente
    return out


# ─── Mercator helpers (para alinear con el mapa Mercator de Mapbox) ─
def lat_to_merc_y(lat):
    lat = np.clip(lat, -85.051129, 85.051129)
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def merc_y_to_lat(y):
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)


# ─── Reproyección geoestacionaria → equirectangular (LUT por vista) ─
_lut_cache = {}


def build_reproj_lut(view_key, cfg, ds):
    """Construye índices (row,col) del grid fuente para cada píxel de salida."""
    if view_key in _lut_cache:
        return _lut_cache[view_key]

    gip = ds['goes_imager_projection'].attrs
    h = float(gip['perspective_point_height'])
    lon0 = float(gip['longitude_of_projection_origin'])
    sweep = gip.get('sweep_angle_axis', 'x')
    a = float(gip['semi_major_axis']); b = float(gip['semi_minor_axis'])

    geos = CRS.from_proj4(
        f"+proj=geos +h={h} +lon_0={lon0} +sweep={sweep} +a={a} +b={b} +units=m +no_defs"
    )
    tf = Transformer.from_crs("EPSG:4326", geos, always_xy=True)

    # x,y del NetCDF son ángulos de escaneo (rad) → metros geos = ángulo * h
    xm = ds['x'].values.astype('float64') * h
    ym = ds['y'].values.astype('float64') * h
    x0, dx = xm[0], (xm[1] - xm[0])
    y0, dy = ym[0], (ym[1] - ym[0])
    src_h, src_w = ds['CMI'].shape

    bn = cfg['bounds']
    W, H = cfg['out_w'], cfg['out_h']
    # Filas espaciadas en Mercator (no lineal en lat) para casar con Mapbox.
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

    _lut_cache[view_key] = (row, col, valid)
    return _lut_cache[view_key]


# ─── AWS GOES (anónimo) ────────────────────────────────────────────
def aws_anon_ls(bucket, prefix):
    cmd = ['aws', 's3', 'ls', '--no-sign-request', f's3://{bucket}/{prefix}']
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return out.stdout.splitlines()
    except Exception as e:
        log.error(f"  ls error: {e}")
        return []


def list_latest_c13(cfg):
    """Lista los ficheros banda 13 que cubren las últimas `span_min`, a razón de
    1 por `bucket_sec` (cadencia estable para el cache), hasta `max_frames`."""
    now = datetime.now(timezone.utc)
    span_min = cfg.get('span_min', 195)
    bucket = cfg.get('bucket_sec', 600)
    n = cfg.get('max_frames', 18)
    cutoff = now.timestamp() - span_min * 60
    # Horas a mirar: las necesarias para cubrir la ventana + margen.
    hours_back = int(span_min / 60) + 2
    files = []  # (start_dt, key)
    for back in range(hours_back + 1):
        t = now - timedelta(hours=back)
        prefix = f"{cfg['product']}/{t.strftime('%Y')}/{t.strftime('%j')}/{t.strftime('%H')}/"
        for line in aws_anon_ls(cfg['aws_bucket'], prefix):
            parts = line.split()
            if not parts:
                continue
            fname = parts[-1]
            if not fname.endswith('.nc') or 'C13' not in fname:
                continue
            m = re.search(r'_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})', fname)
            if not m:
                continue
            yr, jd, hh, mm, ss = m.groups()
            sdt = datetime.strptime(f"{yr}{jd}{hh}{mm}{ss}", '%Y%j%H%M%S').replace(tzinfo=timezone.utc)
            if sdt.timestamp() >= cutoff:
                files.append((sdt, prefix + fname))
    # 1 frame por bucket (el más reciente de cada bucket) → cadencia estable.
    by_bucket = {}
    for sdt, key in files:
        b = int(sdt.timestamp() // bucket)
        if b not in by_bucket or sdt > by_bucket[b][0]:
            by_bucket[b] = (sdt, key)
    chosen = sorted(by_bucket.values(), key=lambda x: x[0], reverse=True)[:n]
    return chosen


def aws_anon_download(bucket, key, dst):
    cmd = ['aws', 's3', 'cp', '--no-sign-request', f's3://{bucket}/{key}', str(dst), '--quiet']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return r.returncode == 0 and dst.exists()
    except Exception as e:
        log.error(f"  download error: {e}")
        return False


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


# ─── Procesado de una vista ────────────────────────────────────────
def render_frame(nc_path: Path, png_path: Path, view_key: str, cfg: dict) -> bool:
    try:
        ds = xr.open_dataset(nc_path, engine='netcdf4', lock=False)
        row, col, valid = build_reproj_lut(view_key, cfg, ds)
        tb = ds['CMI'].values.astype('float32')  # temperatura de brillo (K)
        sampled = tb[row, col]
        valid_data = valid & np.isfinite(sampled)
        rgba = colorize_ir(sampled, valid_data)
        Image.fromarray(rgba, mode='RGBA').save(png_path, 'PNG', optimize=True, compress_level=6)
        ds.close()
        return True
    except Exception as e:
        log.error(f"  render error: {e}")
        import traceback; traceback.print_exc()
        return False


def process_view(view_key: str):
    cfg = VIEWS[view_key]
    log.info(f"── vista '{view_key}' ({cfg['sat']} {cfg['product']}) ──")
    base = f"{CDN_BASE}/{view_key}"
    latest = list_latest_c13(cfg)
    if not latest:
        log.error(f"  sin ficheros C13 en AWS para '{view_key}'")
        return 0
    latest = list(reversed(latest))  # viejo→nuevo

    existing = {Path(k).stem for k in cdn_list(base + '/') if k.endswith('.png')}
    frames_manifest = []
    new = 0
    for sdt, key in latest:
        stem = f"ir_{sdt.strftime('%Y%m%d%H%M%S')}"
        info = {'url': f'{CDN_URL_ROOT}/{view_key}/{stem}.png',
                'timestamp': int(sdt.timestamp()), 'iso': sdt.isoformat()}
        if stem in existing:
            frames_manifest.append(info)
            continue
        nc = WORK_DIR / Path(key).name
        if not aws_anon_download(cfg['aws_bucket'], key, nc):
            continue
        png = WORK_DIR / f'{stem}.png'
        ok = render_frame(nc, png, view_key, cfg)
        try: nc.unlink()
        except Exception: pass
        if not ok:
            continue
        if cdn_upload(png, f'{base}/{stem}.png', 'image/png'):
            frames_manifest.append(info); new += 1
            log.info(f"  ☁️  {stem}.png")
        try: png.unlink()
        except Exception: pass

    frames_manifest.sort(key=lambda f: f['timestamp'])
    manifest = {
        'sat': cfg['sat'], 'product': cfg['product'], 'band': 'C13',
        'bounds': cfg['bounds'], 'width': cfg['out_w'], 'height': cfg['out_h'],
        'count': len(frames_manifest), 'frames': frames_manifest,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    mpath = WORK_DIR / f'manifest_{view_key}.json'
    mpath.write_text(json.dumps(manifest, indent=2))
    cdn_upload(mpath, f'{base}/manifest.json', 'application/json')
    mpath.unlink()

    # Limpieza: borrar PNG del CDN que ya no estén en el manifest.
    keep = {Path(f['url']).stem for f in frames_manifest}
    for k in cdn_list(base + '/'):
        if k.endswith('.png') and Path(k).stem not in keep:
            cdn_delete(f'{base}/{k}')
    log.info(f"  vista '{view_key}': {len(frames_manifest)} frames ({new} nuevos)")
    return len(frames_manifest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--views', default='este,oeste,conus',
                    help='vistas a procesar, coma-separadas (este,oeste,conus)')
    args = ap.parse_args()

    t0 = time.time()
    views = [v.strip() for v in args.views.split(',') if v.strip() in VIEWS]
    log.info(f"═══ GOES IR pipeline · vistas={views} ═══")
    total = 0
    for v in views:
        try:
            total += process_view(v)
        except Exception as e:
            log.error(f"vista '{v}' falló: {e}")
            import traceback; traceback.print_exc()
    log.info(f"═══ Completado en {time.time()-t0:.1f}s · {total} frames totales ═══")


if __name__ == '__main__':
    main()
