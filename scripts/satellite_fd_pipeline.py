#!/usr/bin/env python3
"""
Full Disk multi-vista / multi-satélite pipeline para Canal Meteo TV — Tormenta.

Descarga el Full Disk de GOES-East (GOES-19) y GOES-West (GOES-18) desde NOAA STAR
(una vez por satélite+banda), lo reproyecta de geoestacionario a equirectangular
(Mercator-Y) y publica cada vista donde el frontend (toggleSatFD) ya las busca:

    data/satellite-fd/{vista}/{banda}_{ts}.jpg   (frames)
    data/satellite-fd/{vista}/{banda}.jpg        (latest)
    data/satellite-fd/{vista}/manifest.json      ({bounds, sat, products{banda:[frames]}})

Vistas: disco-oeste, epac (West) · disco-este, caribe-golfo, mexico-ca, atlantico (East).
El Full Disk se actualiza cada ~10 min -> cron */10.

Cron: */10 * * * * flock -n /tmp/sat_fd.lock timeout 600 /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/satellite_fd_pipeline.py >> /var/log/canalmeteo/satellite_fd.log 2>&1
"""

import requests, subprocess, logging, time, json, math, re
import numpy as np
from PIL import Image
from io import BytesIO
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pyproj import Transformer
from scipy.ndimage import map_coordinates

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
CDN_PUBLIC = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_BASE = 'data/satellite-fd'

STAR = 'https://cdn.star.nesdis.noaa.gov'
H = 35786023.0
REQ, RPOL, SWEEP = 6378137.0, 6356752.31414, 'x'
FD_SIZE = '5424x5424'
FD_SCAN = (-0.151844, 0.151844, -0.151844, 0.151844)  # x_min,x_max,y_min,y_max (rad)

SATS = {
    'GOES18': {'lon_0': -137.0},   # West
    'GOES19': {'lon_0': -75.0},    # East
}

# banda frontend -> código de producto STAR FD
BANDS = {
    'ir':       '13',
    'geocolor': 'GEOCOLOR',
    'vis':      '02',
    'wv-alto':  '08',
    'wv-medio': '09',
    'dust':     'Dust',
    'airmass':  'AirMass',
}

# vistas: cada una con su satélite y bbox de salida
VIEWS = {
    # ---- West (GOES-18) ----
    'disco-oeste':  {'sat': 'GOES18', 'bounds': {'north': 62.0,  'south': -62.0, 'west': -179.0, 'east': -96.0}, 'width': 2400, 'height': 2000},
    'epac':         {'sat': 'GOES18', 'bounds': {'north': 35.0,  'south':  5.0,  'west': -118.0, 'east': -80.0}, 'width': 2200, 'height': 1600},
    # ---- East (GOES-19) ----
    'disco-este':   {'sat': 'GOES19', 'bounds': {'north': 62.0,  'south': -62.0, 'west': -130.0, 'east': -10.0}, 'width': 2400, 'height': 2000},
    'caribe-golfo': {'sat': 'GOES19', 'bounds': {'north': 32.0,  'south':  8.0,  'west': -100.0, 'east': -58.0}, 'width': 2200, 'height': 1300},
    'mexico-ca':    {'sat': 'GOES19', 'bounds': {'north': 33.0,  'south':  5.0,  'west': -118.0, 'east': -77.0}, 'width': 2200, 'height': 1500},
    'atlantico':    {'sat': 'GOES19', 'bounds': {'north': 45.0,  'south':  5.0,  'west': -90.0,  'east': -15.0}, 'width': 2400, 'height': 1500},
}


