#!/usr/bin/env python3
"""
Borrasca - MRMS Radar Tile Generator con PrecipFlag
====================================================
Genera tiles de radar diferenciando tipo de precipitación:
- Lluvia: Cyan → Verde → Amarillo → Rojo → Magenta
- Nieve: Azul claro → Azul → Morado
- Mixta: Gris → Rosa

Combina MergedReflectivityQCComposite + PrecipFlag de MRMS.

Uso:
    python fetch_radar_tiles.py              # Últimos frames
    python fetch_radar_tiles.py --hours 1    # Última hora

Cron (cada 2 minutos):
    */2 * * * * python fetch_radar_tiles.py
"""

import sys
import gzip
import argparse
import re
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Tuple
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

logger = setup_logger('radar', 'radar.log')

# =============================================
# CONFIGURACIÓN
# =============================================

MRMS_BASE_URL = "https://mrms.ncep.noaa.gov/data/2D"

# Productos MRMS
REFLECTIVITY_PRODUCT = "MergedReflectivityQCComposite"
REFLECTIVITY_FILE = "MRMS_MergedReflectivityQCComposite_00.50"

PRECIPFLAG_PRODUCT = "PrecipFlag"
PRECIPFLAG_FILE = "MRMS_PrecipFlag_00.00"

# Bounds CONUS
DATA_BOUNDS = {
    'west': -130.0,
    'east': -60.0,
    'south': 20.0,
    'north': 55.0
}

# Configuración de tiles
TILE_SIZE = 256
MIN_ZOOM = 3
MAX_ZOOM = 6

HISTORY_HOURS = 6
FRAMES_TO_KEEP = HISTORY_HOURS * 30

# =============================================
# TIPOS DE PRECIPITACIÓN (PrecipFlag)
# =============================================
# -3 = Unknown/Cold (tratamos como nieve)
# 0 = No precipitation
# 1 = Warm stratiform rain
# 2 = Snow
# 3 = Warm stratiform rain
# 4 = Cool stratiform rain  
# 6 = Convective rain
# 7 = Hail
# 10 = Rain/snow mix
# 91 = Tropical warm rain
# 96 = Tropical snow

PRECIP_RAIN = [1, 3, 6, 91]       # Lluvia (quitamos 4 - lluvia fría)
PRECIP_SNOW = [2, 96, -3]         # Nieve (añadimos -3 como nieve)
PRECIP_MIX = [10, 4]              # Mixta (añadimos 4 - lluvia fría)
PRECIP_HAIL = [7]                 # Granizo

# =============================================
# ESCALAS DE COLORES POR TIPO
# =============================================

# LLUVIA: Cyan → Verde → Amarillo → Naranja → Rojo → Magenta
COLORS_RAIN = [
    (-999, 5,    0,   0,   0,   0),      # Transparente
    (5,    10,   0,   255, 255, 150),    # Cyan claro
    (10,   15,   0,   230, 230, 180),
    (15,   20,   0,   200, 200, 210),
    (20,   25,   0,   255, 0,   230),    # Verde brillante
    (25,   30,   0,   220, 0,   245),
    (30,   35,   0,   180, 0,   255),
    (35,   40,   255, 255, 0,   255),    # Amarillo
    (40,   45,   255, 220, 0,   255),
    (45,   50,   255, 160, 0,   255),    # Naranja
    (50,   55,   255, 100, 0,   255),
    (55,   60,   255, 0,   0,   255),    # Rojo
    (60,   65,   220, 0,   0,   255),
    (65,   70,   180, 0,   0,   255),
    (70,   999,  255, 0,   255, 255),    # Magenta
]

# NIEVE: Gris azulado → Azul → Azul oscuro (estilo Baron Weather)
COLORS_SNOW = [
    (-999, 5,    0,   0,   0,   0),      # Transparente
    (5,    10,   200, 210, 220, 180),    # Gris muy claro
    (10,   15,   180, 195, 210, 200),    # Gris azulado claro
    (15,   20,   160, 180, 205, 220),    # Gris azulado
    (20,   25,   140, 165, 200, 235),    # Azul grisáceo
    (25,   30,   120, 150, 195, 245),    # Azul claro
    (30,   35,   100, 135, 190, 255),    # Azul medio
    (35,   40,   80,  120, 185, 255),    # Azul
    (40,   45,   60,  100, 175, 255),    # Azul más intenso
    (45,   50,   50,  80,  160, 255),    # Azul oscuro
    (50,   55,   70,  60,  150, 255),    # Azul-morado
    (55,   60,   100, 50,  140, 255),    # Morado azulado
    (60,   65,   130, 60,  150, 255),    # Morado
    (65,   999,  160, 80,  170, 255),    # Morado claro
]

