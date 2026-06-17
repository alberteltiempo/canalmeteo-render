#!/usr/bin/env python3
"""
HRRR "Radar a futuro" — Canal Meteo TV
─────────────────────────────────────────────────────────────────────
Descarga del HRRR (AWS Open Data, anónimo) la REFLECTIVIDAD COMPUESTA simulada
(REFC, dBZ) + el TIPO de precipitación categórico (CRAIN/CSNOW/CICEP/CFRZR) de las
próximas horas y produce un BUCLE de "radar a futuro" coloreado por tipo:
lluvia (verde→amarillo→rojo, escala de reflectividad), nieve (azul), hielo (rosa).

Es radar SIMULADO real (no un proxy de precip como el NBM). Se drapea sobre el
mapa base igual que el satélite/radar/temperatura.

Campos por byte-range del .idx (HRRR es determinista, sin percentiles):
  REFC  (cat 16, num 196)  reflectividad compuesta (dBZ)
  CRAIN (cat 1,  num 33)   1 = lluvia
  CFRZR (cat 1,  num 34)   1 = lluvia engelante (hielo)
  CICEP (cat 1,  num 35)   1 = aguanieve/pellets de hielo
  CSNOW (cat 1,  num 36)   1 = nieve

Salida CDN: data/hrrr/radar_fcst/conus/  (frames + manifest)

Reusa de nbm_temp_pipeline: reproyección Mercator, máscara tierra/mar, CDN.

Uso:
  /opt/canalmeteo/venv/bin/python3 hrrr_radar_pipeline.py --once
  ... --once --fhmax 24 --step 2
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

CDN_URL_ROOT = f'https://{nt.CDN_BUCKET}.sfo3.digitaloceanspaces.com/data/hrrr'
CDN_BASE = 'data/hrrr/radar_fcst/conus'
WORK = Path('/tmp/hrrr_radar_work'); WORK.mkdir(exist_ok=True)
AWS_BUCKET = 'noaa-hrrr-bdp-pds'

# (parameterCategory, parameterNumber) → nombre
FIELDS = {(16, 196): 'refc', (1, 33): 'crain', (1, 34): 'cfrzr', (1, 35): 'cicep', (1, 36): 'csnow'}
IDX_VARS = {'REFC', 'CRAIN', 'CFRZR', 'CICEP', 'CSNOW'}

REFC_MIN = 5.0  # dBZ mínimo para pintar

# Rampas de reflectividad (dBZ → RGB) por tipo.
RAIN_STOPS = [(5, (120, 225, 120)), (20, (40, 180, 70)), (32, (240, 230, 70)),
              (42, (245, 150, 40)), (52, (225, 40, 40)), (65, (150, 15, 15))]
SNOW_STOPS = [(5, (205, 230, 255)), (20, (110, 170, 235)), (35, (60, 90, 210)), (50, (95, 40, 160))]
ICE_STOPS = [(5, (255, 200, 228)), (20, (235, 110, 170)), (35, (200, 45, 125)), (50, (140, 15, 90))]


def ramp_rgb(val, stops):
    ks = np.array([s[0] for s in stops])
    r = np.array([s[1][0] for s in stops]); g = np.array([s[1][1] for s in stops]); b = np.array([s[1][2] for s in stops])
    return np.interp(val, ks, r), np.interp(val, ks, g), np.interp(val, ks, b)


# ─── AWS idx + byte-range ───────────────────────────────────────────
def aws_text(key):
    r = subprocess.run(['aws', 's3', 'cp', '--no-sign-request', f's3://{AWS_BUCKET}/{key}', '-'],
                       capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ''


def aws_range(key, start, end, dst):
    rng = f'bytes={start}-{end}' if end != '' else f'bytes={start}-'
    r = subprocess.run(['aws', 's3api', 'get-object', '--no-sign-request', '--bucket', AWS_BUCKET,
                        '--key', key, '--range', rng, str(dst)], capture_output=True, text=True, timeout=120)
    return r.returncode == 0 and dst.exists()


def fetch_fields(date_str, cycle, fh):
    key = f'hrrr.{date_str}/conus/hrrr.t{cycle:02d}z.wrfsfcf{fh:02d}.grib2'
    idx = aws_text(key + '.idx')
    if not idx:
        return None
    recs = []
    for ln in idx.splitlines():
        p = ln.split(':')
        if len(p) >= 6:
            recs.append((int(p[1]), p[3], p[4]))
    recs.sort()
    offs = [r[0] for r in recs]
    out = WORK / f'f{fh:02d}.grib2'
    if out.exists():
        out.unlink()
    tmp = WORK / f'f{fh:02d}_p.grib2'
    n = 0
    with open(out, 'wb') as fo:
        for i, (off, var, lev) in enumerate(recs):
            # REFC en "entire atmosphere"; categóricos en "surface".
            if var in IDX_VARS:
                end = offs[i + 1] - 1 if i + 1 < len(offs) else ''
                if aws_range(key, off, end, tmp):
                    fo.write(tmp.read_bytes()); n += 1
    try: tmp.unlink()
    except Exception: pass
    return out if out.exists() and n >= 1 else None


def read_fields(grib_path):
    out = {}; grid = None
    f = open(grib_path, 'rb')
    while True:
        gid = ec.codes_grib_new_from_file(f)
        if gid is None:
            break
        cat = ec.codes_get(gid, 'parameterCategory'); num = ec.codes_get(gid, 'parameterNumber')
        name = FIELDS.get((cat, num))
        if name:
            nx = ec.codes_get(gid, 'Nx'); ny = ec.codes_get(gid, 'Ny')
            out[name] = ec.codes_get_values(gid).reshape(ny, nx).astype('float32')
            if grid is None:
                grid = dict(
                    Nx=nx, Ny=ny,
                    la1=ec.codes_get(gid, 'latitudeOfFirstGridPointInDegrees'),
                    lo1=ec.codes_get(gid, 'longitudeOfFirstGridPointInDegrees'),
                    lad=ec.codes_get(gid, 'LaDInDegrees'), lov=ec.codes_get(gid, 'LoVInDegrees'),
                    lat1=ec.codes_get(gid, 'Latin1InDegrees'), lat2=ec.codes_get(gid, 'Latin2InDegrees'),
                    dx=ec.codes_get(gid, 'DxInMetres'), dy=ec.codes_get(gid, 'DyInMetres'))
        ec.codes_release(gid)
    f.close()
    return out, grid


_LUT = None


def build_lut(grid):
    global _LUT
    if _LUT is not None:
        return _LUT
    lov = grid['lov']; lov = lov - 360 if lov > 180 else lov
    lo1 = grid['lo1']; lo1 = lo1 - 360 if lo1 > 180 else lo1
    lcc = CRS.from_proj4(
        f"+proj=lcc +lat_1={grid['lat1']} +lat_2={grid['lat2']} +lat_0={grid['lad']} "
        f"+lon_0={lov} +x_0=0 +y_0=0 +R=6371229 +units=m +no_defs")
    tf = Transformer.from_crs("EPSG:4326", lcc, always_xy=True)
    x0, y0 = tf.transform(lo1, grid['la1'])
    dx, dy = grid['dx'], grid['dy']
    bn = nt.VIEW['bounds']; W, H = nt.VIEW['out_w'], nt.VIEW['out_h']
    my = np.linspace(nt.lat_to_merc_y(bn['north']), nt.lat_to_merc_y(bn['south']), H)
    lats = nt.merc_y_to_lat(my); lons = np.linspace(bn['west'], bn['east'], W)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    X, Y = tf.transform(lon_grid.ravel(), lat_grid.ravel())
    X = X.reshape(H, W); Y = Y.reshape(H, W)
    col = np.round((X - x0) / dx).astype(np.int32); row = np.round((Y - y0) / dy).astype(np.int32)
    valid = np.isfinite(X) & np.isfinite(Y) & (row >= 0) & (row < grid['Ny']) & (col >= 0) & (col < grid['Nx'])
    col = np.clip(col, 0, grid['Nx'] - 1); row = np.clip(row, 0, grid['Ny'] - 1)
    _LUT = (row, col, valid)
    return _LUT


def sample(field, lut):
    row, col, valid = lut
    out = field[row, col].copy()
    out[~valid] = np.nan
    return out


def colorize(fields, lut):
    refc = sample(fields['refc'], lut)
    def cat(name):
        return sample(fields[name], lut) > 0.5 if name in fields else np.zeros_like(refc, bool)
    crain, csnow, cicep, cfrzr = cat('crain'), cat('csnow'), cat('cicep'), cat('cfrzr')
    H, W = refc.shape
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    # SIN stencil: la reflectividad se muestra también sobre el mar (tormentas en
    # el océano son válidas), a diferencia de la temperatura.
    base = (refc >= REFC_MIN) & np.isfinite(refc)
    m_ice = base & (cicep | cfrzr)
    m_snow = base & csnow & ~m_ice
    m_rain = base & ~m_ice & ~m_snow  # lluvia o sin categoría → lluvia
    for mask, stops in ((m_rain, RAIN_STOPS), (m_snow, SNOW_STOPS), (m_ice, ICE_STOPS)):
        if not mask.any():
            continue
        R, G, B = ramp_rgb(refc[mask], stops)
        rgba[mask, 0] = np.clip(R, 0, 255); rgba[mask, 1] = np.clip(G, 0, 255)
        rgba[mask, 2] = np.clip(B, 0, 255); rgba[mask, 3] = 255
    return rgba


def save_png(rgba, path):
    from PIL import Image
    Image.fromarray(rgba, 'RGBA').save(path, 'PNG', optimize=True, compress_level=6)


def detect_cycle():
    now = datetime.now(timezone.utc)
    for back in range(1, 7):
        t = now - timedelta(hours=back)
        date_str = t.strftime('%Y%m%d'); cycle = t.hour
        # exige f18 disponible (longitud de pronóstico decente)
        if aws_text(f'hrrr.{date_str}/conus/hrrr.t{cycle:02d}z.wrfsfcf18.grib2.idx'):
            return date_str, cycle
    return None, None


def process(date_str=None, cycle=None, fhmax=24, step=2):
    if not (date_str and cycle is not None):
        date_str, cycle = detect_cycle()
    if not date_str:
        log.error("  sin ciclo HRRR con f18 disponible")
        return 0
    cycle = int(cycle)
    log.info(f"── HRRR radar · ciclo {date_str}/{cycle:02d}z · paso {step}h hasta f{fhmax} ──")
    cyc_dt = datetime.strptime(f"{date_str}{cycle:02d}", '%Y%m%d%H').replace(tzinfo=timezone.utc)
    frames = []
    for fh in range(step, fhmax + 1, step):
        g = fetch_fields(date_str, cycle, fh)
        if not g:
            log.info(f"  f{fh:02d}: no disponible, fin de la ventana")
            break
        fields, grid = read_fields(g)
        try: g.unlink()
        except Exception: pass
        if 'refc' not in fields or grid is None:
            continue
        lut = build_lut(grid)
        valid_dt = cyc_dt + timedelta(hours=fh)
        stem = f"radar_{valid_dt.strftime('%Y%m%d%H%M%S')}"
        png = WORK / f'{stem}.png'
        save_png(colorize(fields, lut), png)
        if nt.cdn_upload(png, f'{CDN_BASE}/{stem}.png', 'image/png'):
            frames.append((stem, valid_dt))
            log.info(f"  f{fh:02d} → {stem}")
        try: png.unlink()
        except Exception: pass

    if not frames:
        log.error("  sin frames")
        return 0
    manifest = {
        'model': 'HRRR', 'product': 'refc_type', 'units': 'dBZ',
        'cycle': f"{date_str}{cycle:02d}", 'bounds': nt.VIEW['bounds'],
        'width': nt.VIEW['out_w'], 'height': nt.VIEW['out_h'],
        'frames': [{'url': f'{CDN_URL_ROOT}/radar_fcst/conus/{s}.png',
                    'timestamp': int(v.timestamp()), 'iso': v.isoformat()} for s, v in frames],
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    mp = WORK / 'manifest.json'; mp.write_text(json.dumps(manifest, indent=2))
    nt.cdn_upload(mp, f'{CDN_BASE}/manifest.json', 'application/json'); mp.unlink()
    keep = {s for s, _ in frames}
    for k in nt.cdn_list(CDN_BASE + '/'):
        if k.endswith('.png') and Path(k).stem not in keep:
            nt.cdn_delete(f'{CDN_BASE}/{k}')
    log.info(f"  {len(frames)} frames")
    return len(frames)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--date', default=None); ap.add_argument('--cycle', default=None)
    ap.add_argument('--fhmax', type=int, default=24); ap.add_argument('--step', type=int, default=2)
    args = ap.parse_args()
    t0 = time.time()
    log.info("═══ HRRR radar pipeline ═══")
    n = process(args.date, args.cycle, args.fhmax, args.step)
    log.info(f"═══ Completado en {time.time()-t0:.1f}s · {n} frames ═══")


if __name__ == '__main__':
    main()
