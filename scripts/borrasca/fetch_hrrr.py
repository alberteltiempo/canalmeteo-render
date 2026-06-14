#!/usr/bin/env python3
"""
Borrasca - HRRR Data Processor
==============================
Descarga datos GRIB2 del modelo HRRR (High-Resolution Rapid Refresh) de NOAA NOMADS.
Resolución: 3km - ideal para pronósticos a corto plazo con alto detalle.

HRRR se actualiza cada hora y tiene pronósticos hasta 18-48 horas.

Uso:
    python fetch_hrrr.py                    # Procesa todas las variables
    python fetch_hrrr.py temp-2m            # Solo temperatura 2m
    python fetch_hrrr.py --hours 18         # Solo hasta hora 18
    python fetch_hrrr.py refl-sim --hours 6 # Reflectividad 6 horas

Cron (cada hora):
    15 * * * * /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/borrasca/fetch_hrrr.py --hours 18
"""

import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import tempfile
from io import BytesIO

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    setup_logger, upload_to_spaces, get_spaces_url,
    DATA_DIR, download_binary, utcnow
)

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    from PIL import Image, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from scipy.ndimage import zoom as scipy_zoom
    from scipy.ndimage import gaussian_filter
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

logger = setup_logger('hrrr', 'hrrr.log')

# =============================================
# CONFIGURACIÓN HRRR
# =============================================

# HRRR tiene resolución nativa de 3km (~1059x1799 puntos para CONUS)
# No necesitamos interpolar tanto como GFS
INTERPOLATION_FACTOR = 2  # Solo 2x porque ya es alta resolución
OUTPUT_WIDTH = 3500
OUTPUT_HEIGHT = 1750

# Bounds CONUS (HRRR solo cubre CONUS)
CONUS_BOUNDS = {
    'west': -130,
    'east': -60,
    'south': 20,
    'north': 55
}

# Escala de temperatura Tropical Tidbits (Fahrenheit)
TEMP_COLORSCALE_F = [
    (-100, 255, 255, 255), (-90, 219, 191, 255), (-80, 177, 127, 229),
    (-70, 145, 55, 193), (-60, 123, 0, 163), (-50, 87, 0, 128),
    (-40, 207, 0, 99), (-30, 255, 0, 112), (-20, 255, 46, 185),
    (-10, 180, 90, 180), (0, 128, 128, 192), (10, 64, 64, 192),
    (20, 0, 0, 255), (30, 0, 112, 255), (32, 0, 144, 255),
    (40, 0, 192, 224), (50, 0, 224, 176), (60, 0, 255, 128),
    (70, 128, 255, 0), (80, 224, 224, 0), (90, 255, 176, 0),
    (100, 255, 112, 0), (110, 255, 48, 0), (120, 255, 0, 0), (130, 192, 0, 64),
]

# Escala para CAPE
CAPE_COLORSCALE = [
    (0, 255, 255, 255), (100, 200, 255, 200), (250, 150, 255, 150),
    (500, 255, 255, 0), (1000, 255, 200, 0), (1500, 255, 150, 0),
    (2000, 255, 100, 0), (2500, 255, 50, 0), (3000, 255, 0, 0),
    (4000, 200, 0, 50), (5000, 150, 0, 100),
]

# Escala para reflectividad (dBZ) - igual que radar
REFL_COLORSCALE = [
    (-10, 0, 0, 0), (5, 4, 233, 231), (10, 1, 159, 244),
    (15, 3, 0, 244), (20, 2, 253, 2), (25, 1, 197, 1),
    (30, 0, 142, 0), (35, 253, 248, 2), (40, 229, 188, 0),
    (45, 253, 149, 0), (50, 253, 0, 0), (55, 212, 0, 0),
    (60, 188, 0, 0), (65, 248, 0, 253), (70, 152, 84, 198),
    (75, 255, 255, 255),
]

