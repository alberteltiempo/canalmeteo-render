#!/usr/bin/env python3
"""
Borrasca - MRMS Radar Fetcher v2
================================
Descarga datos de radar MRMS con tipo de precipitación (lluvia/nieve/mixta).

Productos MRMS usados:
- MergedReflectivityQCComposite: Reflectividad compuesta (dBZ)
- PrecipFlag: Tipo de precipitación (lluvia/nieve/convectiva/granizo)

Fuente: https://mrms.ncep.noaa.gov/data/2D/

Uso:
    python fetch_radar.py              # Descarga frames recientes
    python fetch_radar.py --hours 2    # Solo últimas 2 horas
    python fetch_radar.py --full       # Historial completo (6h)

Cron (cada 2 minutos):
    */2 * * * * python fetch_radar.py
"""

import sys
import gzip
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Tuple
from io import BytesIO
import tempfile
import os

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import setup_logger, upload_to_spaces, get_spaces_url, utcnow, DATA_DIR

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

logger = setup_logger('radar', 'radar.log')

# =============================================
# CONFIGURACIÓN
# =============================================

MRMS_BASE_URL = "https://mrms.ncep.noaa.gov/data/2D"

# Productos MRMS
PRODUCTS = {
    'reflectivity': {
        'path': 'MergedReflectivityQCComposite',
        'file': 'MRMS_MergedReflectivityQCComposite_00.50',
    },
    'precip_flag': {
        'path': 'PrecipFlag',
        'file': 'MRMS_PrecipFlag_00.00',
    },
}

CONUS_BOUNDS = {
    'west': -130.0,
    'east': -60.0,
    'south': 20.0,
    'north': 55.0
}

# Resolución máxima para mejor calidad (como Baron)
OUTPUT_WIDTH = 7000   # Aumentado significativamente
OUTPUT_HEIGHT = 3500

HISTORY_HOURS = 6
FRAMES_TO_KEEP = HISTORY_HOURS * 30

# =============================================
# ESCALAS DE COLORES ESTILO BARON (EXACTO)
# =============================================

# Colores para LLUVIA - Escala Baron exacta
# Cyan claro → Cyan → Verde → Amarillo → Naranja → Rojo → Magenta
RAIN_COLORS = [
    # (min_dbz, max_dbz, R, G, B, Alpha)
    (-999, 5,    0,   0,   0,   0),      # Transparente
    
    # Cyan muy claro (5-10 dBZ) - Precipitación muy ligera
    (5,    7,    0,   255, 255, 120),    # Cyan brillante claro
    (7,    10,   0,   240, 240, 150),    # Cyan claro
    
    # Cyan/Verde-agua (10-20 dBZ) - Precipitación ligera  
    (10,   12,   0,   220, 220, 180),    # Cyan
    (12,   15,   0,   200, 200, 200),    # Cyan medio
    (15,   18,   0,   180, 180, 220),    # Cyan oscuro
    (18,   20,   0,   160, 160, 235),    # Transición a verde
    
    # Verde (20-35 dBZ) - Lluvia ligera a moderada
    (20,   22,   0,   255, 0,   240),    # Verde brillante
    (22,   25,   0,   230, 0,   245),    # Verde
    (25,   28,   0,   200, 0,   250),    # Verde medio
    (28,   30,   0,   170, 0,   252),    # Verde oscuro
    (30,   33,   0,   140, 0,   254),    # Verde muy oscuro
    (33,   35,   0,   120, 0,   255),    # Verde intenso
    
    # Amarillo (35-45 dBZ) - Lluvia moderada
    (35,   37,   200, 255, 0,   255),    # Verde-amarillo
    (37,   40,   255, 255, 0,   255),    # Amarillo brillante
    (40,   42,   255, 230, 0,   255),    # Amarillo
    (42,   45,   255, 200, 0,   255),    # Amarillo oscuro
    
    # Naranja (45-55 dBZ) - Lluvia fuerte
    (45,   47,   255, 170, 0,   255),    # Naranja claro
    (47,   50,   255, 140, 0,   255),    # Naranja
    (50,   52,   255, 100, 0,   255),    # Naranja oscuro
    (52,   55,   255, 60,  0,   255),    # Naranja rojizo
    
    # Rojo (55-70 dBZ) - Lluvia muy fuerte
    (55,   58,   255, 0,   0,   255),    # Rojo brillante
    (58,   60,   230, 0,   0,   255),    # Rojo
    (60,   63,   200, 0,   0,   255),    # Rojo medio
    (63,   65,   170, 0,   0,   255),    # Rojo oscuro
    (65,   68,   140, 0,   0,   255),    # Rojo muy oscuro
    (68,   70,   120, 0,   20,  255),    # Rojo-púrpura
    
    # Magenta/Púrpura (70+ dBZ) - Extremo/Granizo
    (70,   75,   255, 0,   255, 255),    # Magenta brillante
    (75,   80,   200, 0,   200, 255),    # Púrpura
    (80,   85,   255, 150, 255, 255),    # Rosa claro
    (85,   999,  255, 255, 255, 255),    # Blanco (extremo)
]

