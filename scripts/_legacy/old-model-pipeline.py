#!/usr/bin/env python3
"""
===============================================================================
Multi-Model Raster Pipeline — Canal Meteo TV
===============================================================================
Supports: NBM, GFS, HRRR
Usage:
  python model_pipeline.py              # defaults to NBM
  python model_pipeline.py --model gfs
  python model_pipeline.py --model hrrr

Cron:
  20 * * * *  .../model_pipeline.py --model nbm  >> .../nbm.log 2>&1
  25 */6 * * * .../model_pipeline.py --model gfs  >> .../gfs.log 2>&1
  30 * * * *  .../model_pipeline.py --model hrrr >> .../hrrr.log 2>&1
===============================================================================
"""
import requests, json, subprocess, logging, sys, os, time, warnings, argparse
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
    print(f"ERROR: {e}"); sys.exit(1)

# =============================================================================
# COMMON CONFIG
# =============================================================================
BASE = {
    'aws_profile': 'do-tor1',
    'cdn_bucket': 'canalmeteo-public',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',
    'cdn_base': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com',
    'user_agent': 'CanalMeteoTV/1.0',
    'lat_min': 24.0, 'lat_max': 50.0,
    'lon_min': -125.0, 'lon_max': -66.0,
    'img_width': 590, 'img_height': 260,
    # High-res for radar products — 2x native for smooth metro-level viewing
    'img_width_hires': 3600, 'img_height_hires': 2120,
}

# Variables that get rendered at high resolution
HIRES_VARS = {'reflectivity', 'refd1km', 'ptypeRefl'}

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================
MODELS = {
    'nbm': {
        'name': 'NBM',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl',
        'file_tmpl': 'blend.t{cc}z.core.f{fh:03d}.co.grib2',
        'dir_tmpl': '/blend.{dd}/{cc}/core',
        'cycles': list(range(24)),
        # Hourly 1-48, then every 3h to 60
        'forecast_hours': list(range(1,49)) + [51,54,57,60],
        'lon_360': True,
        'groups': [
            {'name':'2m',  'params':'var_TMP=on&var_DPT=on&var_RH=on&var_APTMP=on&lev_2_m_above_ground=on'},
            {'name':'10m', 'params':'var_WIND=on&var_GUST=on&var_WDIR=on&lev_10_m_above_ground=on'},
            {'name':'sfc', 'params':'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&lev_surface=on'},
        ],
        'fields': {
            't2m':'tempF', 'd2m':'dewpF', 'r2':'rh', 'aptmp':'feelsF',
            'si10':'wspdMph', 'i10fg':'gustMph', 'wdir10':'wdir',
            'vis':'visMi', 'tcc':'cloudPct', 'cape':'cape', 'tp':'precipIn',
        },
    },
    'gfs': {
        'name': 'GFS',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl',
        'file_tmpl': 'gfs.t{cc}z.pgrb2.0p25.f{fh:03d}',
        'dir_tmpl': '/gfs.{dd}/{cc}/atmos',
        'cycles': [0, 6, 12, 18],
        # Hourly 0-48, then every 3h to 120
        'forecast_hours': list(range(0,49)) + list(range(51,121,3)),
        'lon_360': False,
        'groups': [
            {'name':'2m',  'params':'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name':'10m', 'params':'var_UGRD=on&var_VGRD=on&var_GUST=on&lev_10_m_above_ground=on'},
            {'name':'sfc', 'params':'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&var_PRMSL=on&var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&lev_surface=on&lev_mean_sea_level=on'},
            {'name':'refl','params':'var_REFD=on&all_lev=on'},
        ],
        'fields': {
            't2m':'tempF', 'd2m':'dewpF', 'r2':'rh',
            'u10':'u10', 'v10':'v10', 'i10fg':'gustMph',
            'vis':'visMi', 'tcc':'cloudPct', 'cape':'cape', 'tp':'precipIn',
            'prmsl':'pressureMb',
            'refd':'refd1km',
            'crain':'crain', 'csnow':'csnow', 'cfrzr':'cfrzr', 'cicep':'cicep',
        },
    },
    'hrrr': {
        'name': 'HRRR',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl',
        'file_tmpl': 'hrrr.t{cc}z.wrfsfcf{fh:02d}.grib2',
        'dir_tmpl': '/hrrr.{dd}/conus',
        'cycles': list(range(24)),
        # 0-18 for all cycles; 0-48 for 00/06/12/18z (handled dynamically)
        'forecast_hours': list(range(0,19)),
        'forecast_hours_extended': list(range(0,49)),  # for 00/06/12/18z cycles
        'lon_360': False,
        'groups': [
            {'name':'2m',  'params':'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name':'10m', 'params':'var_UGRD=on&var_VGRD=on&var_GUST=on&lev_10_m_above_ground=on'},
            {'name':'sfc', 'params':'var_VIS=on&var_TCDC=on&var_CAPE=on&var_APCP=on&var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&lev_surface=on'},
            {'name':'refc','params':'var_REFC=on&lev_entire_atmosphere=on'},
            {'name':'refd','params':'var_REFD=on&lev_1000_m_above_ground=on'},
        ],
        'fields': {
            't2m':'tempF', 'd2m':'dewpF', 'r2':'rh',
            'u10':'u10', 'v10':'v10', 'gust':'gustMph',
            'vis':'visMi', 'tcc':'cloudPct', 'cape':'cape', 'tp':'precipIn',
            'refc':'reflectivity', 'refd':'refd1km',
            'crain':'crain', 'csnow':'csnow', 'cfrzr':'cfrzr', 'cicep':'cicep',
        },
    },
}