# MIXTA: Gris rosado → Rosa claro (estilo Baron Weather)
COLORS_MIX = [
    (-999, 5,    0,   0,   0,   0),      # Transparente
    (5,    10,   210, 200, 210, 180),    # Gris rosado muy claro
    (10,   15,   220, 195, 210, 200),
    (15,   20,   230, 190, 210, 220),    # Gris rosado
    (20,   25,   240, 185, 210, 235),
    (25,   30,   250, 180, 210, 245),    # Rosa muy claro
    (30,   35,   255, 175, 205, 255),
    (35,   40,   255, 165, 195, 255),    # Rosa claro
    (40,   45,   255, 150, 185, 255),
    (45,   50,   255, 135, 175, 255),    # Rosa
    (50,   55,   255, 120, 165, 255),
    (55,   60,   255, 100, 150, 255),    # Rosa más fuerte
    (60,   65,   255, 80,  135, 255),
    (65,   999,  255, 60,  120, 255),    # Rosa intenso
]

# GRANIZO: Verde → Amarillo → Blanco (destaca sobre todo)
COLORS_HAIL = [
    (-999, 5,    0,   0,   0,   0),
    (5,    20,   0,   255, 0,   200),    # Verde
    (20,   35,   255, 255, 0,   230),    # Amarillo
    (35,   50,   255, 200, 200, 255),    # Rosa claro
    (50,   65,   255, 255, 255, 255),    # Blanco
    (65,   999,  255, 150, 255, 255),    # Magenta brillante
]


# =============================================
# FUNCIONES DE TILES
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


# =============================================
# FUNCIONES DE DATOS
# =============================================

def get_available_files(product: str, file_prefix: str) -> List[str]:
    url = f"{MRMS_BASE_URL}/{product}/"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        pattern = rf"{file_prefix}_(\d{{8}}-\d{{6}})\.grib2\.gz"
        matches = re.findall(pattern, response.text)
        return sorted(set(matches))
    except Exception as e:
        logger.error(f"Error obteniendo lista {product}: {e}")
        return []


def parse_timestamp(ts: str) -> datetime:
    return datetime.strptime(ts, '%Y%m%d-%H%M%S').replace(tzinfo=timezone.utc)


def download_grib(product: str, file_prefix: str, timestamp: str) -> Optional[bytes]:
    url = f"{MRMS_BASE_URL}/{product}/{file_prefix}_{timestamp}.grib2.gz"
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return gzip.decompress(response.content)
    except Exception as e:
        logger.debug(f"Error descargando {product} {timestamp}: {e}")
        return None


def read_grib_to_array(grib_data: bytes) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
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


def apply_colormap_by_type(reflectivity: np.ndarray, precip_flag: np.ndarray) -> np.ndarray:
    """
    Aplica colores según reflectividad Y tipo de precipitación.
    """
    height, width = reflectivity.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    
    # Crear máscaras por tipo de precipitación
    mask_rain = np.isin(precip_flag, PRECIP_RAIN)
    mask_snow = np.isin(precip_flag, PRECIP_SNOW)
    mask_mix = np.isin(precip_flag, PRECIP_MIX)
    mask_hail = np.isin(precip_flag, PRECIP_HAIL)
    
    # Si no hay PrecipFlag válido pero hay reflectividad, asumir lluvia
    mask_unknown = (~mask_rain & ~mask_snow & ~mask_mix & ~mask_hail) & (reflectivity >= 5)
    mask_rain = mask_rain | mask_unknown
    
    # Aplicar colores de lluvia
    for dbz_min, dbz_max, r, g, b, a in COLORS_RAIN:
        mask = mask_rain & (reflectivity >= dbz_min) & (reflectivity < dbz_max)
        rgba[mask] = [r, g, b, a]
    
    # Aplicar colores de nieve
    for dbz_min, dbz_max, r, g, b, a in COLORS_SNOW:
        mask = mask_snow & (reflectivity >= dbz_min) & (reflectivity < dbz_max)
        rgba[mask] = [r, g, b, a]
    
    # Aplicar colores de mixta
    for dbz_min, dbz_max, r, g, b, a in COLORS_MIX:
        mask = mask_mix & (reflectivity >= dbz_min) & (reflectivity < dbz_max)
        rgba[mask] = [r, g, b, a]
    
    # Aplicar colores de granizo (sobrescribe otros)
    for dbz_min, dbz_max, r, g, b, a in COLORS_HAIL:
        mask = mask_hail & (reflectivity >= dbz_min) & (reflectivity < dbz_max)
        rgba[mask] = [r, g, b, a]
    
    return rgba


