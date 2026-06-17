#!/usr/bin/env python3
"""
NBM Precipitación a futuro (24 h) — Canal Meteo TV
─────────────────────────────────────────────────────────────────────
Descarga del NBM (AWS Open Data, anónimo) la precipitación HORARIA determinista
de las próximas 24 h y produce DOS salidas, drapeable como el satélite/radar:

  1) BUCLE "radar a futuro" (data/nbm/precip_fcst/conus/): un PNG por hora con la
     precipitación clasificada por TIPO — lluvia (verde), nieve (azul), hielo
     (rosa) — e intensidad por saturación.
  2) ACUMULADO 24 h (data/nbm/precip_accum/conus/): un PNG con el total de las
     24 h, mismo esquema lluvia/nieve/hielo.

Campos deterministas (pdt=8) por byte-range del .idx (rápido, ~1.5 MB c/u):
  APCP  (parameterNumber 8)   precipitación total (kg/m² = mm, equiv. líquido)
  ASNOW (parameterNumber 29)  nieve acumulada (m)
  FICEAC(parameterNumber 228) acreción de hielo (kg/m² = mm)

Reusa de nbm_temp_pipeline: reproyección Lambert→equirect Mercator, máscara
tierra/mar (stencil) y utilidades de CDN.

Uso:
  /opt/canalmeteo/venv/bin/python3 nbm_precip_pipeline.py --once
  ... --once --fhmax 24 --step 2     (paso del bucle, h)
"""

import sys
import json
import time
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import eccodes as ec
from pyproj import CRS, Transformer

import nbm_temp_pipeline as nt  # reproj/máscara/CDN compartidos

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

CDN_URL_ROOT = f'https://{nt.CDN_BUCKET}.sfo3.digitaloceanspaces.com/data/nbm'
CDN_BASE_FCST = 'data/nbm/precip_fcst/conus'
CDN_BASE_ACCUM = 'data/nbm/precip_accum/conus'

WORK = Path('/tmp/nbm_precip_work'); WORK.mkdir(exist_ok=True)

AWS_BUCKET = 'noaa-nbm-grib2-pds'
PARAMS = {8: 'APCP', 29: 'ASNOW', 228: 'FICEAC'}

# ─── Paletas por tipo (pulgadas → RGB) ──────────────────────────────
RAIN_STOPS = [(0.01, (178, 235, 160)), (0.1, (110, 205, 120)), (0.5, (45, 165, 75)),
              (1.5, (20, 120, 55)), (4.0, (12, 80, 85))]
SNOW_STOPS = [(0.1, (205, 230, 255)), (1.0, (120, 175, 240)), (3.0, (70, 120, 225)),
              (6.0, (95, 60, 185)), (12.0, (135, 35, 150))]
ICE_STOPS = [(0.01, (255, 205, 228)), (0.1, (238, 130, 180)), (0.3, (205, 50, 130)),
             (0.6, (150, 20, 95))]

# Umbrales mínimos para pintar (pulgadas). Distintos para acumulado (24 h) vs
# horario (tasa): así se evita el moteado de trazas y se ve solo precip relevante.
THR_ACCUM = (0.1, 0.5, 0.02)   # (lluvia, nieve, hielo)
THR_HOURLY = (0.03, 0.1, 0.005)

MM_TO_IN = 1.0 / 25.4
M_TO_IN = 39.3701


def ramp_rgb(val, stops):
    ks = np.array([s[0] for s in stops])
    r = np.array([s[1][0] for s in stops]); g = np.array([s[1][1] for s in stops]); b = np.array([s[1][2] for s in stops])
    R = np.interp(val, ks, r); G = np.interp(val, ks, g); B = np.interp(val, ks, b)
    return R, G, B