# Variable conversions (grib field values → display units)
CONVERTERS = {
    'tempF':    lambda k: (k - 273.15) * 9/5 + 32,
    'dewpF':    lambda k: (k - 273.15) * 9/5 + 32,
    'feelsF':   lambda k: (k - 273.15) * 9/5 + 32,
    'rh':       lambda x: x,
    'wspdMph':  lambda ms: ms * 2.237,
    'gustMph':  lambda ms: ms * 2.237,
    'wdir':     lambda x: x,
    'visMi':    lambda m: m / 1609.34,
    'cloudPct': lambda x: x,
    'cape':     lambda x: x,
    'precipIn': lambda kg: np.where(kg > 0, kg / 25.4, 0),
    'reflectivity': lambda x: x,
    'refd1km':  lambda x: x,
    'pressureMb': lambda pa: pa / 100.0,
    'crain':    lambda x: x,
    'csnow':    lambda x: x,
    'cfrzr':    lambda x: x,
    'cicep':    lambda x: x,
    'u10':      lambda x: x,
    'v10':      lambda x: x,
}

# Render config (color maps for PNG output)
RENDER_VARS = {
    'tempF':    {'label':'Temperatura (°F)','unit':'°F','vmin':-10,'vmax':110,
                 'colors':['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a','#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'dewpF':    {'label':'Punto de rocío (°F)','unit':'°F','vmin':-10,'vmax':80,
                 'colors':['#4e342e','#6d4c41','#a1887f','#e0e0e0','#a5d6a7','#66bb6a','#2e7d32','#00e676','#0097a7','#01579b','#4a148c']},
    'feelsF':   {'label':'Sensación (°F)','unit':'°F','vmin':-10,'vmax':120,
                 'colors':['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a','#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'rh':       {'label':'Humedad (%)','unit':'%','vmin':0,'vmax':100,
                 'colors':['#b71c1c','#e65100','#f57f17','#cddc39','#8bc34a','#43a047','#2e7d32','#1565c0','#0d47a1']},
    'wspdMph':  {'label':'Viento (mph)','unit':'mph','vmin':0,'vmax':60,
                 'colors':['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c']},
    'gustMph':  {'label':'Ráfagas (mph)','unit':'mph','vmin':0,'vmax':80,
                 'colors':['#e0e0e0','#81d4fa','#29b6f6','#ffeb3b','#ffa726','#ff7043','#e53935','#b71c1c','#4a148c']},
    'visMi':    {'label':'Visibilidad (mi)','unit':'mi','vmin':0,'vmax':15,
                 'colors':['#b71c1c','#e53935','#ff7043','#ffa726','#ffeb3b','#e0e0e0','#90caf9']},
    'cloudPct': {'label':'Nubes (%)','unit':'%','vmin':0,'vmax':100,
                 'colors':['#0d47a1','#1565c0','#42a5f5','#90caf9','#e0e0e0','#bdbdbd','#9e9e9e','#757575','#424242']},
    'cape':     {'label':'CAPE (J/kg)','unit':'J/kg','vmin':0,'vmax':4000,
                 'colors':['#263238','#37474f','#4caf50','#8bc34a','#ffeb3b','#ff9800','#f44336','#d32f2f','#880e4f']},
    'precipIn': {'label':'Precipitación (in)','unit':'in','vmin':0,'vmax':2,
                 'colors':['#263238','#1b5e20','#4caf50','#a5d6a7','#ffeb3b','#ff9800','#f44336','#e040fb']},
    'reflectivity':{'label':'Radar simulado (dBZ)','unit':'dBZ','vmin':0,'vmax':80,
                 'colors':'nws_refl', 'discrete': True},
    'refd1km':  {'label':'Radar 1km base (dBZ)','unit':'dBZ','vmin':0,'vmax':80,
                 'colors':'nws_refl', 'discrete': True},
    'ptypeRefl':{'label':'Tipo precip + radar','unit':'dBZ','vmin':0,'vmax':75,
                 'colors':['#00000000','#02fd02','#01c501','#008e00','#fdf802','#fd9500','#fd0000','#81d4fa','#039be5','#01579b','#f48fb1','#e91e63','#880e4f','#7c4dff','#6200ea','#fdfdfd']},
    'pressureMb':{'label':'Presión (mb)','unit':'mb','vmin':980,'vmax':1050,
                 'colors':['#4a148c','#1565c0','#42a5f5','#81c784','#ffeb3b','#ff9800','#e53935','#880e4f']},
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# =============================================================================
# FUNCTIONS
# =============================================================================

def find_latest_cycle(model_cfg):
    """Find latest available cycle for this model."""
    now = datetime.now(timezone.utc)
    max_lookback = 24 if model_cfg['name'] == 'GFS' else 12
    seen_cycles = set()

    for hb in range(0, max_lookback):
        t = now - timedelta(hours=hb)
        cc_int = t.hour
        valid_cycles = sorted(model_cfg['cycles'])
        cc_int = max([c for c in valid_cycles if c <= cc_int], default=valid_cycles[-1])
        cc = f"{cc_int:02d}"
        dd = t.strftime('%Y%m%d')

        cycle_key = f"{dd}/{cc}"
        if cycle_key in seen_cycles:
            continue
        seen_cycles.add(cycle_key)

        dir_path = model_cfg['dir_tmpl'].format(dd=dd, cc=cc)
        fh = model_cfg['forecast_hours'][0]
        fname = model_cfg['file_tmpl'].format(cc=cc, fh=fh)
        lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
        test_group = model_cfg['groups'][0]
        url = (f"{model_cfg['filter']}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
               f"{test_group['params']}&subregion=&toplat=26&leftlon={lw}&rightlon={lw+2}&bottomlat=24")
        try:
            r = requests.get(url, timeout=20, headers={'User-Agent': BASE['user_agent']})
            if r.status_code == 200 and len(r.content) > 100:
                log.info(f"Cycle: {dd}/{cc}z")
                return dd, cc
        except:
            pass
    return None, None


def download_group(model_cfg, date, cycle, fhour, group):
    """Download one filtered GRIB2."""
    data_dir = f"/opt/canalmeteo/data/{model_cfg['name'].lower()}"
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    outpath = os.path.join(data_dir, f"{model_cfg['name'].lower()}_{group['name']}_f{fhour:03d}.grib2")

    lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
    le = BASE['lon_max'] + (360 if model_cfg['lon_360'] else 0)
    dir_path = model_cfg['dir_tmpl'].format(dd=date, cc=cycle)
    fname = model_cfg['file_tmpl'].format(cc=cycle, fh=fhour)

    url = (f"{model_cfg['filter']}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
           f"{group['params']}&subregion=&toplat={BASE['lat_max']}&leftlon={lw}&"
           f"rightlon={le}&bottomlat={BASE['lat_min']}")
    try:
        r = requests.get(url, timeout=90, headers={'User-Agent': BASE['user_agent']})
        if r.status_code == 200 and len(r.content) > 500:
            with open(outpath, 'wb') as f: f.write(r.content)
            return outpath, len(r.content)
    except Exception as e:
        log.warning(f"    {group['name']}: {e}")
    return None, 0


def extract_fields(grib_path, field_map):
    """Extract known fields from GRIB2. If a field has multiple levels, use the first (lowest)."""
    found = {}
    try:
        for ds in cfgrib.open_datasets(grib_path):
            for fname in ds.data_vars:
                if fname in field_map and fname not in found:
                    data = ds[fname].values
                    # If 3D (multiple levels), take first level (usually lowest/1000m)
                    if data.ndim == 3:
                        data = data[0]
                    found[fname] = (data, ds.latitude.values, ds.longitude.values)
    except Exception as e:
        log.warning(f"    cfgrib: {e}")
    return found


# NWS standard radar reflectivity color table (exact dBZ thresholds)
# Matches Baron/Aguaceros/RadarScope standard
NWS_REFL_TABLE = [
    #  dBZ,  (R,    G,    B)
    ( 15,  (  1, 159, 244)),  # cyan
    ( 20,  (  3,   0, 244)),  # blue
    ( 25,  (  2, 253,   2)),  # light green
    ( 30,  (  1, 197,   1)),  # green
    ( 35,  (  0, 142,   0)),  # dark green
    ( 40,  (253, 248,   2)),  # yellow
    ( 45,  (229, 188,   0)),  # dark yellow
    ( 50,  (253, 149,   0)),  # orange
    ( 55,  (253,   0,   0)),  # red
    ( 60,  (212,   0,   0)),  # dark red
    ( 65,  (188,   0,   0)),  # darker red
    ( 70,  (248,   0, 253)),  # magenta
    ( 75,  (152,  84, 198)),  # purple
    ( 80,  (253, 253, 253)),  # white
]

def render_nws_refl(field):
    """Render radar field using exact NWS discrete color bins."""
    h, w = field.shape
    rgba = np.zeros((h, w, 4), dtype=np.float32)

    for i, (threshold, (r, g, b)) in enumerate(NWS_REFL_TABLE):
        if i < len(NWS_REFL_TABLE) - 1:
            next_threshold = NWS_REFL_TABLE[i + 1][0]
            mask = (field >= threshold) & (field < next_threshold)
        else:
            mask = field >= threshold
        rgba[mask, 0] = r / 255.0
        rgba[mask, 1] = g / 255.0
        rgba[mask, 2] = b / 255.0
        rgba[mask, 3] = 0.92

    return rgba


def reproject_to_regular(data, lats_2d, lons_2d, target_h, target_w):
    """Reproject 2D Lambert Conformal grid to regular lat/lon grid using nearest-neighbor.
    Fast approach: build KDTree once, reuse for all variables in same hour."""
    from scipy.spatial import cKDTree

    # Convert 360-based lons to -180/180
    lons_2d = np.where(lons_2d > 180, lons_2d - 360, lons_2d)

    # Target regular grid
    lat_reg = np.linspace(BASE['lat_max'], BASE['lat_min'], target_h)
    lon_reg = np.linspace(BASE['lon_min'], BASE['lon_max'], target_w)
    lon_grid, lat_grid = np.meshgrid(lon_reg, lat_reg)

    # Build KDTree from source coords
    src_points = np.column_stack([lats_2d.ravel(), lons_2d.ravel()])
    tree = cKDTree(src_points)

    # Query nearest neighbor for each target point
    tgt_points = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
    _, indices = tree.query(tgt_points)

    # Map data
    result = data.ravel()[indices].reshape(target_h, target_w)
    return result


# Cache for KDTree to avoid rebuilding for each variable in same hour
_kdtree_cache = {}

def reproject_cached(data, lats_2d, lons_2d, target_h, target_w):
    """Cached version — reuses KDTree across variables for same grid shape."""
    global _kdtree_cache
    from scipy.spatial import cKDTree

    cache_key = (lats_2d.shape, target_h, target_w)

    if cache_key not in _kdtree_cache:
        lons_fixed = np.where(lons_2d > 180, lons_2d - 360, lons_2d)
        lat_reg = np.linspace(BASE['lat_max'], BASE['lat_min'], target_h)
        lon_reg = np.linspace(BASE['lon_min'], BASE['lon_max'], target_w)
        lon_grid, lat_grid = np.meshgrid(lon_reg, lat_reg)

        src_points = np.column_stack([lats_2d.ravel(), lons_fixed.ravel()])
        tree = cKDTree(src_points)
        tgt_points = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
        _, indices = tree.query(tgt_points)

        _kdtree_cache[cache_key] = indices
        log.info(f"    Built KDTree for {lats_2d.shape} -> {target_h}x{target_w}")

    indices = _kdtree_cache[cache_key]
    return data.ravel()[indices].reshape(target_h, target_w)


def render_png(data, lats, lons, var_name, convert_fn, output_path, needs_reproject=False):
    """Render field as PNG using fast PIL resize.
    Radar products (reflectivity, refd1km, ptypeRefl) render at native resolution
    with full transparency below 5 dBZ threshold."""
    if var_name not in RENDER_VARS:
        return False
    rcfg = RENDER_VARS[var_name]

    field = convert_fn(data.copy())
    field = np.where(np.isnan(field), rcfg['vmin'], field)

    # Reproject Lambert Conformal (2D coords) to regular lat/lon grid
    if needs_reproject and lats.ndim == 2:
        if var_name in HIRES_VARS:
            field = reproject_cached(field, lats, lons, BASE['img_height_hires'], BASE['img_width_hires'])
        else:
            field = reproject_cached(field, lats, lons, BASE['img_height'], BASE['img_width'])

    # Use discrete NWS colormap for radar products
    if rcfg.get('discrete') and rcfg['colors'] == 'nws_refl':
        rgba = render_nws_refl(field)
        out_w, out_h = BASE['img_width_hires'], BASE['img_height_hires']
    else:
        norm = np.clip((field - rcfg['vmin']) / (rcfg['vmax'] - rcfg['vmin']), 0, 1)
        cmap = mcolors.LinearSegmentedColormap.from_list('c', rcfg['colors'], N=256)
        rgba = cmap(norm)

        if var_name in HIRES_VARS:
            rgba[:, :, 3] = np.where(field > 15, 0.92, 0.0)
            out_w, out_h = BASE['img_width_hires'], BASE['img_height_hires']
        else:
            rgba[:, :, 3] = 0.70
            out_w, out_h = BASE['img_width'], BASE['img_height']

    img_full = Image.fromarray((rgba * 255).astype(np.uint8), 'RGBA')
    # If already reprojected to target size, no resize needed
    if needs_reproject and lats.ndim == 2:
        img_out = img_full
    else:
        img_out = img_full.resize((out_w, out_h), Image.BILINEAR)
    img_out.save(output_path, 'PNG', optimize=True)
    return True


def upload(filepath, cdn_key, content_type='image/png'):
    cmd = ['aws','s3','cp', filepath, f"s3://{BASE['cdn_bucket']}/{cdn_key}",
           '--profile', BASE['aws_profile'], '--acl','public-read',
           '--content-type', content_type, '--cache-control','max-age=600',
           '--endpoint-url', BASE['cdn_endpoint']]
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    except: return False


def process_hour(model_cfg, date, cycle, fhour, cycle_dt):
    """Process one forecast hour."""
    t0 = time.time()
    model_id = model_cfg['name'].lower()
    valid_dt = cycle_dt + timedelta(hours=fhour)
    hour_imgs = {}
    hour_points = {}
    img_dir = f"/opt/canalmeteo/data/{model_id}/images"
    Path(img_dir).mkdir(parents=True, exist_ok=True)

    # Download all groups
    all_fields = {}
    total_bytes = 0
    for group in model_cfg['groups']:
        grib_path, nbytes = download_group(model_cfg, date, cycle, fhour, group)
        total_bytes += nbytes
        if grib_path:
            fields = extract_fields(grib_path, model_cfg['fields'])
            all_fields.update(fields)
            try: os.remove(grib_path)
            except: pass

    if not all_fields:
        return None

    log.info(f"    Downloaded: {total_bytes//1024} KB · Fields: {list(all_fields.keys())}")

    # GFS/HRRR: compute wind speed from UGRD+VGRD
    if 'u10' in all_fields and 'v10' in all_fields:
        u_data, u_lats, u_lons = all_fields['u10']
        v_data, _, _ = all_fields['v10']
        wspd = np.sqrt(u_data**2 + v_data**2)
        wdir = (270 - np.degrees(np.arctan2(v_data, u_data))) % 360
        all_fields['_wspd'] = (wspd, u_lats, u_lons)
        all_fields['_wdir'] = (wdir, u_lats, u_lons)
        # Map to our var names
        model_cfg['fields']['_wspd'] = 'wspdMph'
        model_cfg['fields']['_wdir'] = 'wdir'

    # Process each field
    for grib_field, (data, lats, lons) in all_fields.items():
        if grib_field not in model_cfg['fields']:
            continue
        var_name = model_cfg['fields'][grib_field]
        if var_name not in CONVERTERS:
            continue
        convert_fn = CONVERTERS[var_name]

        # GeoJSON points
        gjstep = 20
        if lats.ndim == 2:
            for iy in range(0, lats.shape[0], gjstep):
                for ix in range(0, lats.shape[1], gjstep):
                    la, lo = float(lats[iy,ix]), float(lons[iy,ix])
                    if lo > 180: lo -= 360
                    if la < BASE['lat_min'] or la > BASE['lat_max']: continue
                    if lo < BASE['lon_min'] or lo > BASE['lon_max']: continue
                    val = float(data[iy,ix])
                    if np.isnan(val): continue
                    cv = convert_fn(val)
                    if hasattr(cv, '__len__'): cv = float(cv)
                    key = (round(la,2), round(lo,2))
                    if key not in hour_points: hour_points[key] = {}
                    hour_points[key][var_name] = round(float(cv), 1)

        # Render PNG
        # HRRR uses Lambert Conformal - always needs reprojection
        needs_reproj = (lats.ndim == 2) or (model_cfg['name'] == 'HRRR')
        if lats.ndim == 1 and model_cfg['name'] == 'HRRR':
            log.warning(f"    ⚠️ HRRR has 1D lats ({lats.shape}) - possible cfgrib mis-decode of Lambert grid")
            # Build pseudo-2D grid from 1D coords for reprojection
            # This is wrong geometry but at least we detect the issue
            log.info(f"    lat range: {lats.min():.2f} to {lats.max():.2f}, lon range: {lons.min():.2f} to {lons.max():.2f}")
            log.info(f"    data shape: {data.shape}")
        elif lats.ndim == 2:
            log.info(f"    2D coords: lat {lats.shape}, reproj to {BASE['img_width']}x{BASE['img_height']}")
        png_path = os.path.join(img_dir, f"{model_id}_{var_name}_f{fhour:03d}.png")
        if render_png(data, lats, lons, var_name, convert_fn, png_path, needs_reproject=needs_reproj):
            cdn_key = f"data/{model_id}/{model_id}_{var_name}_f{fhour:03d}.png"
            if upload(png_path, cdn_key):
                hour_imgs[var_name] = f"{BASE['cdn_base']}/{cdn_key}"

    # Upload GeoJSON
    if hour_points:
        features = [{'type':'Feature','geometry':{'type':'Point','coordinates':[lo,la]},'properties':props}
                     for (la,lo),props in hour_points.items()]
        gj = {'type':'FeatureCollection',
              'properties':{'fhour':fhour,'validTime':valid_dt.isoformat(),'validTimeUnix':int(valid_dt.timestamp())},
              'features':features}
        gj_path = os.path.join(img_dir, f"{model_id}_f{fhour:03d}.json")
        with open(gj_path, 'w') as f: json.dump(gj, f, separators=(',',':'))
        upload(gj_path, f"data/{model_id}/{model_id}_f{fhour:03d}.json", 'application/json')

    # === SPECIAL: Precipitation Type Reflectivity composite ===
    # Combines refd1km/refc + crain/csnow/cfrzr/cicep into one color-coded image
    # Rain=green, Snow=blue, Freezing Rain=pink, Ice Pellets=purple
    refl_data = None
    refl_lats = refl_lons = None
    for rkey in ['refd1km', 'reflectivity']:
        gf = [k for k,v in model_cfg['fields'].items() if v == rkey]
        for gk in gf:
            if gk in all_fields:
                refl_data, refl_lats, refl_lons = all_fields[gk]
                break
        if refl_data is not None: break

    has_ptype = all(k in all_fields for k in ['crain','csnow','cfrzr','cicep'] if k in model_cfg['fields'].keys())

    if refl_data is not None and has_ptype:
        try:
            cr = all_fields.get('crain', (np.zeros_like(refl_data),))[0]
            cs = all_fields.get('csnow', (np.zeros_like(refl_data),))[0]
            cf = all_fields.get('cfrzr', (np.zeros_like(refl_data),))[0]
            ci = all_fields.get('cicep', (np.zeros_like(refl_data),))[0]

            # Reproject all fields if 2D Lambert coords
            if refl_lats.ndim == 2:
                th, tw = BASE['img_height_hires'], BASE['img_width_hires']
                refl_data = reproject_cached(refl_data, refl_lats, refl_lons, th, tw)
                cr = reproject_cached(cr, refl_lats, refl_lons, th, tw)
                cs = reproject_cached(cs, refl_lats, refl_lons, th, tw)
                cf = reproject_cached(cf, refl_lats, refl_lons, th, tw)
                ci = reproject_cached(ci, refl_lats, refl_lons, th, tw)

            # Normalize reflectivity to 0-1
            refl_norm = np.clip(refl_data / 75.0, 0, 1)

            # Color by precip type (RGBA)
            h, w = refl_data.shape[:2]
            rgba = np.zeros((h, w, 4), dtype=np.float32)
            # Rain: green palette
            rain_r = np.array([0.02,0.01,0.01,0.02,0.01,0.00,0.99,0.90,0.99,0.99,0.83,0.74,0.97,0.60,0.99])
            rain_g = np.array([0.91,0.62,0.00,0.99,0.77,0.56,0.97,0.74,0.58,0.00,0.00,0.00,0.00,0.33,0.99])
            rain_b = np.array([0.91,0.96,0.96,0.02,0.02,0.00,0.02,0.00,0.00,0.00,0.00,0.00,0.99,0.77,0.99])
            snow_c = np.array([0.4, 0.6, 0.8, 1.0])  # blue tones
            frzr_c = np.array([1.0, 0.6, 0.7, 1.0])   # pink
            ice_c  = np.array([0.6, 0.2, 0.8, 1.0])    # purple

            mask_valid = refl_data > 5  # Only show where there's actual echo
            # Default: rain colors (NWS radar scale)
            cmap = mcolors.LinearSegmentedColormap.from_list('radar',
                ['#00000000','#04e9e7','#019ff4','#0300f4','#02fd02','#01c501','#008e00',
                 '#fdf802','#e5bc00','#fd9500','#fd0000','#d40000','#bc0000','#f800fd','#9854c6','#fdfdfd'], N=256)
            rgba_rain = cmap(refl_norm)

            # Snow: shift to blue tones
            cmap_snow = mcolors.LinearSegmentedColormap.from_list('snow',
                ['#00000000','#b3e5fc','#81d4fa','#4fc3f7','#29b6f6','#039be5','#0277bd',
                 '#01579b','#e1bee7','#ce93d8','#ab47bc','#8e24aa','#6a1b9a','#4a148c','#e0e0e0','#ffffff'], N=256)
            rgba_snow = cmap_snow(refl_norm)

            # Freezing rain: pink tones
            cmap_frzr = mcolors.LinearSegmentedColormap.from_list('frzr',
                ['#00000000','#fce4ec','#f8bbd0','#f48fb1','#f06292','#ec407a','#e91e63',
                 '#d81b60','#c2185b','#ad1457','#880e4f','#ff6f00','#ff8f00','#ffa000','#ffb300','#ffffff'], N=256)
            rgba_frzr = cmap_frzr(refl_norm)

            # Ice pellets: purple tones
            cmap_ice = mcolors.LinearSegmentedColormap.from_list('ice',
                ['#00000000','#e8eaf6','#c5cae9','#9fa8da','#7986cb','#5c6bc0','#3f51b5',
                 '#3949ab','#303f9f','#283593','#1a237e','#b388ff','#7c4dff','#651fff','#6200ea','#ffffff'], N=256)
            rgba_ice = cmap_ice(refl_norm)

            # Blend by precip type flags
            final = np.copy(rgba_rain)
            snow_mask = (cs > 0.5) & mask_valid
            frzr_mask = (cf > 0.5) & mask_valid
            ice_mask = (ci > 0.5) & mask_valid
            final[snow_mask] = rgba_snow[snow_mask]
            final[frzr_mask] = rgba_frzr[frzr_mask]
            final[ice_mask] = rgba_ice[ice_mask]

            # Set alpha
            final[:, :, 3] = np.where(mask_valid, 0.92, 0)

            img_full = Image.fromarray((final * 255).astype(np.uint8), 'RGBA')
            if refl_lats.ndim == 2:
                img_out = img_full  # already at target size from reprojection
            else:
                img_out = img_full.resize((BASE['img_width_hires'], BASE['img_height_hires']), Image.BILINEAR)
            ptype_path = os.path.join(img_dir, f"{model_id}_ptypeRefl_f{fhour:03d}.png")
            img_out.save(ptype_path, 'PNG', optimize=True)
            cdn_key = f"data/{model_id}/{model_id}_ptypeRefl_f{fhour:03d}.png"
            if upload(ptype_path, cdn_key):
                hour_imgs['ptypeRefl'] = f"{BASE['cdn_base']}/{cdn_key}"
                log.info(f"    ✅ ptypeRefl")
        except Exception as e:
            log.warning(f"    ptypeRefl error: {e}")

    elapsed = time.time() - t0
    log.info(f"    f{fhour:03d}: {len(hour_imgs)} PNGs · {elapsed:.0f}s")

    if hour_imgs:
        return {'fhour':fhour, 'validTime':valid_dt.isoformat(),
                'validTimeUnix':int(valid_dt.timestamp()), 'images':hour_imgs}
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='nbm', choices=['nbm','gfs','hrrr'])
    args = parser.parse_args()

    model_cfg = MODELS[args.model]
    model_id = model_cfg['name'].lower()

    t_start = time.time()
    log.info("=" * 50)
    log.info(f"Model Pipeline — {model_cfg['name']} — Canal Meteo TV")
    log.info("=" * 50)

    date, cycle = find_latest_cycle(model_cfg)
    if not date:
        log.error("No cycle available"); return

    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    manifest_hours = []

    # HRRR: use extended hours (0-48) for 00/06/12/18z cycles
    forecast_hours = model_cfg['forecast_hours']
    if model_cfg['name'] == 'HRRR' and int(cycle) in [0, 6, 12, 18]:
        forecast_hours = model_cfg.get('forecast_hours_extended', forecast_hours)
        log.info(f"Extended HRRR cycle {cycle}z: {len(forecast_hours)} hours")

    for i, fh in enumerate(forecast_hours):
        log.info(f"--- f{fh:03d} ---")
        result = process_hour(model_cfg, date, cycle, fh, cycle_dt)
        if result:
            manifest_hours.append(result)

        # Free memory: delete old GRIB files and force garbage collection
        import gc, glob
        for g in glob.glob(f"/opt/canalmeteo/data/{model_id}/*.grib2"):
            try: os.remove(g)
            except: pass
        for g in glob.glob(f"/opt/canalmeteo/data/{model_id}/*.idx"):
            try: os.remove(g)
            except: pass
        gc.collect()

        # Upload partial manifest every 12 hours so Tormenta shows progress
        if manifest_hours and (i + 1) % 12 == 0:
            partial_manifest = {
                'model': model_cfg['name'], 'version': 'raster-v4',
                'cycle': f"{date}/{cycle}z",
                'generated': datetime.now(timezone.utc).isoformat(),
                'bounds': {'north':BASE['lat_max'],'south':BASE['lat_min'],
                           'east':BASE['lon_max'],'west':BASE['lon_min']},
                'variables': {k:{'label':v['label'],'unit':v['unit'],'vmin':v['vmin'],
                    'vmax':v['vmax']} for k,v in RENDER_VARS.items()},
                'hours': manifest_hours
            }
            mpath = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
            with open(mpath, 'w') as f: json.dump(partial_manifest, f)
            upload(mpath, f"data/{model_id}/{model_id}_manifest.json", 'application/json')
            log.info(f"  📤 Partial manifest: {len(manifest_hours)} hours")

        time.sleep(1)

    if manifest_hours:
        manifest = {
            'model': model_cfg['name'], 'version': 'raster-v4',
            'cycle': f"{date}/{cycle}z",
            'generated': datetime.now(timezone.utc).isoformat(),
            'bounds': {'north':BASE['lat_max'],'south':BASE['lat_min'],
                       'east':BASE['lon_max'],'west':BASE['lon_min']},
            'variables': {k:{'label':v['label'],'unit':v['unit'],'vmin':v['vmin'],
                            'vmax':v['vmax'],'colors':v['colors']}
                         for k,v in RENDER_VARS.items()},
            'hours': manifest_hours,
        }
        tmp = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
        with open(tmp, 'w') as f: json.dump(manifest, f, separators=(',',':'))
        if upload(tmp, f"data/{model_id}/{model_id}_manifest.json", 'application/json'):
            log.info(f"✅ Manifest uploaded")

    total = sum(len(h['images']) for h in manifest_hours)
    log.info(f"✅ {model_cfg['name']}: {total} images, {len(manifest_hours)} hours in {time.time()-t_start:.0f}s")


if __name__ == '__main__':
    main()
