#!/usr/bin/env python3
"""
Borrasca - Cleanup Script
=========================
Limpia datos antiguos (>24h) tanto localmente como en DigitalOcean Spaces.

Uso:
    python cleanup.py                  # Limpiar todo (local + Spaces)
    python cleanup.py --local          # Solo local
    python cleanup.py --spaces         # Solo Spaces
    python cleanup.py --hours 48       # Mantener últimas 48h (default: 24)
    python cleanup.py --dry-run        # Simular sin borrar

Cron (cada 6 horas):
    0 */6 * * * python cleanup.py >> /var/log/borrasca/cleanup.log 2>&1
"""

import sys
import os
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).parent))
from config import setup_logger, DATA_DIR, utcnow, SPACES_CONFIG, get_s3_client, SPACES_BASE_PATH

logger = setup_logger('cleanup', 'cleanup.log')

# =============================================
# CONFIGURACIÓN
# =============================================

# Productos y sus políticas de retención (horas)
RETENTION_POLICIES = {
    'gfs': 24,           # Mantener última corrida + 1 anterior
    'gfs-global': 24,
    'hrrr': 24,          # Mantener últimas 24h de corridas
    'ndfd': 24,
    'radar': 12,         # Radar más reciente, 12h suficiente
    'satellite': 12,     # Satélite reciente
    'alerts': 6,         # Alertas muy recientes
}

# Patrones de carpetas con fecha (YYYYMMDD/HH)
DATE_FOLDER_PRODUCTS = ['gfs', 'gfs-global', 'hrrr', 'ndfd']

# Patrones de archivos con timestamp
TIMESTAMP_FILE_PRODUCTS = ['radar', 'satellite']


def get_spaces_client():
    """Obtiene cliente de DigitalOcean Spaces desde config centralizado."""
    client = get_s3_client()
    if client is None:
        logger.error("No se pudo obtener cliente de Spaces - verifica credenciales en /opt/canalmeteo/.env")
    return client


def parse_date_from_path(path: str) -> datetime:
    """
    Extrae fecha de una ruta tipo:
    - gfs/20260109/12/... -> 2026-01-09 12:00
    - radar/frames/20260109_1430.png -> 2026-01-09 14:30
    """
    import re
    
    # Patrón YYYYMMDD/HH
    match = re.search(r'(\d{8})/(\d{2})/', path)
    if match:
        date_str = match.group(1)
        hour_str = match.group(2)
        try:
            return datetime.strptime(f"{date_str}{hour_str}", '%Y%m%d%H').replace(tzinfo=timezone.utc)
        except:
            pass
    
    # Patrón YYYYMMDD_HHMM en nombre de archivo
    match = re.search(r'(\d{8})_(\d{4})', path)
    if match:
        date_str = match.group(1)
        time_str = match.group(2)
        try:
            return datetime.strptime(f"{date_str}{time_str}", '%Y%m%d%H%M').replace(tzinfo=timezone.utc)
        except:
            pass
    
    # Patrón YYYYMMDD solo
    match = re.search(r'(\d{8})', path)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d').replace(tzinfo=timezone.utc)
        except:
            pass
    
    return None


def cleanup_spaces(hours: int = 24, dry_run: bool = False) -> dict:
    """Limpia archivos antiguos de DigitalOcean Spaces."""
    client = get_spaces_client()
    if not client:
        return {'error': 'No se pudo conectar a Spaces'}
    
    bucket = SPACES_CONFIG['bucket']
    prefix = SPACES_BASE_PATH  # 'borrasca'
    cutoff = utcnow() - timedelta(hours=hours)
    
    stats = {
        'scanned': 0,
        'deleted': 0,
        'bytes_freed': 0,
        'errors': 0,
        'by_product': {}
    }
    
    logger.info(f"Limpiando Spaces: archivos anteriores a {cutoff.isoformat()}")
    
    # Listar todos los objetos
    paginator = client.get_paginator('list_objects_v2')
    
    for product, retention in RETENTION_POLICIES.items():
        product_cutoff = utcnow() - timedelta(hours=retention)
        objects_to_delete = []
        product_bytes = 0
        
        try:
            # Usar prefijo completo: borrasca/gfs/, borrasca/radar/, etc.
            full_prefix = f'{prefix}/{product}/'
            for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
                for obj in page.get('Contents', []):
                    stats['scanned'] += 1
                    key = obj['Key']
                    
                    # Determinar fecha del archivo
                    file_date = parse_date_from_path(key)
                    
                    if file_date and file_date < product_cutoff:
                        objects_to_delete.append({'Key': key})
                        product_bytes += obj.get('Size', 0)
                        
                        if len(objects_to_delete) >= 1000:
                            # Borrar en lotes de 1000 (límite de S3)
                            if not dry_run:
                                client.delete_objects(
                                    Bucket=bucket,
                                    Delete={'Objects': objects_to_delete}
                                )
                            stats['deleted'] += len(objects_to_delete)
                            objects_to_delete = []
            
            # Borrar resto
            if objects_to_delete:
                if not dry_run:
                    client.delete_objects(
                        Bucket=bucket,
                        Delete={'Objects': objects_to_delete}
                    )
                stats['deleted'] += len(objects_to_delete)
            
            stats['bytes_freed'] += product_bytes
            stats['by_product'][product] = {
                'deleted': len(objects_to_delete),
                'bytes': product_bytes
            }
            
            if product_bytes > 0:
                logger.info(f"  {product}: {len(objects_to_delete)} archivos, {product_bytes/1024/1024:.1f} MB")
                
        except Exception as e:
            logger.error(f"Error limpiando {product}: {e}")
            stats['errors'] += 1
    
    return stats


