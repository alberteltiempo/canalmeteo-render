#!/usr/bin/env python3
"""
Borrasca - MRMS Multi-Product Tile Generator
=============================================
Genera tiles para múltiples productos MRMS:
- Reflectividad (MergedReflectivityQCComposite)
- Precipitación 1h (RadarOnly_QPE_01H)
- Precipitación 24h (RadarOnly_QPE_24H)
- Echo Tops (EchoTop_18)
- MESH/Granizo (MESH)
- Rotación (RotationTrack30min)

Uso:
    python fetch_radar_products.py                    # Todos los productos
    python fetch_radar_products.py --product mesh    # Solo MESH
    python fetch_radar_products.py --hours 1         # Última hora

Cron (cada 5 minutos):
    */5 * * * * python fetch_radar_products.py --hours 0.2
"""

import sys
import gzip
import argparse
import re
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from io import BytesIO
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import setup_logger, upload_to_spaces, utcnow, DATA_DIR

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = setup_logger('radar-products', 'radar-products.log')

# =============================================
# CONFIGURACIÓN
# =============================================

MRMS_BASE_URL = "https://mrms.ncep.noaa.gov/data/2D"

# Productos MRMS disponibles
PRODUCTS = {
    'reflectivity': {
        'path': 'MergedReflectivityQCComposite',
        'file': 'MRMS_MergedReflectivityQCComposite_00.50',
        'unit': 'dBZ',
        'scale': 'reflectivity',
    },
    'precip-1h': {
        'path': 'RadarOnly_QPE_01H',
        'file': 'MRMS_RadarOnly_QPE_01H_00.00',
        'unit': 'mm',
        'scale': 'precip',
    },
    'precip-24h': {
        'path': 'RadarOnly_QPE_24H',
        'file': 'MRMS_RadarOnly_QPE_24H_00.00',
        'unit': 'mm',
        'scale': 'precip-24h',
    },
    'echo-tops': {
        'path': 'EchoTop_18',
        'file': 'MRMS_EchoTop_18_00.00',
        'unit': 'km',
        'scale': 'echo-tops',
    },
    'mesh': {
        'path': 'MESH',
        'file': 'MRMS_MESH_00.00',
        'unit': 'mm',
        'scale': 'mesh',
    },
    'rotation': {
        'path': 'RotationTrack30min',
        'file': 'MRMS_RotationTrack30min_00.00',
        'unit': '1/s',
        'scale': 'rotation',
    },
}

# Bounds CONUS
DATA_BOUNDS = {
    'west': -130.0,
    'east': -60.0,
    'south': 20.0,
    'north': 55.0
}

TILE_SIZE = 256
MIN_ZOOM = 3
MAX_ZOOM = 6

# =============================================
# ESCALAS DE COLORES
# =============================================

COLOR_SCALES = {
    'reflectivity': [
        (-999, 5,    0,   0,   0,   0),
        (5,    10,   0,   255, 255, 150),
        (10,   20,   0,   200, 200, 200),
        (20,   25,   0,   255, 0,   240),
        (25,   30,   0,   200, 0,   250),
        (30,   35,   0,   140, 0,   255),
        (35,   40,   255, 255, 0,   255),
        (40,   45,   255, 200, 0,   255),
        (45,   50,   255, 140, 0,   255),
        (50,   55,   255, 60,  0,   255),
        (55,   60,   255, 0,   0,   255),
        (60,   65,   200, 0,   0,   255),
        (65,   70,   140, 0,   0,   255),
        (70,   999,  255, 0,   255, 255),
    ],
    'precip': [  # mm/h - escala 0-50mm
        (-999, 0.1,  0,   0,   0,   0),
        (0.1,  1,    160, 255, 160, 150),
        (1,    2.5,  100, 230, 100, 180),
        (2.5,  5,    0,   200, 0,   210),
        (5,    10,   255, 255, 0,   240),
        (10,   15,   255, 200, 0,   250),
        (15,   25,   255, 100, 0,   255),
        (25,   40,   255, 0,   0,   255),
        (40,   999,  255, 0,   255, 255),
    ],
    'precip-24h': [  # mm - escala 0-200mm
        (-999, 0.5,  0,   0,   0,   0),
        (0.5,  5,    160, 255, 160, 150),
        (5,    10,   100, 230, 100, 180),
        (10,   25,   0,   200, 0,   210),
        (25,   50,   255, 255, 0,   240),
        (50,   75,   255, 200, 0,   250),
        (75,   100,  255, 100, 0,   255),
        (100,  150,  255, 0,   0,   255),
        (150,  999,  255, 0,   255, 255),
    ],
    'echo-tops': [  # km
        (-999, 1,    0,   0,   0,   0),
        (1,    3,    0,   200, 255, 150),
        (3,    5,    0,   255, 200, 180),
        (5,    8,    0,   255, 0,   210),
        (8,    10,   255, 255, 0,   240),
        (10,   12,   255, 150, 0,   250),
        (12,   15,   255, 0,   0,   255),
        (15,   18,   255, 0,   255, 255),
        (18,   999,  255, 255, 255, 255),
    ],
    'mesh': [  # mm de diámetro de granizo
        (-999, 5,    0,   0,   0,   0),
        (5,    10,   0,   255, 0,   180),
        (10,   20,   255, 255, 0,   210),
        (20,   30,   255, 180, 0,   240),
        (30,   50,   255, 100, 0,   250),
        (50,   75,   255, 0,   0,   255),
        (75,   100,  255, 0,   255, 255),
        (100,  999,  255, 255, 255, 255),
    ],
    'rotation': [  # 1/s - valores muy pequeños
        (-999, 0.001, 0,   0,   0,   0),
        (0.001, 0.002, 0,   255, 255, 150),
        (0.002, 0.003, 0,   255, 0,   200),
        (0.003, 0.004, 255, 255, 0,   230),
        (0.004, 0.005, 255, 150, 0,   250),
        (0.005, 0.007, 255, 0,   0,   255),
        (0.007, 0.01,  255, 0,   255, 255),
        (0.01,  999,   255, 255, 255, 255),
    ],
}


