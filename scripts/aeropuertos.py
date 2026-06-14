#!/usr/bin/env python3
"""
Script para obtener demoras de aeropuertos de la FAA.
Genera JSON con top 10 aeropuertos con más demoras.

Ubicación: /opt/canalmeteo/scripts/aeropuertos.py

Salidas:
- JSON a DigitalOcean Spaces: /lynx/datos/aeropuertos.json
- CSV a GoDaddy SFTP: /lynx/csv/airport_delays.csv

Uso:
    python aeropuertos.py         # Ejecución normal
    python aeropuertos.py --once  # Una sola ejecución

Cron recomendado (cada 30 min):
    */30 * * * * /usr/bin/python3 /opt/canalmeteo/scripts/aeropuertos.py --once >> /var/log/canalmeteo/aeropuertos.log 2>&1
"""

import os
import sys
import json
import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import logging
import argparse
import time

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# =========================
# CONFIGURACIÓN
# =========================
CONFIG = {
    # Fuente de datos
    'faa_csv_url': 'https://s3.us-east-1.amazonaws.com/baron.luda/faa/faa_airport_status.csv',
    
    # Salidas locales
    'output_dir': '/tmp/canalmeteo/aeropuertos',
    'json_filename': 'aeropuertos.json',
    'csv_filename': 'airport_delays.csv',
    
    # DigitalOcean Spaces
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_base_path': 'lynx/datos',
    
    # GoDaddy SFTP
    'sftp_host': 'canalmeteo.tv',
    'sftp_user': 'zz7622j72pvq',
    'sftp_port': 22,
    'sftp_remote_base': '/home/zz7622j72pvq/public_html/canalmeteo.tv/lynx',
    
    # Otros
    'intervalo_segundos': 1800,  # 30 minutos
    'top_n': 10,  # Número de aeropuertos a mostrar
}

# Traducciones de motivos de demora
TRADUCCIONES_MOTIVO = {
    # Motivos principales
    "Weather": "Tiempo adverso",
    "Volume": "Alta demanda",
    "Runway Construction": "Obras en pista",
    "Equipment": "Fallo de equipamiento",
    "Staffing": "Falta de personal",
    "Construction": "Construcción",
    "Aircraft Swapping": "Cambio de aeronave",
    "Maintenance": "Mantenimiento",
    "Security": "Seguridad",
    "Other": "Otro",
    "Ops": "Operaciones",
    "Gate Issues": "Problemas de puerta",
    "Deicing": "Deshielo",
    
    # Condiciones meteorológicas específicas
    "Wind": "Viento",
    "WX:Wind": "Viento",
    "Thunderstorms": "Tormentas",
    "WX:Thunderstorms": "Tormentas",
    "WX:TStorms": "Tormentas",
    "Low Ceilings": "Techos bajos",
    "WX:Low Ceilings": "Techos bajos",
    "Fog": "Niebla",
    "WX:Fog": "Niebla",
    "Snow": "Nieve",
    "WX:Snow": "Nieve",
    "Snow/Ice": "Nieve/Hielo",
    "WX:Snow/Ice": "Nieve/Hielo",
    "Ice": "Hielo",
    "WX:Ice": "Hielo",
    "Rain": "Lluvia",
    "WX:Rain": "Lluvia",
    "Low Visibility": "Baja visibilidad",
    "WX:Low Visibility": "Baja visibilidad",
    "WX:Visibility": "Visibilidad reducida",
    "WX": "Tiempo adverso",
    
    # Combinaciones y variantes
    "Weather / Volume": "Tiempo/Alta demanda",
    "Weather/Volume": "Tiempo/Alta demanda",
    "Ground Stop": "Parada en tierra",
    "Ground Delay": "Demora en tierra",
    "Traffic": "Tráfico aéreo",
    "ATC": "Control de tráfico",
    "FAA": "Restricción FAA",
    
    # Vacío o desconocido
    "": "No especificado",
    "Unknown": "Desconocido",
    "N/A": "No especificado"
}

# Meses en español
MESES_ES = {
    'January': 'enero', 'February': 'febrero', 'March': 'marzo',
    'April': 'abril', 'May': 'mayo', 'June': 'junio',
    'July': 'julio', 'August': 'agosto', 'September': 'septiembre',
    'October': 'octubre', 'November': 'noviembre', 'December': 'diciembre'
}

