#!/usr/bin/env python3
"""
YouTube Analytics Daily Collector - Multi-Channel
===================================================
Recolecta métricas diarias de MÚLTIPLES canales de YouTube y las almacena en SQLite.

Canales configurados:
    - @alberteltiempo (UCL6UGqm6qEmQPa4TMngYENg)
    - @canalmeteotv (UCGE4R_0C46brGIq6T6RpEPg)

Uso:
    python3 youtube_daily_collector.py              # Recolecta datos de ayer
    python3 youtube_daily_collector.py --date 2025-01-15  # Fecha específica
    python3 youtube_daily_collector.py --backfill 30      # Últimos 30 días
    python3 youtube_daily_collector.py --channel UCxxxxx  # Solo un canal específico

Métricas recolectadas:
    - Nivel canal: views, watchTime, subscribers, etc.
    - Nivel video: views, likes, comments, etc. (top 50 videos activos por canal)
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("ERROR: Faltan dependencias.")
    print("Ejecuta: pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# Configuración de rutas
SCRIPT_DIR = Path(__file__).parent.parent
CONFIG_DIR = SCRIPT_DIR / "config"
DATA_DIR = SCRIPT_DIR / "data"
LOGS_DIR = SCRIPT_DIR / "logs"

CREDENTIALS_FILE = CONFIG_DIR / "youtube_credentials.json"
CONFIG_FILE = CONFIG_DIR / "youtube_config.json"
DATABASE_FILE = DATA_DIR / "youtube_analytics.db"

# Canales a monitorear (backup si no existe config file)
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

# Configurar logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / "youtube_collector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class YouTubeAnalyticsCollector:
    """Recolector de métricas de YouTube - Multi-Canal"""
    
    # Métricas disponibles en YouTube Analytics API
    CHANNEL_METRICS = [
        'views',
        'estimatedMinutesWatched',
        'averageViewDuration',
        'subscribersGained',
        'subscribersLost',
        'likes',
        'dislikes',
        'shares',
        'comments',
        'annotationClickThroughRate',
        'annotationCloseRate',
        'cardClickRate',
        'cardTeaserClickRate'
    ]
    
    VIDEO_METRICS = [
        'views',
        'estimatedMinutesWatched',
        'averageViewDuration',
        'averageViewPercentage',
        'likes',
        'dislikes',
        'comments',
        'shares',
        'subscribersGained',
        'subscribersLost'
    ]
    
    def __init__(self):
        self.credentials = None
        self.youtube = None
        self.youtube_analytics = None
        self.channels = []  # Lista de canales a monitorear
        self.current_channel_id = None  # Canal actual siendo procesado
        self.db_conn = None
        self.settings = {}
        
    def initialize(self) -> bool:
        """Inicializa las conexiones a APIs y base de datos"""
        
        # Cargar credenciales
        if not CREDENTIALS_FILE.exists():
            logger.error(f"No se encontró archivo de credenciales: {CREDENTIALS_FILE}")
            logger.error("Ejecuta primero: python3 youtube_auth_setup.py")
            return False
        
        try:
            with open(CREDENTIALS_FILE) as f:
                creds_data = json.load(f)
            
            self.credentials = Credentials(
                token=creds_data.get('token'),
                refresh_token=creds_data['refresh_token'],
                token_uri=creds_data['token_uri'],
                client_id=creds_data['client_id'],
                client_secret=creds_data['client_secret'],
                scopes=creds_data['scopes']
            )
            
            # Refrescar token si es necesario
            if self.credentials.expired or not self.credentials.valid:
                logger.info("Refrescando token de acceso...")
                self.credentials.refresh(Request())
                
                # Guardar el nuevo token
                creds_data['token'] = self.credentials.token
                with open(CREDENTIALS_FILE, 'w') as f:
                    json.dump(creds_data, f, indent=2)
            
            # Inicializar clientes de API
            self.youtube = build('youtube', 'v3', credentials=self.credentials)
            self.youtube_analytics = build('youtubeAnalytics', 'v2', credentials=self.credentials)
            
            # Cargar configuración de canales
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
                self.channels = config.get('channels', DEFAULT_CHANNELS)
                self.settings = config.get('settings', {})
            else:
                self.channels = DEFAULT_CHANNELS
            
            logger.info(f"Canales configurados: {len(self.channels)}")
            for ch in self.channels:
                logger.info(f"  - {ch['name']} ({ch['handle']}): {ch['channel_id']}")
            
            # Inicializar base de datos
            self._init_database()
            
            return True
            
        except Exception as e:
            logger.error(f"Error inicializando: {e}")
            return False
    
    def set_current_channel(self, channel_id: str):
        """Establece el canal actual para las operaciones"""
        self.current_channel_id = channel_id
        for ch in self.channels:
            if ch['channel_id'] == channel_id:
                logger.info(f"Canal activo: {ch['name']} ({ch['handle']})")
                return True
        logger.warning(f"Canal {channel_id} no encontrado en configuración")
        return True  # Permitir canales no configurados
    
    def _init_database(self):
        """Inicializa el esquema de la base de datos SQLite"""
        
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db_conn = sqlite3.connect(DATABASE_FILE)
        cursor = self.db_conn.cursor()
        
        # Tabla de métricas diarias del canal
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_daily (
                date TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                views INTEGER,
                estimated_minutes_watched REAL,
                average_view_duration REAL,
                subscribers_gained INTEGER,
                subscribers_lost INTEGER,
                net_subscribers INTEGER,
                likes INTEGER,
                dislikes INTEGER,
                shares INTEGER,
                comments INTEGER,
                card_click_rate REAL,
                card_teaser_click_rate REAL,
                PRIMARY KEY (date, channel_id)
            )
        ''')
        
        # Tabla de métricas diarias por video
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS video_daily (
                date TEXT NOT NULL,
                video_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                views INTEGER,
                estimated_minutes_watched REAL,
                average_view_duration REAL,
                average_view_percentage REAL,
                likes INTEGER,
                dislikes INTEGER,
                comments INTEGER,
                shares INTEGER,
                subscribers_gained INTEGER,
                subscribers_lost INTEGER,
                PRIMARY KEY (date, video_id)
            )
        ''')
        
        # Tabla de metadatos de videos (se actualiza con cada recolección)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                published_at TEXT,
                duration TEXT,
                category_id TEXT,
                tags TEXT,
                thumbnail_url TEXT,
                total_views INTEGER,
                total_likes INTEGER,
                total_comments INTEGER,
                updated_at TEXT
            )
        ''')
        
        # Tabla de snapshots del canal (estadísticas totales)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_snapshots (
                date TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                total_subscribers INTEGER,
                total_views INTEGER,
                total_videos INTEGER,
                PRIMARY KEY (date, channel_id)
            )
        ''')
        
        # Índices para consultas rápidas
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel_daily_date ON channel_daily(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_video_daily_date ON video_daily(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_video_daily_video ON video_daily(video_id)')
        
        self.db_conn.commit()
        logger.info(f"Base de datos inicializada: {DATABASE_FILE}")
    
    def collect_channel_stats(self, date: str) -> Optional[Dict]:
        """Recolecta estadísticas del canal para una fecha específica"""
        
        try:
            # YouTube Analytics - métricas del día
            response = self.youtube_analytics.reports().query(
                ids=f'channel=={self.current_channel_id}',
                startDate=date,
                endDate=date,
                metrics=','.join(self.CHANNEL_METRICS)
            ).execute()
            
            if not response.get('rows'):
                logger.warning(f"No hay datos de Analytics para {date} - {self.current_channel_id}")
                return None
            
            row = response['rows'][0]
            headers = [h['name'] for h in response['columnHeaders']]
            metrics = dict(zip(headers, row))
            
            # YouTube Data API - estadísticas totales del canal
            channel_response = self.youtube.channels().list(
                part='statistics',
                id=self.current_channel_id
            ).execute()
            
            total_stats = {}
            if channel_response.get('items'):
                stats = channel_response['items'][0]['statistics']
                total_stats = {
                    'total_subscribers': int(stats.get('subscriberCount', 0)),
                    'total_views': int(stats.get('viewCount', 0)),
                    'total_videos': int(stats.get('videoCount', 0))
                }
            
            return {
                'analytics': metrics,
                'totals': total_stats
            }
            
        except HttpError as e:
            logger.error(f"Error API YouTube: {e}")
            return None
    
    def collect_video_stats(self, date: str, max_videos: int = 50) -> List[Dict]:
        """Recolecta estadísticas de los videos más activos"""
        
        try:
            # Primero, obtener los videos con más actividad ese día
            response = self.youtube_analytics.reports().query(
                ids=f'channel=={self.current_channel_id}',
                startDate=date,
                endDate=date,
                metrics='views,estimatedMinutesWatched',
                dimensions='video',
                sort='-views',
                maxResults=max_videos
            ).execute()
            
            if not response.get('rows'):
                logger.warning(f"No hay datos de videos para {date} - {self.current_channel_id}")
                return []
            
            video_ids = [row[0] for row in response['rows']]
            
            # Obtener métricas detalladas de cada video
            video_stats = []
            
            # YouTube Analytics en batch no es posible, consultar uno por uno
            # Pero podemos usar el informe con dimensión video
            detailed_response = self.youtube_analytics.reports().query(
                ids=f'channel=={self.current_channel_id}',
                startDate=date,
                endDate=date,
                metrics=','.join(self.VIDEO_METRICS),
                dimensions='video',
                filters=f'video=={",".join(video_ids)}',
                maxResults=max_videos
            ).execute()
            
            if detailed_response.get('rows'):
                headers = [h['name'] for h in detailed_response['columnHeaders']]
                for row in detailed_response['rows']:
                    metrics = dict(zip(headers, row))
                    video_stats.append(metrics)
            
            # Obtener metadatos de videos (YouTube Data API)
            self._update_video_metadata(video_ids)
            
            return video_stats
            
        except HttpError as e:
            logger.error(f"Error obteniendo stats de videos: {e}")
            return []
    
    def _update_video_metadata(self, video_ids: List[str]):
        """Actualiza los metadatos de los videos"""
        
        try:
            # La API permite hasta 50 IDs por llamada
            for i in range(0, len(video_ids), 50):
                batch_ids = video_ids[i:i+50]
                
                response = self.youtube.videos().list(
                    part='snippet,contentDetails,statistics',
                    id=','.join(batch_ids)
                ).execute()
                
                cursor = self.db_conn.cursor()
                now = datetime.utcnow().isoformat()
                
                for video in response.get('items', []):
                    snippet = video['snippet']
                    stats = video.get('statistics', {})
                    content = video.get('contentDetails', {})
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO videos
                        (video_id, channel_id, title, description, published_at,
                         duration, category_id, tags, thumbnail_url,
                         total_views, total_likes, total_comments, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        video['id'],
                        self.current_channel_id,
                        snippet.get('title'),
                        snippet.get('description', '')[:1000],  # Truncar descripción
                        snippet.get('publishedAt'),
                        content.get('duration'),
                        snippet.get('categoryId'),
                        json.dumps(snippet.get('tags', [])),
                        snippet.get('thumbnails', {}).get('high', {}).get('url'),
                        int(stats.get('viewCount', 0)),
                        int(stats.get('likeCount', 0)),
                        int(stats.get('commentCount', 0)),
                        now
                    ))
                
                self.db_conn.commit()
                
        except HttpError as e:
            logger.error(f"Error actualizando metadatos de videos: {e}")
    
    def save_channel_stats(self, date: str, data: Dict):
        """Guarda las estadísticas del canal en la base de datos"""
        
        cursor = self.db_conn.cursor()
        now = datetime.utcnow().isoformat()
        analytics = data['analytics']
        
        # Calcular net_subscribers
        gained = analytics.get('subscribersGained', 0)
        lost = analytics.get('subscribersLost', 0)
        net = (gained or 0) - (lost or 0)
        
        cursor.execute('''
            INSERT OR REPLACE INTO channel_daily
            (date, channel_id, collected_at, views, estimated_minutes_watched,
             average_view_duration, subscribers_gained, subscribers_lost, net_subscribers,
             likes, dislikes, shares, comments, card_click_rate, card_teaser_click_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date,
            self.current_channel_id,
            now,
            analytics.get('views'),
            analytics.get('estimatedMinutesWatched'),
            analytics.get('averageViewDuration'),
            gained,
            lost,
            net,
            analytics.get('likes'),
            analytics.get('dislikes'),
            analytics.get('shares'),
            analytics.get('comments'),
            analytics.get('cardClickRate'),
            analytics.get('cardTeaserClickRate')
        ))
        
        # Guardar snapshot de totales
        totals = data.get('totals', {})
        if totals:
            cursor.execute('''
                INSERT OR REPLACE INTO channel_snapshots
                (date, channel_id, collected_at, total_subscribers, total_views, total_videos)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                date,
                self.current_channel_id,
                now,
                totals.get('total_subscribers'),
                totals.get('total_views'),
                totals.get('total_videos')
            ))
        
        self.db_conn.commit()
        logger.info(f"Estadísticas del canal guardadas para {date} - {self.current_channel_id}")
    
    def save_video_stats(self, date: str, videos: List[Dict]):
        """Guarda las estadísticas de videos en la base de datos"""
        
        cursor = self.db_conn.cursor()
        now = datetime.utcnow().isoformat()
        
        for video in videos:
            cursor.execute('''
                INSERT OR REPLACE INTO video_daily
                (date, video_id, channel_id, collected_at, views, estimated_minutes_watched,
                 average_view_duration, average_view_percentage, likes, dislikes,
                 comments, shares, subscribers_gained, subscribers_lost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                date,
                video.get('video'),
                self.current_channel_id,
                now,
                video.get('views'),
                video.get('estimatedMinutesWatched'),
                video.get('averageViewDuration'),
                video.get('averageViewPercentage'),
                video.get('likes'),
                video.get('dislikes'),
                video.get('comments'),
                video.get('shares'),
                video.get('subscribersGained'),
                video.get('subscribersLost')
            ))
        
        self.db_conn.commit()
        logger.info(f"Estadísticas de {len(videos)} videos guardadas para {date} - {self.current_channel_id}")
    
    def collect_date(self, date: str) -> bool:
        """Recolecta todas las métricas para una fecha específica (canal actual)"""
        
        logger.info(f"Recolectando datos para: {date} - Canal: {self.current_channel_id}")
        
        # Verificar si ya existe
        cursor = self.db_conn.cursor()
        cursor.execute('SELECT 1 FROM channel_daily WHERE date = ? AND channel_id = ?', 
                      (date, self.current_channel_id))
        if cursor.fetchone():
            logger.info(f"Ya existen datos para {date}, actualizando...")
        
        # Recolectar estadísticas del canal
        channel_data = self.collect_channel_stats(date)
        if channel_data:
            self.save_channel_stats(date, channel_data)
        
        # Recolectar estadísticas de videos
        video_data = self.collect_video_stats(date)
        if video_data:
            self.save_video_stats(date, video_data)
        
        return bool(channel_data or video_data)
    
    def collect_all_channels_date(self, date: str) -> Dict[str, bool]:
        """Recolecta datos de TODOS los canales configurados para una fecha"""
        
        results = {}
        for channel in self.channels:
            channel_id = channel['channel_id']
            self.set_current_channel(channel_id)
            
            try:
                success = self.collect_date(date)
                results[channel_id] = success
            except Exception as e:
                logger.error(f"Error recolectando {channel['name']}: {e}")
                results[channel_id] = False
        
        return results
    
    def backfill(self, days: int, channel_id: str = None):
        """Recolecta datos históricos de los últimos N días"""
        
        if channel_id:
            # Solo un canal específico
            channels_to_process = [ch for ch in self.channels if ch['channel_id'] == channel_id]
            if not channels_to_process:
                channels_to_process = [{'channel_id': channel_id, 'name': 'Unknown', 'handle': channel_id}]
        else:
            # Todos los canales
            channels_to_process = self.channels
        
        logger.info(f"Iniciando backfill de {days} días para {len(channels_to_process)} canal(es)...")
        
        total_collected = 0
        total_failed = 0
        
        for channel in channels_to_process:
            logger.info(f"\n{'='*50}")
            logger.info(f"Procesando: {channel['name']} ({channel['handle']})")
            logger.info(f"{'='*50}")
            
            self.set_current_channel(channel['channel_id'])
            collected = 0
            failed = 0
            
            for i in range(days, 0, -1):
                date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                
                try:
                    if self.collect_date(date):
                        collected += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"Error recolectando {date}: {e}")
                    failed += 1
            
            logger.info(f"Canal {channel['name']}: {collected} días OK, {failed} fallidos")
            total_collected += collected
            total_failed += failed
        
        logger.info(f"\nBackfill completado: {total_collected} total OK, {total_failed} total fallidos")
    
    def close(self):
        """Cierra conexiones"""
        if self.db_conn:
            self.db_conn.close()


def main():
    parser = argparse.ArgumentParser(description='YouTube Analytics Daily Collector - Multi-Channel')
    parser.add_argument('--date', type=str, help='Fecha específica (YYYY-MM-DD)')
    parser.add_argument('--backfill', type=int, help='Recolectar últimos N días')
    parser.add_argument('--channel', type=str, help='Channel ID específico (opcional, si no se especifica procesa todos)')
    args = parser.parse_args()
    
    collector = YouTubeAnalyticsCollector()
    
    try:
        if not collector.initialize():
            sys.exit(1)
        
        if args.backfill:
            # Backfill: puede ser un canal específico o todos
            collector.backfill(args.backfill, args.channel)
        elif args.date:
            # Fecha específica
            if args.channel:
                collector.set_current_channel(args.channel)
                collector.collect_date(args.date)
            else:
                collector.collect_all_channels_date(args.date)
        else:
            # Por defecto, recolectar ayer para TODOS los canales
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            if args.channel:
                collector.set_current_channel(args.channel)
                collector.collect_date(yesterday)
            else:
                collector.collect_all_channels_date(yesterday)
            
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        collector.close()


if __name__ == '__main__':
    main()