# Colores para NIEVE (Snow) - Azul claro → Azul → Morado
SNOW_COLORS = [
    (-999, 5,    0,   0,   0,   0),
    (5,    10,   180, 220, 255, 150),
    (10,   15,   140, 190, 255, 180),
    (15,   20,   100, 160, 255, 210),
    (20,   25,   60,  130, 255, 230),
    (25,   30,   80,  80,  220, 245),
    (30,   35,   100, 60,  200, 255),
    (35,   40,   130, 50,  180, 255),
    (40,   50,   160, 40,  160, 255),
    (50,   999,  180, 80,  180, 255),
]

# Colores para MIXTA (Mixed/Sleet) - Gris → Blanco → Rosa
MIXED_COLORS = [
    (-999, 5,    0,   0,   0,   0),
    (5,    10,   180, 180, 200, 140),
    (10,   15,   200, 200, 220, 170),
    (15,   20,   220, 220, 235, 200),
    (20,   25,   240, 240, 250, 220),
    (25,   30,   255, 230, 240, 240),
    (30,   35,   255, 200, 220, 250),
    (35,   45,   255, 170, 200, 255),
    (45,   55,   255, 140, 180, 255),
    (55,   999,  255, 100, 150, 255),
]

# PrecipFlag values
PRECIP_TYPES = {
    0: 'none',
    1: 'rain',       # warm stratiform
    3: 'snow',
    6: 'rain',       # convection (mostrar como lluvia intensa)
    7: 'rain',       # hail (mostrar como lluvia muy intensa)
    10: 'mixed',     # cool stratiform (puede ser mixta)
    91: 'rain',      # tropical stratiform
    96: 'rain',      # tropical convective
}


def get_available_files(product: str = 'reflectivity') -> List[str]:
    """Obtiene lista de archivos MRMS disponibles."""
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
    """Convierte YYYYMMDD-HHMMSS a datetime UTC."""
    return datetime.strptime(ts, '%Y%m%d-%H%M%S').replace(tzinfo=timezone.utc)


def download_mrms_grib(timestamp: str, product: str = 'reflectivity') -> Optional[bytes]:
    """Descarga y descomprime archivo MRMS GRIB2."""
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
    """Lee datos GRIB2 y retorna (data, lats, lons)."""
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


def apply_color_scale(dbz: np.ndarray, scale: list) -> np.ndarray:
    """Aplica escala de colores a datos de reflectividad."""
    height, width = dbz.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    
    for dbz_min, dbz_max, r, g, b, a in scale:
        mask = (dbz >= dbz_min) & (dbz < dbz_max)
        rgba[mask] = [r, g, b, a]
    
    return rgba


def process_radar_frame(refl_data: bytes, flag_data: Optional[bytes] = None) -> Optional[bytes]:
    """
    Procesa frame de radar combinando reflectividad y tipo de precipitación.
    """
    if not HAS_PIL:
        return None
    
    # Leer reflectividad
    result = read_grib_data(refl_data)
    if result is None:
        return None
    
    dbz, lats, lons = result
    
    # Leer tipo de precipitación si está disponible
    precip_type = None
    if flag_data:
        flag_result = read_grib_data(flag_data)
        if flag_result:
            precip_type = flag_result[0]
    
    # Recortar a CONUS
    lat_mask = (lats >= CONUS_BOUNDS['south']) & (lats <= CONUS_BOUNDS['north'])
    lon_mask = (lons >= CONUS_BOUNDS['west']) & (lons <= CONUS_BOUNDS['east'])
    
    lat_idx = np.where(lat_mask)[0]
    lon_idx = np.where(lon_mask)[0]
    
    if len(lat_idx) == 0 or len(lon_idx) == 0:
        return None
    
    dbz = dbz[lat_idx[0]:lat_idx[-1]+1, lon_idx[0]:lon_idx[-1]+1]
    
    if precip_type is not None:
        precip_type = precip_type[lat_idx[0]:lat_idx[-1]+1, lon_idx[0]:lon_idx[-1]+1]
    
    # Crear imagen RGBA
    height, width = dbz.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    
    if precip_type is not None:
        # Aplicar colores según tipo de precipitación
        # Nieve
        snow_mask = (precip_type == 3)
        if np.any(snow_mask):
            snow_rgba = apply_color_scale(dbz, SNOW_COLORS)
            rgba[snow_mask] = snow_rgba[snow_mask]
        
        # Mixta (cool stratiform)
        mixed_mask = (precip_type == 10)
        if np.any(mixed_mask):
            mixed_rgba = apply_color_scale(dbz, MIXED_COLORS)
            rgba[mixed_mask] = mixed_rgba[mixed_mask]
        
        # Lluvia (todo lo demás)
        rain_mask = ~snow_mask & ~mixed_mask & (dbz > 5)
        if np.any(rain_mask):
            rain_rgba = apply_color_scale(dbz, RAIN_COLORS)
            rgba[rain_mask] = rain_rgba[rain_mask]
    else:
        # Sin datos de tipo, usar escala de lluvia para todo
        rgba = apply_color_scale(dbz, RAIN_COLORS)
    
    # Crear imagen
    img = Image.fromarray(rgba, mode='RGBA')
    img = img.resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
    
    # NO aplicar suavizado - mantener nitidez como Baron
    
    buffer = BytesIO()
    img.save(buffer, format='PNG', optimize=True, compress_level=6)
    return buffer.getvalue()


