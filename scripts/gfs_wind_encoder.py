#!/usr/bin/env python3
"""
GFS Wind Encoder — Canal Meteo TV
Descarga U/V del GFS 0.25° (NOMADS), lo codifica en PNGs RGB
(R=u, G=v, B=velocidad) + JSON de metadatos, y lo sube al CDN de
DO Spaces para el motor de partículas de Tormenta.

Niveles: 10 m (superficie), 500 hPa, 250 hPa (chorro).

Instalación (en el droplet):
  pip3 install pygrib pillow numpy requests

Cron sugerido (cada hora; el script sale rápido si el ciclo ya está subido):
  20 * * * * /usr/bin/python3 /opt/canalmeteo/scripts/gfs_wind_encoder.py >> /var/log/gfs_wind.log 2>&1

Salida en el CDN:
  data/wind/gfs_wind_{nivel}_f000.png
  data/wind/gfs_wind_{nivel}_f000.json
  data/wind/manifest.json
"""

import json
import logging
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

NOMADS_FILTER = 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl'

WORK_DIR = Path('/tmp/gfs_wind')
WORK_DIR.mkdir(exist_ok=True)

F_HOURS = list(range(0, 73, 6))   # f000-f072 cada 6 h (sincroniza con el timeline)
DOWNSAMPLE = 2           # 0.25° → 0.5° (720×341 px tras recorte ±85°)
LAT_CLAMP = 85.0         # mercator no representa los polos

LEVELS = {
    '10m': {'typeOfLevel': 'heightAboveGround', 'level': 10,  'lev_param': 'lev_10_m_above_ground'},
    '500': {'typeOfLevel': 'isobaricInhPa',     'level': 500, 'lev_param': 'lev_500_mb'},
    '250': {'typeOfLevel': 'isobaricInhPa',     'level': 250, 'lev_param': 'lev_250_mb'},
}


# ─── Descubrimiento del último ciclo disponible ────────────────────
def find_latest_cycle():
    """Prueba ciclos de hoy y ayer (18/12/06/00Z) comprobando el .idx en NOMADS."""
    now = datetime.now(timezone.utc)
    for days_back in range(2):
        d = now - timedelta(days=days_back)
        for hh in (18, 12, 6, 0):
            cyc = d.replace(hour=hh, minute=0, second=0, microsecond=0)
            if cyc > now:
                continue
            url = (f'https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/'
                   f'gfs.{cyc.strftime("%Y%m%d")}/{hh:02d}/atmos/'
                   f'gfs.t{hh:02d}z.pgrb2.0p25.f000.idx')
            try:
                r = requests.head(url, timeout=15)
                if r.status_code == 200:
                    return cyc
            except Exception:
                continue
    return None


def download_grib(cycle: datetime, fhour: int) -> Path:
    """Descarga un subset GRIB2 con UGRD/VGRD en los 3 niveles (~2-4 MB)."""
    hh = cycle.strftime('%H')
    params = {
        'dir': f'/gfs.{cycle.strftime("%Y%m%d")}/{hh}/atmos',
        'file': f'gfs.t{hh}z.pgrb2.0p25.f{fhour:03d}',
        'var_UGRD': 'on',
        'var_VGRD': 'on',
    }
    for lv in LEVELS.values():
        params[lv['lev_param']] = 'on'

    out = WORK_DIR / f'gfs_{cycle.strftime("%Y%m%d%H")}_f{fhour:03d}.grib2'
    log.info(f'  ⬇️  GFS {cycle.strftime("%Y-%m-%d %HZ")} f{fhour:03d} ...')
    r = requests.get(NOMADS_FILTER, params=params, timeout=120)
    r.raise_for_status()
    if len(r.content) < 10000:
        raise RuntimeError(f'GRIB demasiado pequeño ({len(r.content)} bytes): ¿ciclo incompleto?')
    out.write_bytes(r.content)
    log.info(f'    {len(r.content) / 1e6:.1f} MB')
    return out


