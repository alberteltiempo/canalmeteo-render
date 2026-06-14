#!/usr/bin/env python3
"""
YouTube Analytics Exporter - Multi-Channel
============================================
Exporta los datos de SQLite a JSON para el dashboard.

Canales:
    - @alberteltiempo (UCL6UGqm6qEmQPa4TMngYENg)
    - @canalmeteotv (UCGE4R_0C46brGIq6T6RpEPg)

Uso:
    python3 youtube_exporter.py              # Exporta y sube todo
    python3 youtube_exporter.py --local      # Solo genera JSON localmente
    python3 youtube_exporter.py --days 30    # Últimos 30 días (default)
"""

import os
import sys
import json
import sqlite3
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

# Configuración de rutas
SCRIPT_DIR = Path(__file__).parent.parent
CONFIG_DIR = SCRIPT_DIR / "config"
DATA_DIR = SCRIPT_DIR / "data"
EXPORT_DIR = DATA_DIR / "exports"

DATABASE_FILE = DATA_DIR / "youtube_analytics.db"
CONFIG_FILE = CONFIG_DIR / "youtube_config.json"

# DigitalOcean Spaces config
# Bucket canalmeteo-public en SFO3
SPACES_BUCKET = "canalmeteo-public"
SPACES_REGION = "sfo3"
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"
SPACES_PATH = "analytics/youtube"
SPACES_CDN_URL = f"https://{SPACES_BUCKET}.{SPACES_REGION}.cdn.digitaloceanspaces.com/{SPACES_PATH}"

# Credenciales directas (para uso sin profile configurado)
SPACES_ACCESS_KEY = "DO801YRDAPCE3XTH9N7E"
SPACES_SECRET_KEY = "Y4iXd1+4Cyp8qlFjZPkCnCD6tUcVuPFnslgCAC3ofoI"

# Canales por defecto
DEFAULT_CHANNELS = [
    {
        "channel_id": "UCL6UGqm6qEmQPa4TMngYENg",
        "name": "Albert El Tiempo",
        "handle": "@alberteltiempo"
    },
    {
        "channel_id": "UCGE4R_0C46brGIq6T6RpEPg",
        "name": "Canal Meteo TV",
        "handle": "@canalmeteotv"
    }
]


def now_utc():
    """Retorna la fecha/hora actual en UTC"""
    return datetime.now(timezone.utc).isoformat()


