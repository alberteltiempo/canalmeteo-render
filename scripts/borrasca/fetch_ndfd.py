#!/usr/bin/env python3
"""
Borrasca - NDFD Fetcher (National Digital Forecast Database)
============================================================
Descarga datos del NDFD de NOAA - pronósticos oficiales del NWS.

El NDFD es el pronóstico "oficial" del NWS, con mayor resolución
que GFS sobre CONUS (~2.5km) y actualizaciones más frecuentes.

Variables:
- Temperatura
- Punto de rocío
- Viento
- Probabilidad de precipitación
- Cantidad de precipitación
- Nubosidad
- Tiempo significativo

Fuente: https://tgftp.nws.noaa.gov/SL.us008001/ST.opnl/DF.gr2/DC.ndfd/

Uso:
    python fetch_ndfd.py                    # Todas las variables
    python fetch_ndfd.py temp               # Solo temperatura
    python fetch_ndfd.py --hours 72         # Primeras 72h

Cron (cada hora):
    15 * * * * python fetch_ndfd.py
"""

import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict
from io import BytesIO
import tempfile
import os
import gzip

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

logger = setup_logger('ndfd', 'ndfd.log')

# =============================================
# CONFIGURACIÓN
# =============================================

# URLs del NDFD
NDFD_BASE_URL = "https://tgftp.nws.noaa.gov/SL.us008001/ST.opnl/DF.gr2/DC.ndfd/AR.conus"

# Alternativa: NCEP NOMADS
NOMADS_NDFD_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_ndfd.pl"

# Bounds CONUS
CONUS_BOUNDS = {
    'west': -130,
    'east': -60,
    'south': 20,
    'north': 55
}

OUTPUT_WIDTH = 3500
OUTPUT_HEIGHT = 1750

# Variables NDFD disponibles
VARIABLES = {
    'temp': {
        'name': 'Temperatura',
        'ndfd_var': 'temp',
        'nomads_param': 'var_TMP',
        'file_pattern': 'VP.001-003/ds.temp.bin',
        'unit': '°F',
        'colormap': 'temp',
    },
    'dewpoint': {
        'name': 'Punto de Rocío',
        'ndfd_var': 'td',
        'nomads_param': 'var_DPT',
        'file_pattern': 'VP.001-003/ds.td.bin',
        'unit': '°F',
        'colormap': 'dewpoint',
    },
    'wind-speed': {
        'name': 'Velocidad del Viento',
        'ndfd_var': 'wspd',
        'nomads_param': 'var_WIND',
        'file_pattern': 'VP.001-003/ds.wspd.bin',
        'unit': 'kt',
        'colormap': 'wind',
    },
    'wind-gust': {
        'name': 'Rachas de Viento',
        'ndfd_var': 'wgust',
        'nomads_param': 'var_GUST',
        'file_pattern': 'VP.001-003/ds.wgust.bin',
        'unit': 'kt',
        'colormap': 'wind',
    },
    'pop12': {
        'name': 'Prob. Precipitación 12h',
        'ndfd_var': 'pop12',
        'nomads_param': 'var_POP12',
        'file_pattern': 'VP.001-003/ds.pop12.bin',
        'unit': '%',
        'colormap': 'probability',
    },
    'qpf': {
        'name': 'Precipitación Acumulada',
        'ndfd_var': 'qpf',
        'nomads_param': 'var_QPF',
        'file_pattern': 'VP.001-003/ds.qpf.bin',
        'unit': 'mm',
        'colormap': 'precip',
    },
    'sky': {
        'name': 'Nubosidad',
        'ndfd_var': 'sky',
        'nomads_param': 'var_TCDC',
        'file_pattern': 'VP.001-003/ds.sky.bin',
        'unit': '%',
        'colormap': 'clouds',
    },
    'snow': {
        'name': 'Nieve Acumulada',
        'ndfd_var': 'snow',
        'nomads_param': 'var_SNOW',
        'file_pattern': 'VP.001-003/ds.snow.bin',
        'unit': 'in',
        'colormap': 'snow',
    },
    'wx': {
        'name': 'Tiempo Significativo',
        'ndfd_var': 'wx',
        'nomads_param': 'var_WX',
        'file_pattern': 'VP.001-003/ds.wx.bin',
        'unit': '',
        'colormap': 'wx',
    },
    'maxtemp': {
        'name': 'Temperatura Máxima',
        'ndfd_var': 'maxt',
        'nomads_param': 'var_TMAX',
        'file_pattern': 'VP.001-003/ds.maxt.bin',
        'unit': '°F',
        'colormap': 'temp',
    },
    'mintemp': {
        'name': 'Temperatura Mínima',
        'ndfd_var': 'mint',
        'nomads_param': 'var_TMIN',
        'file_pattern': 'VP.001-003/ds.mint.bin',
        'unit': '°F',
        'colormap': 'temp',
    },
}