# ─── Codificación ──────────────────────────────────────────────────
def extract_uv(grib_path: Path, level_key: str):
    """Devuelve (u, v) en m/s, recortado a ±85° lat, lon -180..180, downsampled."""
    cfg = LEVELS[level_key]
    grbs = pygrib.open(str(grib_path))
    try:
        gu = grbs.select(shortName='10u' if level_key == '10m' else 'u',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]
        gv = grbs.select(shortName='10v' if level_key == '10m' else 'v',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]
    except Exception:
        # Fallback por nombre largo (varía entre versiones de eccodes)
        gu = grbs.select(name='U component of wind' if level_key != '10m' else '10 metre U wind component',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]
        gv = grbs.select(name='V component of wind' if level_key != '10m' else '10 metre V wind component',
                         typeOfLevel=cfg['typeOfLevel'], level=cfg['level'])[0]

    u = np.asarray(gu.values, dtype=np.float32)   # (721, 1440), lat 90→-90, lon 0→359.75
    v = np.asarray(gv.values, dtype=np.float32)
    lats = gu.latlons()[0][:, 0]                  # 90 → -90
    grbs.close()

    # Lon 0..360 → -180..180
    half = u.shape[1] // 2
    u = np.roll(u, half, axis=1)
    v = np.roll(v, half, axis=1)

    # Recorte de latitudes a ±85
    keep = np.where((lats <= LAT_CLAMP) & (lats >= -LAT_CLAMP))[0]
    u, v = u[keep], v[keep]

    # Downsample
    u = u[::DOWNSAMPLE, ::DOWNSAMPLE]
    v = v[::DOWNSAMPLE, ::DOWNSAMPLE]
    return u, v


def encode_png(u: np.ndarray, v: np.ndarray, out_png: Path, out_json: Path,
               level_key: str, cycle: datetime, fhour: int):
    """R=u normalizado, G=v normalizado, B=velocidad. JSON con rangos y bbox."""
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

    meta = {
        'bbox': [-180.0, -LAT_CLAMP, 180.0, LAT_CLAMP],   # [oeste, sur, este, norte]
        'width': w, 'height': h,
        'uMin': u_min, 'uMax': u_max,
        'vMin': v_min, 'vMax': v_max,
        'maxSpeed': s_max,
        'level': level_key,
        'fhour': fhour,
        'cycle': cycle.strftime('%Y-%m-%d %HZ'),
        'generated': datetime.now(timezone.utc).isoformat(),
    }
    out_json.write_text(json.dumps(meta))
    log.info(f'    {level_key}: {w}×{h}px  u[{u_min},{u_max}] v[{v_min},{v_max}] '
             f'vmax={s_max:.0f} m/s  {out_png.stat().st_size / 1024:.0f} KB')
    return meta


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


def get_remote_manifest() -> dict:
    """Lee el manifest ya subido para no repetir trabajo."""
    try:
        r = requests.get(f'{CDN_URL_BASE}/manifest.json?ts={int(time.time())}', timeout=10)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


# ─── Main ──────────────────────────────────────────────────────────
def main():
    cycle = find_latest_cycle()
    if not cycle:
        log.error('No se encontró ningún ciclo GFS disponible en NOMADS')
        sys.exit(1)

    cycle_str = cycle.strftime('%Y-%m-%d %HZ')
    rm = get_remote_manifest()
    if rm.get('cycle') == cycle_str and set(rm.get('hours', [])) >= set(F_HOURS):
        log.info(f'Ciclo {cycle_str} ya subido con todas las horas — nada que hacer.')
        return

    log.info(f'═══ GFS Wind Encoder: ciclo {cycle_str} ═══')
    ok_levels = []

    for fhour in F_HOURS:
        grib = download_grib(cycle, fhour)
        for level_key in LEVELS:
            try:
                u, v = extract_uv(grib, level_key)
                png = WORK_DIR / f'gfs_wind_{level_key}_f{fhour:03d}.png'
                js = WORK_DIR / f'gfs_wind_{level_key}_f{fhour:03d}.json'
                encode_png(u, v, png, js, level_key, cycle, fhour)
                if cdn_upload(png, f'{CDN_BASE}/{png.name}', 'image/png') and \
                   cdn_upload(js, f'{CDN_BASE}/{js.name}', 'application/json'):
                    ok_levels.append(level_key)
            except Exception as e:
                log.error(f'  {level_key}: {e}')
        grib.unlink(missing_ok=True)

    if ok_levels:
        manifest = WORK_DIR / 'manifest.json'
        manifest.write_text(json.dumps({
            'cycle': cycle_str,
            'levels': sorted(set(ok_levels)),
            'hours': F_HOURS,
            'generated': datetime.now(timezone.utc).isoformat(),
        }))
        cdn_upload(manifest, f'{CDN_BASE}/manifest.json', 'application/json')
        log.info(f'✅ Subido: {sorted(set(ok_levels))} → {CDN_URL_BASE}/')
    else:
        log.error('❌ Ningún nivel se procesó correctamente')
        sys.exit(1)


if __name__ == '__main__':
    main()
