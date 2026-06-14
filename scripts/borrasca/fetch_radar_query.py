#!/usr/bin/env python3
"""
Borrasca - MRMS Point Query Generator
=====================================
Genera archivos JSON con datos de todos los productos MRMS
para una grid de puntos, permitiendo queries rápidas desde el frontend.

Estrategia: Pre-generar datos para una grid de puntos cada 0.25°
Esto permite queries instantáneas sin acceder a MRMS en tiempo real.

Estructura de salida:
  radar/query/{lat}/{lon}/latest.json

Uso:
    python fetch_radar_query.py              # Generar grid
    python fetch_radar_query.py --sparse     # Solo puntos con datos

Cron (cada 5 minutos):
    */5 * * * * python fetch_radar_query.py --sparse
"""

import sys
import gzip
import argparse
import re
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import json

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import setup_logger, upload_to_spaces, utcnow

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

logger = setup_logger('radar-query', 'radar-query.log')

# =============================================
# CONFIGURACIÓN
# =============================================

MRMS_BASE_URL = "https://mrms.ncep.noaa.gov/data/2D"

# Productos a consultar
QUERY_PRODUCTS = {
    'MergedReflectivityQCComposite': {
        'path': 'MergedReflectivityQCComposite',
        'file': 'MRMS_MergedReflectivityQCComposite_00.50',
    },
    'RadarOnly_QPE_01H': {
        'path': 'RadarOnly_QPE_01H',
        'file': 'MRMS_RadarOnly_QPE_01H_00.00',
    },
    'PrecipFlag': {
        'path': 'PrecipFlag',
        'file': 'MRMS_PrecipFlag_00.00',
    },
    'EchoTop_18': {
        'path': 'EchoTop_18',
        'file': 'MRMS_EchoTop_18_00.00',
    },
    'MESH': {
        'path': 'MESH',
        'file': 'MRMS_MESH_00.00',
    },
}

# Grid de puntos (cada 0.5° para reducir cantidad)
GRID_RESOLUTION = 0.5  # grados
BOUNDS = {
    'west': -125.0,
    'east': -65.0,
    'south': 24.0,
    'north': 50.0
}


# =============================================
# FUNCIONES
# =============================================

def get_latest_timestamp(product: str) -> Optional[str]:
    """Obtiene el timestamp más reciente disponible."""
    cfg = QUERY_PRODUCTS[product]
    url = f"{MRMS_BASE_URL}/{cfg['path']}/"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        pattern = rf"{cfg['file']}_(\d{{8}}-\d{{6}})\.grib2\.gz"
        matches = re.findall(pattern, response.text)
        if matches:
            return sorted(matches)[-1]
    except Exception as e:
        logger.debug(f"Error obteniendo timestamp {product}: {e}")
    return None


def download_and_read_grib(timestamp: str, product: str) -> Optional[tuple]:
    """Descarga y lee datos GRIB."""
    cfg = QUERY_PRODUCTS[product]
    url = f"{MRMS_BASE_URL}/{cfg['path']}/{cfg['file']}_{timestamp}.grib2.gz"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        grib_data = gzip.decompress(response.content)
        
        with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
            f.write(grib_data)
            temp_path = f.name
        
        try:
            ds = xr.open_dataset(temp_path, engine='cfgrib')
            var_name = list(ds.data_vars)[0]
            data = ds[var_name].values
            lats = ds.latitude.values
            lons = ds.longitude.values
            
            # Convertir longitudes
            if lons.max() > 180:
                lons = np.where(lons > 180, lons - 360, lons)
            
            ds.close()
            return data, lats, lons
        finally:
            os.unlink(temp_path)
    except Exception as e:
        logger.debug(f"Error descargando {product}: {e}")
        return None


