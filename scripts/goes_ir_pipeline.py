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
import math
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
CDN_URL_ROOT = f'https://{CDN_BUCKET}.sfo3.cdn.digitaloceanspaces.com/{CDN_BASE}'

WORK_DIR = Path('/tmp/goes_ir_work')
WORK_DIR.mkdir(exist_ok=True)

# ─── Vistas a procesar ─────────────────────────────────────────────
# bounds = recuadro equirectangular de salida (coords del image source Mapbox).
# span_min = ventana temporal a cubrir (≥3 h). bucket_sec = cadencia (1 frame por
# bucket, estable para el cache). max_frames = tope de frames en el manifest.
# #8 Studio: los PNG viven EXT_HOURS en el CDN y se publican además en
# manifest_extended.json por vista (conus ~576 frames a 10 min, discos ~384 a 15).
EXT_HOURS = 96
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
        # ~6 h de historia (Remotion decima a 10 frames para el bucle).
        'span_min': 375, 'bucket_sec': 600, 'max_frames': 38,
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

# W-15: rampa IR estándar EN KELVIN para quien pinte por valor desde `url_raw`
# (cálido oscuro → frío blanco, con el realce clásico en los topes muy fríos).
IR_RAMPA_K = [
    (310.0, '#000000'), (295.0, '#3a3a3a'), (280.0, '#6e6e6e'),
    (265.0, '#9c9c9c'), (250.0, '#c8c8c8'), (240.0, '#ffffff'),
    (235.0, '#00b4b4'), (230.0, '#00c800'), (225.0, '#ffff00'),
    (220.0, '#ff9600'), (215.0, '#ff0000'), (205.0, '#c800c8'),
    (195.0, '#ffffff'), (180.0, '#b4b4ff'),
]


def _res_km(cfg):
    """Kilómetros por píxel en el centro de la vista (W-17.3)."""
    b = cfg['bounds']
    lat_c = (b['north'] + b['south']) / 2
    return round((b['east'] - b['west']) * 111.32 * math.cos(math.radians(lat_c))
                 / cfg['out_w'], 3)


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


# W-3 del Studio Pro: gemelo CRUDO en gris 8 bits con la temperatura de brillo.
# K = raw*RAW_SCALE + RAW_TMIN; raw 0 = fuera de cobertura. Los datos válidos se
# recortan a 1 para no confundirse con el nodata (170 K no se da en la realidad).
RAW_TMIN, RAW_TMAX = 170.0, 310.0
RAW_SCALE = (RAW_TMAX - RAW_TMIN) / 255.0


def crudo_ir(tb_kelvin: np.ndarray, valid: np.ndarray) -> np.ndarray:
    v = np.clip(np.round((np.nan_to_num(tb_kelvin, nan=RAW_TMIN) - RAW_TMIN) / RAW_SCALE),
                1, 255).astype(np.uint8)
    return np.where(valid, v, 0).astype(np.uint8)


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
def _s3_anon():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    if not hasattr(_s3_anon, 'c'):
        _s3_anon.c = boto3.client('s3', config=Config(signature_version=UNSIGNED),
                                  region_name='us-east-1')
    return _s3_anon.c


def aws_anon_ls(bucket, prefix):
    """Líneas «size basename» (los llamadores hacen line.split()[-1])."""
    try:
        out, tok = [], None
        while True:
            kw = {'Bucket': bucket, 'Prefix': prefix, 'MaxKeys': 1000}
            if tok:
                kw['ContinuationToken'] = tok
            r = _s3_anon().list_objects_v2(**kw)
            out += [f"{o['Size']} {o['Key'].rsplit('/', 1)[-1]}"
                    for o in r.get('Contents', [])]
            if not r.get('IsTruncated'):
                return out
            tok = r.get('NextContinuationToken')
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
    try:
        _s3_anon().download_file(bucket, key, str(dst))
        return dst.exists()
    except Exception as e:
        log.error(f"  download error: {e}")
        return False


# ─── CDN (DigitalOcean, boto3 en proceso — limpieza de carga 26/07) ─────────
def _cdn_client():
    import boto3
    if not hasattr(_cdn_client, 'c'):
        _cdn_client.c = boto3.Session(profile_name=AWS_PROFILE).client(
            's3', endpoint_url=CDN_ENDPOINT)
    return _cdn_client.c


def cdn_upload(local_path, cdn_key, content_type):
    try:
        _cdn_client().upload_file(str(local_path), CDN_BUCKET, cdn_key,
                                  ExtraArgs={'ACL': 'public-read',
                                             'ContentType': content_type,
                                             'CacheControl': 'max-age=300'})
        return True
    except Exception:
        return False