def apply_colormap_rain_only(reflectivity: np.ndarray) -> np.ndarray:
    """
    Fallback: solo colores de lluvia si no hay PrecipFlag.
    """
    height, width = reflectivity.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    
    for dbz_min, dbz_max, r, g, b, a in COLORS_RAIN:
        mask = (reflectivity >= dbz_min) & (reflectivity < dbz_max)
        rgba[mask] = [r, g, b, a]
    
    return rgba


# =============================================
# GENERACIÓN DE TILES
# =============================================

class RadarTileGenerator:
    def __init__(self, rgba_data: np.ndarray, lats: np.ndarray, lons: np.ndarray):
        self.rgba_data = rgba_data
        self.lats = lats
        self.lons = lons
        self.data_north = lats.max()
        self.data_south = lats.min()
        self.data_west = lons.min()
        self.data_east = lons.max()
    
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


def generate_tiles_for_frame(refl_data: np.ndarray, precip_data: Optional[np.ndarray],
                             lats: np.ndarray, lons: np.ndarray, timestamp: str) -> int:
    """Genera todos los tiles para un frame."""
    
    # Aplicar colormap según tipo de precipitación
    if precip_data is not None:
        rgba_data = apply_colormap_by_type(refl_data, precip_data)
    else:
        rgba_data = apply_colormap_rain_only(refl_data)
    
    generator = RadarTileGenerator(rgba_data, lats, lons)
    
    dt = parse_timestamp(timestamp)
    frame_id = dt.strftime('%Y%m%d_%H%M')
    
    tiles_to_upload = []
    
    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
        tiles = get_tiles_for_bounds(DATA_BOUNDS, zoom)
        
        for x, y in tiles:
            tile_data = generator.generate_tile(x, y, zoom)
            if tile_data:
                path = f"radar/tiles/{frame_id}/{zoom}/{x}/{y}.png"
                tiles_to_upload.append((tile_data, path))
    
    # Subir en paralelo
    def upload_tile(args):
        tile_data, path = args
        return upload_to_spaces(tile_data, path, 'image/png', cache_control='max-age=60')
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(upload_tile, tiles_to_upload))
    
    return sum(results)


def find_closest_timestamp(target: str, available: List[str], max_diff_minutes: int = 5) -> Optional[str]:
    """Encuentra el timestamp más cercano dentro del rango permitido."""
    target_dt = parse_timestamp(target)
    
    best_match = None
    best_diff = timedelta(minutes=max_diff_minutes + 1)
    
    for ts in available:
        ts_dt = parse_timestamp(ts)
        diff = abs(ts_dt - target_dt)
        if diff < best_diff:
            best_diff = diff
            best_match = ts
    
    if best_diff <= timedelta(minutes=max_diff_minutes):
        return best_match
    return None


