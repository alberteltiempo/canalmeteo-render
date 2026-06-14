#!/usr/bin/env python3
"""
YouTube OAuth2 Authentication Setup
====================================
Este script se ejecuta UNA SOLA VEZ para obtener el refresh_token.
Después de ejecutarlo, las credenciales se guardan y el cron las usa automáticamente.

Uso:
    python3 youtube_auth_setup.py

Requisitos:
    pip install google-auth-oauthlib google-api-python-client
"""

import os
import sys
import json
from pathlib import Path

# Intentar importar las librerías necesarias
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
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

# Scopes necesarios para YouTube Analytics
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/yt-analytics.readonly',
    'https://www.googleapis.com/auth/yt-analytics-monetary.readonly'
]


def check_client_secrets():
    """Verifica que exista el archivo client_secrets.json"""
    if not CLIENT_SECRETS_FILE.exists():
        print("=" * 60)
        print("ERROR: No se encontró client_secrets.json")
        print("=" * 60)
        print()
        print("Pasos para obtenerlo:")
        print()
        print("1. Ve a https://console.cloud.google.com/")
        print("2. Crea un proyecto o selecciona uno existente")
        print("3. Ve a 'APIs & Services' > 'Library'")
        print("4. Habilita 'YouTube Data API v3' y 'YouTube Analytics API'")
        print("5. Ve a 'APIs & Services' > 'OAuth consent screen'")
        print("   - Configura como 'External'")
        print("   - Agrega tu email como 'Test user'")
        print("6. Ve a 'APIs & Services' > 'Credentials'")
        print("7. Click '+ Create Credentials' > 'OAuth client ID'")
        print("8. Selecciona 'Desktop app'")
        print("9. Descarga el JSON y guárdalo como:")
        print(f"   {CLIENT_SECRETS_FILE}")
        print()
        return False
    return True


def authenticate():
    """Ejecuta el flujo OAuth2 y guarda las credenciales"""
    
    print("=" * 60)
    print("YouTube OAuth2 Authentication")
    print("=" * 60)
    print()
    
    if not check_client_secrets():
        return False
    
    # Leer client_secrets para mostrar info
    with open(CLIENT_SECRETS_FILE) as f:
        secrets = json.load(f)
    
    # Puede ser "installed" o "web"
    client_type = "installed" if "installed" in secrets else "web"
    client_id = secrets[client_type]["client_id"]
    
    print(f"Client ID: {client_id[:20]}...")
    print(f"Scopes solicitados:")
    for scope in SCOPES:
        print(f"  - {scope.split('/')[-1]}")
    print()
    
    # Ejecutar flujo OAuth
    print("Abriendo navegador para autenticación...")
    print("(Si no se abre, copia la URL que aparece)")
    print()
    
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES
    )
    
    # Esto abre el navegador y espera la autorización
    credentials = flow.run_local_server(
        port=8080,
        prompt='consent',
        access_type='offline'
    )
    
    # Guardar credenciales
    creds_data = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    with open(CREDENTIALS_FILE, 'w') as f:
        json.dump(creds_data, f, indent=2)
    
    print()
    print("=" * 60)
    print("✓ AUTENTICACIÓN EXITOSA")
    print("=" * 60)
    print()
    print(f"Credenciales guardadas en: {CREDENTIALS_FILE}")
    print()
    print("Datos importantes:")
    print(f"  Refresh Token: {credentials.refresh_token[:20]}...")
    print(f"  (Este token NO expira, guárdalo como backup)")
    print()
    
    # Verificar acceso
    print("Verificando acceso a la API...")
    return verify_access(credentials)


def verify_access(credentials):
    """Verifica que las credenciales funcionen correctamente"""
    
    try:
        # Probar YouTube Data API
        youtube = build('youtube', 'v3', credentials=credentials)
        
        # Obtener info del canal autenticado
        request = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        )
        response = request.execute()
        
        if response.get('items'):
            channel = response['items'][0]
            print()
            print("✓ YouTube Data API: OK")
            print(f"  Canal: {channel['snippet']['title']}")
            print(f"  ID: {channel['id']}")
            print(f"  Suscriptores: {channel['statistics'].get('subscriberCount', 'Oculto')}")
            print(f"  Videos: {channel['statistics']['videoCount']}")
            print(f"  Vistas totales: {channel['statistics']['viewCount']}")
            
            # Guardar channel_id en config
            config_file = CONFIG_DIR / "youtube_config.json"
            config = {
                'channel_id': channel['id'],
                'channel_name': channel['snippet']['title']
            }
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            print()
            print(f"  Config guardada en: {config_file}")
        
        # Probar YouTube Analytics API
        youtube_analytics = build('youtubeAnalytics', 'v2', credentials=credentials)
        
        # Consulta simple de los últimos 7 días
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
        
        print()
        print("✓ YouTube Analytics API: OK")
        if response.get('rows'):
            row = response['rows'][0]
            print(f"  Últimos 7 días:")
            print(f"    Vistas: {row[0]:,}")
            print(f"    Minutos vistos: {row[1]:,.0f}")
            print(f"    Suscriptores ganados: {row[2]:,}")
        
        print()
        print("=" * 60)
        print("✓ TODO LISTO - Puedes ejecutar el script de recolección")
        print("=" * 60)
        return True
        
    except Exception as e:
        print()
        print(f"✗ Error verificando acceso: {e}")
        return False


def main():
    # Asegurar que existe el directorio config
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Si ya existen credenciales, preguntar si regenerar
    if CREDENTIALS_FILE.exists():
        print(f"Ya existen credenciales en: {CREDENTIALS_FILE}")
        response = input("¿Regenerar? (s/N): ").strip().lower()
        if response != 's':
            print("Verificando credenciales existentes...")
            with open(CREDENTIALS_FILE) as f:
                creds_data = json.load(f)
            credentials = Credentials(
                token=creds_data['token'],
                refresh_token=creds_data['refresh_token'],
                token_uri=creds_data['token_uri'],
                client_id=creds_data['client_id'],
                client_secret=creds_data['client_secret'],
                scopes=creds_data['scopes']
            )
            verify_access(credentials)
            return
    
    authenticate()


if __name__ == '__main__':
    main()