def cdn_list(prefix):
    base = prefix[:prefix.rfind('/') + 1] if '/' in prefix else ''
    out, tok = [], None
    try:
        while True:
            kw = {'Bucket': CDN_BUCKET, 'Prefix': prefix, 'MaxKeys': 1000}
            if tok:
                kw['ContinuationToken'] = tok
            r = _cdn_client().list_objects_v2(**kw)
            for o in r.get('Contents', []):
                resto = o['Key'][len(base):]
                if resto and '/' not in resto:
                    out.append(resto)
            if not r.get('IsTruncated'):
                return out
            tok = r.get('NextContinuationToken')
    except Exception:
        return out


def cdn_delete(cdn_key):
    try:
        _cdn_client().delete_object(Bucket=CDN_BUCKET, Key=cdn_key)
        return True
    except Exception:
        return False


# ─── Procesado de una vista ────────────────────────────────────────
_ULTIMO_CRUDO = {}      # vista → (datetime, array del crudo)


def _motion(raw_png, view_key, sdt, destino):
    """Campo de movimiento contra el fotograma anterior de ESTA vista.

    El crudo anterior se guarda en memoria dentro de la pasada; entre pasadas se
    relee del disco de trabajo si sigue ahí. Si no hay anterior, no se publica
    nada (el primer fotograma de una serie no tiene con qué compararse).
    """
    try:
        import movimiento
        from PIL import Image
        actual = np.asarray(Image.open(raw_png).convert('L'), dtype='float32')
        prev = _ULTIMO_CRUDO.get(view_key)
        if not prev:
            # Cada pasada del cron es un proceso nuevo y normalmente solo trae UN
            # fotograma, así que el anterior tiene que sobrevivir en disco o no
            # habría nunca con qué comparar (03/10).
            cache = WORK_DIR / f'motion_prev_{view_key}.png'
            sello = WORK_DIR / f'motion_prev_{view_key}.txt'
            try:
                t_prev = datetime.fromisoformat(sello.read_text().strip())
                prev = (t_prev, np.asarray(Image.open(cache).convert('L'), dtype='float32'))
            except Exception:
                prev = None
        _ULTIMO_CRUDO[view_key] = (sdt, actual)
        try:
            import shutil
            shutil.copyfile(raw_png, WORK_DIR / f'motion_prev_{view_key}.png')
            (WORK_DIR / f'motion_prev_{view_key}.txt').write_text(sdt.isoformat())
        except OSError:
            pass
        if not prev:
            return False
        minutos = (sdt - prev[0]).total_seconds() / 60.0
        # saltos muy largos (hueco en la serie) no sirven para advectar
        if not (0 < minutos <= 40) or prev[1].shape != actual.shape:
            return False
        return movimiento.escribir_png(prev[1], actual, minutos, destino)
    except Exception as e:
        log.warning(f'  campo de movimiento: {type(e).__name__}: {e}')
        return False


