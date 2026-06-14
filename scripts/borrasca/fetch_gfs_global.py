#!/usr/bin/env python3
"""
Borrasca - GFS Global Fetcher
=============================
Descarga datos del modelo GFS a escala global (0.25°).
Mismas variables que GFS CONUS pero cobertura mundial.

Variables:
- Temperatura 2m, 850hPa, 500hPa
- CAPE, Reflectividad simulada
- Viento 10m, 250hPa
- Precipitación, Tipo de precipitación
- MSLP, Humedad relativa, Nubosidad

Uso:
    python fetch_gfs_global.py                    # Todas las variables
    python fetch_gfs_global.py temp-2m wind-10m  # Variables específicas
    python fetch_gfs_global.py --hours 48        # Solo primeras 48h

Cron (cada 6 horas después de GFS):
    30 4,10,16,22 * * * python fetch_gfs_global.py
"""

import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict
from io import BytesIO
import tempfile
import os

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import setup_logger, upload_to_spaces, DATA_DIR, utcnow

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    from PIL import Image
    from scipy.ndimage import zoom
    HAS_IMAGING = True
except ImportError:
    HAS_IMAGING = False

logger = setup_logger('gfs_global', 'gfs_global.log')

# =============================================
# CONFIGURACIÓN
# =============================================

GFS_BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"

# Bounds globales
GLOBAL_BOUNDS = {
    'west': -180,
    'east': 180,
    'south': -90,
    'north': 90
}

# Output más grande para global
OUTPUT_WIDTH = 4320   # 360° * 12 px/grado
OUTPUT_HEIGHT = 2160  # 180° * 12 px/grado

# Variables disponibles (mismas que CONUS)
VARIABLES = {
    'temp-2m': {
        'name': 'Temperatura 2m',
        'params': {'var_TMP': 'on', 'lev_2_m_above_ground': 'on'},
        'unit': '°F',
        'colormap': 'temp',
    },
    'temp-850': {
        'name': 'Temperatura 850 hPa',
        'params': {'var_TMP': 'on', 'lev_850_mb': 'on'},
        'unit': '°F',
        'colormap': 'temp',
    },
    'temp-500': {
        'name': 'Temperatura 500 hPa',
        'params': {'var_TMP': 'on', 'lev_500_mb': 'on'},
        'unit': '°C',
        'colormap': 'temp_500',
    },
    'dewpoint-2m': {
        'name': 'Punto de Rocío 2m',
        'params': {'var_DPT': 'on', 'lev_2_m_above_ground': 'on'},
        'unit': '°F',
        'colormap': 'dewpoint',
    },
    'cape': {
        'name': 'CAPE',
        'params': {'var_CAPE': 'on', 'lev_surface': 'on'},
        'unit': 'J/kg',
        'colormap': 'cape',
    },
    'refl-sim': {
        'name': 'Reflectividad Simulada',
        'params': {'var_REFC': 'on', 'lev_entire_atmosphere': 'on'},
        'unit': 'dBZ',
        'colormap': 'reflectivity',
    },
    'precip': {
        'name': 'Precipitación Acumulada',
        'params': {'var_APCP': 'on', 'lev_surface': 'on'},
        'unit': 'mm',
        'colormap': 'precip',
    },
    'wind-10m': {
        'name': 'Viento 10m',
        'params': {'var_UGRD': 'on', 'var_VGRD': 'on', 'lev_10_m_above_ground': 'on'},
        'unit': 'kt',
        'colormap': 'wind',
        'is_wind': True,
    },
    'wind-250': {
        'name': 'Jet Stream (250 hPa)',
        'params': {'var_UGRD': 'on', 'var_VGRD': 'on', 'lev_250_mb': 'on'},
        'unit': 'kt',
        'colormap': 'jet',
        'is_wind': True,
    },
    'mslp': {
        'name': 'Presión a Nivel del Mar',
        'params': {'var_PRMSL': 'on', 'lev_mean_sea_level': 'on'},
        'unit': 'hPa',
        'colormap': 'pressure',
    },
    'rh-700': {
        'name': 'Humedad Relativa 700 hPa',
        'params': {'var_RH': 'on', 'lev_700_mb': 'on'},
        'unit': '%',
        'colormap': 'humidity',
    },
    'clouds': {
        'name': 'Nubosidad Total',
        'params': {'var_TCDC': 'on', 'lev_entire_atmosphere': 'on'},
        'unit': '%',
        'colormap': 'clouds',
    },
}

# Escalas de colores (importadas de fetch_gfs.py)
from fetch_gfs import (
    TEMP_SCALE_TROPICAL_TIDBITS,
    create_colormap_from_scale,
    apply_colormap,
    COLORMAP_CONFIGS
)