def get_existing_frames() -> set:
    """Obtiene lista de frames ya subidos a Spaces."""
    # Por simplicidad, verificamos localmente o asumimos vacío
    return set()


def fetch_and_process(timestamps: List[str]) -> int:
    """Descarga y procesa múltiples timestamps."""
    success = 0
    precip_flag_success = 0
    
    for ts in timestamps:
        # Descargar reflectividad
        refl_data = download_mrms_grib(ts, 'reflectivity')
        if not refl_data:
            continue
        
        # Intentar descargar tipo de precipitación (opcional)
        flag_data = download_mrms_grib(ts, 'precip_flag')
        if flag_data:
            precip_flag_success += 1
        
        # Procesar
        png_data = process_radar_frame(refl_data, flag_data)
        if not png_data:
            continue
        
        # Convertir timestamp a formato de archivo
        dt = parse_timestamp(ts)
        frame_id = dt.strftime('%Y%m%d_%H%M')
        
        # Subir a Spaces
        if upload_to_spaces(png_data, f'radar/frames/{frame_id}.png', 'image/png'):
            success += 1
            logger.info(f"  ✓ {frame_id}")
    
    if precip_flag_success > 0:
        logger.info(f"PrecipFlag disponible en {precip_flag_success}/{len(timestamps)} frames")
    else:
        logger.info("PrecipFlag no disponible - usando solo reflectividad")
    
    return success


def update_metadata(frames: List[str]):
    """Actualiza metadata del radar."""
    metadata = {
        'product': 'MRMS Composite Reflectivity + PrecipType',
        'frames': sorted(frames)[-FRAMES_TO_KEEP:],  # Últimos N frames
        'frame_count': min(len(frames), FRAMES_TO_KEEP),
        'latest_frame': frames[-1] if frames else None,
        'history_hours': HISTORY_HOURS,
        'bounds': CONUS_BOUNDS,
        'resolution': '1km',
        'update_interval': '2min',
        'updated_at': utcnow().isoformat() + 'Z',
        'legend': {
            'rain': 'Verde → Amarillo → Rojo',
            'snow': 'Azul → Morado',
            'mixed': 'Rosa → Magenta',
        }
    }
    
    upload_to_spaces(metadata, 'radar/metadata.json')


def main():
    parser = argparse.ArgumentParser(description='Borrasca MRMS Radar Fetcher')
    parser.add_argument('--hours', type=int, default=1, help='Horas a descargar')
    parser.add_argument('--full', action='store_true', help='Descargar historial completo')
    args = parser.parse_args()
    
    if args.full:
        args.hours = HISTORY_HOURS
    
    logger.info("=" * 50)
    logger.info("BORRASCA - MRMS Radar Fetcher v2")
    logger.info("=" * 50)
    
    if not HAS_XARRAY or not HAS_PIL:
        logger.error("Faltan dependencias (xarray, PIL)")
        sys.exit(1)
    
    # Obtener archivos disponibles
    available = get_available_files('reflectivity')
    logger.info(f"Archivos disponibles: {len(available)}")
    
    if not available:
        logger.error("No hay archivos disponibles")
        return
    
    # Filtrar por tiempo
    cutoff = utcnow() - timedelta(hours=args.hours)
    to_process = [ts for ts in available if parse_timestamp(ts) >= cutoff]
    
    logger.info(f"Frames a procesar: {len(to_process)}")
    
    if not to_process:
        logger.info("Nada nuevo que procesar")
        return
    
    # Procesar
    success = fetch_and_process(to_process)
    
    # Actualizar metadata
    all_frames = [parse_timestamp(ts).strftime('%Y%m%d_%H%M') for ts in available]
    update_metadata(all_frames)
    
    logger.info("=" * 50)
    logger.info(f"COMPLETADO: {success}/{len(to_process)} frames")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
