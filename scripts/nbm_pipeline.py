#!/usr/bin/env python3
"""
===============================================================================
NBM Raster Pipeline v3 — Canal Meteo TV (OPTIMIZED)
===============================================================================
Downloads ONLY needed variables via 3 filtered GRIB2 requests per forecast hour:
  - Group A (2m):     TMP, DPT, RH, APTMP     ~4 MB
  - Group B (10m):    WIND, GUST, WDIR         ~3 MB  
  - Group C (surface): VIS, TCDC, CAPE, APCP, REFC  ~5 MB
  Total: ~12 MB per hour vs 310 MB with all_var=on (25x faster download)

Generates PNG raster images + GeoJSON for click queries, uploads to CDN.

Cron: 20 * * * * /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/nbm_pipeline.py >> /var/log/canalmeteo/nbm.log 2>&1
===============================================================================
"""
import requests, json, subprocess, logging, sys, os, time, warnings
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
warnings.filterwarnings('ignore')

try:
    import cfgrib
    from PIL import Image
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.colors as mcolors
except ImportError as e:
    print(f"ERROR: {e}")
    sys.exit(1)

# =============================================================================
CONFIG = {
    'data_dir': '/opt/canalmeteo/data/nbm',
    'output_dir': '/opt/canalmeteo/data/nbm/images',
    'aws_profile': 'do-tor1',
    'cdn_bucket': 'canalmeteo-public',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',
    'cdn_base': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com',
    'user_agent': 'CanalMeteoTV/1.0',
    'lat_min': 24.0, 'lat_max': 50.0,
    'lon_min': -125.0, 'lon_max': -66.0,
    'img_width': 590, 'img_height': 260,
    'grid_step': 8,
    'forecast_hours': [1, 2, 3, 4, 5, 6, 9, 12, 18, 24, 36, 48, 60],
    'nomads': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl',
}

# 3 download groups by level — each is a small filtered GRIB request
DOWNLOAD_GROUPS = [
    {
        'name': '2m',
        'params': 'var_TMP=on&var_DPT=on&var_RH=on&var_APTMP=on&lev_2_m_above_ground=on',
    },
    {
        'name': '10m',
        'params': 'var_WIND=on&var_GUST=on&var_WDIR=on&lev_10_m_above_ground=on',
    },
    {
        'name': 'sfc',
        'params': 'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&lev_surface=on',
    },
]

# cfgrib field name → our variable name + conversion
# Based on actual dataset inspection:
#   Dataset 8 (heightAboveGround=2.0):  t2m, d2m, r2, aptmp
#   Dataset 9 (heightAboveGround=10.0): si10, i10fg, wdir10
#   Dataset 13 (surface=0.0):           cape, t, vis, tstm, tcc, tp, ptype, sdswrf
FIELD_MAP = {
    't2m':   {'var': 'tempF',    'convert': lambda k: (k - 273.15) * 9/5 + 32},
    'd2m':   {'var': 'dewpF',    'convert': lambda k: (k - 273.15) * 9/5 + 32},
    'r2':    {'var': 'rh',       'convert': lambda x: x},
    'aptmp': {'var': 'feelsF',   'convert': lambda k: (k - 273.15) * 9/5 + 32},
    'si10':  {'var': 'wspdMph',  'convert': lambda ms: ms * 2.237},
    'i10fg': {'var': 'gustMph',  'convert': lambda ms: ms * 2.237},
    'wdir10':{'var': 'wdir',     'convert': lambda x: x},
    'vis':   {'var': 'visMi',    'convert': lambda m: m / 1609.34},
    'tcc':   {'var': 'cloudPct', 'convert': lambda x: x},
    'cape':  {'var': 'cape',     'convert': lambda x: x},
    'tp':    {'var': 'precipIn', 'convert': lambda kg: np.where(kg > 0, kg / 25.4, 0)},
}