# Escalas de colores
COLORMAPS = {
    'temp': [
        (-60, -40, 148, 0, 211, 255),    # Violeta
        (-40, -20, 75, 0, 130, 255),     # Índigo
        (-20, 0, 0, 0, 255, 255),        # Azul
        (0, 20, 0, 191, 255, 255),       # Cyan
        (20, 32, 0, 255, 127, 255),      # Verde claro
        (32, 50, 0, 255, 0, 255),        # Verde
        (50, 60, 173, 255, 47, 255),     # Verde amarillo
        (60, 70, 255, 255, 0, 255),      # Amarillo
        (70, 80, 255, 165, 0, 255),      # Naranja
        (80, 90, 255, 69, 0, 255),       # Rojo naranja
        (90, 100, 255, 0, 0, 255),       # Rojo
        (100, 110, 139, 0, 0, 255),      # Rojo oscuro
        (110, 130, 128, 0, 128, 255),    # Púrpura
    ],
    'dewpoint': [
        (-20, 20, 139, 90, 43, 255),     # Marrón (seco)
        (20, 40, 210, 180, 140, 255),    # Marrón claro
        (40, 55, 255, 255, 200, 255),    # Beige
        (55, 65, 144, 238, 144, 255),    # Verde claro
        (65, 70, 0, 128, 0, 255),        # Verde
        (70, 75, 0, 255, 255, 255),      # Cyan
        (75, 80, 30, 144, 255, 255),     # Azul
        (80, 100, 138, 43, 226, 255),    # Violeta
    ],
    'wind': [
        (0, 5, 200, 255, 255, 150),      # Cyan muy claro
        (5, 10, 100, 200, 255, 200),     # Cyan
        (10, 15, 50, 150, 255, 220),     # Azul claro
        (15, 20, 0, 100, 255, 240),      # Azul
        (20, 30, 0, 255, 0, 255),        # Verde
        (30, 40, 255, 255, 0, 255),      # Amarillo
        (40, 50, 255, 165, 0, 255),      # Naranja
        (50, 65, 255, 0, 0, 255),        # Rojo
        (65, 100, 128, 0, 128, 255),     # Púrpura
    ],
    'probability': [
        (0, 10, 0, 0, 0, 0),             # Transparente
        (10, 20, 200, 255, 200, 100),    # Verde muy claro
        (20, 40, 100, 255, 100, 150),    # Verde claro
        (40, 60, 0, 200, 0, 200),        # Verde
        (60, 80, 255, 255, 0, 230),      # Amarillo
        (80, 90, 255, 165, 0, 250),      # Naranja
        (90, 100, 255, 0, 0, 255),       # Rojo
    ],
    'precip': [
        (0, 0.5, 0, 0, 0, 0),            # Transparente
        (0.5, 2, 170, 255, 170, 180),    # Verde muy claro
        (2, 5, 100, 255, 100, 200),      # Verde claro
        (5, 10, 0, 200, 0, 220),         # Verde
        (10, 20, 255, 255, 0, 240),      # Amarillo
        (20, 35, 255, 165, 0, 255),      # Naranja
        (35, 50, 255, 0, 0, 255),        # Rojo
        (50, 100, 128, 0, 128, 255),     # Púrpura
    ],
    'clouds': [
        (0, 10, 0, 0, 0, 0),             # Transparente
        (10, 30, 255, 255, 255, 50),     # Blanco muy tenue
        (30, 50, 220, 220, 220, 100),    # Gris muy claro
        (50, 70, 180, 180, 180, 150),    # Gris claro
        (70, 85, 140, 140, 140, 200),    # Gris
        (85, 100, 100, 100, 100, 230),   # Gris oscuro
    ],
    'snow': [
        (0, 0.5, 0, 0, 0, 0),            # Transparente
        (0.5, 1, 200, 230, 255, 150),    # Azul muy claro
        (1, 2, 150, 200, 255, 180),      # Azul claro
        (2, 4, 100, 150, 255, 200),      # Azul
        (4, 8, 50, 100, 255, 220),       # Azul medio
        (8, 12, 100, 50, 200, 240),      # Púrpura azul
        (12, 24, 150, 0, 150, 255),      # Púrpura
        (24, 999, 255, 100, 255, 255),   # Magenta
    ],
}


