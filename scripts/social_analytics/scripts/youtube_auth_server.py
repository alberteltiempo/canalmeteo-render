#!/usr/bin/env python3
"""
YouTube OAuth2 Authentication Setup - Server Version
=====================================================
Versión para servidores SIN navegador.
Te muestra la URL para que la abras en tu computadora local.

Uso:
    python3 youtube_auth_server.py
"""

import os
import sys
import json
from pathlib import Path

try:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    print("ERROR: Faltan dependencias.")
    print("Ejecuta: pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# Configuración de rutas
SCRIPT_DIR = Path(__file__).parent.parent
CONFIG_DIR = SCRIPT_DIR / "config"
CREDENTIALS_FILE = CONFIG_DIR / "youtube_credentials.json"
CLIENT_SECRETS_FILE = CONFIG_DIR / "client_secrets.json"

# Scopes necesarios
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/yt-analytics.readonly',
    'https://www.googleapis.com/auth/yt-analytics-monetary.readonly'
]

# Redirect URI para flujo manual
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'


def authenticate():
    """Ejecuta el flujo OAuth2 manual (sin navegador)"""
    
    print("=" * 60)
    print("YouTube OAuth2 Authentication (Server Mode)")
    print("=" * 60)
    print()
    
    if not CLIENT_SECRETS_FILE.exists():
        print(f"ERROR: No se encontró {CLIENT_SECRETS_FILE}")
        return False
    
    # Crear flujo OAuth
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    # Generar URL de autorización
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    
    print("PASO 1: Abre esta URL en tu navegador (en tu computadora):")
    print()
    print("-" * 60)
    print(auth_url)
    print("-" * 60)
    print()
    print("PASO 2: Inicia sesión con tu cuenta de Google")
    print("        (la que administra los canales de YouTube)")
    print()
    print("PASO 3: Autoriza la aplicación")
    print()
    print("PASO 4: Google te dará un CÓDIGO. Cópialo y pégalo aquí:")
    print()
    
    # Esperar el código del usuario
    auth_code = input("Código de autorización: ").strip()
    
    if not auth_code:
        print("ERROR: No ingresaste ningún código")
        return False
    
    print()
    print("Intercambiando código por tokens...")
    
    try:
        # Intercambiar código por tokens
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        
        # Guardar credenciales
        creds_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': list(credentials.scopes)
        }
        
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CREDENTIALS_FILE, 'w') as f:
            json.dump(creds_data, f, indent=2)
        
        print()
        print("=" * 60)
        print("✓ AUTENTICACIÓN EXITOSA")
        print("=" * 60)
        print()
        print(f"Credenciales guardadas en: {CREDENTIALS_FILE}")
        print()
        
        # Verificar acceso
        return verify_access(credentials)
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def verify_access(credentials):
    """Verifica que las credenciales funcionen"""
    
    print("Verificando acceso a las APIs...")
    print()
    
    try:
        # Probar YouTube Data API
        youtube = build('youtube', 'v3', credentials=credentials)
        
        request = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        )
        response = request.execute()
        
        if response.get('items'):
            channel = response['items'][0]
            print("✓ YouTube Data API: OK")
            print(f"  Canal principal: {channel['snippet']['title']}")
            print(f"  ID: {channel['id']}")
            print(f"  Suscriptores: {channel['statistics'].get('subscriberCount', 'Oculto')}")
        
        # Listar todos los canales accesibles
        print()
        print("Canales accesibles con esta cuenta:")
        
        # Obtener canales del usuario
        request = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        )
        response = request.execute()
        
        for ch in response.get('items', []):
            print(f"  - {ch['snippet']['title']} ({ch['id']})")
        
        # Probar YouTube Analytics API
        print()
        youtube_analytics = build('youtubeAnalytics', 'v2', credentials=credentials)
        
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        request = youtube_analytics.reports().query(
            ids='channel==MINE',
            startDate=start_date,
            endDate=end_date,
            metrics='views,estimatedMinutesWatched,subscribersGained'
        )
        response = request.execute()
        
        print("✓ YouTube Analytics API: OK")
        if response.get('rows'):
            row = response['rows'][0]
            print(f"  Últimos 7 días (canal principal):")
            print(f"    Vistas: {row[0]:,}")
            print(f"    Minutos vistos: {row[1]:,.0f}")
            print(f"    Suscriptores ganados: {row[2]:,}")
        
        print()
        print("=" * 60)
        print("✓ TODO LISTO")
        print("=" * 60)
        print()
        print("Ahora puedes ejecutar:")
        print("  python3 youtube_daily_collector.py --backfill 7")
        print()
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if CREDENTIALS_FILE.exists():
        print(f"Ya existen credenciales en: {CREDENTIALS_FILE}")
        response = input("¿Regenerar? (s/N): ").strip().lower()
        if response != 's':
            print("Verificando credenciales existentes...")
            with open(CREDENTIALS_FILE) as f:
                creds_data = json.load(f)
            credentials = Credentials(
                token=creds_data.get('token'),
                refresh_token=creds_data['refresh_token'],
                token_uri=creds_data['token_uri'],
                client_id=creds_data['client_id'],
                client_secret=creds_data['client_secret'],
                scopes=creds_data.get('scopes', SCOPES)
            )
            verify_access(credentials)
            return
    
    authenticate()


if __name__ == '__main__':
    main()