# =============================================
# FUNCIONES AUXILIARES
# =============================================

def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n)
    return x, y


def tile_to_lat_lon(x: int, y: int, zoom: int) -> Tuple[float, float, float, float]:
    n = 2 ** zoom
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    south_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
    return math.degrees(north_rad), math.degrees(south_rad), east, west


def get_tiles_for_bounds(bounds: dict, zoom: int) -> List[Tuple[int, int]]:
    min_x, min_y = lat_lon_to_tile(bounds['north'], bounds['west'], zoom)
    max_x, max_y = lat_lon_to_tile(bounds['south'], bounds['east'], zoom)
    return [(x, y) for x in range(min_x, max_x + 1) for y in range(min_y, max_y + 1)]


def get_available_files(product: str) -> List[str]:
    prod_config = PRODUCTS[product]
    url = f"{MRMS_BASE_URL}/{prod_config['path']}/"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        pattern = rf"{prod_config['file']}_(\d{{8}}-\d{{6}})\.grib2\.gz"
        matches = re.findall(pattern, response.text)
        return sorted(set(matches))
    except Exception as e:
        logger.error(f"Error obteniendo lista {product}: {e}")
        return []


def parse_timestamp(ts: str) -> datetime:
    return datetime.strptime(ts, '%Y%m%d-%H%M%S').replace(tzinfo=timezone.utc)


def download_grib(timestamp: str, product: str) -> Optional[bytes]:
    prod_config = PRODUCTS[product]
    url = f"{MRMS_BASE_URL}/{prod_config['path']}/{prod_config['file']}_{timestamp}.grib2.gz"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return gzip.decompress(response.content)
    except Exception as e:
        logger.debug(f"Error descargando {product} {timestamp}: {e}")
        return None


def read_grib_data(grib_data: bytes) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    if not HAS_XARRAY:
        return None
    
    try:
        with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
            f.write(grib_data)
            temp_path = f.name
        
        try:
            ds = xr.open_dataset(temp_path, engine='cfgrib')
            var_name = list(ds.data_vars)[0]
            data = ds[var_name].values
            lats = ds.latitude.values
            lons = ds.longitude.values
            
            if lons.max() > 180:
                lons = np.where(lons > 180, lons - 360, lons)
            
            ds.close()
            return data, lats, lons
        finally:
            os.unlink(temp_path)
    except Exception as e:
        logger.error(f"Error leyendo GRIB: {e}")
        return None


def apply_colormap(data: np.ndarray, scale_name: str) -> np.ndarray:
    scale = COLOR_SCALES.get(scale_name, COLOR_SCALES['reflectivity'])
    height, width = data.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    
    for val_min, val_max, r, g, b, a in scale:
        mask = (data >= val_min) & (data < val_max)
        rgba[mask] = [r, g, b, a]
    
    return rgba


# =============================================
# GENERADOR DE TILES
# =============================================