# Variables HRRR disponibles
HRRR_VARIABLES = {
    'temp-2m': {
        'name': 'Temperatura 2m',
        'filter_level': 'lev_2_m_above_ground=on',
        'filter_var': 'var_TMP=on',
        'unit': '°F',
        'kelvin_offset': -273.15,
        'to_fahrenheit': True,
        'range_f': (-40, 120),
        'colorscale': TEMP_COLORSCALE_F,
    },
    'dewpoint-2m': {
        'name': 'Punto de Rocío 2m',
        'filter_level': 'lev_2_m_above_ground=on',
        'filter_var': 'var_DPT=on',
        'unit': '°F',
        'kelvin_offset': -273.15,
        'to_fahrenheit': True,
        'range_f': (-40, 90),
        'colorscale': TEMP_COLORSCALE_F,
    },
    'wind-10m': {
        'name': 'Viento 10m',
        'filter_level': 'lev_10_m_above_ground=on',
        'filter_var': 'var_UGRD=on&var_VGRD=on',
        'unit': 'kt',
        'is_wind': True,
        'range': (0, 80),
        'colorscale': [
            (0, 200, 230, 200), (20, 144, 238, 144), (40, 255, 255, 0),
            (60, 255, 165, 0), (80, 255, 0, 0),
        ],
    },
    'gust': {
        'name': 'Rachas de Viento',
        'filter_level': 'lev_surface=on',
        'filter_var': 'var_GUST=on',
        'unit': 'kt',
        'ms_to_kt': True,
        'range': (0, 100),
        'colorscale': [
            (0, 200, 230, 200), (25, 144, 238, 144), (50, 255, 255, 0),
            (75, 255, 100, 0), (100, 255, 0, 0),
        ],
    },
    'cape': {
        'name': 'CAPE',
        'filter_level': 'lev_surface=on',
        'filter_var': 'var_CAPE=on',
        'unit': 'J/kg',
        'range': (0, 5000),
        'colorscale': CAPE_COLORSCALE,
    },
    'refl-sim': {
        'name': 'Reflectividad Simulada',
        'filter_level': 'lev_entire_atmosphere=on',
        'filter_var': 'var_REFC=on',
        'unit': 'dBZ',
        'range': (-10, 75),
        'colorscale': REFL_COLORSCALE,
        'transparent_below': 5,
    },
    'refl-1km': {
        'name': 'Reflectividad 1km AGL',
        'filter_level': 'lev_1000_m_above_ground=on',
        'filter_var': 'var_REFD=on',
        'unit': 'dBZ',
        'range': (-10, 75),
        'colorscale': REFL_COLORSCALE,
        'transparent_below': 5,
    },
    'precip': {
        'name': 'Precipitación Acumulada',
        'filter_level': 'lev_surface=on',
        'filter_var': 'var_APCP=on',
        'unit': 'mm',
        'range': (0, 50),
        'colorscale': [
            (0, 255, 255, 255), (1, 200, 255, 200), (5, 100, 255, 100),
            (10, 0, 200, 0), (25, 0, 0, 255), (50, 255, 0, 255),
        ],
    },
    'visibility': {
        'name': 'Visibilidad',
        'filter_level': 'lev_surface=on',
        'filter_var': 'var_VIS=on',
        'unit': 'mi',
        'm_to_mi': True,
        'range': (0, 10),
        'colorscale': [
            (0, 128, 0, 0), (0.25, 255, 0, 0), (0.5, 255, 128, 0),
            (1, 255, 255, 0), (3, 200, 255, 200), (10, 255, 255, 255),
        ],
        'invert': True,  # Menor visibilidad = más color
    },
    'clouds': {
        'name': 'Nubosidad Total',
        'filter_level': 'lev_entire_atmosphere=on',
        'filter_var': 'var_TCDC=on',
        'unit': '%',
        'range': (0, 100),
        'colorscale': [
            (0, 30, 30, 50), (25, 80, 80, 100), (50, 140, 140, 160),
            (75, 200, 200, 210), (100, 255, 255, 255),
        ],
    },
}

# HRRR forecast hours (depende del ciclo)
# 00Z, 06Z, 12Z, 18Z: hasta 48h
# Otros ciclos: hasta 18h
DEFAULT_FORECAST_HOURS = list(range(0, 19))  # 0-18 por defecto


def interpolate_colorscale(colorscale, value):
    """Interpola un color de una escala."""
    for i in range(len(colorscale) - 1):
        v1, r1, g1, b1 = colorscale[i][:4]
        v2, r2, g2, b2 = colorscale[i + 1][:4]
        if v1 <= value <= v2:
            t = (value - v1) / (v2 - v1) if v2 != v1 else 0
            return (int(r1 + t * (r2 - r1)), int(g1 + t * (g2 - g1)), int(b1 + t * (b2 - b1)))
    if value < colorscale[0][0]:
        return colorscale[0][1:4]
    return colorscale[-1][1:4]


def create_colormap_from_scale(colorscale, vmin, vmax, n=256):
    """Genera colormap numpy desde escala de colores."""
    result = np.zeros((n, 3), dtype=np.uint8)
    for i in range(n):
        value = vmin + (i / (n - 1)) * (vmax - vmin)
        result[i] = interpolate_colorscale(colorscale, value)
    return result