# Variables to render as PNG images (with color maps)
RENDER_VARS = {
    'tempF': {
        'label': 'Temperatura (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 110,
        'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a','#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f'],
    },
    'dewpF': {
        'label': 'Punto de rocío (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 80,
        'colors': ['#4e342e','#6d4c41','#a1887f','#e0e0e0','#a5d6a7','#66bb6a','#2e7d32','#00e676','#0097a7','#01579b','#4a148c'],
    },
    'rh': {
        'label': 'Humedad (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
        'colors': ['#b71c1c','#e65100','#f57f17','#cddc39','#8bc34a','#43a047','#2e7d32','#1565c0','#0d47a1'],
    },
    'wspdMph': {
        'label': 'Viento (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 60,
        'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c'],
    },
    'gustMph': {
        'label': 'Ráfagas (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 80,
        'colors': ['#e0e0e0','#81d4fa','#29b6f6','#ffeb3b','#ffa726','#ff7043','#e53935','#b71c1c','#4a148c'],
    },
    'visMi': {
        'label': 'Visibilidad (mi)', 'unit': 'mi', 'vmin': 0, 'vmax': 15,
        'colors': ['#b71c1c','#e53935','#ff7043','#ffa726','#ffeb3b','#e0e0e0','#90caf9'],
    },
    'cloudPct': {
        'label': 'Nubes (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
        'colors': ['#0d47a1','#1565c0','#42a5f5','#90caf9','#e0e0e0','#bdbdbd','#9e9e9e','#757575','#424242'],
    },
    'cape': {
        'label': 'CAPE (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 4000,
        'colors': ['#263238','#37474f','#4caf50','#8bc34a','#ffeb3b','#ff9800','#f44336','#d32f2f','#880e4f'],
    },
    'precipIn': {
        'label': 'Precipitación (in)', 'unit': 'in', 'vmin': 0, 'vmax': 2,
        'colors': ['#263238','#1b5e20','#4caf50','#a5d6a7','#ffeb3b','#ff9800','#f44336','#e040fb'],
    },
    'feelsF': {
        'label': 'Sensación (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 120,
        'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a','#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f'],
    },
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


def find_latest_cycle():
    now = datetime.now(timezone.utc)
    for hb in range(0, 6):
        t = now - timedelta(hours=hb)
        cc, dd = t.strftime('%H'), t.strftime('%Y%m%d')
        url = (f"{CONFIG['nomads']}?dir=%2Fblend.{dd}%2F{cc}%2Fcore&"
               f"file=blend.t{cc}z.core.f001.co.grib2&var_TMP=on&lev_2_m_above_ground=on&"
               f"subregion=&toplat=26&leftlon=235&rightlon=237&bottomlat=24")
        try:
            r = requests.get(url, timeout=15, headers={'User-Agent': CONFIG['user_agent']})
            if r.status_code == 200 and len(r.content) > 100:
                log.info(f"Cycle: {dd}/{cc}z")
                return dd, cc
        except:
            continue
    return None, None


def download_group(date, cycle, fhour, group):
    """Download a filtered GRIB2 for one level group."""
    outpath = os.path.join(CONFIG['data_dir'], f"nbm_{group['name']}_f{fhour:03d}.grib2")
    lw, le = CONFIG['lon_min'] + 360, CONFIG['lon_max'] + 360
    url = (f"{CONFIG['nomads']}?dir=%2Fblend.{date}%2F{cycle}%2Fcore&"
           f"file=blend.t{cycle}z.core.f{fhour:03d}.co.grib2&"
           f"{group['params']}&"
           f"subregion=&toplat={CONFIG['lat_max']}&leftlon={lw}&rightlon={le}&bottomlat={CONFIG['lat_min']}")
    try:
        r = requests.get(url, timeout=60, headers={'User-Agent': CONFIG['user_agent']})
        if r.status_code == 200 and len(r.content) > 500:
            with open(outpath, 'wb') as f:
                f.write(r.content)
            return outpath, len(r.content)
    except Exception as e:
        log.warning(f"    {group['name']}: {e}")
    return None, 0