def get_latest_gfs_run() -> tuple:
    """Obtiene la última corrida GFS disponible."""
    now = utcnow()
    
    # GFS corre cada 6h: 00, 06, 12, 18 UTC
    # Disponible ~4h después
    hours_back = (now.hour % 6) + 4
    run_time = now - timedelta(hours=hours_back)
    run_hour = (run_time.hour // 6) * 6
    run_time = run_time.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    return run_time.strftime('%Y%m%d'), f'{run_hour:02d}'


def download_gfs_global(run_date: str, run_hour: str, fhr: int, variable: str) -> Optional[bytes]:
    """Descarga datos GFS globales para una variable y hora de pronóstico."""
    var_config = VARIABLES.get(variable)
    if not var_config:
        return None
    
    params = {
        'file': f'gfs.t{run_hour}z.pgrb2.0p25.f{fhr:03d}',
        'dir': f'/gfs.{run_date}/{run_hour}/atmos',
        'subregion': '',
        'leftlon': -180,
        'rightlon': 180,
        'toplat': 90,
        'bottomlat': -90,
    }
    params.update(var_config['params'])
    
    try:
        response = requests.get(GFS_BASE_URL, params=params, timeout=120)
        response.raise_for_status()
        
        if len(response.content) < 1000:
            logger.warning(f"Archivo muy pequeño para {variable} f{fhr:03d}")
            return None
            
        return response.content
    except Exception as e:
        logger.error(f"Error descargando {variable} f{fhr:03d}: {e}")
        return None


def process_gfs_data(grib_data: bytes, variable: str) -> Optional[bytes]:
    """Procesa datos GRIB2 a PNG."""
    if not HAS_XARRAY or not HAS_IMAGING:
        logger.error("Faltan dependencias (xarray, PIL, scipy)")
        return None
    
    var_config = VARIABLES.get(variable)
    if not var_config:
        return None
    
    try:
        # Guardar temporalmente
        with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
            f.write(grib_data)
            temp_path = f.name
        
        try:
            ds = xr.open_dataset(temp_path, engine='cfgrib')
            var_name = list(ds.data_vars)[0]
            data = ds[var_name].values
            lats = ds.latitude.values
            lons = ds.longitude.values
            ds.close()
        finally:
            os.unlink(temp_path)
        
        # Manejar viento (calcular magnitud)
        if var_config.get('is_wind'):
            # Para viento necesitamos U y V
            # Por simplicidad, si solo hay un componente, usamos ese
            if len(data.shape) == 2:
                wind_speed = np.abs(data)
            else:
                wind_speed = data
            data = wind_speed * 1.944  # m/s a kt
        
        # Convertir temperatura
        if 'temp' in variable or 'dewpoint' in variable:
            if variable != 'temp-500':
                data = (data - 273.15) * 9/5 + 32  # K a °F
            else:
                data = data - 273.15  # K a °C
        
        # Convertir presión
        if variable == 'mslp':
            data = data / 100  # Pa a hPa
        
        # Aplicar colormap
        colormap = var_config['colormap']
        rgba = apply_colormap(data, colormap)
        
        # Crear imagen
        img = Image.fromarray(rgba, mode='RGBA')
        
        # Redimensionar
        img = img.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
        
        # Guardar
        buffer = BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Error procesando {variable}: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_variable(variable: str, run_date: str, run_hour: str, max_hours: int = 120) -> int:
    """Descarga y procesa una variable para todas las horas de pronóstico."""
    logger.info(f"\n{'='*50}")
    logger.info(f"Variable: {VARIABLES[variable]['name']}")
    logger.info(f"{'='*50}")
    
    success = 0
    hours = list(range(0, min(max_hours + 1, 121), 3))  # 0, 3, 6, ... 120
    
    for fhr in hours:
        grib_data = download_gfs_global(run_date, run_hour, fhr, variable)
        if not grib_data:
            continue
        
        png_data = process_gfs_data(grib_data, variable)
        if not png_data:
            continue
        
        # Subir a Spaces
        remote_path = f"gfs-global/{run_date}/{run_hour}/{variable}/f{fhr:03d}.png"
        if upload_to_spaces(png_data, remote_path, 'image/png'):
            success += 1
            logger.info(f"  ✓ f{fhr:03d}")
    
    return success


def main():
    parser = argparse.ArgumentParser(description='Borrasca GFS Global Fetcher')
    parser.add_argument('variables', nargs='*', default=list(VARIABLES.keys()),
                        help='Variables a descargar')
    parser.add_argument('--hours', type=int, default=120,
                        help='Horas de pronóstico (default: 120)')
    parser.add_argument('--run', type=str, help='Run específico (YYYYMMDDHH)')
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("BORRASCA - GFS Global Fetcher")
    logger.info("=" * 60)
    
    if not HAS_XARRAY:
        logger.error("❌ xarray no instalado")
        sys.exit(1)
    
    # Determinar corrida
    if args.run:
        run_date = args.run[:8]
        run_hour = args.run[8:10]
    else:
        run_date, run_hour = get_latest_gfs_run()
    
    logger.info(f"Corrida: {run_date} {run_hour}Z")
    logger.info(f"Variables: {len(args.variables)}")
    logger.info(f"Horas: 0-{args.hours}")
    
    # Procesar variables
    total_success = 0
    for variable in args.variables:
        if variable in VARIABLES:
            total_success += fetch_variable(variable, run_date, run_hour, args.hours)
    
    # Metadata
    run_timestamp = f"{run_date}{run_hour}"
    metadata = {
        'model': 'gfs-global',
        'run_date': run_date,
        'run_hour': run_hour,
        'run_timestamp': run_timestamp,
        'max_hours': args.hours,
        'interval': 3,
        'variables': list(args.variables),
        'bounds': GLOBAL_BOUNDS,
        'resolution': '0.25°',
        'updated_at': utcnow().isoformat() + 'Z',
    }
    
    upload_to_spaces(metadata, f"gfs-global/{run_date}/{run_hour}/metadata.json")
    upload_to_spaces(metadata, "gfs-global/latest.json")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETADO: {total_success} archivos generados")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
