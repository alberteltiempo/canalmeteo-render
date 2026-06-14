#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
TORNADO WARNING ALERT SYSTEM - Canal Meteo TV
===============================================================================
Detecta Tornado Warnings activos del NWS, genera mapa, y envía notificaciones
por correo electrónico y SMS.

Ubicación sugerida: /opt/canalmeteo/scripts/tornado_warning.py
Entorno: /opt/canalmeteo/env/

Uso:
    python3 tornado_warning.py              # Ejecutar una vez
    python3 tornado_warning.py --daemon     # Loop continuo (cada 60 seg)
    python3 tornado_warning.py --test       # Modo test (umbral bajo)

Cron (cada minuto - los tornados son urgentes):
    * * * * * /opt/canalmeteo/env/bin/python3 /opt/canalmeteo/scripts/tornado_warning.py >> /var/log/canalmeteo/tornado.log 2>&1

Requisitos:
    pip install requests python-dotenv paramiko folium pillow twilio sendgrid

===============================================================================
"""

import os
import sys
import json
import requests
import subprocess
import hashlib
import argparse
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

# Carga de entorno
from dotenv import load_dotenv, find_dotenv

# ===== Configuración de logging =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ===== Carga de .env =====
_env_path = find_dotenv(usecwd=True)
if _env_path:
    load_dotenv(_env_path)
else:
    BASE_SCRIPTS = os.path.abspath(os.path.dirname(__file__))
    load_dotenv(os.path.join(BASE_SCRIPTS, ".env"))

# Cargar sendgrid.env si existe
BASE_SCRIPTS = os.path.abspath(os.path.dirname(__file__))
sendgrid_env = os.path.join(BASE_SCRIPTS, "sendgrid.env")
if os.path.exists(sendgrid_env):
    load_dotenv(sendgrid_env)

# ===== Configuración =====
CONFIG = {
    # NWS API
    'nws_url': 'https://api.weather.gov/alerts/active',
    'user_agent': 'CanalMeteoTV/1.0 (contacto@canalmeteo.tv)',
    
    # Tipos de alerta a monitorear
    'alert_types': ['Tornado Warning'],  # Puede expandirse: 'Tornado Watch', 'Severe Thunderstorm Warning'
    
    # Directorios
    'data_dir': '/opt/canalmeteo/data/tornado',
    'web_dir': '/opt/canalmeteo/data/tornado/web',
    'cache_file': '/opt/canalmeteo/data/tornado/processed_alerts.json',
    
    # DigitalOcean Spaces
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_base_path': 'alertas/tornado',
    
    # SFTP (remoto)
    'sftp_enabled': True,
    'remote_base': '/home/zz7622j72pvq/public_html/canalmeteo.tv/lynx/tornado',
    
    # Notificaciones
    'email_enabled': True,
    'sms_enabled': True,
    
    # Intervalo daemon (segundos)
    'check_interval': 60,
}

# ===== Credenciales desde entorno =====
SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_USER = os.getenv("SFTP_USER")
SFTP_PASS = os.getenv("SFTP_PASS")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "alertas@canalmeteo.tv")
TO_EMAILS = [e.strip() for e in os.getenv("TO_EMAILS", "").split(",") if e.strip()]

# Twilio para SMS
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
SMS_TO_NUMBERS = [n.strip() for n in os.getenv("SMS_TO_NUMBERS", "").split(",") if n.strip()]


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def ensure_dirs():
    """Crear directorios necesarios."""
    for d in [CONFIG['data_dir'], CONFIG['web_dir']]:
        Path(d).mkdir(parents=True, exist_ok=True)


def load_processed_alerts():
    """Cargar IDs de alertas ya procesadas."""
    cache_file = CONFIG['cache_file']
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'processed': [], 'last_check': None}


def save_processed_alerts(data):
    """Guardar IDs de alertas procesadas."""
    cache_file = CONFIG['cache_file']
    Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump(data, f, indent=2)


def get_alert_hash(alert):
    """Generar hash único para una alerta."""
    alert_id = alert.get('properties', {}).get('id', '')
    return hashlib.md5(alert_id.encode()).hexdigest()[:12]


# =============================================================================
# OBTENER ALERTAS DEL NWS
# =============================================================================

def fetch_tornado_warnings():
    """Obtener Tornado Warnings activos del NWS."""
    headers = {
        'User-Agent': CONFIG['user_agent'],
        'Accept': 'application/geo+json'
    }
    
    params = {
        'status': 'actual',
        'message_type': 'alert',
        'event': 'Tornado Warning'
    }
    
    try:
        log.info("🌪️ Consultando NWS para Tornado Warnings...")
        response = requests.get(
            CONFIG['nws_url'],
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        warnings = data.get('features', [])
        log.info(f"   Encontrados: {len(warnings)} Tornado Warning(s) activo(s)")
        return warnings
        
    except requests.exceptions.RequestException as e:
        log.error(f"❌ Error consultando NWS: {e}")
        return []


def parse_warning(warning):
    """Extraer información relevante de una alerta."""
    props = warning.get('properties', {})
    geom = warning.get('geometry', {})
    
    # Extraer coordenadas del polígono
    coordinates = []
    if geom and geom.get('type') == 'Polygon':
        coordinates = geom.get('coordinates', [[]])[0]
    elif geom and geom.get('type') == 'MultiPolygon':
        # Tomar el primer polígono
        coordinates = geom.get('coordinates', [[[]]])[0][0]
    
    # Calcular centro aproximado
    if coordinates:
        lons = [c[0] for c in coordinates]
        lats = [c[1] for c in coordinates]
        center_lon = sum(lons) / len(lons)
        center_lat = sum(lats) / len(lats)
    else:
        center_lon, center_lat = -98.5, 39.8  # Centro de EEUU por defecto
    
    # Parsear fechas
    effective = props.get('effective', '')
    expires = props.get('expires', '')
    
    try:
        effective_dt = datetime.fromisoformat(effective.replace('Z', '+00:00'))
        expires_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
    except:
        effective_dt = datetime.now(timezone.utc)
        expires_dt = datetime.now(timezone.utc)
    
    return {
        'id': props.get('id', 'unknown'),
        'event': props.get('event', 'Tornado Warning'),
        'headline': props.get('headline', ''),
        'description': props.get('description', ''),
        'instruction': props.get('instruction', ''),
        'severity': props.get('severity', 'Extreme'),
        'certainty': props.get('certainty', 'Observed'),
        'urgency': props.get('urgency', 'Immediate'),
        'sender': props.get('senderName', 'National Weather Service'),
        'areas': props.get('areaDesc', ''),
        'effective': effective,
        'expires': expires,
        'effective_dt': effective_dt,
        'expires_dt': expires_dt,
        'coordinates': coordinates,
        'center': [center_lat, center_lon],
        'nws_url': f"https://alerts.weather.gov/search?id={props.get('id', '')}",
        # Parámetros del tornado (si están disponibles)
        'parameters': props.get('parameters', {}),
    }


# =============================================================================
# GENERAR MAPA
# =============================================================================

def generate_map(warning_data, output_path):
    """Generar mapa HTML interactivo con el área del tornado warning."""
    try:
        import folium
        from folium.plugins import Fullscreen
    except ImportError:
        log.warning("⚠️ folium no instalado. Saltando generación de mapa.")
        return None
    
    center = warning_data['center']
    
    # Crear mapa base
    m = folium.Map(
        location=center,
        zoom_start=9,
        tiles='CartoDB dark_matter'
    )
    
    # Añadir capa de satélite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satélite',
        overlay=False
    ).add_to(m)
    
    # Añadir polígono del warning
    if warning_data['coordinates']:
        # Convertir a formato [lat, lon] para folium
        polygon_coords = [[c[1], c[0]] for c in warning_data['coordinates']]
        
        folium.Polygon(
            locations=polygon_coords,
            color='#FF0000',
            weight=3,
            fill=True,
            fill_color='#FF0000',
            fill_opacity=0.3,
            popup=folium.Popup(
                f"""
                <div style="font-family: Arial; min-width: 250px;">
                    <h3 style="color: #dc2626; margin: 0 0 10px 0;">🌪️ TORNADO WARNING</h3>
                    <p><strong>Área:</strong> {warning_data['areas']}</p>
                    <p><strong>Expira:</strong> {warning_data['expires_dt'].strftime('%H:%M UTC')}</p>
                    <p><strong>Emisor:</strong> {warning_data['sender']}</p>
                </div>
                """,
                max_width=300
            )
        ).add_to(m)
        
        # Marcador en el centro
        folium.Marker(
            location=center,
            popup=warning_data['headline'],
            icon=folium.DivIcon(
                html='''
                <div style="
                    background: #dc2626;
                    border-radius: 50%;
                    width: 40px;
                    height: 40px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 24px;
                    box-shadow: 0 0 20px rgba(220, 38, 38, 0.8);
                    animation: pulse 1.5s infinite;
                ">🌪️</div>
                <style>
                @keyframes pulse {
                    0%, 100% { transform: scale(1); opacity: 1; }
                    50% { transform: scale(1.1); opacity: 0.8; }
                }
                </style>
                ''',
                icon_size=(40, 40),
                icon_anchor=(20, 20)
            )
        ).add_to(m)
    
    # Añadir título
    title_html = f'''
    <div style="
        position: fixed;
        top: 10px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 1000;
        background: linear-gradient(135deg, #dc2626, #991b1b);
        padding: 15px 30px;
        border-radius: 10px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        font-family: Arial, sans-serif;
    ">
        <div style="color: white; font-size: 14px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;">
            ⚠️ TORNADO WARNING ACTIVO
        </div>
        <div style="color: #fecaca; font-size: 12px; margin-top: 5px;">
            {warning_data['areas'][:60]}{'...' if len(warning_data['areas']) > 60 else ''}
        </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    # Añadir fullscreen
    Fullscreen().add_to(m)
    
    # Añadir control de capas
    folium.LayerControl().add_to(m)
    
    # Guardar
    m.save(output_path)
    log.info(f"✅ Mapa generado: {output_path}")
    return output_path


def generate_static_image(warning_data, output_path):
    """Generar imagen PNG estática del mapa (para email/SMS)."""
    try:
        import folium
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        import time as time_module
    except ImportError:
        log.warning("⚠️ selenium no instalado. Usando método alternativo para imagen.")
        return generate_simple_image(warning_data, output_path)
    
    # Generar mapa temporal
    temp_html = output_path.replace('.png', '_temp.html')
    generate_map(warning_data, temp_html)
    
    try:
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--width=1200')
        options.add_argument('--height=800')
        
        driver = webdriver.Firefox(options=options)
        driver.get(f'file://{temp_html}')
        time_module.sleep(3)  # Esperar a que cargue
        driver.save_screenshot(output_path)
        driver.quit()
        
        # Limpiar
        os.remove(temp_html)
        log.info(f"✅ Imagen generada: {output_path}")
        return output_path
        
    except Exception as e:
        log.warning(f"⚠️ Error con selenium: {e}")
        return generate_simple_image(warning_data, output_path)


def generate_simple_image(warning_data, output_path):
    """Generar imagen simple con PIL (fallback)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        log.warning("⚠️ PIL no instalado. No se puede generar imagen.")
        return None
    
    # Crear imagen
    width, height = 800, 600
    img = Image.new('RGB', (width, height), color='#1a1a2e')
    draw = ImageDraw.Draw(img)
    
    # Intentar cargar fuente, usar default si falla
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large
    
    # Barra superior roja
    draw.rectangle([0, 0, width, 80], fill='#dc2626')
    
    # Título
    draw.text((width//2, 40), "⚠️ TORNADO WARNING", font=font_large, fill='white', anchor='mm')
    
    # Información
    y_pos = 120
    
    draw.text((40, y_pos), "📍 Área afectada:", font=font_medium, fill='#60a5fa')
    y_pos += 35
    
    # Dividir área en líneas si es muy larga
    area_text = warning_data['areas']
    max_chars = 50
    lines = [area_text[i:i+max_chars] for i in range(0, len(area_text), max_chars)]
    for line in lines[:3]:  # Máximo 3 líneas
        draw.text((40, y_pos), line, font=font_small, fill='white')
        y_pos += 25
    
    y_pos += 20
    draw.text((40, y_pos), f"⏰ Expira: {warning_data['expires_dt'].strftime('%H:%M UTC')}", 
              font=font_medium, fill='#fbbf24')
    
    y_pos += 50
    draw.text((40, y_pos), f"🏢 Emisor: {warning_data['sender']}", 
              font=font_small, fill='#9ca3af')
    
    y_pos += 40
    draw.text((40, y_pos), f"📍 Coordenadas: {warning_data['center'][0]:.4f}, {warning_data['center'][1]:.4f}", 
              font=font_small, fill='#9ca3af')
    
    # Footer
    draw.rectangle([0, height-50, width, height], fill='#0f172a')
    draw.text((width//2, height-25), "Canal Meteo TV - www.canalmeteo.tv", 
              font=font_small, fill='#64748b', anchor='mm')
    
    img.save(output_path)
    log.info(f"✅ Imagen simple generada: {output_path}")
    return output_path


# =============================================================================
# GENERAR HTML DE ALERTA
# =============================================================================

def generate_alert_html(warning_data, output_path):
    """Generar página HTML con toda la información de la alerta."""
    
    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌪️ Tornado Warning - {warning_data['areas'][:50]} | Canal Meteo TV</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            min-height: 100vh;
            color: white;
        }}
        .alert-banner {{
            background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%);
            padding: 20px;
            text-align: center;
            animation: pulse-bg 2s infinite;
        }}
        @keyframes pulse-bg {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.9; }}
        }}
        .alert-banner h1 {{
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        .alert-banner .expires {{
            font-size: 1.1rem;
            color: #fecaca;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .info-card {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .info-card h3 {{
            color: #60a5fa;
            margin-bottom: 15px;
            font-size: 1rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .info-card p {{
            color: #e2e8f0;
            line-height: 1.6;
        }}
        .map-container {{
            width: 100%;
            height: 500px;
            border-radius: 12px;
            overflow: hidden;
            margin: 20px 0;
        }}
        .map-container iframe {{
            width: 100%;
            height: 100%;
            border: none;
        }}
        .instructions {{
            background: rgba(251, 191, 36, 0.1);
            border-left: 4px solid #fbbf24;
            padding: 20px;
            border-radius: 0 12px 12px 0;
            margin: 20px 0;
        }}
        .instructions h3 {{
            color: #fbbf24;
            margin-bottom: 10px;
        }}
        .meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .meta-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            color: #94a3b8;
            font-size: 0.9rem;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .badge-extreme {{ background: #dc2626; color: white; }}
        .badge-immediate {{ background: #f97316; color: white; }}
        footer {{
            text-align: center;
            padding: 30px;
            color: #64748b;
            font-size: 0.9rem;
        }}
        footer a {{ color: #60a5fa; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="alert-banner">
        <h1>🌪️ TORNADO WARNING</h1>
        <p class="expires">Expira: {warning_data['expires_dt'].strftime('%d/%m/%Y %H:%M UTC')}</p>
    </div>
    
    <div class="container">
        <div class="info-grid">
            <div class="info-card">
                <h3>📍 Área Afectada</h3>
                <p>{warning_data['areas']}</p>
            </div>
            <div class="info-card">
                <h3>📋 Resumen</h3>
                <p>{warning_data['headline']}</p>
            </div>
        </div>
        
        <div class="info-card">
            <h3>📝 Descripción</h3>
            <p>{warning_data['description'][:1000]}{'...' if len(warning_data['description']) > 1000 else ''}</p>
        </div>
        
        {f'''
        <div class="instructions">
            <h3>⚠️ Instrucciones de Seguridad</h3>
            <p>{warning_data['instruction']}</p>
        </div>
        ''' if warning_data['instruction'] else ''}
        
        <div class="map-container">
            <iframe src="mapa_{get_alert_hash({'properties': {'id': warning_data['id']}})}.html"></iframe>
        </div>
        
        <div class="meta">
            <div class="meta-item">
                <span class="badge badge-extreme">{warning_data['severity']}</span>
            </div>
            <div class="meta-item">
                <span class="badge badge-immediate">{warning_data['urgency']}</span>
            </div>
            <div class="meta-item">
                🏢 {warning_data['sender']}
            </div>
            <div class="meta-item">
                🕐 Emitido: {warning_data['effective_dt'].strftime('%H:%M UTC')}
            </div>
            <div class="meta-item">
                📍 Centro: {warning_data['center'][0]:.4f}°N, {abs(warning_data['center'][1]):.4f}°W
            </div>
        </div>
    </div>
    
    <footer>
        <p>Datos proporcionados por el <a href="https://www.weather.gov" target="_blank">National Weather Service</a></p>
        <p style="margin-top: 10px;">Canal Meteo TV - <a href="https://www.canalmeteo.tv">www.canalmeteo.tv</a></p>
        <p style="margin-top: 10px; font-size: 0.8rem;">Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    </footer>
</body>
</html>'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    log.info(f"✅ HTML de alerta generado: {output_path}")
    return output_path


# =============================================================================
# ENVÍO DE NOTIFICACIONES
# =============================================================================

def send_email(warning_data, image_path=None):
    """Enviar email con SendGrid."""
    if not SENDGRID_API_KEY or not TO_EMAILS:
        log.warning("⚠️ Email no configurado (falta SENDGRID_API_KEY o TO_EMAILS)")
        return False
    
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
        import base64
    except ImportError:
        log.warning("⚠️ sendgrid no instalado")
        return False
    
    subject = f"🌪️ TORNADO WARNING - {warning_data['areas'][:50]}"
    
    html_content = f'''
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #dc2626, #991b1b); padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">🌪️ TORNADO WARNING</h1>
        </div>
        
        <div style="background: #1e293b; padding: 20px; color: white;">
            <h2 style="color: #60a5fa; font-size: 18px;">📍 {warning_data['areas']}</h2>
            
            <p style="color: #e2e8f0; line-height: 1.6;">{warning_data['headline']}</p>
            
            <div style="background: rgba(251, 191, 36, 0.1); border-left: 4px solid #fbbf24; padding: 15px; margin: 15px 0;">
                <strong style="color: #fbbf24;">⏰ Expira:</strong>
                <span style="color: white;">{warning_data['expires_dt'].strftime('%d/%m/%Y %H:%M UTC')}</span>
            </div>
            
            {f'<div style="background: rgba(220, 38, 38, 0.1); border-left: 4px solid #dc2626; padding: 15px; margin: 15px 0;"><strong style="color: #dc2626;">⚠️ Instrucciones:</strong><p style="color: white; margin-top: 10px;">{warning_data["instruction"][:500]}</p></div>' if warning_data['instruction'] else ''}
            
            <div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #334155;">
                <small style="color: #94a3b8;">
                    Emisor: {warning_data['sender']}<br>
                    Coordenadas: {warning_data['center'][0]:.4f}°N, {abs(warning_data['center'][1]):.4f}°W
                </small>
            </div>
        </div>
        
        <div style="background: #0f172a; padding: 15px; text-align: center; border-radius: 0 0 10px 10px;">
            <a href="{warning_data['nws_url']}" style="color: #60a5fa; text-decoration: none;">Ver en NWS →</a>
            <p style="color: #64748b; font-size: 12px; margin-top: 10px;">Canal Meteo TV - www.canalmeteo.tv</p>
        </div>
    </div>
    '''
    
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=TO_EMAILS,
        subject=subject,
        html_content=html_content
    )
    
    # Adjuntar imagen si existe
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode()
        
        attachment = Attachment(
            FileContent(image_data),
            FileName('tornado_warning_map.png'),
            FileType('image/png'),
            Disposition('attachment')
        )
        message.attachment = attachment
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        log.info(f"📧 Email enviado a {len(TO_EMAILS)} destinatario(s). Status: {response.status_code}")
        return True
    except Exception as e:
        log.error(f"❌ Error enviando email: {e}")
        return False


def send_sms(warning_data):
    """Enviar SMS con Twilio."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, SMS_TO_NUMBERS]):
        log.warning("⚠️ SMS no configurado (faltan credenciales Twilio)")
        return False
    
    try:
        from twilio.rest import Client
    except ImportError:
        log.warning("⚠️ twilio no instalado")
        return False
    
    # Mensaje corto para SMS (máximo ~160 caracteres)
    area_short = warning_data['areas'][:80]
    expires_str = warning_data['expires_dt'].strftime('%H:%M UTC')
    
    message_body = f"🌪️ TORNADO WARNING\n{area_short}\nExpira: {expires_str}\nRefugio inmediato!"
    
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        for number in SMS_TO_NUMBERS:
            msg = client.messages.create(
                body=message_body,
                from_=TWILIO_FROM_NUMBER,
                to=number
            )
            log.info(f"📱 SMS enviado a {number}. SID: {msg.sid}")
        
        return True
    except Exception as e:
        log.error(f"❌ Error enviando SMS: {e}")
        return False


# =============================================================================
# SUBIDA DE ARCHIVOS
# =============================================================================

def upload_to_spaces(local_path, remote_filename):
    """Subir archivo a DigitalOcean Spaces via AWS CLI."""
    s3_path = f"s3://{CONFIG['s3_bucket']}/{CONFIG['s3_base_path']}/{remote_filename}"
    
    cmd = [
        'aws', 's3', 'cp', local_path, s3_path,
        '--endpoint-url', CONFIG['aws_endpoint'],
        '--profile', CONFIG['aws_profile'],
        '--acl', 'public-read'
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        public_url = f"https://{CONFIG['s3_bucket']}.sfo3.digitaloceanspaces.com/{CONFIG['s3_base_path']}/{remote_filename}"
        log.info(f"☁️ Subido a Spaces: {public_url}")
        return public_url
    except subprocess.CalledProcessError as e:
        log.error(f"❌ Error subiendo a Spaces: {e.stderr.decode()}")
        return None


def upload_via_sftp(local_path, remote_filename):
    """Subir archivo via SFTP."""
    if not CONFIG['sftp_enabled'] or not all([SFTP_HOST, SFTP_USER, SFTP_PASS]):
        return None
    
    try:
        import paramiko
    except ImportError:
        log.warning("⚠️ paramiko no instalado")
        return None
    
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        remote_path = f"{CONFIG['remote_base']}/{remote_filename}"
        
        # Crear directorio si no existe
        try:
            sftp.stat(CONFIG['remote_base'])
        except IOError:
            sftp.mkdir(CONFIG['remote_base'])
        
        sftp.put(local_path, remote_path)
        log.info(f"📤 SFTP: {local_path} -> {remote_path}")
        
        sftp.close()
        transport.close()
        return remote_path
        
    except Exception as e:
        log.error(f"❌ Error SFTP: {e}")
        return None


# =============================================================================
# PROCESO PRINCIPAL
# =============================================================================

def process_warning(warning):
    """Procesar una alerta de tornado."""
    warning_data = parse_warning(warning)
    alert_hash = get_alert_hash(warning)
    
    log.info(f"🌪️ Procesando: {warning_data['headline'][:80]}...")
    
    # Generar archivos
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    map_html = os.path.join(CONFIG['web_dir'], f"mapa_{alert_hash}.html")
    map_png = os.path.join(CONFIG['web_dir'], f"mapa_{alert_hash}.png")
    alert_html = os.path.join(CONFIG['web_dir'], f"tornado_{alert_hash}.html")
    
    # Generar mapa interactivo
    generate_map(warning_data, map_html)
    
    # Generar imagen estática
    generate_simple_image(warning_data, map_png)
    
    # Generar HTML de alerta
    generate_alert_html(warning_data, alert_html)
    
    # Subir a Spaces
    upload_to_spaces(map_html, f"mapa_{alert_hash}.html")
    upload_to_spaces(map_png, f"mapa_{alert_hash}.png")
    upload_to_spaces(alert_html, f"tornado_{alert_hash}.html")
    
    # Subir via SFTP
    upload_via_sftp(map_html, f"mapa_{alert_hash}.html")
    upload_via_sftp(map_png, f"mapa_{alert_hash}.png")
    upload_via_sftp(alert_html, f"tornado_{alert_hash}.html")
    
    # Enviar notificaciones
    if CONFIG['email_enabled']:
        send_email(warning_data, map_png)
    
    if CONFIG['sms_enabled']:
        send_sms(warning_data)
    
    return warning_data


def main(daemon=False, test_mode=False):
    """Función principal."""
    log.info("=" * 60)
    log.info("🌪️ TORNADO WARNING ALERT SYSTEM - Canal Meteo TV")
    log.info("=" * 60)
    
    ensure_dirs()
    
    while True:
        try:
            # Cargar alertas procesadas
            cache = load_processed_alerts()
            processed_ids = set(cache.get('processed', []))
            
            # Obtener warnings activos
            warnings = fetch_tornado_warnings()
            
            if not warnings:
                log.info("✅ No hay Tornado Warnings activos")
            else:
                new_count = 0
                for warning in warnings:
                    alert_id = warning.get('properties', {}).get('id', '')
                    
                    if alert_id not in processed_ids:
                        process_warning(warning)
                        processed_ids.add(alert_id)
                        new_count += 1
                    else:
                        log.debug(f"⏭️ Ya procesado: {alert_id[:30]}...")
                
                if new_count > 0:
                    log.info(f"🆕 {new_count} nueva(s) alerta(s) procesada(s)")
                
                # Guardar cache (mantener últimas 100 alertas)
                cache['processed'] = list(processed_ids)[-100:]
                cache['last_check'] = datetime.now(timezone.utc).isoformat()
                save_processed_alerts(cache)
        
        except Exception as e:
            log.error(f"❌ Error en ciclo principal: {e}")
            import traceback
            traceback.print_exc()
        
        if not daemon:
            break
        
        log.info(f"💤 Esperando {CONFIG['check_interval']} segundos...")
        time.sleep(CONFIG['check_interval'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Tornado Warning Alert System')
    parser.add_argument('--daemon', action='store_true', help='Ejecutar en loop continuo')
    parser.add_argument('--test', action='store_true', help='Modo test')
    args = parser.parse_args()
    
    main(daemon=args.daemon, test_mode=args.test)