def extract_fields(grib_path):
    """Extract all known fields from a GRIB2 file."""
    found = {}
    try:
        for ds in cfgrib.open_datasets(grib_path):
            for fname in ds.data_vars:
                if fname in FIELD_MAP and fname not in found:
                    found[fname] = (ds[fname].values, ds.latitude.values, ds.longitude.values)
    except Exception as e:
        log.warning(f"    cfgrib: {e}")
    return found


def render_png(data, lats, lons, var_cfg, output_path):
    """Render field as PNG using fast PIL resize instead of slow scipy griddata.
    The NBM grid is regular enough that direct resize produces good results."""
    convert = var_cfg['convert']
    
    # Convert the full field (no subsampling needed with PIL approach)
    field = convert(data.copy())
    
    # Handle NaN: replace with vmin so they render as the lowest color
    field = np.where(np.isnan(field), var_cfg['vmin'], field)
    
    # Normalize to 0-255
    vmin, vmax = var_cfg['vmin'], var_cfg['vmax']
    norm = np.clip((field - vmin) / (vmax - vmin), 0, 1)
    
    # Apply colormap
    cmap = mcolors.LinearSegmentedColormap.from_list('c', var_cfg['colors'], N=256)
    rgba = cmap(norm)  # (H, W, 4) float 0-1
    rgba[:, :, 3] = 0.70
    
    # Convert to PIL and resize with bilinear interpolation (fast!)
    img_full = Image.fromarray((rgba * 255).astype(np.uint8), 'RGBA')
    img_out = img_full.resize((CONFIG['img_width'], CONFIG['img_height']), Image.BILINEAR)
    img_out.save(output_path, 'PNG', optimize=True)
    return True


def upload(filepath, cdn_key, content_type='image/png'):
    cmd = ['aws', 's3', 'cp', filepath, f"s3://{CONFIG['cdn_bucket']}/{cdn_key}",
           '--profile', CONFIG['aws_profile'], '--acl', 'public-read',
           '--content-type', content_type, '--cache-control', 'max-age=600',
           '--endpoint-url', CONFIG['cdn_endpoint']]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    except:
        return False


def process_hour(date, cycle, fhour, cycle_dt):
    """Process a single forecast hour: download, extract, render, upload."""
    t0 = time.time()
    valid_dt = cycle_dt + timedelta(hours=fhour)
    hour_imgs = {}
    hour_points = {}

    # Download 3 filtered GRIBs (much smaller than all_var=on)
    all_fields = {}
    total_bytes = 0
    for group in DOWNLOAD_GROUPS:
        grib_path, nbytes = download_group(date, cycle, fhour, group)
        total_bytes += nbytes
        if grib_path:
            fields = extract_fields(grib_path)
            all_fields.update(fields)
            try:
                os.remove(grib_path)
            except:
                pass

    if not all_fields:
        log.warning(f"    f{fhour:03d}: no data")
        return None

    log.info(f"    Downloaded: {total_bytes // 1024} KB · Fields: {list(all_fields.keys())}")

    # Process each field → convert + collect GeoJSON points
    converted = {}  # var_name → (converted_data, lats, lons)
    for grib_field, (data, lats, lons) in all_fields.items():
        if grib_field not in FIELD_MAP:
            continue
        fm = FIELD_MAP[grib_field]
        var_name = fm['var']
        converted[var_name] = (data, lats, lons, fm['convert'])

        # GeoJSON points (step=20 for lighter file)
        gjstep = 20
        if lats.ndim == 2:
            for iy in range(0, lats.shape[0], gjstep):
                for ix in range(0, lats.shape[1], gjstep):
                    la = float(lats[iy, ix])
                    lo = float(lons[iy, ix])
                    if lo > 180: lo -= 360
                    if la < CONFIG['lat_min'] or la > CONFIG['lat_max']:
                        continue
                    if lo < CONFIG['lon_min'] or lo > CONFIG['lon_max']:
                        continue
                    val = float(data[iy, ix])
                    if np.isnan(val):
                        continue
                    val = fm['convert'](val)
                    # Handle numpy arrays from np.where
                    if hasattr(val, '__len__'):
                        val = float(val)
                    key = (round(la, 2), round(lo, 2))
                    if key not in hour_points:
                        hour_points[key] = {}
                    hour_points[key][var_name] = round(float(val), 1)

    # Render PNGs for variables that have render configs
    for var_name, (data, lats, lons, convert_fn) in converted.items():
        if var_name not in RENDER_VARS:
            continue
        rcfg = RENDER_VARS[var_name]
        rcfg_with_convert = {**rcfg, 'convert': convert_fn}

        png = os.path.join(CONFIG['output_dir'], f"nbm_{var_name}_f{fhour:03d}.png")
        if render_png(data, lats, lons, rcfg_with_convert, png):
            cdn_key = f"data/nbm/nbm_{var_name}_f{fhour:03d}.png"
            if upload(png, cdn_key):
                hour_imgs[var_name] = f"{CONFIG['cdn_base']}/{cdn_key}"

    # Upload GeoJSON
    if hour_points:
        features = [
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lo, la]}, 'properties': props}
            for (la, lo), props in hour_points.items()
        ]
        gj_out = {
            'type': 'FeatureCollection',
            'properties': {'fhour': fhour, 'validTime': valid_dt.isoformat(), 'validTimeUnix': int(valid_dt.timestamp())},
            'features': features
        }
        gj_path = os.path.join(CONFIG['output_dir'], f"nbm_f{fhour:03d}.json")
        with open(gj_path, 'w') as f:
            json.dump(gj_out, f, separators=(',', ':'))
        upload(gj_path, f"data/nbm/nbm_f{fhour:03d}.json", 'application/json')

    elapsed = time.time() - t0
    log.info(f"    f{fhour:03d}: {len(hour_imgs)} PNGs, {len(hour_points)} pts · {elapsed:.0f}s")

    if hour_imgs:
        return {
            'fhour': fhour,
            'validTime': valid_dt.isoformat(),
            'validTimeUnix': int(valid_dt.timestamp()),
            'images': hour_imgs,
        }
    return None