def cleanup_local(hours: int = 24, dry_run: bool = False) -> dict:
    """Limpia archivos antiguos del sistema local."""
    stats = {
        'scanned': 0,
        'deleted': 0,
        'bytes_freed': 0,
        'errors': 0,
    }
    
    cutoff = utcnow() - timedelta(hours=hours)
    
    logger.info(f"Limpiando local: archivos anteriores a {cutoff.isoformat()}")
    
    # Limpiar carpeta de datos
    if DATA_DIR.exists():
        for product_dir in DATA_DIR.iterdir():
            if not product_dir.is_dir():
                continue
            
            product = product_dir.name
            retention = RETENTION_POLICIES.get(product, hours)
            product_cutoff = utcnow() - timedelta(hours=retention)
            
            # Buscar carpetas con fecha
            for item in product_dir.rglob('*'):
                stats['scanned'] += 1
                
                if item.is_file():
                    file_date = parse_date_from_path(str(item))
                    
                    if file_date and file_date < product_cutoff:
                        try:
                            size = item.stat().st_size
                            if not dry_run:
                                item.unlink()
                            stats['deleted'] += 1
                            stats['bytes_freed'] += size
                        except Exception as e:
                            logger.error(f"Error borrando {item}: {e}")
                            stats['errors'] += 1
    
    # Limpiar carpetas vacías
    if not dry_run and DATA_DIR.exists():
        for product_dir in DATA_DIR.iterdir():
            if product_dir.is_dir():
                cleanup_empty_dirs(product_dir)
    
    return stats


def cleanup_empty_dirs(path: Path):
    """Elimina directorios vacíos recursivamente."""
    for item in path.iterdir():
        if item.is_dir():
            cleanup_empty_dirs(item)
            try:
                item.rmdir()  # Solo funciona si está vacío
            except OSError:
                pass  # No está vacío


def cleanup_logs(days: int = 7, dry_run: bool = False) -> int:
    """Limpia logs antiguos."""
    log_dir = Path(__file__).parent / 'logs'
    if not log_dir.exists():
        return 0
    
    cutoff = utcnow() - timedelta(days=days)
    deleted = 0
    
    for log_file in log_dir.glob('*.log.*'):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                if not dry_run:
                    log_file.unlink()
                deleted += 1
        except:
            pass
    
    return deleted


def format_bytes(bytes_val: int) -> str:
    """Formatea bytes a unidad legible."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def main():
    parser = argparse.ArgumentParser(description='Borrasca Cleanup')
    parser.add_argument('--local', action='store_true', help='Solo limpiar local')
    parser.add_argument('--spaces', action='store_true', help='Solo limpiar Spaces')
    parser.add_argument('--hours', type=int, default=24, help='Horas a mantener (default: 24)')
    parser.add_argument('--dry-run', action='store_true', help='Simular sin borrar')
    parser.add_argument('--logs', action='store_true', help='También limpiar logs antiguos')
    args = parser.parse_args()
    
    # Si no se especifica, limpiar ambos
    clean_local = args.local or (not args.local and not args.spaces)
    clean_spaces = args.spaces or (not args.local and not args.spaces)
    
    logger.info("=" * 60)
    logger.info("BORRASCA - Cleanup")
    logger.info("=" * 60)
    logger.info(f"Retención: {args.hours} horas")
    logger.info(f"Modo: {'DRY-RUN (simulación)' if args.dry_run else 'REAL'}")
    logger.info(f"Local: {'Sí' if clean_local else 'No'}")
    logger.info(f"Spaces: {'Sí' if clean_spaces else 'No'}")
    
    total_deleted = 0
    total_bytes = 0
    
    # Limpiar local
    if clean_local:
        logger.info("\n--- Limpieza Local ---")
        stats = cleanup_local(args.hours, args.dry_run)
        logger.info(f"Local: {stats['deleted']} archivos, {format_bytes(stats['bytes_freed'])}")
        total_deleted += stats['deleted']
        total_bytes += stats['bytes_freed']
    
    # Limpiar Spaces
    if clean_spaces:
        logger.info("\n--- Limpieza Spaces ---")
        stats = cleanup_spaces(args.hours, args.dry_run)
        if 'error' not in stats:
            logger.info(f"Spaces: {stats['deleted']} archivos, {format_bytes(stats['bytes_freed'])}")
            total_deleted += stats['deleted']
            total_bytes += stats['bytes_freed']
        else:
            logger.error(f"Spaces: {stats['error']}")
    
    # Limpiar logs
    if args.logs:
        logger.info("\n--- Limpieza Logs ---")
        deleted_logs = cleanup_logs(7, args.dry_run)
        logger.info(f"Logs: {deleted_logs} archivos eliminados")
    
    logger.info("\n" + "=" * 60)
    logger.info(f"TOTAL: {total_deleted} archivos, {format_bytes(total_bytes)} liberados")
    if args.dry_run:
        logger.info("(Simulación - nada fue borrado realmente)")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