def celsius_to_fahrenheit(c):
    return c * 9/5 + 32


def get_latest_hrrr_run():
    """Obtiene la última corrida HRRR disponible (cada hora, ~2h de retraso)."""
    now = utcnow()
    # HRRR tiene ~2 horas de retraso
    available = now - timedelta(hours=2)
    run_hour = available.hour
    run_time = available.replace(minute=0, second=0, microsecond=0)
    return run_time, f"{run_hour:02d}"


def build_hrrr_filter_url(run_date, run_hour, fhr, var_config):
    """Construye URL del filtro NOMADS para HRRR."""
    date_str = run_date.strftime('%Y%m%d')
    file_name = f"hrrr.t{run_hour}z.wrfsfcf{fhr:02d}.grib2"
    
    base_url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl"
    
    params = [
        f"file={file_name}",
        var_config['filter_level'],
        var_config['filter_var'],
        "subregion=",
        f"leftlon={CONUS_BOUNDS['west']}",
        f"rightlon={CONUS_BOUNDS['east']}",
        f"toplat={CONUS_BOUNDS['north']}",
        f"bottomlat={CONUS_BOUNDS['south']}",
        f"dir=/hrrr.{date_str}/conus"
    ]
    
    return f"{base_url}?{'&'.join(params)}"


def download_hrrr_grib(url, output_path):
    """Descarga archivo GRIB2."""
    logger.info(f"Descargando: {url[:80]}...")
    try:
        data = download_binary(url, timeout=120)
        if data and len(data) > 100:
            with open(output_path, 'wb') as f:
                f.write(data)
            logger.info(f"Descargado: {output_path.name} ({len(data)/1024:.1f} KB)")
            return True
        logger.error("Archivo vacío")
        return False
    except Exception as e:
        logger.error(f"Error descargando: {e}")
        return False