def apply_ndfd_colormap(data: np.ndarray, colormap_name: str) -> np.ndarray:
    """Aplica colormap a los datos."""
    scale = COLORMAPS.get(colormap_name, COLORMAPS['temp'])
    
    height, width = data.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    
    for vmin, vmax, r, g, b, a in scale:
        mask = (data >= vmin) & (data < vmax)
        rgba[mask] = [r, g, b, a]
    
    return rgba


def download_ndfd_nomads(variable: str, fhr: int) -> Optional[bytes]:
    """Descarga datos NDFD desde NOMADS."""
    var_config = VARIABLES.get(variable)
    if not var_config:
        return None
    
    params = {
        'file': f'ds.{var_config["ndfd_var"]}.bin',
        'dir': '/ndfd/conus',
        'subregion': '',
        'leftlon': CONUS_BOUNDS['west'],
        'rightlon': CONUS_BOUNDS['east'],
        'toplat': CONUS_BOUNDS['north'],
        'bottomlat': CONUS_BOUNDS['south'],
        var_config['nomads_param']: 'on',
    }
    
    try:
        response = requests.get(NOMADS_NDFD_URL, params=params, timeout=120)
        response.raise_for_status()
        
        if len(response.content) < 1000:
            return None
            
        return response.content
    except Exception as e:
        logger.error(f"Error descargando NDFD {variable}: {e}")
        return None


def download_ndfd_direct(variable: str) -> Optional[bytes]:
    """Descarga datos NDFD directamente del servidor NWS."""
    var_config = VARIABLES.get(variable)
    if not var_config:
        return None
    
    url = f"{NDFD_BASE_URL}/{var_config['file_pattern']}"
    
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Error descargando NDFD {variable}: {e}")
        return None


def process_ndfd_data(grib_data: bytes, variable: str) -> List[tuple]:
    """
    Procesa datos NDFD GRIB2 a PNGs.
    NDFD contiene múltiples tiempos de pronóstico en un solo archivo.
    Retorna lista de (fhr, png_bytes).
    """
    if not HAS_XARRAY or not HAS_IMAGING:
        return []
    
    var_config = VARIABLES.get(variable)
    if not var_config:
        return []
    
    results = []
    
    try:
        with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
            f.write(grib_data)
            temp_path = f.name
        
        try:
            # NDFD puede tener múltiples mensajes (tiempos)
            ds = xr.open_dataset(temp_path, engine='cfgrib')
            var_name = list(ds.data_vars)[0]
            
            # Verificar si hay dimensión de tiempo
            if 'step' in ds.dims or 'time' in ds.dims:
                time_dim = 'step' if 'step' in ds.dims else 'time'
                times = ds[time_dim].values
                
                for i, t in enumerate(times):
                    data = ds[var_name].isel({time_dim: i}).values
                    
                    # Calcular hora de pronóstico
                    if hasattr(t, 'astype'):
                        hours = int(t.astype('timedelta64[h]').astype(int))
                    else:
                        hours = i * 3  # Estimación
                    
                    png_data = render_ndfd_frame(data, var_config)
                    if png_data:
                        results.append((hours, png_data))
            else:
                # Solo un tiempo
                data = ds[var_name].values
                png_data = render_ndfd_frame(data, var_config)
                if png_data:
                    results.append((0, png_data))
            
            ds.close()
        finally:
            os.unlink(temp_path)
            
    except Exception as e:
        logger.error(f"Error procesando NDFD {variable}: {e}")
        import traceback
        traceback.print_exc()
    
    return results