# ─── AWS: idx + byte-range de los 3 campos deterministas ────────────
def aws_text(key):
    r = subprocess.run(['aws', 's3', 'cp', '--no-sign-request', f's3://{AWS_BUCKET}/{key}', '-'],
                       capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ''


def aws_range(key, start, end, dst):
    rng = f'bytes={start}-{end}' if end != '' else f'bytes={start}-'
    r = subprocess.run(['aws', 's3api', 'get-object', '--no-sign-request', '--bucket', AWS_BUCKET,
                        '--key', key, '--range', rng, str(dst)],
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and dst.exists()


def fetch_det_fields(date_str, cycle, fh):
    """Descarga (por byte-range) los 3 campos deterministas de una hora fcst.
    Devuelve la ruta a un grib ensamblado, o None."""
    key = f'blend.{date_str}/{cycle:02d}/core/blend.t{cycle:02d}z.core.f{fh:03d}.co.grib2'
    idx = aws_text(key + '.idx')
    if not idx:
        return None
    recs = []
    for ln in idx.splitlines():
        p = ln.split(':')
        if len(p) < 6:
            continue
        recs.append((int(p[1]), p[3], p[5], len(p), p))
    recs.sort()
    offs = [r[0] for r in recs]
    sel = []
    for i, (off, var, tr, n, p) in enumerate(recs):
        # determinista = var objetivo, ventana "* hour acc fcst", sin sufijo
        # (percentil/probabilidad). La línea termina justo en ':' → 7 campos, último ''.
        if var in PARAMS.values() and 'acc fcst' in tr and n == 7 and p[6] == '':
            end = offs[i + 1] - 1 if i + 1 < len(offs) else ''
            sel.append((var, off, end))
    if len(sel) < 1:
        return None
    out = WORK / f'f{fh:03d}.grib2'
    if out.exists():
        out.unlink()
    tmp = WORK / f'f{fh:03d}_part.grib2'
    with open(out, 'wb') as fo:
        for var, off, end in sel:
            if aws_range(key, off, end, tmp):
                fo.write(tmp.read_bytes())
    try: tmp.unlink()
    except Exception: pass
    return out if out.exists() and out.stat().st_size > 1000 else None


def read_fields(grib_path):
    """Lee los campos deterministas (pdt=8) → {num: array (Ny,Nx)} + grid keys."""
    out = {}; grid = None
    f = open(grib_path, 'rb')
    while True:
        gid = ec.codes_grib_new_from_file(f)
        if gid is None:
            break
        num = ec.codes_get(gid, 'parameterNumber')
        pdt = ec.codes_get(gid, 'productDefinitionTemplateNumber')
        if pdt == 8 and num in PARAMS:
            nx = ec.codes_get(gid, 'Nx'); ny = ec.codes_get(gid, 'Ny')
            out[num] = ec.codes_get_values(gid).reshape(ny, nx).astype('float32')
            if grid is None:
                grid = dict(
                    Nx=nx, Ny=ny,
                    la1=ec.codes_get(gid, 'latitudeOfFirstGridPointInDegrees'),
                    lo1=ec.codes_get(gid, 'longitudeOfFirstGridPointInDegrees'),
                    lad=ec.codes_get(gid, 'LaDInDegrees'), lov=ec.codes_get(gid, 'LoVInDegrees'),
                    lat1=ec.codes_get(gid, 'Latin1InDegrees'), lat2=ec.codes_get(gid, 'Latin2InDegrees'),
                    dx=ec.codes_get(gid, 'DxInMetres'), dy=ec.codes_get(gid, 'DyInMetres'),
                )
        ec.codes_release(gid)
    f.close()
    return out, grid


# ─── Reproyección Lambert → equirect (LUT por grid) ─────────────────
_LUT = None


def build_lut(grid):
    global _LUT
    if _LUT is not None:
        return _LUT
    lov = grid['lov']; lov = lov - 360 if lov > 180 else lov
    lo1 = grid['lo1']; lo1 = lo1 - 360 if lo1 > 180 else lo1
    lcc = CRS.from_proj4(
        f"+proj=lcc +lat_1={grid['lat1']} +lat_2={grid['lat2']} +lat_0={grid['lad']} "
        f"+lon_0={lov} +x_0=0 +y_0=0 +R=6371200 +units=m +no_defs")
    tf = Transformer.from_crs("EPSG:4326", lcc, always_xy=True)
    x0, y0 = tf.transform(lo1, grid['la1'])
    dx, dy = grid['dx'], grid['dy']
    bn = nt.VIEW['bounds']; W, H = nt.VIEW['out_w'], nt.VIEW['out_h']
    my = np.linspace(nt.lat_to_merc_y(bn['north']), nt.lat_to_merc_y(bn['south']), H)
    lats = nt.merc_y_to_lat(my)
    lons = np.linspace(bn['west'], bn['east'], W)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    X, Y = tf.transform(lon_grid.ravel(), lat_grid.ravel())
    X = X.reshape(H, W); Y = Y.reshape(H, W)
    # Índices FRACCIONARIOS (no redondeados) → muestreo BILINEAL, que suaviza el
    # "rayado"/pixelado del vecino más cercano (igual idea que el remotion del
    # trópico, que remuestrea con bilineal).
    fcol = (X - x0) / dx
    frow = (Y - y0) / dy
    valid = (np.isfinite(X) & np.isfinite(Y) &
             (frow >= 0) & (frow <= grid['Ny'] - 1) & (fcol >= 0) & (fcol <= grid['Nx'] - 1))
    fcol = np.clip(fcol, 0, grid['Nx'] - 1); frow = np.clip(frow, 0, grid['Ny'] - 1)
    _LUT = (frow, fcol, valid)
    return _LUT


def sample(field, lut):
    """Muestreo BILINEAL del campo fuente sobre la rejilla de salida."""
    frow, fcol, valid = lut
    ny, nx = field.shape
    r0 = np.floor(frow).astype(np.int32); c0 = np.floor(fcol).astype(np.int32)
    r1 = np.minimum(r0 + 1, ny - 1); c1 = np.minimum(c0 + 1, nx - 1)
    dr = frow - r0; dc = fcol - c0
    out = ((1 - dr) * (1 - dc) * field[r0, c0] + (1 - dr) * dc * field[r0, c1]
           + dr * (1 - dc) * field[r1, c0] + dr * dc * field[r1, c1])
    out[~valid] = 0.0
    return out


# ─── Composición por tipo (lluvia/nieve/hielo) → RGBA ───────────────
def colorize_types(rain_in, snow_in, ice_in, land, thr=THR_ACCUM):
    H, W = rain_in.shape
    t_rain, t_snow, t_ice = thr
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    # Precedencia: hielo > nieve > lluvia (el más impactante manda).
    m_ice = (ice_in > t_ice) & land
    m_snow = (snow_in > t_snow) & land & ~m_ice
    m_rain = (rain_in > t_rain) & land & ~m_ice & ~m_snow
    for mask, val, stops in ((m_rain, rain_in, RAIN_STOPS),
                             (m_snow, snow_in, SNOW_STOPS),
                             (m_ice, ice_in, ICE_STOPS)):
        if not mask.any():
            continue
        R, G, B = ramp_rgb(val[mask], stops)
        rgba[mask, 0] = np.clip(R, 0, 255)
        rgba[mask, 1] = np.clip(G, 0, 255)
        rgba[mask, 2] = np.clip(B, 0, 255)
        rgba[mask, 3] = 255
    return rgba


def save_png(rgba, path):
    from PIL import Image
    Image.fromarray(rgba, 'RGBA').save(path, 'PNG', optimize=True, compress_level=6)


# ─── Ciclo NBM con f024 disponible ──────────────────────────────────
def detect_cycle():
    now = datetime.now(timezone.utc)
    for back in range(2, 10):  # f024 tarda ~1-2 h en publicarse entero
        t = now - timedelta(hours=back)
        date_str = t.strftime('%Y%m%d'); cycle = t.hour
        key = f'blend.{date_str}/{cycle:02d}/core/blend.t{cycle:02d}z.core.f024.co.grib2.idx'
        if aws_text(key):
            return date_str, cycle
    return None, None


def process(date_str=None, cycle=None, fhmax=24, step=2, accum_only=False):
    if not (date_str and cycle is not None):
        date_str, cycle = detect_cycle()
    if not date_str:
        log.error("  sin ciclo NBM con f024 disponible")
        return 0
    cycle = int(cycle)
    log.info(f"── NBM precip · ciclo {date_str}/{cycle:02d}z · 1..{fhmax}h ──")
    cyc_dt = datetime.strptime(f"{date_str}{cycle:02d}", '%Y%m%d%H').replace(tzinfo=timezone.utc)

    land = nt.get_land_mask()
    bn = nt.VIEW['bounds']
    acc_rain = acc_snow = acc_ice = None
    loop_frames = []

    for fh in range(1, fhmax + 1):
        g = fetch_det_fields(date_str, cycle, fh)
        if not g:
            log.warning(f"  f{fh:03d}: sin datos, salto")
            continue
        fields, grid = read_fields(g)
        try: g.unlink()
        except Exception: pass
        if not fields or grid is None:
            continue
        lut = build_lut(grid)
        zero = np.zeros((nt.VIEW['out_h'], nt.VIEW['out_w']), dtype='float32')
        rain = sample(fields[8], lut) * MM_TO_IN if 8 in fields else zero.copy()
        snow = sample(fields[29], lut) * M_TO_IN if 29 in fields else zero.copy()
        ice = sample(fields[228], lut) * MM_TO_IN if 228 in fields else zero.copy()

        if acc_rain is None:
            acc_rain, acc_snow, acc_ice = rain.copy(), snow.copy(), ice.copy()
        else:
            acc_rain += rain; acc_snow += snow; acc_ice += ice

        # Frame del bucle (cada `step` horas). El "radar a futuro" usa HRRR, así
        # que en producción este pipeline corre con --accum-only (solo el total).
        if not accum_only and fh % step == 0:
            valid_dt = cyc_dt + timedelta(hours=fh)
            stem = f"pcp_{valid_dt.strftime('%Y%m%d%H%M%S')}"
            png = WORK / f'{stem}.png'
            save_png(colorize_types(rain, snow, ice, land, THR_HOURLY), png)
            loop_frames.append((stem, png, valid_dt))
            log.info(f"  f{fh:03d} → frame bucle ({stem})")

    if acc_rain is None:
        log.error("  no se procesó ninguna hora")
        return 0

    # ── Subir bucle (solo si NO es accum-only; el bucle lo cubre HRRR) ──
    if not accum_only:
        for stem, png, vdt in loop_frames:
            nt.cdn_upload(png, f'{CDN_BASE_FCST}/{stem}.png', 'image/png')
            try: png.unlink()
            except Exception: pass
        fcst_manifest = {
            'model': 'NBM', 'product': 'precip_fcst_type', 'units': 'in',
            'cycle': f"{date_str}{cycle:02d}", 'bounds': bn,
            'width': nt.VIEW['out_w'], 'height': nt.VIEW['out_h'],
            'frames': [{'url': f'{CDN_URL_ROOT}/precip_fcst/conus/{s}.png',
                        'timestamp': int(v.timestamp()), 'iso': v.isoformat()}
                       for s, _, v in loop_frames],
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        _upload_manifest(fcst_manifest, CDN_BASE_FCST, {s for s, _, _ in loop_frames})

    # ── Subir acumulado 24 h ──
    stem_acc = f"accum_{date_str}{cycle:02d}_f{fhmax:03d}"
    png_acc = WORK / f'{stem_acc}.png'
    # Suavizado ligero del total (look continuo tipo trópico, sin pixelado).
    from scipy.ndimage import gaussian_filter
    acc_rain = gaussian_filter(acc_rain, sigma=1.2)
    acc_snow = gaussian_filter(acc_snow, sigma=1.2)
    acc_ice = gaussian_filter(acc_ice, sigma=1.2)
    save_png(colorize_types(acc_rain, acc_snow, acc_ice, land), png_acc)
    nt.cdn_upload(png_acc, f'{CDN_BASE_ACCUM}/{stem_acc}.png', 'image/png')
    valid_end = cyc_dt + timedelta(hours=fhmax)
    accum_manifest = {
        'model': 'NBM', 'product': 'precip_accum_type', 'units': 'in', 'hours': fhmax,
        'cycle': f"{date_str}{cycle:02d}", 'bounds': bn,
        'width': nt.VIEW['out_w'], 'height': nt.VIEW['out_h'],
        'frames': [{'url': f'{CDN_URL_ROOT}/precip_accum/conus/{stem_acc}.png',
                    'timestamp': int(valid_end.timestamp()), 'iso': valid_end.isoformat()}],
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    _upload_manifest(accum_manifest, CDN_BASE_ACCUM, {stem_acc})
    try: png_acc.unlink()
    except Exception: pass

    log.info(f"  bucle: {len(loop_frames)} frames · acumulado 24 h listo")
    return len(loop_frames)


def _upload_manifest(manifest, base, keep_stems):
    mpath = WORK / 'manifest.json'
    mpath.write_text(json.dumps(manifest, indent=2))
    nt.cdn_upload(mpath, f'{base}/manifest.json', 'application/json')
    mpath.unlink()
    for k in nt.cdn_list(base + '/'):
        if k.endswith('.png') and Path(k).stem not in keep_stems:
            nt.cdn_delete(f'{base}/{k}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--date', default=None)
    ap.add_argument('--cycle', default=None)
    ap.add_argument('--fhmax', type=int, default=24)
    ap.add_argument('--step', type=int, default=2)
    ap.add_argument('--accum-only', action='store_true', help='solo el total 24 h (sin bucle)')
    args = ap.parse_args()
    t0 = time.time()
    log.info("═══ NBM precip pipeline ═══")
    n = process(args.date, args.cycle, args.fhmax, args.step, args.accum_only)
    log.info(f"═══ Completado en {time.time()-t0:.1f}s · {n} frame(s) de bucle ═══")


if __name__ == '__main__':
    main()