def get_value_at_point(data: np.ndarray, lats: np.ndarray, lons: np.ndarray, 
                       target_lat: float, target_lon: float) -> Optional[float]:
    """Obtiene valor en un punto específico."""
    try:
        # Encontrar índices más cercanos
        lat_idx = np.argmin(np.abs(lats - target_lat))
        lon_idx = np.argmin(np.abs(lons - target_lon))
        
        value = float(data[lat_idx, lon_idx])
        
        # Filtrar valores inválidos
        if value < -900 or np.isnan(value):
            return None
        
        return value
    except:
        return None


def generate_query_data(sparse: bool = True):
    """Genera archivos JSON de query para grid de puntos."""
    
    logger.info("Descargando productos MRMS...")
    
    # Descargar todos los productos
    product_data = {}
    timestamp = None
    
    for product in QUERY_PRODUCTS:
        ts = get_latest_timestamp(product)
        if not ts:
            continue
        
        if timestamp is None:
            timestamp = ts
        
        result = download_and_read_grib(ts, product)
        if result:
            product_data[product] = result
            logger.info(f"  ✓ {product}")
    
    if not product_data:
        logger.error("No se pudieron descargar productos")
        return
    
    # Generar grid de puntos
    lats = np.arange(BOUNDS['south'], BOUNDS['north'], GRID_RESOLUTION)
    lons = np.arange(BOUNDS['west'], BOUNDS['east'], GRID_RESOLUTION)
    
    logger.info(f"Generando datos para {len(lats) * len(lons)} puntos...")
    
    # Timestamp para los archivos
    dt = datetime.strptime(timestamp, '%Y%m%d-%H%M%S').replace(tzinfo=timezone.utc)
    
    points_generated = 0
    points_with_data = 0
    
    def process_point(lat, lon):
        nonlocal points_generated, points_with_data
        
        point_data = {
            'lat': round(lat, 4),
            'lon': round(lon, 4),
            'timestamp': dt.isoformat(),
        }
        
        has_significant_data = False
        
        for product, (data, prod_lats, prod_lons) in product_data.items():
            value = get_value_at_point(data, prod_lats, prod_lons, lat, lon)
            point_data[product] = value
            
            # Verificar si hay datos significativos
            if value is not None:
                if product == 'MergedReflectivityQCComposite' and value >= 5:
                    has_significant_data = True
                elif product == 'RadarOnly_QPE_01H' and value >= 0.1:
                    has_significant_data = True
                elif product == 'MESH' and value >= 1:
                    has_significant_data = True
        
        # En modo sparse, solo guardar puntos con datos significativos
        if sparse and not has_significant_data:
            return False
        
        # Guardar JSON
        path = f"radar/query/{lat:.2f}/{lon:.2f}/latest.json"
        upload_to_spaces(point_data, path, cache_control='max-age=120')
        
        return has_significant_data
    
    # Procesar puntos
    for lat in lats:
        for lon in lons:
            points_generated += 1
            if process_point(lat, lon):
                points_with_data += 1
    
    logger.info(f"Completado: {points_with_data} puntos con datos de {points_generated} total")
    
    # Guardar índice de puntos con datos
    index = {
        'timestamp': dt.isoformat(),
        'grid_resolution': GRID_RESOLUTION,
        'bounds': BOUNDS,
        'points_with_data': points_with_data,
        'updated_at': utcnow().isoformat() + 'Z',
    }
    upload_to_spaces(index, 'radar/query/index.json')


def main():
    parser = argparse.ArgumentParser(description='MRMS Point Query Generator')
    parser.add_argument('--sparse', action='store_true', help='Solo generar puntos con datos')
    parser.add_argument('--full', action='store_true', help='Generar todos los puntos')
    args = parser.parse_args()
    
    logger.info("=" * 50)
    logger.info("BORRASCA - MRMS Query Generator")
    logger.info("=" * 50)
    
    if not HAS_XARRAY:
        logger.error("Falta xarray")
        sys.exit(1)
    
    sparse = not args.full
    generate_query_data(sparse=sparse)


if __name__ == '__main__':
    main()
