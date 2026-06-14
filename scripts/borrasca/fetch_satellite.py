#!/usr/bin/env python3
"""
Borrasca - GOES Satellite Downloader (STAR NESDIS)
==================================================
Descarga imágenes de satélite GOES desde NOAA STAR NESDIS.

Productos:
- GEOCOLOR: Visible día / IR noche combinado
- Band 13: IR limpio (10.3 µm)
- Band 08: Vapor de agua superior (6.2 µm)

Uso:
    python fetch_satellite.py                    # Todos los productos
    python fetch_satellite.py visible            # Solo visible/geocolor
    python fetch_satellite.py --hours 3          # Solo últimas 3 horas

Cron (cada 5 minutos):
    */5 * * * * /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/borrasca/fetch_satellite.py
"""

import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    setup_logger, upload_to_spaces, get_spaces_url,
    DATA_DIR, utcnow
)

logger = setup_logger('satellite', 'satellite.log')

# =============================================
# CONFIGURACIÓN
# =============================================

# URLs directas de STAR NESDIS
# Formato: https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/GEOCOLOR/1250x750.jpg
# Las imágenes se actualizan cada 5 minutos

PRODUCTS = {
    'visible': {
        'name': 'GeoColor',
        'url_pattern': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/GEOCOLOR/{size}.jpg',
        'description': 'Visible día / IR noche combinado',
    },
    'infrared': {
        'name': 'Infrarrojo (Band 13)',
        'url_pattern': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/13/{size}.jpg',
        'description': 'IR limpio 10.3 µm',
    },
    'vapor': {
        'name': 'Vapor de Agua (Band 08)',
        'url_pattern': 'https://cdn.star.nesdis.noaa.gov/GOES19/ABI/CONUS/08/{size}.jpg',
        'description': 'Vapor de agua superior 6.2 µm',
    },
}

# Tamaños disponibles: 625x375, 1250x750, 2500x1500, 5000x3000
IMAGE_SIZE = '2500x1500'

HISTORY_HOURS = 6
FRAME_INTERVAL = 5  # minutos

CONUS_BOUNDS = {
    'west': -125,
    'east': -65,
    'south': 24,
    'north': 50
}


def download_current_image(product_key: str) -> Optional[bytes]:
    """Descarga la imagen actual de un producto."""
    config = PRODUCTS.get(product_key)
    if not config:
        return None
    
    url = config['url_pattern'].format(size=IMAGE_SIZE)
    
    try:
        # Añadir timestamp para evitar cache
        response = requests.get(f"{url}?t={int(datetime.now().timestamp())}", timeout=60)
        response.raise_for_status()
        logger.info(f"Descargado: {product_key} ({len(response.content)/1024:.1f} KB)")
        return response.content
    except Exception as e:
        logger.error(f"Error descargando {product_key}: {e}")
        return None


def fetch_product(product_key: str, hours: int = 6) -> bool:
    """
    Descarga un producto de satélite.
    Como STAR solo proporciona la imagen actual, guardamos cada descarga
    con timestamp para construir el historial.
    """
    config = PRODUCTS.get(product_key)
    if not config:
        logger.error(f"Producto no encontrado: {product_key}")
        return False
    
    logger.info(f"\n{'='*50}")
    logger.info(f"Procesando: {config['name']}")
    logger.info(f"{'='*50}")
    
    # Descargar imagen actual
    img_data = download_current_image(product_key)
    if not img_data:
        return False
    
    # Generar frame_id basado en tiempo actual (redondeado a 5 min)
    now = utcnow()
    # Redondear a múltiplo de 5 minutos
    minutes = (now.minute // FRAME_INTERVAL) * FRAME_INTERVAL
    frame_time = now.replace(minute=minutes, second=0, microsecond=0)
    frame_id = frame_time.strftime('%Y%m%d_%H%M')
    
    # Subir frame con timestamp
    remote_frame = f"satellite/{product_key}/frames/{frame_id}.jpg"
    upload_to_spaces(img_data, remote_frame, 'image/jpeg', 'max-age=86400')
    
    # Subir como current
    remote_current = f"satellite/{product_key}/current.jpg"
    upload_to_spaces(img_data, remote_current, 'image/jpeg', 'max-age=60')
    
    # Construir lista de frames (últimas N horas)
    frames = []
    for i in range(int(hours * 60 / FRAME_INTERVAL)):
        t = frame_time - timedelta(minutes=i * FRAME_INTERVAL)
        frames.append(t.strftime('%Y%m%d_%H%M'))
    frames.reverse()  # Orden cronológico
    
    # Metadata
    metadata = {
        'product': product_key,
        'name': config['name'],
        'description': config['description'],
        'frames': frames,
        'frame_count': len(frames),
        'updated_at': utcnow().isoformat() + 'Z',
        'bounds': CONUS_BOUNDS,
        'latest_frame': frame_id,
        'frame_interval_minutes': FRAME_INTERVAL,
    }
    
    upload_to_spaces(metadata, f"satellite/{product_key}/metadata.json")
    
    logger.info(f"✅ {product_key}: frame {frame_id} guardado")
    return True


def update_global_metadata():
    """Actualiza el metadata global de satélite."""
    metadata = {
        'updated_at': utcnow().isoformat() + 'Z',
        'products': {
            key: {
                'name': config['name'],
                'description': config['description'],
            }
            for key, config in PRODUCTS.items()
        },
        'bounds': CONUS_BOUNDS,
        'source': 'NOAA STAR NESDIS',
    }
    upload_to_spaces(metadata, "satellite/metadata.json")


def main():
    parser = argparse.ArgumentParser(description='Borrasca GOES Satellite Downloader')
    parser.add_argument('products', nargs='*', default=list(PRODUCTS.keys()))
    parser.add_argument('--hours', type=int, default=HISTORY_HOURS,
                        help=f'Horas de historial (default: {HISTORY_HOURS})')
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("BORRASCA - GOES Satellite Downloader")
    logger.info("=" * 60)
    
    success = 0
    for product in args.products:
        if product in PRODUCTS:
            if fetch_product(product, args.hours):
                success += 1
    
    update_global_metadata()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETADO: {success}/{len(args.products)} productos")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