# =========================
# UTILIDADES
# =========================
def get_fecha_hoy():
    """Retorna fecha de hoy en español."""
    hoy = datetime.now()
    return f"{hoy.day} de {MESES_ES[hoy.strftime('%B')]} de {hoy.year}"

def traducir_motivo(motivo):
    """Traduce el motivo de demora al español."""
    if pd.isna(motivo) or motivo == '':
        return "No especificado"
    
    motivo_str = str(motivo).strip()
    
    # Buscar coincidencia exacta primero
    if motivo_str in TRADUCCIONES_MOTIVO:
        return TRADUCCIONES_MOTIVO[motivo_str]
    
    # Buscar coincidencia parcial (para casos como "WX:Wind")
    motivo_lower = motivo_str.lower()
    for key, value in TRADUCCIONES_MOTIVO.items():
        if key.lower() in motivo_lower or motivo_lower in key.lower():
            return value
    
    # Si contiene "WX" o "Weather", es tiempo adverso
    if 'wx' in motivo_lower or 'weather' in motivo_lower:
        return "Tiempo adverso"
    
    # Si no hay traducción, devolver el original
    return motivo_str

# =========================
# EXTRACCIÓN DE DATOS
# =========================
def obtener_demoras_aeropuertos():
    """Descarga y procesa datos de demoras de aeropuertos."""
    fecha_hoy = get_fecha_hoy()
    
    try:
        logger.info("Descargando datos de la FAA...")
        resp = requests.get(CONFIG['faa_csv_url'], timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
    except Exception as e:
        logger.error(f"Error descargando datos FAA: {e}")
        return {'aeropuertos': [], 'fecha': fecha_hoy, 'total_con_demora': 0}
    
    # Filtrar aeropuertos con demora
    df_delay = df[df['general_delay'] == 'Yes'].copy()
    
    if df_delay.empty:
        logger.info("No hay aeropuertos con demoras actualmente")
        return {'aeropuertos': [], 'fecha': fecha_hoy, 'total_con_demora': 0}
    
    # Procesar columnas
    df_delay['max_delay_min'] = pd.to_numeric(df_delay['general_delays_max_time'], errors='coerce')
    df_delay = df_delay.dropna(subset=['max_delay_min'])
    
    if df_delay.empty:
        return {'aeropuertos': [], 'fecha': fecha_hoy, 'total_con_demora': 0}
    
    # Traducir motivos
    df_delay['motivo_es'] = df_delay['general_delays_reason'].apply(traducir_motivo)
    
    # Ordenar por demora máxima
    df_sorted = df_delay.sort_values('max_delay_min', ascending=False)
    
    # Tomar top N
    top = df_sorted.head(CONFIG['top_n'])
    
    # Construir lista de aeropuertos
    aeropuertos = []
    for _, row in top.iterrows():
        aeropuertos.append({
            'codigo': row.get('code', ''),
            'nombre': row.get('name', ''),
            'ciudad': row.get('city', ''),
            'estado': row.get('state', ''),
            'demora_minutos': int(row['max_delay_min']),
            'demora_texto': f"{int(row['max_delay_min'])} min",
            'motivo': row.get('general_delays_reason', ''),
            'motivo_es': row['motivo_es'],
            'tipo_demora': row.get('general_delays_type', '')
        })
    
    return {
        'aeropuertos': aeropuertos,
        'fecha': fecha_hoy,
        'total_con_demora': len(df_delay),
        'generado': datetime.now(timezone.utc).isoformat()
    }

# =========================
# SUBIDA A SPACES Y SFTP
# =========================
def subir_a_spaces(local_path, remote_filename):
    """Sube archivo a DigitalOcean Spaces."""
    s3_path = f"s3://{CONFIG['s3_bucket']}/{CONFIG['s3_base_path']}/{remote_filename}"
    
    cmd = [
        'aws', 's3', 'cp',
        str(local_path),
        s3_path,
        '--endpoint-url', CONFIG['aws_endpoint'],
        '--profile', CONFIG['aws_profile'],
        '--acl', 'public-read'
    ]
    
    ext = Path(local_path).suffix.lower()
    content_types = {'.json': 'application/json', '.csv': 'text/csv'}
    if ext in content_types:
        cmd.extend(['--content-type', content_types[ext]])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            url = f"https://{CONFIG['s3_bucket']}.sfo3.digitaloceanspaces.com/{CONFIG['s3_base_path']}/{remote_filename}"
            logger.info(f"✅ Subido a Spaces: {url}")
            return True
        else:
            logger.error(f"Error subiendo a Spaces: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error en subida a Spaces: {e}")
        return False

def subir_a_sftp(local_path, remote_dir, remote_filename):
    """Sube archivo a GoDaddy via SFTP."""
    env_path = Path('/opt/canalmeteo/scripts/.env')
    sftp_pass = None
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith('SFTP_PASS='):
                    sftp_pass = line.strip().split('=', 1)[1].strip('"\'')
                    break
    
    if not sftp_pass:
        logger.warning("No se encontró SFTP_PASS en .env, saltando SFTP")
        return False
    
    remote_path = f"{CONFIG['sftp_remote_base']}/{remote_dir}/{remote_filename}"
    
    # Crear directorio
    mkdir_cmd = f"sshpass -p '{sftp_pass}' ssh -o StrictHostKeyChecking=no -p {CONFIG['sftp_port']} {CONFIG['sftp_user']}@{CONFIG['sftp_host']} 'mkdir -p {CONFIG['sftp_remote_base']}/{remote_dir}'"
    try:
        subprocess.run(mkdir_cmd, shell=True, capture_output=True, timeout=30)
    except:
        pass
    
    # Subir
    cmd = f"sshpass -p '{sftp_pass}' scp -o StrictHostKeyChecking=no -P {CONFIG['sftp_port']} {local_path} {CONFIG['sftp_user']}@{CONFIG['sftp_host']}:{remote_path}"
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info(f"✅ Subido a SFTP: {remote_path}")
            return True
        else:
            logger.error(f"Error SFTP: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error SFTP: {e}")
        return False

# =========================
# GENERACIÓN DE SALIDAS
# =========================
def generar_json(data, output_path):
    """Genera archivo JSON."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON generado: {output_path}")

def generar_csv(data, output_path):
    """Genera archivo CSV."""
    aeropuertos = data.get('aeropuertos', [])
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Código', 'Aeropuerto', 'Ciudad', 'Estado', 'Demora (min)', 'Motivo'])
        for a in aeropuertos:
            writer.writerow([
                a['codigo'],
                a['nombre'],
                a['ciudad'],
                a['estado'],
                a['demora_minutos'],
                a['motivo_es']
            ])
    
    logger.info(f"CSV generado: {output_path}")

# Importar csv para generar_csv
import csv

# =========================
# FUNCIÓN PRINCIPAL
# =========================
def ejecutar():
    """Ejecuta la recolección y subida de datos."""
    logger.info("=" * 50)
    logger.info("Obteniendo demoras de aeropuertos")
    logger.info("=" * 50)
    
    # Crear directorio de salida
    output_dir = Path(CONFIG['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Obtener datos
    data = obtener_demoras_aeropuertos()
    
    logger.info(f"🛫 {len(data['aeropuertos'])} aeropuertos con demoras significativas")
    logger.info(f"📊 Total con alguna demora: {data['total_con_demora']}")
    
    # Generar archivos
    json_path = output_dir / CONFIG['json_filename']
    csv_path = output_dir / CONFIG['csv_filename']
    
    generar_json(data, json_path)
    generar_csv(data, csv_path)
    
    # Subir a Spaces
    logger.info("☁️ Subiendo a DigitalOcean Spaces...")
    subir_a_spaces(json_path, CONFIG['json_filename'])
    
    # Subir a SFTP
    logger.info("📤 Subiendo a GoDaddy SFTP...")
    subir_a_sftp(csv_path, 'csv', CONFIG['csv_filename'])
    
    logger.info("✅ Proceso completado")
    return data

def main():
    parser = argparse.ArgumentParser(description='Demoras de aeropuertos FAA')
    parser.add_argument('--once', action='store_true', help='Ejecutar una sola vez')
    args = parser.parse_args()
    
    if args.once:
        ejecutar()
    else:
        logger.info(f"Modo continuo - intervalo: {CONFIG['intervalo_segundos']} segundos")
        while True:
            try:
                ejecutar()
            except Exception as e:
                logger.error(f"Error en ejecución: {e}")
            
            logger.info(f"Esperando {CONFIG['intervalo_segundos']} segundos...")
            time.sleep(CONFIG['intervalo_segundos'])

if __name__ == "__main__":
    main()
