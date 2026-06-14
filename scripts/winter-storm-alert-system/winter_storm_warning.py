#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WINTER STORM WARNING ALERT SYSTEM - Canal Meteo TV
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

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# Configuración
BASE_SCRIPTS = "/opt/canalmeteo/scripts/winter-storm-alert-system"

env_file = os.path.join(BASE_SCRIPTS, ".env")
if os.path.exists(env_file):
    load_dotenv(env_file)

CONFIG = {
    'nws_url': 'https://api.weather.gov/alerts/active',
    'user_agent': 'CanalMeteoTV/1.0 (contacto@canalmeteo.tv)',
    'data_dir': f'{BASE_SCRIPTS}/data',
    'web_dir': f'{BASE_SCRIPTS}/web',
    'cache_file': f'{BASE_SCRIPTS}/data/processed_alerts.json',
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_base_path': 'alertas/winter-storm',
    'sftp_enabled': False,
    'email_enabled': True,
    'sms_enabled': True,
    'check_interval': 300,
}

SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_USER = os.getenv("SFTP_USER")
SFTP_PASS = os.getenv("SFTP_PASS")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "alertas@canalmeteo.tv")
TO_EMAILS = [e.strip() for e in os.getenv("TO_EMAILS", "").split(",") if e.strip()]

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
SMS_TO_NUMBERS = [n.strip() for n in os.getenv("SMS_TO_NUMBERS", "").split(",") if n.strip()]


def ensure_dirs():
    for d in [CONFIG['data_dir'], CONFIG['web_dir']]:
        Path(d).mkdir(parents=True, exist_ok=True)


def load_processed_alerts():
    cache_file = CONFIG['cache_file']
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'processed': [], 'last_check': None}


def save_processed_alerts(data):
    cache_file = CONFIG['cache_file']
    Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump(data, f, indent=2)


def get_alert_hash(alert):
    alert_id = alert.get('properties', {}).get('id', '')
    return hashlib.md5(alert_id.encode()).hexdigest()[:12]


def fetch_winter_warnings():
    headers = {
        'User-Agent': CONFIG['user_agent'],
        'Accept': 'application/geo+json'
    }
    params = {
        'status': 'actual',
        'message_type': 'alert',
    }
    
    winter_events = [
        'Winter Storm Warning',
        'Blizzard Warning',
        'Ice Storm Warning',
        'Winter Storm Watch',
        'Extreme Cold Warning',
    ]
    
    try:
        log.info("❄️ Consultando NWS para alertas invernales...")
        response = requests.get(CONFIG['nws_url'], headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        all_alerts = data.get('features', [])
        log.info(f"   Total alertas activas: {len(all_alerts)}")
        
        warnings = [w for w in all_alerts if w.get('properties', {}).get('event') in winter_events]
        
        event_counts = {}
        for w in warnings:
            event = w.get('properties', {}).get('event', 'Unknown')
            event_counts[event] = event_counts.get(event, 0) + 1
        
        for event, count in event_counts.items():
            log.info(f"   - {count} {event}")
        
        log.info(f"   Encontrados: {len(warnings)} alerta(s) invernal(es)")
        return warnings
        
    except requests.exceptions.RequestException as e:
        log.error(f"❌ Error consultando NWS: {e}")
        return []


def parse_warning(warning):
    props = warning.get('properties', {})
    geom = warning.get('geometry', {})
    
    coordinates = []
    if geom and geom.get('type') == 'Polygon':
        coordinates = geom.get('coordinates', [[]])[0]
    elif geom and geom.get('type') == 'MultiPolygon':
        coordinates = geom.get('coordinates', [[[]]])[0][0]
    
    if coordinates:
        lons = [c[0] for c in coordinates]
        lats = [c[1] for c in coordinates]
        center_lon = sum(lons) / len(lons)
        center_lat = sum(lats) / len(lats)
    else:
        center_lon, center_lat = -98.5, 39.8
    
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
        'event': props.get('event', 'Winter Storm Warning'),
        'headline': props.get('headline', ''),
        'description': props.get('description', ''),
        'instruction': props.get('instruction', ''),
        'severity': props.get('severity', 'Severe'),
        'certainty': props.get('certainty', 'Likely'),
        'urgency': props.get('urgency', 'Expected'),
        'sender': props.get('senderName', 'National Weather Service'),
        'areas': props.get('areaDesc', ''),
        'effective': effective,
        'expires': expires,
        'effective_dt': effective_dt,
        'expires_dt': expires_dt,
        'coordinates': coordinates,
        'center': [center_lat, center_lon],
        'nws_url': f"https://alerts.weather.gov/search?id={props.get('id', '')}",
        'parameters': props.get('parameters', {}),
    }