def lat_to_merc_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def merc_y_to_lat(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


for _v in VIEWS.values():
    _b = _v['bounds']
    _v['lons'] = np.linspace(_b['west'], _b['east'], _v['width'])
    yN, yS = lat_to_merc_y(_b['north']), lat_to_merc_y(_b['south'])
    _v['lats'] = np.array([merc_y_to_lat(yN + (yS - yN) * i / (_v['height'] - 1)) for i in range(_v['height'])])

_lut_cache = {}


def build_lut(view_key, src_h, src_w):
    ck = (view_key, src_h, src_w)
    if ck in _lut_cache:
        return _lut_cache[ck]
    v = VIEWS[view_key]
    lon_0 = SATS[v['sat']]['lon_0']
    log.info(f"  LUT {view_key} [{v['sat']}] ({src_w}x{src_h} -> {v['width']}x{v['height']})")
    t0 = time.time()
    tr = Transformer.from_crs("EPSG:4326",
                              f"+proj=geos +lon_0={lon_0} +h={H} +a={REQ} +b={RPOL} +sweep={SWEEP} +units=m",
                              always_xy=True)
    sxn, sxx, syn, syx = FD_SCAN
    gxn, gxx, gyn, gyx = sxn * H, sxx * H, syn * H, syx * H
    ppx = src_w / (gxx - gxn)
    ppy = src_h / (gyx - gyn)
    lon_g, lat_g = np.meshgrid(v['lons'], v['lats'])
    gx, gy = tr.transform(lon_g.ravel(), lat_g.ravel())
    gx = np.array(gx).reshape(v['height'], v['width'])
    gy = np.array(gy).reshape(v['height'], v['width'])
    sc = (gx - gxn) * ppx
    sr = (gyx - gy) * ppy
    valid = (np.isfinite(gx) & np.isfinite(gy) &
             (sc >= 0) & (sc < src_w) & (sr >= 0) & (sr < src_h))
    sr = np.where(valid, sr, 0).astype(np.float32)
    sc = np.where(valid, sc, 0).astype(np.float32)
    _lut_cache[ck] = (sr, sc, valid)
    log.info(f"    {int(valid.sum())}/{valid.size} valid ({100*valid.sum()/valid.size:.0f}%) {time.time()-t0:.1f}s")
    return sr, sc, valid


def reproject(arr, view_key):
    src_h, src_w = arr.shape[:2]
    n_ch = arr.shape[2] if arr.ndim == 3 else 1
    sr, sc, valid = build_lut(view_key, src_h, src_w)
    out_h, out_w = valid.shape
    if n_ch == 1:
        out = map_coordinates(arr, [sr, sc], order=1, mode='constant', cval=0)
        return np.where(valid, out, 0).astype(np.uint8)
    out = np.zeros((out_h, out_w, n_ch), dtype=np.uint8)
    for c in range(n_ch):
        ch = map_coordinates(arr[:, :, c], [sr, sc], order=1, mode='constant', cval=0)
        out[:, :, c] = np.where(valid, ch, 0).astype(np.uint8)
    return out


def aws(*args, timeout=120):
    try:
        return subprocess.run(['aws', *args, '--profile', AWS_PROFILE, '--endpoint-url', CDN_ENDPOINT],
                              capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def upload(filepath, cdn_key, content_type='image/jpeg'):
    r = aws('s3', 'cp', filepath, f's3://{CDN_BUCKET}/{cdn_key}',
            '--acl', 'public-read', '--content-type', content_type, '--cache-control', 'max-age=60')
    return r is not None and r.returncode == 0


def fetch_fd(sat, code):
    url = f'{STAR}/{sat}/ABI/FD/{code}/{FD_SIZE}.jpg'
    try:
        r = requests.get(url, timeout=90, headers={'User-Agent': 'CanalMeteoTV/1.0 (contacto@canalmeteo.tv)'})
        if r.status_code != 200:
            log.warning(f"  STAR {sat}/{code}: HTTP {r.status_code}")
            return None
        return np.array(Image.open(BytesIO(r.content)))
    except Exception as e:
        log.warning(f"  STAR {sat}/{code}: {e}")
        return None


def cleanup(view, band, max_age_hours=6):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime('%Y%m%d%H%M')
    r = aws('s3', 'ls', f's3://{CDN_BUCKET}/{CDN_BASE}/{view}/{band}_', timeout=30)
    if not r or r.returncode != 0:
        return
    for line in r.stdout.strip().split('\n'):
        parts = line.strip().split()
        if len(parts) < 4:
            continue
        m = re.search(r'_(\d{12})\.jpg$', parts[-1])
        if m and m.group(1) < cutoff:
            aws('s3', 'rm', f's3://{CDN_BUCKET}/{CDN_BASE}/{view}/{parts[-1]}', timeout=15)


def list_frames(view, band):
    r = aws('s3', 'ls', f's3://{CDN_BUCKET}/{CDN_BASE}/{view}/{band}_', timeout=30)
    frames = []
    if r and r.returncode == 0:
        for line in r.stdout.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            m = re.search(r'_(\d{12})\.jpg$', parts[-1])
            if m:
                ts = m.group(1)
                dt = datetime.strptime(ts, '%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                frames.append({'time': int(dt.timestamp()), 'ts': ts,
                               'url': f'{CDN_PUBLIC}/{CDN_BASE}/{view}/{parts[-1]}'})
    frames.sort(key=lambda f: f['time'])
    return frames


def main():
    t0 = time.time()
    log.info("=== Satellite Full Disk Pipeline (East+West) ===")
    ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M')

    # agrupar vistas por satélite para descargar cada Full Disk una sola vez
    sat_views = defaultdict(list)
    for vk, vc in VIEWS.items():
        sat_views[vc['sat']].append(vk)

    n_ok = 0
    for sat, vks in sat_views.items():
        log.info(f"--- {sat} -> vistas: {', '.join(vks)} ---")
        for band, code in BANDS.items():
            arr = fetch_fd(sat, code)
            if arr is None:
                continue
            for vk in vks:
                try:
                    out = reproject(arr, vk)
                    p = f'/tmp/satfd_{vk}_{band}_{ts}.jpg'
                    Image.fromarray(out).save(p, 'JPEG', quality=88)
                    if upload(p, f'{CDN_BASE}/{vk}/{band}_{ts}.jpg'):
                        upload(p, f'{CDN_BASE}/{vk}/{band}.jpg')
                        n_ok += 1
                        log.info(f"  ✅ {vk}/{band}")
                except Exception as e:
                    log.warning(f"  {vk}/{band}: {e}")
            del arr

    # limpieza + manifest por vista
    for view, vcfg in VIEWS.items():
        for band in BANDS:
            cleanup(view, band)
        manifest = {
            'generated': datetime.now(timezone.utc).isoformat(),
            'sat': vcfg['sat'],
            'view': view,
            'bounds': vcfg['bounds'],
            'products': {band: list_frames(view, band) for band in BANDS},
        }
        mp = f'/tmp/satfd_{view}_manifest.json'
        with open(mp, 'w') as f:
            json.dump(manifest, f)
        upload(mp, f'{CDN_BASE}/{view}/manifest.json', 'application/json')

    log.info(f"Done: {n_ok} imágenes nuevas en {len(VIEWS)} vistas, {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