def render_ndfd_frame(data: np.ndarray, var_config: dict) -> Optional[bytes]:
    """Renderiza un frame NDFD a PNG."""
    try:
        # Conversiones de unidades
        if var_config['unit'] == '°F':
            # NDFD ya está en °F para temperatura
            pass
        elif var_config['unit'] == 'kt':
            # Convertir m/s a kt si es necesario
            if np.nanmax(data) < 50:  # Probablemente m/s
                data = data * 1.944
        
        # Aplicar colormap
        rgba = apply_ndfd_colormap(data, var_config['colormap'])
        
        # Crear imagen
        img = Image.fromarray(rgba, mode='RGBA')
        
        # Redimensionar
        img = img.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Error renderizando frame: {e}")
        return None


def fetch_variable(variable: str, max_hours: int = 168) -> int:
    """Descarga y procesa una variable NDFD."""
    logger.info(f"\n{'='*50}")
    logger.info(f"Variable: {VARIABLES[variable]['name']}")
    logger.info(f"{'='*50}")
    
    # Intentar descarga directa primero
    grib_data = download_ndfd_direct(variable)
    
    if not grib_data:
        # Intentar NOMADS
        grib_data = download_ndfd_nomads(variable, 0)
    
    if not grib_data:
        logger.error(f"No se pudo descargar {variable}")
        return 0
    
    # Procesar
    frames = process_ndfd_data(grib_data, variable)
    
    if not frames:
        logger.warning(f"No se generaron frames para {variable}")
        return 0
    
    # Subir frames
    now = utcnow()
    run_date = now.strftime('%Y%m%d')
    run_hour = f"{(now.hour // 6) * 6:02d}"
    
    success = 0
    for fhr, png_data in frames:
        if fhr > max_hours:
            continue
            
        remote_path = f"ndfd/{run_date}/{run_hour}/{variable}/f{fhr:03d}.png"
        if upload_to_spaces(png_data, remote_path, 'image/png'):
            success += 1
            logger.info(f"  ✓ f{fhr:03d}")
    
    return success


def main():
    parser = argparse.ArgumentParser(description='Borrasca NDFD Fetcher')
    parser.add_argument('variables', nargs='*', 
                        default=['temp', 'dewpoint', 'wind-speed', 'pop12', 'sky'],
                        help='Variables a descargar')
    parser.add_argument('--hours', type=int, default=168,
                        help='Horas de pronóstico (default: 168)')
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("BORRASCA - NDFD Fetcher")
    logger.info("=" * 60)
    
    if not HAS_XARRAY:
        logger.error("❌ xarray no instalado")
        sys.exit(1)
    
    now = utcnow()
    run_date = now.strftime('%Y%m%d')
    run_hour = f"{(now.hour // 6) * 6:02d}"
    
    logger.info(f"Fecha: {run_date} {run_hour}Z")
    logger.info(f"Variables: {args.variables}")
    
    total_success = 0
    for variable in args.variables:
        if variable in VARIABLES:
            total_success += fetch_variable(variable, args.hours)
    
    # Metadata
    metadata = {
        'model': 'ndfd',
        'run_date': run_date,
        'run_hour': run_hour,
        'run_timestamp': f"{run_date}{run_hour}",
        'max_hours': args.hours,
        'interval': 1,  # NDFD tiene intervalos variables
        'variables': list(args.variables),
        'bounds': CONUS_BOUNDS,
        'resolution': '2.5km',
        'source': 'NWS NDFD',
        'updated_at': utcnow().isoformat() + 'Z',
    }
    
    upload_to_spaces(metadata, f"ndfd/{run_date}/{run_hour}/metadata.json")
    upload_to_spaces(metadata, "ndfd/latest.json")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETADO: {total_success} archivos generados")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