def main():
    t_start = time.time()
    log.info("=" * 50)
    log.info("NBM Raster Pipeline v3 — Canal Meteo TV")
    log.info("=" * 50)

    Path(CONFIG['data_dir']).mkdir(parents=True, exist_ok=True)
    Path(CONFIG['output_dir']).mkdir(parents=True, exist_ok=True)

    date, cycle = find_latest_cycle()
    if not date:
        log.error("No cycle available")
        return

    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    manifest_hours = []

    for fh in CONFIG['forecast_hours']:
        log.info(f"--- f{fh:03d} ---")
        result = process_hour(date, cycle, fh, cycle_dt)
        if result:
            manifest_hours.append(result)
        # Small delay between hours to be nice to NOMADS
        time.sleep(2)

    # Upload manifest
    if manifest_hours:
        manifest = {
            'model': 'NBM', 'version': 'raster-v3',
            'cycle': f"{date}/{cycle}z",
            'generated': datetime.now(timezone.utc).isoformat(),
            'bounds': {
                'north': CONFIG['lat_max'], 'south': CONFIG['lat_min'],
                'east': CONFIG['lon_max'], 'west': CONFIG['lon_min'],
            },
            'variables': {
                k: {'label': v['label'], 'unit': v['unit'], 'vmin': v['vmin'], 'vmax': v['vmax'], 'colors': v['colors']}
                for k, v in RENDER_VARS.items()
            },
            'hours': manifest_hours,
        }
        tmp = os.path.join(CONFIG['data_dir'], 'nbm_manifest.json')
        with open(tmp, 'w') as f:
            json.dump(manifest, f, separators=(',', ':'))
        if upload(tmp, 'data/nbm/nbm_manifest.json', 'application/json'):
            log.info(f"✅ Manifest uploaded")

    total_imgs = sum(len(h['images']) for h in manifest_hours)
    elapsed = time.time() - t_start
    log.info(f"✅ Complete: {total_imgs} images, {len(manifest_hours)} hours in {elapsed:.0f}s")


if __name__ == '__main__':
    main()