def process_frames(refl_timestamps: List[str], precip_timestamps: List[str]) -> Tuple[int, int]:
    """Procesa múltiples frames."""
    frames_success = 0
    total_tiles = 0
    
    for refl_ts in refl_timestamps:
        # Descargar reflectividad
        refl_grib = download_grib(REFLECTIVITY_PRODUCT, REFLECTIVITY_FILE, refl_ts)
        if not refl_grib:
            continue
        
        refl_result = read_grib_to_array(refl_grib)
        if not refl_result:
            continue
        
        refl_data, lats, lons = refl_result
        
        # Buscar PrecipFlag más cercano
        precip_data = None
        precip_ts = find_closest_timestamp(refl_ts, precip_timestamps)
        
        if precip_ts:
            precip_grib = download_grib(PRECIPFLAG_PRODUCT, PRECIPFLAG_FILE, precip_ts)
            if precip_grib:
                precip_result = read_grib_to_array(precip_grib)
                if precip_result:
                    precip_data = precip_result[0]
        
        # Generar tiles
        has_precip = precip_data is not None
        tiles = generate_tiles_for_frame(refl_data, precip_data, lats, lons, refl_ts)
        
        if tiles > 0:
            frames_success += 1
            total_tiles += tiles
            dt = parse_timestamp(refl_ts)
            flag = "🌨️" if has_precip else "🌧️"
            logger.info(f"  {flag} {dt.strftime('%Y%m%d_%H%M')} ({tiles} tiles) {'+ PrecipFlag' if has_precip else '(sin PrecipFlag)'}")
    
    return frames_success, total_tiles


def update_metadata(timestamps: List[str]):
    """Actualiza metadata."""
    frames = [parse_timestamp(ts).strftime('%Y%m%d_%H%M') for ts in timestamps]
    frames = sorted(frames)[-FRAMES_TO_KEEP:]
    
    tile_bounds = {}
    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):
        tiles = get_tiles_for_bounds(DATA_BOUNDS, zoom)
        xs = [t[0] for t in tiles]
        ys = [t[1] for t in tiles]
        tile_bounds[zoom] = {
            'minX': min(xs), 'maxX': max(xs),
            'minY': min(ys), 'maxY': max(ys)
        }
    
    metadata = {
        'type': 'tiles',
        'product': 'MRMS Composite Reflectivity + PrecipFlag',
        'frames': frames,
        'frame_count': len(frames),
        'latest_frame': frames[-1] if frames else None,
        'history_hours': HISTORY_HOURS,
        'tile_size': TILE_SIZE,
        'min_zoom': MIN_ZOOM,
        'max_zoom': MAX_ZOOM,
        'bounds': DATA_BOUNDS,
        'tile_bounds': tile_bounds,
        'update_interval': '2min',
        'updated_at': utcnow().isoformat() + 'Z',
    }
    
    upload_to_spaces(metadata, 'radar/metadata.json')


def main():
    parser = argparse.ArgumentParser(description='Borrasca MRMS Radar Tile Generator')
    parser.add_argument('--hours', type=float, default=0.5, help='Horas a descargar')
    parser.add_argument('--full', action='store_true', help='Historial completo (6h)')
    args = parser.parse_args()
    
    if args.full:
        args.hours = HISTORY_HOURS
    
    logger.info("=" * 50)
    logger.info("BORRASCA - MRMS Radar + PrecipFlag")
    logger.info("=" * 50)
    
    if not HAS_XARRAY or not HAS_PIL:
        logger.error("Faltan dependencias (xarray, PIL)")
        sys.exit(1)
    
    # Obtener archivos disponibles
    refl_available = get_available_files(REFLECTIVITY_PRODUCT, REFLECTIVITY_FILE)
    precip_available = get_available_files(PRECIPFLAG_PRODUCT, PRECIPFLAG_FILE)
    
    logger.info(f"Reflectividad disponible: {len(refl_available)}")
    logger.info(f"PrecipFlag disponible: {len(precip_available)}")
    
    if not refl_available:
        logger.error("No hay archivos de reflectividad")
        return
    
    # Filtrar por tiempo
    cutoff = utcnow() - timedelta(hours=args.hours)
    to_process = [ts for ts in refl_available if parse_timestamp(ts) >= cutoff]
    
    logger.info(f"Frames a procesar: {len(to_process)}")
    
    if not to_process:
        logger.info("Nada nuevo que procesar")
        return
    
    # Procesar
    frames_ok, total_tiles = process_frames(to_process, precip_available)
    
    # Actualizar metadata
    update_metadata(refl_available)
    
    logger.info("=" * 50)
    logger.info(f"COMPLETADO: {frames_ok} frames, {total_tiles} tiles")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