def process_grib_to_png(grib_path, var_config):
    """Procesa GRIB2 a PNG coloreado."""
    if not HAS_XARRAY or not HAS_PIL:
        return None, None
    
    try:
        ds = xr.open_dataset(grib_path, engine='cfgrib')
        var_names = list(ds.data_vars)
        
        # Manejar viento
        if var_config.get('is_wind'):
            u_var = [v for v in var_names if 'u' in v.lower()][0]
            v_var = [v for v in var_names if 'v' in v.lower()][0]
            u = ds[u_var].values
            v = ds[v_var].values
            data = np.sqrt(u**2 + v**2) * 1.94384  # m/s a nudos
            vmin, vmax = var_config['range']
        else:
            data = ds[var_names[0]].values
            
            # Conversiones
            if 'kelvin_offset' in var_config:
                data = data + var_config['kelvin_offset']
            if var_config.get('to_fahrenheit'):
                data = celsius_to_fahrenheit(data)
            if var_config.get('ms_to_kt'):
                data = data * 1.94384
            if var_config.get('m_to_mi'):
                data = data / 1609.34
            
            if 'range_f' in var_config:
                vmin, vmax = var_config['range_f']
            else:
                vmin, vmax = var_config['range']
        
        ds.close()
        
        while data.ndim > 2:
            data = data[0]
        
        # Interpolación (menos agresiva que GFS porque HRRR ya es alta res)
        if HAS_SCIPY and INTERPOLATION_FACTOR > 1:
            data = scipy_zoom(data, INTERPOLATION_FACTOR, order=3)
            data = gaussian_filter(data, sigma=0.5)
        
        data_stats = {
            'min': float(np.nanmin(data)),
            'max': float(np.nanmax(data)),
            'vmin': vmin, 'vmax': vmax,
            'unit': var_config['unit']
        }
        
        # Colormap
        colorscale = var_config.get('colorscale', TEMP_COLORSCALE_F)
        colormap = create_colormap_from_scale(colorscale, vmin, vmax)
        
        # Normalizar
        if var_config.get('invert'):
            data_norm = np.clip(1 - (data - vmin) / (vmax - vmin), 0, 1)
        else:
            data_norm = np.clip((data - vmin) / (vmax - vmin), 0, 1)
        
        data_uint8 = (data_norm * 255).astype(np.uint8)
        rgb = colormap[data_uint8]
        
        # Transparencia para reflectividad
        if var_config.get('transparent_below') is not None:
            threshold = var_config['transparent_below']
            mask = data < threshold
            rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
            rgba[:, :, :3] = rgb
            rgba[:, :, 3] = 255
            rgba[mask, 3] = 0
            img = Image.fromarray(rgba, mode='RGBA')
        else:
            img = Image.fromarray(rgb, mode='RGB')
        
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        img = img.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
        img = img.filter(ImageFilter.SMOOTH)
        
        buffer = BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue(), data_stats
        
    except Exception as e:
        logger.error(f"Error procesando GRIB: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def process_variable(var_key, run_date, run_hour, forecast_hours):
    """Procesa una variable para todas las horas."""
    var_config = HRRR_VARIABLES[var_key]
    logger.info(f"\n{'='*50}")
    logger.info(f"Procesando HRRR: {var_config['name']}")
    logger.info(f"{'='*50}")
    
    success_count = 0
    date_str = run_date.strftime('%Y%m%d')
    all_stats = {}
    
    for fhr in forecast_hours:
        try:
            url = build_hrrr_filter_url(run_date, run_hour, fhr, var_config)
            
            with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as tmp:
                tmp_path = Path(tmp.name)
            
            if not download_hrrr_grib(url, tmp_path):
                continue
            
            png_data, stats = process_grib_to_png(tmp_path, var_config)
            tmp_path.unlink(missing_ok=True)
            
            if png_data is None:
                continue
            
            if stats:
                all_stats[f"f{fhr:02d}"] = stats
            
            remote_path = f"hrrr/{date_str}/{run_hour}/{var_key}/f{fhr:02d}.png"
            
            if upload_to_spaces(png_data, remote_path, 'image/png', 'max-age=1800'):
                logger.info(f"✅ {var_key} f{fhr:02d}")
                success_count += 1
                
        except Exception as e:
            logger.error(f"Error en {var_key} f{fhr:02d}: {e}")
    
    # Metadata de la variable
    var_meta = {
        'name': var_config['name'],
        'unit': var_config['unit'],
        'stats': all_stats,
    }
    if 'range_f' in var_config:
        var_meta['range'] = var_config['range_f']
    elif 'range' in var_config:
        var_meta['range'] = var_config['range']
    
    upload_to_spaces(var_meta, f"hrrr/{date_str}/{run_hour}/{var_key}/metadata.json")
    
    return success_count


def upload_metadata(run_date, run_hour, variables, forecast_hours):
    """Sube metadatos generales del HRRR."""
    metadata = {
        'model': 'HRRR',
        'resolution': '3km',
        'run_date': run_date.strftime('%Y-%m-%d'),
        'run_hour': run_hour,
        'run_timestamp': run_date.strftime('%Y%m%d') + run_hour,
        'updated_at': utcnow().isoformat() + 'Z',
        'forecast_hours': forecast_hours,
        'variables': {
            key: {
                'name': HRRR_VARIABLES[key]['name'],
                'unit': HRRR_VARIABLES[key]['unit'],
            }
            for key in variables if key in HRRR_VARIABLES
        },
        'bounds': CONUS_BOUNDS,
        'base_url': get_spaces_url('hrrr')
    }
    
    date_str = run_date.strftime('%Y%m%d')
    upload_to_spaces(metadata, f"hrrr/{date_str}/{run_hour}/metadata.json")
    upload_to_spaces(metadata, "hrrr/latest.json")
    logger.info("✅ Metadatos subidos")


def main():
    parser = argparse.ArgumentParser(description='Borrasca HRRR Processor')
    parser.add_argument('variables', nargs='*', default=list(HRRR_VARIABLES.keys()))
    parser.add_argument('--hours', type=int, default=18)
    parser.add_argument('--run', type=str, default=None, help='Run específico YYYYMMDDHH')
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("BORRASCA - HRRR Processor (3km)")
    logger.info("=" * 60)
    
    if args.run:
        run_date = datetime.strptime(args.run[:8], '%Y%m%d')
        run_hour = args.run[8:10]
    else:
        run_date, run_hour = get_latest_hrrr_run()
    
    logger.info(f"Run: {run_date.strftime('%Y-%m-%d')} {run_hour}Z")
    
    forecast_hours = [h for h in DEFAULT_FORECAST_HOURS if h <= args.hours]
    variables = [v for v in args.variables if v in HRRR_VARIABLES]
    
    logger.info(f"Variables: {', '.join(variables)}")
    logger.info(f"Horas: 0-{max(forecast_hours)}")
    
    if not HAS_XARRAY or not HAS_PIL:
        logger.error("Instalar: pip install xarray cfgrib pillow scipy")
        sys.exit(1)
    
    total = 0
    for var_key in variables:
        total += process_variable(var_key, run_date, run_hour, forecast_hours)
    
    upload_metadata(run_date, run_hour, variables, forecast_hours)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETADO: {total} frames HRRR")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