class YouTubeExporter:
    """Exportador de datos de YouTube Analytics - Multi-Canal"""
    
    def __init__(self, db_path: Path = DATABASE_FILE):
        self.db_path = db_path
        self.conn = None
        self.channels = []
        
    def connect(self) -> bool:
        """Conecta a la base de datos y carga configuración"""
        if not self.db_path.exists():
            print(f"ERROR: Base de datos no encontrada: {self.db_path}")
            print("Ejecuta primero: python3 youtube_daily_collector.py --backfill 30")
            return False
        
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        
        # Cargar configuración de canales
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                config = json.load(f)
            self.channels = config.get('channels', DEFAULT_CHANNELS)
        else:
            self.channels = DEFAULT_CHANNELS
        
        return True
    
    def get_channel_info(self, channel_id: str) -> Dict:
        """Obtiene información del canal desde la configuración"""
        for ch in self.channels:
            if ch['channel_id'] == channel_id:
                return ch
        return {'channel_id': channel_id, 'name': 'Unknown', 'handle': channel_id}
    
    def get_available_channels(self) -> List[str]:
        """Obtiene la lista de canales que tienen datos en la BD"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT channel_id FROM channel_daily')
        return [row[0] for row in cursor.fetchall()]
    
    def get_channel_summary(self, channel_id: str, days: int = 30) -> Dict[str, Any]:
        """Genera resumen de un canal específico"""
        
        cursor = self.conn.cursor()
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        channel_info = self.get_channel_info(channel_id)
        
        # Datos diarios
        cursor.execute('''
            SELECT * FROM channel_daily
            WHERE date >= ? AND channel_id = ?
            ORDER BY date DESC
        ''', (start_date, channel_id))
        
        daily_data = [dict(row) for row in cursor.fetchall()]
        
        # Último snapshot
        cursor.execute('''
            SELECT * FROM channel_snapshots
            WHERE channel_id = ?
            ORDER BY date DESC
            LIMIT 1
        ''', (channel_id,))
        row = cursor.fetchone()
        latest_snapshot = dict(row) if row else None
        
        # Calcular totales del período
        cursor.execute('''
            SELECT 
                SUM(views) as total_views,
                SUM(estimated_minutes_watched) as total_watch_time,
                SUM(subscribers_gained) as total_subs_gained,
                SUM(subscribers_lost) as total_subs_lost,
                SUM(net_subscribers) as net_subs,
                SUM(likes) as total_likes,
                SUM(comments) as total_comments,
                SUM(shares) as total_shares,
                AVG(average_view_duration) as avg_view_duration,
                COUNT(*) as days_with_data
            FROM channel_daily
            WHERE date >= ? AND channel_id = ?
        ''', (start_date, channel_id))
        
        period_totals = dict(cursor.fetchone())
        
        # Calcular tendencias (comparar últimos 7 días vs 7 anteriores)
        cursor.execute('''
            SELECT 
                SUM(CASE WHEN date >= date('now', '-7 days') THEN views ELSE 0 END) as recent_views,
                SUM(CASE WHEN date >= date('now', '-14 days') AND date < date('now', '-7 days') THEN views ELSE 0 END) as previous_views,
                SUM(CASE WHEN date >= date('now', '-7 days') THEN net_subscribers ELSE 0 END) as recent_subs,
                SUM(CASE WHEN date >= date('now', '-14 days') AND date < date('now', '-7 days') THEN net_subscribers ELSE 0 END) as previous_subs
            FROM channel_daily
            WHERE channel_id = ?
        ''', (channel_id,))
        
        trends_data = dict(cursor.fetchone())
        
        # Calcular porcentaje de cambio
        def calc_trend(recent, previous):
            if previous and previous > 0:
                return round(((recent - previous) / previous) * 100, 1)
            return None
        
        trends = {
            'views_trend_pct': calc_trend(trends_data['recent_views'], trends_data['previous_views']),
            'subs_trend_pct': calc_trend(trends_data['recent_subs'], trends_data['previous_subs'])
        }
        
        return {
            'channel_id': channel_id,
            'channel_name': channel_info['name'],
            'channel_handle': channel_info['handle'],
            'generated_at': now_utc(),
            'period_days': days,
            'current_stats': latest_snapshot,
            'period_totals': period_totals,
            'trends': trends,
            'daily_data': daily_data
        }
    
    def get_top_videos(self, channel_id: str, days: int = 30, limit: int = 20) -> List[Dict]:
        """Obtiene los videos con mejor rendimiento de un canal"""
        
        cursor = self.conn.cursor()
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT 
                v.video_id,
                v.title,
                v.published_at,
                v.duration,
                v.thumbnail_url,
                v.total_views,
                v.total_likes,
                v.total_comments,
                SUM(vd.views) as period_views,
                SUM(vd.estimated_minutes_watched) as period_watch_time,
                SUM(vd.likes) as period_likes,
                SUM(vd.subscribers_gained) as period_subs_gained,
                AVG(vd.average_view_percentage) as avg_retention,
                COUNT(vd.date) as days_active
            FROM videos v
            LEFT JOIN video_daily vd ON v.video_id = vd.video_id AND vd.date >= ?
            WHERE v.channel_id = ?
            GROUP BY v.video_id
            HAVING period_views > 0
            ORDER BY period_views DESC
            LIMIT ?
        ''', (start_date, channel_id, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def export_all(self, days: int = 30) -> Dict[str, Path]:
        """Exporta todos los datos de todos los canales con datos"""
        
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        exported_files = {}
        
        # Obtener canales con datos en la BD
        available_channels = self.get_available_channels()
        print(f"Canales con datos: {len(available_channels)}")
        
        all_channels_data = []
        
        # Procesar cada canal que tiene datos
        for channel_id in available_channels:
            channel_info = self.get_channel_info(channel_id)
            print(f"\nExportando: {channel_info['name']} ({channel_info['handle']})...")
            
            # Resumen del canal
            channel_summary = self.get_channel_summary(channel_id, days)
            all_channels_data.append(channel_summary)
            
            # Archivo individual del canal
            safe_handle = channel_info['handle'].replace('@', '')
            channel_file = EXPORT_DIR / f"youtube_{safe_handle}_summary.json"
            with open(channel_file, 'w', encoding='utf-8') as f:
                json.dump(channel_summary, f, indent=2, ensure_ascii=False)
            exported_files[f"{safe_handle}_summary"] = channel_file
            
            # Top videos del canal
            top_videos = self.get_top_videos(channel_id, days)
            videos_data = {
                'channel_id': channel_id,
                'channel_name': channel_info['name'],
                'channel_handle': channel_info['handle'],
                'generated_at': now_utc(),
                'period_days': days,
                'videos': top_videos
            }
            
            videos_file = EXPORT_DIR / f"youtube_{safe_handle}_videos.json"
            with open(videos_file, 'w', encoding='utf-8') as f:
                json.dump(videos_data, f, indent=2, ensure_ascii=False)
            exported_files[f"{safe_handle}_videos"] = videos_file
        
        # Archivo combinado para el dashboard
        print("\nGenerando archivo combinado para dashboard...")
        
        dashboard_data = {
            'generated_at': now_utc(),
            'period_days': days,
            'channels': []
        }
        
        for ch_data in all_channels_data:
            top_videos = self.get_top_videos(ch_data['channel_id'], days, 10)
            
            dashboard_data['channels'].append({
                'channel_id': ch_data['channel_id'],
                'channel_name': ch_data['channel_name'],
                'channel_handle': ch_data['channel_handle'],
                'current': ch_data.get('current_stats'),
                'period_totals': ch_data.get('period_totals'),
                'trends': ch_data.get('trends'),
                'top_videos': top_videos,
                'daily_views': [
                    {'date': d['date'], 'views': d['views'], 'watch_time': d['estimated_minutes_watched']}
                    for d in ch_data.get('daily_data', [])
                ],
                'daily_subscribers': [
                    {'date': d['date'], 'gained': d['subscribers_gained'], 'lost': d['subscribers_lost'], 'net': d['net_subscribers']}
                    for d in ch_data.get('daily_data', [])
                ]
            })
        
        dashboard_file = EXPORT_DIR / "youtube_dashboard.json"
        with open(dashboard_file, 'w', encoding='utf-8') as f:
            json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
        exported_files['dashboard'] = dashboard_file
        
        print(f"\nArchivos exportados en: {EXPORT_DIR}")
        for name, path in exported_files.items():
            print(f"  - {name}: {path.name}")
        
        return exported_files
    
    def upload_to_spaces(self, files: Dict[str, Path]) -> bool:
        """Sube los archivos a DigitalOcean Spaces usando AWS CLI con credenciales directas"""
        
        print("\nSubiendo a DigitalOcean Spaces...")
        print(f"  Bucket: {SPACES_BUCKET}")
        print(f"  Path: {SPACES_PATH}")
        
        # Configurar variables de entorno para AWS CLI
        env = os.environ.copy()
        env['AWS_ACCESS_KEY_ID'] = SPACES_ACCESS_KEY
        env['AWS_SECRET_ACCESS_KEY'] = SPACES_SECRET_KEY
        
        # Verificar acceso
        cmd_test = ['aws', 's3', 'ls', f's3://{SPACES_BUCKET}', 
                   '--endpoint-url', SPACES_ENDPOINT]
        
        result = subprocess.run(cmd_test, capture_output=True, text=True, env=env)
        
        if result.returncode != 0:
            print(f"ERROR: No se puede acceder a Spaces.")
            print(f"Stderr: {result.stderr}")
            return False
        
        # Subir cada archivo
        success = True
        for name, local_path in files.items():
            remote_path = f"s3://{SPACES_BUCKET}/{SPACES_PATH}/{local_path.name}"
            
            cmd = [
                'aws', 's3', 'cp',
                str(local_path),
                remote_path,
                '--endpoint-url', SPACES_ENDPOINT,
                '--acl', 'public-read',
                '--content-type', 'application/json'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            
            if result.returncode == 0:
                print(f"  ✓ {local_path.name}")
            else:
                print(f"  ✗ {local_path.name}: {result.stderr}")
                success = False
        
        if success:
            print(f"\nArchivos disponibles en:")
            for name, local_path in files.items():
                print(f"  {SPACES_CDN_URL}/{local_path.name}")
        
        return success
    
    def close(self):
        """Cierra la conexión"""
        if self.conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(description='YouTube Analytics Exporter')
    parser.add_argument('--days', type=int, default=30, help='Días de datos a exportar (default: 30)')
    parser.add_argument('--local', action='store_true', help='Solo exportar localmente, no subir a Spaces')
    args = parser.parse_args()
    
    exporter = YouTubeExporter()
    
    try:
        if not exporter.connect():
            sys.exit(1)
        
        # Exportar datos
        files = exporter.export_all(args.days)
        
        # Subir a Spaces (si no es --local)
        if not args.local:
            exporter.upload_to_spaces(files)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        exporter.close()


if __name__ == '__main__':
    main()
