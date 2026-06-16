#!/usr/bin/env python3
"""
Wind Encoder multi-modelo — Canal Meteo TV
Sustituye a gfs_wind_encoder.py. Genera los PNGs U/V del motor de
partículas de Tormenta para varios modelos:

  gfs   → global 0.25°, niveles 10 m / 500 hPa / 250 hPa, f000-f072/6h
          (lo usan los modelos GFS, GFS Global, NBM y RTOFS en Tormenta)
  hrrr  → CONUS 3 km regrillado a 0.1° lat-lon, nivel 10 m, f00-f18/1h
          (lo usan HRRR y HRRR EXT)

IMPORTANTE (HRRR): la malla nativa es Lambert conformal y sus U/V son
relativos a la malla, no a los puntos cardinales. Si wgrib2 está
instalado se usa (-new_grid_winds earth, que regrilla y rota); si no,
hay un fallback en Python puro con la rotación verificada numéricamente
contra la proyección oficial del HRRR:
    alpha   = sin(latin1) * (lov - lon)
    u_earth = cos(a)*u_grid - sin(a)*v_grid
    v_earth = sin(a)*u_grid + cos(a)*v_grid

Salida en el CDN:
  data/wind/{modelo}/wind_{nivel}_f{FFF}.png
  data/wind/{modelo}/wind_{nivel}_f{FFF}.json
  data/wind/{modelo}/manifest.json

Cron (cada hora; sale al instante si los ciclos ya están subidos):
  35 * * * * flock -n /tmp/wind_enc.lock timeout 1800 nice -n 10 ionice -c2 -n7 \\
    /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/wind_encoder.py \\
    >> /var/log/canalmeteo/wind_encoder.log 2>&1
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import requests
import pygrib
from PIL import Image

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────
CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_BASE = 'data/wind'
CDN_URL_BASE = f'https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CDN_BASE}'

WORK_DIR = Path('/opt/canalmeteo/tmp/wind_encoder')
WORK_DIR.mkdir(parents=True, exist_ok=True)

LAT_CLAMP = 85.0   # mercator no representa los polos (solo aplica al GFS)

MODELS = {
    'gfs': {
        'hours': list(range(0, 73, 6)),
        'cycles': (0, 6, 12, 18),
        'filter_url': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl',
        'levels': {
            '10m': {'lev_param': 'lev_10_m_above_ground', 'typeOfLevel': 'heightAboveGround', 'level': 10},
            '500': {'lev_param': 'lev_500_mb', 'typeOfLevel': 'isobaricInhPa', 'level': 500},
            '250': {'lev_param': 'lev_250_mb', 'typeOfLevel': 'isobaricInhPa', 'level': 250},
        },
        'kind': 'latlon_global',
        'downsample': 2,   # 0.25° → 0.5°
    },
    'hrrr': {
        'hours': list(range(0, 19)),
        'cycles': tuple(range(24)),   # ciclo horario
        'filter_url': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl',
        'levels': {
            '10m': {'lev_param': 'lev_10_m_above_ground', 'typeOfLevel': 'heightAboveGround', 'level': 10},
        },
        'kind': 'lambert_conus',
        # Malla destino para wgrib2: lon 234→293.9E (-126→-66.1), lat 21→52.9
        'regrid': 'latlon 234:600:0.1 21:320:0.1',
        'downsample': 1,
    },
}


# ─── Descubrimiento del último ciclo disponible ────────────────────
def idx_url(model: str, cyc: datetime, fhour: int) -> str:
    d, hh = cyc.strftime('%Y%m%d'), cyc.strftime('%H')
    if model == 'gfs':
        return (f'https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/'
                f'gfs.{d}/{hh}/atmos/gfs.t{hh}z.pgrb2.0p25.f{fhour:03d}.idx')
    if model == 'hrrr':
        return (f'https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/'
                f'hrrr.{d}/conus/hrrr.t{hh}z.wrfsfcf{fhour:02d}.grib2.idx')
    raise ValueError(model)


def find_latest_cycle(model: str):
    """Último ciclo con el run completo (comprueba el .idx de la última hora)."""
    cfg = MODELS[model]
    last_fh = cfg['hours'][-1]
    now = datetime.now(timezone.utc)
    for hours_back in range(0, 48):
        cyc = (now - timedelta(hours=hours_back)).replace(minute=0, second=0, microsecond=0)
        if cyc.hour not in cfg['cycles']:
            continue
        try:
            r = requests.head(idx_url(model, cyc, last_fh), timeout=15)
            if r.status_code == 200:
                return cyc
        except Exception:
            continue
    return None


def download_grib(model: str, cycle: datetime, fhour: int) -> Path:
    """Subset GRIB2 con UGRD/VGRD en los niveles del modelo."""
    cfg = MODELS[model]
    hh = cycle.strftime('%H')
    if model == 'gfs':
        params = {'dir': f'/gfs.{cycle.strftime("%Y%m%d")}/{hh}/atmos',
                  'file': f'gfs.t{hh}z.pgrb2.0p25.f{fhour:03d}'}
    else:  # hrrr
        params = {'dir': f'/hrrr.{cycle.strftime("%Y%m%d")}/conus',
                  'file': f'hrrr.t{hh}z.wrfsfcf{fhour:02d}.grib2'}
    params.update({'var_UGRD': 'on', 'var_VGRD': 'on'})
    for lv in cfg['levels'].values():
        params[lv['lev_param']] = 'on'

    out = WORK_DIR / f'{model}_{cycle.strftime("%Y%m%d%H")}_f{fhour:03d}.grib2'
    r = requests.get(cfg['filter_url'], params=params, timeout=180)
    r.raise_for_status()
    if len(r.content) < 5000:
        raise RuntimeError(f'GRIB demasiado pequeño ({len(r.content)} bytes)')
    out.write_bytes(r.content)
    return out


def regrid_lambert_to_latlon(model: str, grib_in: Path) -> Path:
    """
    HRRR: Lambert → lat-lon regular con wgrib2.
    -new_grid_winds earth rota U/V de relativos-a-la-malla a geográficos.
    """
    out = grib_in.with_suffix('.latlon.grib2')
    cmd = ['wgrib2', str(grib_in), '-set_grib_type', 'c3',
           '-new_grid_winds', 'earth',
           '-new_grid'] + MODELS[model]['regrid'].split() + [str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f'wgrib2: {r.stderr.strip()[:300]}')
    return out


def extract_uv_lambert_py(model: str, grib_path: Path, level_key: str):
    """
    Fallback sin wgrib2: lee la malla Lambert nativa, ROTA los vectores
    de grid-relative a earth-relative y regrilla a lat-lon 0.1° por vecino
    más cercano (la fuente a 3 km es ~9× más densa que el destino).
    Rotación verificada contra pyproj con la proyección oficial del HRRR.
    """
    cfg = MODELS[model]['levels'][level_key]
    grbs = pygrib.open(str(grib_path))
    try:
        gu = grbs.select(shortName='10u' if level_key == '10m' else 'u',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]
        gv = grbs.select(shortName='10v' if level_key == '10m' else 'v',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]
    except Exception:
        gu = grbs.select(name='10 metre U wind component',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]
        gv = grbs.select(name='10 metre V wind component',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]

    ug = np.ma.filled(gu.values, np.nan).astype(np.float32)
    vg = np.ma.filled(gv.values, np.nan).astype(np.float32)
    lats2d, lons2d = gu.latlons()
    pp = getattr(gu, 'projparams', {}) or {}
    latin1 = float(pp.get('lat_1', 38.5))
    lov = float(pp.get('lon_0', 262.5)) % 360.0
    grbs.close()

    # Rotación de vectores (signo verificado numéricamente)
    lon360 = np.asarray(lons2d, dtype=np.float64) % 360.0
    delta = (lov - lon360 + 540.0) % 360.0 - 180.0
    a = np.deg2rad(np.sin(np.deg2rad(latin1)) * delta)
    cos_a, sin_a = np.cos(a), np.sin(a)
    ue = (cos_a * ug - sin_a * vg).astype(np.float32)
    ve = (sin_a * ug + cos_a * vg).astype(np.float32)

    # Regrillado nearest a la malla destino (misma que la de wgrib2)
    lon0, nx, dlon = 234.0, 600, 0.1
    lat0, ny, dlat = 21.0, 320, 0.1
    xi = np.round((lon360 - lon0) / dlon).astype(int)
    yi = np.round((np.asarray(lats2d) - lat0) / dlat).astype(int)
    valid = (xi >= 0) & (xi < nx) & (yi >= 0) & (yi < ny) & np.isfinite(ue) & np.isfinite(ve)

    ut = np.zeros((ny, nx), dtype=np.float32)
    vt = np.zeros((ny, nx), dtype=np.float32)
    ut[yi[valid], xi[valid]] = ue[valid]
    vt[yi[valid], xi[valid]] = ve[valid]

    # Fila 0 = norte (la malla destino se construyó de sur a norte)
    ut, vt = ut[::-1], vt[::-1]
    bbox = [lon0 - 360.0, lat0, lon0 + (nx - 1) * dlon - 360.0, lat0 + (ny - 1) * dlat]
    return ut, vt, bbox


# ─── Extracción ────────────────────────────────────────────────────
def extract_uv(model: str, grib_path: Path, level_key: str):
    """Devuelve (u, v, bbox) con fila 0 = norte (convención del frontend)."""
    cfg = MODELS[model]
    lcfg = cfg['levels'][level_key]
    short_u = '10u' if level_key == '10m' else 'u'
    short_v = '10v' if level_key == '10m' else 'v'

    grbs = pygrib.open(str(grib_path))
    try:
        gu = grbs.select(shortName=short_u, typeOfLevel=lcfg['typeOfLevel'], level=lcfg['level'])[0]
        gv = grbs.select(shortName=short_v, typeOfLevel=lcfg['typeOfLevel'], level=lcfg['level'])[0]
    except Exception:
        gu = grbs.select(name='U component of wind' if level_key != '10m' else '10 metre U wind component',
                         typeOfLevel=lcfg['typeOfLevel'], level=lcfg['level'])[0]
        gv = grbs.select(name='V component of wind' if level_key != '10m' else '10 metre V wind component',
                         typeOfLevel=lcfg['typeOfLevel'], level=lcfg['level'])[0]

    u = np.asarray(gu.values, dtype=np.float32)
    v = np.asarray(gv.values, dtype=np.float32)
    lats2d, lons2d = gu.latlons()
    lats = lats2d[:, 0]
    lons = lons2d[0, :].copy()
    grbs.close()

    if cfg['kind'] == 'latlon_global':
        # Lon 0..360 → -180..180
        half = u.shape[1] // 2
        u = np.roll(u, half, axis=1)
        v = np.roll(v, half, axis=1)
        # Recorte de latitudes a ±LAT_CLAMP
        keep = np.where((lats <= LAT_CLAMP) & (lats >= -LAT_CLAMP))[0]
        u, v, lats = u[keep], v[keep], lats[keep]
        bbox = [-180.0, -LAT_CLAMP, 180.0, LAT_CLAMP]
    else:
        # Malla regrillada por wgrib2: bbox real de la malla
        lons = np.where(lons > 180.0, lons - 360.0, lons)
        bbox = [float(lons.min()), float(lats.min()), float(lons.max()), float(lats.max())]

    # Convención del frontend: fila 0 = norte
    if lats[0] < lats[-1]:
        u, v = u[::-1], v[::-1]

    ds = cfg['downsample']
    if ds > 1:
        u, v = u[::ds, ::ds], v[::ds, ::ds]
    return u, v, bbox


def encode_png(u, v, bbox, out_png: Path, out_json: Path,
               model: str, level_key: str, cycle: datetime, fhour: int):
    """R=u normalizado, G=v normalizado, B=velocidad (misma codificación de siempre)."""
    u_min, u_max = float(np.floor(u.min())), float(np.ceil(u.max()))
    v_min, v_max = float(np.floor(v.min())), float(np.ceil(v.max()))
    speed = np.hypot(u, v)
    s_max = float(np.ceil(speed.max()))

    h, w = u.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[..., 0] = np.clip((u - u_min) / max(u_max - u_min, 1e-6) * 255, 0, 255)
    rgb[..., 1] = np.clip((v - v_min) / max(v_max - v_min, 1e-6) * 255, 0, 255)
    rgb[..., 2] = np.clip(speed / max(s_max, 1e-6) * 255, 0, 255)
    Image.fromarray(rgb, 'RGB').save(out_png, optimize=True)

    out_json.write_text(json.dumps({
        'bbox': [round(b, 3) for b in bbox],   # [oeste, sur, este, norte]
        'width': w, 'height': h,
        'uMin': u_min, 'uMax': u_max,
        'vMin': v_min, 'vMax': v_max,
        'maxSpeed': s_max,
        'model': model, 'level': level_key, 'fhour': fhour,
        'cycle': cycle.strftime('%Y-%m-%d %HZ'),
        'generated': datetime.now(timezone.utc).isoformat(),
    }))


# ─── CDN ───────────────────────────────────────────────────────────
def cdn_upload(local_path: Path, cdn_key: str, content_type: str) -> bool:
    cmd = ['aws', 's3', 'cp', str(local_path), f's3://{CDN_BUCKET}/{cdn_key}',
           '--profile', AWS_PROFILE, '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=600',
           '--endpoint-url', CDN_ENDPOINT]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        log.error(f'  ❌ CDN upload FAILED ({cdn_key}): {r.stderr.strip()[:300]}')
    return r.returncode == 0


def get_remote_manifest(model: str) -> dict:
    try:
        r = requests.get(f'{CDN_URL_BASE}/{model}/manifest.json?ts={int(time.time())}', timeout=10)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


# ─── Procesado por modelo ─────────────────────────────────────────
def process_model(model: str):
    cfg = MODELS[model]
    cycle = find_latest_cycle(model)
    if not cycle:
        log.error(f'[{model}] sin ciclo disponible en NOMADS')
        return False

    cycle_str = cycle.strftime('%Y-%m-%d %HZ')
    rm = get_remote_manifest(model)
    if rm.get('cycle') == cycle_str and set(rm.get('hours', [])) >= set(cfg['hours']):
        log.info(f'[{model}] ciclo {cycle_str} ya subido — nada que hacer.')
        return True

    log.info(f'═══ [{model}] ciclo {cycle_str}: {len(cfg["hours"])} horas ═══')
    ok_levels = set()
    ok_hours = set()

    for fhour in cfg['hours']:
        try:
            grib = download_grib(model, cycle, fhour)
            has_wgrib2 = shutil.which('wgrib2') is not None
            if cfg['kind'] == 'lambert_conus' and has_wgrib2:
                latlon = regrid_lambert_to_latlon(model, grib)
                grib.unlink(missing_ok=True)
                grib = latlon
            for level_key in cfg['levels']:
                if cfg['kind'] == 'lambert_conus' and not has_wgrib2:
                    u, v, bbox = extract_uv_lambert_py(model, grib, level_key)
                else:
                    u, v, bbox = extract_uv(model, grib, level_key)
                png = WORK_DIR / f'wind_{level_key}_f{fhour:03d}.png'
                js = WORK_DIR / f'wind_{level_key}_f{fhour:03d}.json'
                encode_png(u, v, bbox, png, js, model, level_key, cycle, fhour)
                if cdn_upload(png, f'{CDN_BASE}/{model}/{png.name}', 'image/png') and \
                   cdn_upload(js, f'{CDN_BASE}/{model}/{js.name}', 'application/json'):
                    ok_levels.add(level_key)
                    ok_hours.add(fhour)
                png.unlink(missing_ok=True)
                js.unlink(missing_ok=True)
            grib.unlink(missing_ok=True)
            log.info(f'  [{model}] f{fhour:03d} ✓')
        except Exception as e:
            log.error(f'  [{model}] f{fhour:03d}: {e}')

    if ok_hours:
        manifest = WORK_DIR / 'manifest.json'
        manifest.write_text(json.dumps({
            'model': model,
            'cycle': cycle_str,
            'levels': sorted(ok_levels),
            'hours': sorted(ok_hours),
            'generated': datetime.now(timezone.utc).isoformat(),
        }))
        cdn_upload(manifest, f'{CDN_BASE}/{model}/manifest.json', 'application/json')
        log.info(f'✅ [{model}] subido: niveles {sorted(ok_levels)}, {len(ok_hours)} horas')
        return True
    log.error(f'❌ [{model}] ningún frame procesado')
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', choices=['gfs', 'hrrr', 'all'], default='all')
    args = ap.parse_args()
    targets = ['gfs', 'hrrr'] if args.model == 'all' else [args.model]
    results = [process_model(m) for m in targets]
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