def render_frame(nc_path: Path, png_path: Path, view_key: str, cfg: dict,
                 raw_path: Path | None = None) -> bool:
    try:
        ds = xr.open_dataset(nc_path, engine='netcdf4', lock=False)
        row, col, valid = build_reproj_lut(view_key, cfg, ds)
        tb = ds['CMI'].values.astype('float32')  # temperatura de brillo (K)
        sampled = tb[row, col]
        valid_data = valid & np.isfinite(sampled)
        rgba = colorize_ir(sampled, valid_data)
        Image.fromarray(rgba, mode='RGBA').save(png_path, 'PNG', optimize=True, compress_level=6)
        if raw_path is not None:
            Image.fromarray(crudo_ir(sampled, valid_data), mode='L').save(
                raw_path, 'PNG', optimize=True, compress_level=6)
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
            if f'{stem}_raw' in existing:
                info['url_raw'] = f'{CDN_URL_ROOT}/{view_key}/{stem}_raw.png'
            # 04/10: el campo de movimiento se subía bien pero solo salía en el
            # manifiesto de la pasada que lo generó; en la siguiente el fotograma
            # ya era «existente» y se publicaba sin él. Resultado: 0 url_motion.
            if f'{stem}_motion' in existing:
                info['url_motion'] = f'{CDN_URL_ROOT}/{view_key}/{stem}_motion.png'
            frames_manifest.append(info)
            continue
        nc = WORK_DIR / Path(key).name
        if not aws_anon_download(cfg['aws_bucket'], key, nc):
            continue
        png = WORK_DIR / f'{stem}.png'
        raw = WORK_DIR / f'{stem}_raw.png'
        mot = WORK_DIR / f'{stem}_motion.png'
        ok = render_frame(nc, png, view_key, cfg, raw)
        try: nc.unlink()
        except Exception: pass
        if not ok:
            continue
        if cdn_upload(png, f'{base}/{stem}.png', 'image/png'):
            # el crudo es un extra: si falla, el frame de color se publica igual
            if raw.exists() and cdn_upload(raw, f'{base}/{stem}_raw.png', 'image/png'):
                info['url_raw'] = f'{CDN_URL_ROOT}/{view_key}/{stem}_raw.png'
                # W-20.3 (03/10): campo de movimiento contra el fotograma
                # anterior, para que el Studio ADVECTE al interpolar en vez de
                # fundir (dos nubes fundidas dan fantasmas; desplazarlas, no).
                if _motion(raw, view_key, sdt, mot) and cdn_upload(
                        mot, f'{base}/{stem}_motion.png', 'image/png'):
                    info['url_motion'] = f'{CDN_URL_ROOT}/{view_key}/{stem}_motion.png'
            frames_manifest.append(info); new += 1
            log.info(f"  ☁️  {stem}.png" + (' +mov' if info.get('url_motion') else ''))
        for f_ in (png, raw, mot):
            try: f_.unlink()
            except Exception: pass

    frames_manifest.sort(key=lambda f: f['timestamp'])

    # Guard: si el listado de AWS Open Data vino corto (outage GOES/AWS),
    # publicar este manifest encogido y limpiar el CDN borraría frames buenos
    # y dejaría la animación con 2-3 frames durante horas. Conservar lo previo.
    min_frames = max(2, cfg.get('max_frames', 18) // 2)
    if len(frames_manifest) < min_frames:
        log.warning(f"  vista '{view_key}': solo {len(frames_manifest)} frames "
                    f"(<{min_frames}) — listado corto, conservo manifest y CDN previos")
        return len(frames_manifest)

    manifest = {
        'sat': cfg['sat'], 'product': cfg['product'], 'band': 'C13',
        'bounds': cfg['bounds'], 'width': cfg['out_w'], 'height': cfg['out_h'],
        'count': len(frames_manifest), 'frames': frames_manifest,
        'projection': 'EPSG:3857',
        # W-15 (23/09): la leyenda que publicábamos eran los blancos de la paleta
        # de superposición (todo #ffffff) y encima en °C mientras el crudo va en
        # K: colorear por valor con ella salía en blanco. Ahora es la rampa IR
        # de verdad, EN KELVIN como `encoding`, para pintar por valor. El PNG de
        # color sigue siendo blanco+alfa, que es lo que se ve bien sobre el mapa.
        'render': 'blanco+alfa (superposición); para colorear por valor, usar url_raw',
        'legend': {'units': 'K', 'vmin': 180, 'vmax': 310,
                   'stops': [{'value': k, 'color': c} for k, c in IR_RAMPA_K]},
        'resolution_km': _res_km(cfg),
        'cadence_s': cfg['bucket_sec'],   # ya iba en el extendido; ahora también aquí
        # W-3 Studio Pro: cómo leer `url_raw` (gris 8 bits, misma rejilla que el color)
        'motion_encoding': __import__('movimiento').ENCODING,
        'encoding': {'bits': 8, 'scale': round(RAW_SCALE, 8), 'offset': RAW_TMIN,
                     'nodata': 0, 'units': 'K', 'kind': 'gradient'},
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    mpath = WORK_DIR / f'manifest_{view_key}.json'
    mpath.write_text(json.dumps(manifest, indent=2))
    cdn_upload(mpath, f'{base}/manifest.json', 'application/json; charset=utf-8')
    mpath.unlink()

    # #8 Studio: manifest_extended.json con TODO lo que hay en el CDN dentro de
    # las últimas EXT_HOURS (el histórico se acumula solo: la limpieza de abajo
    # ya no borra hasta cumplir la ventana extendida).
    ext_cutoff = datetime.now(timezone.utc) - timedelta(hours=EXT_HOURS)
    claves_cdn = cdn_list(base + '/')
    ext_frames = {}
    crudos = {Path(k).stem[:-4] for k in claves_cdn if Path(k).stem.endswith('_raw')}
    for k in claves_cdn:
        if not k.endswith('.png') or Path(k).stem.endswith('_raw'):
            continue
        try:
            v = datetime.strptime(Path(k).stem.split('_')[-1], '%Y%m%d%H%M%S') \
                    .replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if v >= ext_cutoff:
            entrada = {'url': f'{CDN_URL_ROOT}/{view_key}/{Path(k).stem}.png',
                       'timestamp': int(v.timestamp()), 'iso': v.isoformat()}
            if Path(k).stem in crudos:
                entrada['url_raw'] = f'{CDN_URL_ROOT}/{view_key}/{Path(k).stem}_raw.png'
            ext_frames[Path(k).stem] = entrada
    for f_ in frames_manifest:  # los recién subidos pueden no estar en el listado
        ext_frames[Path(f_['url']).stem] = dict(f_)
    ext_lista = sorted(ext_frames.values(), key=lambda f: f['timestamp'])
    manifest_ext = dict(manifest, window_hours=EXT_HOURS, cadence_s=cfg['bucket_sec'],
                        count=len(ext_lista), frames=ext_lista)
    epath = WORK_DIR / f'manifest_ext_{view_key}.json'
    epath.write_text(json.dumps(manifest_ext, indent=2))
    cdn_upload(epath, f'{base}/manifest_extended.json', 'application/json; charset=utf-8')
    epath.unlink()

    # Limpieza: solo PNG más viejos que la ventana extendida (los que salen del
    # manifest corto siguen vivos para manifest_extended). La gracia de 1 h del
    # criterio #25/#20 queda subsumida: nada de <96 h se borra.
    keep = {Path(f['url']).stem for f in frames_manifest}
    for k in claves_cdn:
        if not k.endswith('.png') or Path(k).stem in keep:
            continue
        # El gemelo crudo se borra CON su frame: su nombre no parsea como fecha y
        # si no, se quedaría en el CDN para siempre.
        nombre = Path(k).stem
        es_crudo = nombre.endswith('_raw')
        base_stem = nombre[:-4] if es_crudo else nombre
        if es_crudo and base_stem in keep:
            continue
        try:
            v = datetime.strptime(base_stem.split('_')[-1], '%Y%m%d%H%M%S') \
                    .replace(tzinfo=timezone.utc)
        except ValueError:
            continue  # nombre inesperado: no lo tocamos
        if v < ext_cutoff:
            cdn_delete(f'{base}/{k}')
    log.info(f"  vista '{view_key}': {len(frames_manifest)} frames ({new} nuevos, "
             f"{len(ext_lista)} en ext)")
    return len(frames_manifest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--views', default='este,oeste,conus',
                    help='vistas a procesar, coma-separadas (este,oeste,conus)')
    # OJO: el cron llama con --palette windy cada 3 min. Este flag se perdió en
    # la edición del 2026-06-22 (bak-20260622_154741) y la paleta windy estuvo
    # 10 días congelada en el CDN. No retirarlo sin cambiar el cron.
    ap.add_argument('--palette', default='white', choices=['white', 'windy'],
                    help='paleta (white → data/goes_ir; windy → data/goes_ir_windy)')
    args = ap.parse_args()

    # Paleta windy: cambiar LUT y rutas de salida ANTES de procesar.
    if args.palette == 'windy':
        global ACTIVE_PALETTE, CDN_BASE, CDN_URL_ROOT, _IR_LUT, _LUT_TMAX, _LUT_TMIN, _LUT_N
        ACTIVE_PALETTE = PALETTE_WINDY
        CDN_BASE = 'data/goes_ir_windy'
        CDN_URL_ROOT = f'https://{CDN_BUCKET}.sfo3.cdn.digitaloceanspaces.com/{CDN_BASE}'
        _IR_LUT, _LUT_TMAX, _LUT_TMIN, _LUT_N = build_ir_lut(ACTIVE_PALETTE)

    # WORK_DIR por paleta: los crons white (:0/3) y windy (:2/3, timeout 420s)
    # solapan; con un directorio compartido y nombres idénticos un proceso
    # puede subir/borrar los PNG/.nc del otro (frames con paleta cruzada).
    global WORK_DIR
    WORK_DIR = Path(f'/tmp/goes_ir_work_{args.palette}')
    WORK_DIR.mkdir(exist_ok=True)

    t0 = time.time()
    views = [v.strip() for v in args.views.split(',') if v.strip() in VIEWS]
    log.info(f"═══ GOES IR pipeline · paleta={args.palette} · vistas={views} ═══")
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