class TileGenerator:
    def __init__(self, data: np.ndarray, lats: np.ndarray, lons: np.ndarray, scale_name: str):
        self.data = data
        self.lats = lats
        self.lons = lons
        self.data_north = lats.max()
        self.data_south = lats.min()
        self.data_west = lons.min()
        self.data_east = lons.max()
        self.rgba_data = apply_colormap(data, scale_name)
    
    def generate_tile(self, x: int, y: int, zoom: int) -> Optional[bytes]:
        north, south, east, west = tile_to_lat_lon(x, y, zoom)
        
        if (west > self.data_east or east < self.data_west or
            south > self.data_north or north < self.data_south):
            return None
        
        lat_start = np.searchsorted(-self.lats, -north)
        lat_end = np.searchsorted(-self.lats, -south)
        lon_start = np.searchsorted(self.lons, west)
        lon_end = np.searchsorted(self.lons, east)
        
        if lat_start >= lat_end or lon_start >= lon_end:
            return None
        
        tile_data = self.rgba_data[lat_start:lat_end, lon_start:lon_end]
        
        if tile_data.size == 0 or tile_data[:, :, 3].max() == 0:
            return None
        
        img = Image.fromarray(tile_data, mode='RGBA')
        img = img.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()


def generate_tiles_for_product(grib_data: bytes, timestamp: str, product: str) -> int:
    result = read_grib_data(grib_data)
    if result is None:
        return 0
    
    data, lats, lons = result
    scale_name = PRODUCTS[product]['scale']
    generator = TileGenerator(data, lats, lons, scale_name)
    
    dt = parse_timestamp(timestamp)
    frame_id = dt.strftime('%Y%m%d_%H%M')
    
    tiles_to_upload = []
    
    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
        tiles = get_tiles_for_bounds(DATA_BOUNDS, zoom)
        
        for x, y in tiles:
            tile_data = generator.generate_tile(x, y, zoom)
            if tile_data:
                path = f"radar/{product}/tiles/{frame_id}/{zoom}/{x}/{y}.png"
                tiles_to_upload.append((tile_data, path))
    
    def upload_tile(args):
        tile_data, path = args
        return upload_to_spaces(tile_data, path, 'image/png', cache_control='max-age=60')
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(upload_tile, tiles_to_upload))
    
    return sum(results)


def update_metadata(product: str, timestamps: List[str]):
    frames = [parse_timestamp(ts).strftime('%Y%m%d_%H%M') for ts in timestamps]
    frames = sorted(frames)[-180:]  # Últimos 6h
    
    metadata = {
        'type': 'tiles',
        'product': PRODUCTS[product]['path'],
        'unit': PRODUCTS[product]['unit'],
        'frames': frames,
        'frame_count': len(frames),
        'latest_frame': frames[-1] if frames else None,
        'min_zoom': MIN_ZOOM,
        'max_zoom': MAX_ZOOM,
        'bounds': DATA_BOUNDS,
        'updated_at': utcnow().isoformat() + 'Z',
    }
    
    upload_to_spaces(metadata, f'radar/{product}/metadata.json')


def process_product(product: str, hours: float) -> Tuple[int, int]:
    available = get_available_files(product)
    
    if not available:
        logger.warning(f"No hay archivos para {product}")
        return 0, 0
    
    cutoff = utcnow() - timedelta(hours=hours)
    to_process = [ts for ts in available if parse_timestamp(ts) >= cutoff]
    
    frames_ok = 0
    total_tiles = 0
    
    for ts in to_process:
        grib_data = download_grib(ts, product)
        if not grib_data:
            continue
        
        tiles = generate_tiles_for_product(grib_data, ts, product)
        if tiles > 0:
            frames_ok += 1
            total_tiles += tiles
            logger.info(f"  ✓ {product}: {parse_timestamp(ts).strftime('%Y%m%d_%H%M')} ({tiles} tiles)")
    
    update_metadata(product, available)
    
    return frames_ok, total_tiles


def main():
    parser = argparse.ArgumentParser(description='MRMS Multi-Product Tile Generator')
    parser.add_argument('--product', choices=list(PRODUCTS.keys()), help='Producto específico')
    parser.add_argument('--hours', type=float, default=0.5, help='Horas a procesar')
    args = parser.parse_args()
    
    logger.info("=" * 50)
    logger.info("BORRASCA - MRMS Product Generator")
    logger.info("=" * 50)
    
    if not HAS_XARRAY or not HAS_PIL:
        logger.error("Faltan dependencias")
        sys.exit(1)
    
    products_to_process = [args.product] if args.product else list(PRODUCTS.keys())
    
    total_frames = 0
    total_tiles = 0
    
    for product in products_to_process:
        logger.info(f"\n📡 Procesando: {product}")
        frames, tiles = process_product(product, args.hours)
        total_frames += frames
        total_tiles += tiles
    
    logger.info("=" * 50)
    logger.info(f"COMPLETADO: {total_frames} frames, {total_tiles} tiles")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