def generate_map(warning_data, output_path):
    try:
        import folium
    except ImportError:
        log.warning("⚠️ folium no instalado")
        return None
    
    center = warning_data['center']
    
    m = folium.Map(location=center, zoom_start=7, tiles='CartoDB positron')
    
    if warning_data['coordinates']:
        polygon_coords = [[c[1], c[0]] for c in warning_data['coordinates']]
        folium.Polygon(
            locations=polygon_coords,
            color='#0ea5e9',
            weight=3,
            fill=True,
            fill_color='#0ea5e9',
            fill_opacity=0.3,
        ).add_to(m)
    
    folium.Marker(location=center, popup=warning_data['headline']).add_to(m)
    
    m.save(output_path)
    log.info(f"✅ Mapa generado: {output_path}")
    return output_path


def generate_alert_html(warning_data, output_path):
    colors = {'primary': '#0ea5e9', 'secondary': '#0369a1'}
    
    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>❄️ {warning_data['event']} | Canal Meteo TV</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #0c1929; color: white; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, {colors['primary']}, {colors['secondary']}); padding: 20px; border-radius: 10px; text-align: center; }}
        .content {{ margin-top: 20px; }}
        .card {{ background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px; margin: 10px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>❄️ {warning_data['event']}</h1>
        <p>Expira: {warning_data['expires_dt'].strftime('%d/%m/%Y %H:%M')}</p>
    </div>
    <div class="content">
        <div class="card"><h3>📍 Área</h3><p>{warning_data['areas']}</p></div>
        <div class="card"><h3>📋 Descripción</h3><p>{warning_data['description'][:500]}</p></div>
        <div class="card"><h3>⚠️ Instrucciones</h3><p>{warning_data['instruction'] or 'Evite viajar si es posible.'}</p></div>
    </div>
</body>
</html>'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    log.info(f"✅ HTML generado: {output_path}")
    return output_path


def send_email(warning_data, image_path=None):
    if not SENDGRID_API_KEY or not TO_EMAILS:
        log.warning("⚠️ Email no configurado")
        return False
    
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
        import base64
    except ImportError:
        log.warning("⚠️ sendgrid no instalado")
        return False
    
    subject = f"❄️ {warning_data['event']} - {warning_data['areas'][:50]}"
    
    html_content = f'''
    <div style="font-family: Arial; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #0ea5e9, #0369a1); padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
            <h1 style="color: white; margin: 0;">❄️ {warning_data['event']}</h1>
        </div>
        <div style="background: #0c1929; padding: 20px; color: white;">
            <h2 style="color: #7dd3fc;">📍 {warning_data['areas']}</h2>
            <p>{warning_data['headline']}</p>
            <div style="background: rgba(14, 165, 233, 0.1); border-left: 4px solid #0ea5e9; padding: 15px; margin: 15px 0;">
                <strong style="color: #38bdf8;">⏰ Expira:</strong>
                <span>{warning_data['expires_dt'].strftime('%d/%m/%Y %H:%M')}</span>
            </div>
            <p style="color: #94a3b8; font-size: 12px;">Emisor: {warning_data['sender']}</p>
        </div>
        <div style="background: #0369a1; padding: 15px; text-align: center; border-radius: 0 0 10px 10px;">
            <p style="color: #7dd3fc; font-size: 12px;">Canal Meteo TV - www.canalmeteo.tv</p>
        </div>
    </div>
    '''
    
    message = Mail(from_email=FROM_EMAIL, to_emails=TO_EMAILS, subject=subject, html_content=html_content)
    
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode()
        attachment = Attachment(
            FileContent(image_data),
            FileName('alerta_invernal.png'),
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
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, SMS_TO_NUMBERS]):
        log.warning("⚠️ SMS no configurado")
        return False
    
    try:
        from twilio.rest import Client
    except ImportError:
        log.warning("⚠️ twilio no instalado")
        return False
    
    area_short = warning_data['areas'][:80]
    expires_str = warning_data['expires_dt'].strftime('%H:%M')
    message_body = f"❄️ {warning_data['event']}\n{area_short}\nExpira: {expires_str}\nPrecaución!"
    
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        for number in SMS_TO_NUMBERS:
            msg = client.messages.create(body=message_body, from_=TWILIO_FROM_NUMBER, to=number)
            log.info(f"📱 SMS enviado a {number}")
        return True
    except Exception as e:
        log.error(f"❌ Error enviando SMS: {e}")
        return False


def upload_to_spaces(local_path, remote_filename):
    if not os.path.exists(local_path):
        log.error(f"❌ Archivo no existe: {local_path}")
        return None
    
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
        log.info(f"☁️ Subido: {public_url}")
        return public_url
    except subprocess.CalledProcessError as e:
        log.error(f"❌ Error subiendo: {e.stderr.decode()}")
        return None


def process_warning(warning):
    warning_data = parse_warning(warning)
    alert_hash = get_alert_hash(warning)
    
    log.info(f"❄️ Procesando: {warning_data['headline'][:70]}...")
    
    map_html = os.path.join(CONFIG['web_dir'], f"mapa_{alert_hash}.html")
    alert_png = os.path.join(CONFIG['web_dir'], f"alerta_{alert_hash}.png")
    alert_html = os.path.join(CONFIG['web_dir'], f"alerta_{alert_hash}.html")
    
    # Generar mapa HTML
    generate_map(warning_data, map_html)
    
    # Generar imagen 1080x1920 con Playwright
    try:
        # Importar aquí para evitar problemas de módulo
        sys.path.insert(0, BASE_SCRIPTS)
        from generate_alert_image import generate_alert_image
        generate_alert_image(warning_data, alert_png)
    except Exception as e:
        log.error(f"❌ Error generando imagen: {e}")
        alert_png = None
    
    # Generar HTML de alerta
    generate_alert_html(warning_data, alert_html)
    
    # Subir a Spaces
    upload_to_spaces(map_html, f"mapa_{alert_hash}.html")
    if alert_png and os.path.exists(alert_png):
        upload_to_spaces(alert_png, f"alerta_{alert_hash}.png")
    upload_to_spaces(alert_html, f"alerta_{alert_hash}.html")
    
    # Enviar notificaciones
    if CONFIG['email_enabled']:
        send_email(warning_data, alert_png)
    
    if CONFIG['sms_enabled']:
        send_sms(warning_data)
    
    return warning_data


def main(daemon=False, test_mode=False):
    log.info("=" * 60)
    log.info("❄️ WINTER STORM WARNING ALERT SYSTEM - Canal Meteo TV")
    log.info("=" * 60)
    
    ensure_dirs()
    
    while True:
        try:
            cache = load_processed_alerts()
            processed_ids = set(cache.get('processed', []))
            
            warnings = fetch_winter_warnings()
            
            if not warnings:
                log.info("✅ No hay alertas invernales activas")
            else:
                new_count = 0
                for warning in warnings:
                    alert_id = warning.get('properties', {}).get('id', '')
                    
                    if alert_id not in processed_ids:
                        process_warning(warning)
                        processed_ids.add(alert_id)
                        new_count += 1
                
                if new_count > 0:
                    log.info(f"🆕 {new_count} nueva(s) alerta(s) procesada(s)")
                
                cache['processed'] = list(processed_ids)[-100:]
                cache['last_check'] = datetime.now(timezone.utc).isoformat()
                save_processed_alerts(cache)
        
        except Exception as e:
            log.error(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        if not daemon:
            break
        
        log.info(f"💤 Esperando {CONFIG['check_interval']} segundos...")
        time.sleep(CONFIG['check_interval'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--daemon', action='store_true')
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    main(daemon=args.daemon, test_mode=args.test)
