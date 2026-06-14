#!/usr/bin/env python3
"""
Script para obtener récords meteorológicos del día del SPC, WPC y NWS.
Genera JSON y CSV con datos, y mapas PNG estilizados.

Ubicación: /opt/canalmeteo/scripts/records_spc.py

Salidas:
- JSON a DigitalOcean Spaces: /lynx/datos/records.json
- CSV a GoDaddy SFTP: /lynx/csv/records.csv
- Mapas PNG a ambos destinos

Uso:
    python records_spc.py         # Ejecución normal
    python records_spc.py --once  # Una sola ejecución (sin loop)
    
Cron recomendado (cada 30 min):
    */30 * * * * /usr/bin/python3 /opt/canalmeteo/scripts/records_spc.py --once >> /var/log/canalmeteo/records.log 2>&1
"""

import os
import sys
import json
import csv
import io
import re
import requests
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
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
    # Fuentes de datos
    'wpc_url': 'https://www.wpc.ncep.noaa.gov/discussions/hpcdiscussions.php?disc=nathilo&version=0&fmt=reg',
    'spc_tornado_csv': 'https://www.spc.noaa.gov/climo/reports/today_filtered_torn.csv',
    'spc_hail_csv': 'https://www.spc.noaa.gov/climo/reports/today_filtered_hail.csv',
    'spc_wind_csv': 'https://www.spc.noaa.gov/climo/reports/today_filtered_wind.csv',
    'nws_alerts_api': 'https://api.weather.gov/alerts/active',
    
    # Shapefiles
    'estados_shp': '/home/canalmeteo/lynx/data/shapefiles/tl_2023_us_state.shp',
    
    # Salidas locales
    'output_dir': '/tmp/canalmeteo/records',
    'json_filename': 'records.json',
    'csv_filename': 'records.csv',
    'map_tornado': 'reportes-tornado.png',
    'map_hail': 'reportes-granizo.png',
    'map_wind': 'reportes-viento.png',
    
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
    'user_agent': 'CanalMeteoApp/1.0 (contacto@canalmeteo.tv)',
    'intervalo_segundos': 1800,  # 30 minutos
}

# Meses en español
MESES_ES = {
    'January': 'enero', 'February': 'febrero', 'March': 'marzo',
    'April': 'abril', 'May': 'mayo', 'June': 'junio',
    'July': 'julio', 'August': 'agosto', 'September': 'septiembre',
    'October': 'octubre', 'November': 'noviembre', 'December': 'diciembre'
}

# Colores para mapas
COLORES = {
    'tornado': '#DC2626',    # Rojo
    'hail': '#2563EB',       # Azul
    'wind': '#059669',       # Verde
    'land': '#F8FAFC',       # Gris muy claro
    'border': '#94A3B8',     # Gris
    'water': '#E0F2FE',      # Azul claro
    'text': '#1E293B',       # Gris oscuro
}

# =========================
# UTILIDADES
# =========================
def get_fecha_hoy():
    """Retorna fecha de hoy en español."""
    hoy = datetime.now()
    return f"{hoy.day} de {MESES_ES[hoy.strftime('%B')]} de {hoy.year}"

def formatear_fecha_wpc(fecha_str):
    """Convierte fecha del WPC a español."""
    try:
        dt = datetime.strptime(fecha_str.strip(), "%A, %B %d, %Y")
        return f"{dt.day} de {MESES_ES[dt.strftime('%B')]} de {dt.year}"
    except:
        return get_fecha_hoy()

def descargar_csv(url):
    """Descarga CSV del SPC y retorna DataFrame."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        return df
    except Exception as e:
        logger.warning(f"Error descargando {url}: {e}")
        return pd.DataFrame()

def contar_filas_csv(url):
    """Cuenta filas de un CSV remoto."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        return max(0, len(lines) - 1)  # Restar header
    except:
        return 0

# =========================
# EXTRACCIÓN DE DATOS
# =========================
def extraer_temperaturas_wpc():
    """Extrae temperaturas máximas y mínimas del WPC."""
    records = []
    fecha_hoy = get_fecha_hoy()
    
    try:
        response = requests.get(CONFIG['wpc_url'], timeout=20)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        logger.error(f"Error descargando WPC: {e}")
        return records

    # Buscar High Temperature con regex más preciso
    # Formato: "High Temperature for Saturday, December  6, 2025"
    # seguido de "89 at 3 miles east-southeast of Sunniland, FL"
    high_match = re.search(
        r'High Temperature for\s+\w+,\s+(\w+\s+\d+,\s+\d+).*?(\d+)\s+at\s+(.+?),\s*([A-Z]{2})',
        content, re.DOTALL
    )
    
    if high_match:
        try:
            fecha = formatear_fecha_wpc(high_match.group(1).strip())
            valor = int(high_match.group(2))
            ciudad = re.sub(r'\s+', ' ', high_match.group(3).strip())
            # Limpiar ciudad (quitar "3 miles east-southeast of")
            ciudad = re.sub(r'^\d+\s+miles?\s+\w+-?\w*\s+of\s+', '', ciudad, flags=re.IGNORECASE)
            ciudad = ciudad.strip().title()
            estado = high_match.group(4).strip()
            
            records.append({
                'tipo': 'temperatura_maxima',
                'valor': valor,
                'unidad': '°F',
                'ciudad': ciudad,
                'estado': estado,
                'fecha': fecha
            })
            logger.info(f"Temp máxima: {valor}°F en {ciudad}, {estado}")
        except Exception as e:
            logger.warning(f"Error procesando temp máxima: {e}")
    
    # Buscar Low Temperature
    low_match = re.search(
        r'Low Temperature for\s+\w+,\s+(\w+\s+\d+,\s+\d+).*?(-?\d+)\s+at\s+(.+?),\s*([A-Z]{2})',
        content, re.DOTALL
    )
    
    if low_match:
        try:
            fecha = formatear_fecha_wpc(low_match.group(1).strip())
            valor = int(low_match.group(2))
            ciudad = re.sub(r'\s+', ' ', low_match.group(3).strip())
            ciudad = re.sub(r'^\d+\s+miles?\s+\w+-?\w*\s+of\s+', '', ciudad, flags=re.IGNORECASE)
            ciudad = ciudad.strip().title()
            estado = low_match.group(4).strip()
            
            records.append({
                'tipo': 'temperatura_minima',
                'valor': valor,
                'unidad': '°F',
                'ciudad': ciudad,
                'estado': estado,
                'fecha': fecha
            })
            logger.info(f"Temp mínima: {valor}°F en {ciudad}, {estado}")
        except Exception as e:
            logger.warning(f"Error procesando temp mínima: {e}")

    return records

def extraer_reportes_spc():
    """Extrae conteo de reportes del SPC."""
    fecha_hoy = get_fecha_hoy()
    
    reportes = {
        'tornados': {
            'total': contar_filas_csv(CONFIG['spc_tornado_csv']),
            'fecha': fecha_hoy
        },
        'granizo': {
            'total': contar_filas_csv(CONFIG['spc_hail_csv']),
            'fecha': fecha_hoy
        },
        'viento': {
            'total': contar_filas_csv(CONFIG['spc_wind_csv']),
            'fecha': fecha_hoy
        }
    }
    
    return reportes

def extraer_maximos_spc():
    """Extrae valores máximos del día del SPC."""
    fecha_hoy = get_fecha_hoy()
    maximos = []
    
    # Viento máximo
    df_wind = descargar_csv(CONFIG['spc_wind_csv'])
    if not df_wind.empty and 'Speed' in df_wind.columns:
        try:
            df_wind['Speed'] = pd.to_numeric(df_wind['Speed'], errors='coerce')
            idx = df_wind['Speed'].idxmax()
            if pd.notna(idx):
                row = df_wind.loc[idx]
                loc = row.get('Location', '').strip()
                ciudad = loc.split(',')[0].strip().title() if ',' in loc else loc.title()
                maximos.append({
                    'tipo': 'viento_maximo',
                    'valor': int(row['Speed']),
                    'unidad': 'mph',
                    'ciudad': ciudad,
                    'estado': row.get('State', '').strip(),
                    'fecha': fecha_hoy
                })
        except Exception as e:
            logger.warning(f"Error extrayendo viento máximo: {e}")
    
    # Granizo máximo
    df_hail = descargar_csv(CONFIG['spc_hail_csv'])
    if not df_hail.empty and 'Size' in df_hail.columns:
        try:
            df_hail['Size'] = pd.to_numeric(df_hail['Size'], errors='coerce') / 100  # Convertir a pulgadas
            idx = df_hail['Size'].idxmax()
            if pd.notna(idx):
                row = df_hail.loc[idx]
                loc = row.get('Location', '').strip()
                ciudad = loc.split(',')[0].strip().title() if ',' in loc else loc.title()
                maximos.append({
                    'tipo': 'granizo_maximo',
                    'valor': round(row['Size'], 2),
                    'unidad': '"',
                    'ciudad': ciudad,
                    'estado': row.get('State', '').strip(),
                    'fecha': fecha_hoy
                })
        except Exception as e:
            logger.warning(f"Error extrayendo granizo máximo: {e}")
    
    return maximos

def extraer_alertas_nws():
    """Cuenta alertas activas del NWS por tipo."""
    fecha_hoy = get_fecha_hoy()
    alertas = {
        'tormentas': 0,
        'tornados': 0,
        'inundaciones': 0,
        'fecha': fecha_hoy
    }
    
    try:
        headers = {'User-Agent': CONFIG['user_agent']}
        response = requests.get(CONFIG['nws_alerts_api'], headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        for feature in data.get('features', []):
            event = feature['properties'].get('event', '')
            if event == 'Severe Thunderstorm Warning':
                alertas['tormentas'] += 1
            elif event == 'Tornado Warning':
                alertas['tornados'] += 1
            elif 'Flood' in event or 'Flash Flood' in event:
                alertas['inundaciones'] += 1
                
    except Exception as e:
        logger.error(f"Error obteniendo alertas NWS: {e}")
    
    return alertas

# =========================
# GENERACIÓN DE MAPAS
# =========================
def cargar_estados_conus():
    """Carga shapefile de estados CONUS."""
    try:
        gdf = gpd.read_file(CONFIG['estados_shp']).to_crs("EPSG:4326")
        conus = gdf[~gdf["STUSPS"].isin(["AK", "HI", "PR", "VI", "GU", "MP", "AS"])]
        return conus
    except Exception as e:
        logger.error(f"Error cargando shapefile: {e}")
        return None

def generar_mapa_vacio(output_path, titulo):
    """Genera un mapa vacío cuando no hay datos."""
    fig, ax = plt.subplots(figsize=(12, 7), facecolor='white')
    ax.text(0.5, 0.5, f"No hay reportes de {titulo.lower()} hoy",
            ha='center', va='center', fontsize=16, color=COLORES['text'],
            fontfamily='sans-serif')
    ax.axis("off")
    
    # Watermark
    fig.text(0.98, 0.02, "Elaborado para Canal Meteo", 
             ha='right', va='bottom', fontsize=9, 
             color='#64748B', style='italic', alpha=0.8)
    
    plt.savefig(output_path, dpi=150, bbox_inches="tight", 
                facecolor='white', edgecolor='none')
    plt.close()
    logger.info(f"Mapa vacío generado: {output_path}")

def generar_mapa_reportes(output_path, titulo, url_csv, color, marker):
    """Genera mapa estilizado de reportes."""
    # Descargar datos
    df = descargar_csv(url_csv)
    
    if df.empty or not {'Lat', 'Lon'}.issubset(df.columns):
        generar_mapa_vacio(output_path, titulo)
        return
    
    df = df.dropna(subset=['Lat', 'Lon'])
    if df.empty:
        generar_mapa_vacio(output_path, titulo)
        return
    
    # Crear GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df, 
        geometry=gpd.points_from_xy(df['Lon'], df['Lat']), 
        crs="EPSG:4326"
    )
    
    # Filtrar a CONUS
    bounds = {'min_lon': -125, 'max_lon': -66.5, 'min_lat': 24, 'max_lat': 50}
    gdf = gdf.cx[bounds['min_lon']:bounds['max_lon'], bounds['min_lat']:bounds['max_lat']]
    
    if gdf.empty:
        generar_mapa_vacio(output_path, titulo)
        return
    
    # Cargar estados
    estados = cargar_estados_conus()
    
    # Crear figura
    fig, ax = plt.subplots(figsize=(14, 8), facecolor='white')
    
    # Dibujar estados
    if estados is not None:
        estados.plot(ax=ax, facecolor=COLORES['land'], 
                    edgecolor=COLORES['border'], linewidth=0.5)
    
    # Dibujar puntos
    gdf.plot(ax=ax, color=color, markersize=50, marker=marker, 
             alpha=0.7, edgecolor='white', linewidth=0.5)
    
    # Configurar límites
    ax.set_xlim(bounds['min_lon'], bounds['max_lon'])
    ax.set_ylim(bounds['min_lat'], bounds['max_lat'])
    
    # Título
    fecha_hoy = get_fecha_hoy()
    ax.set_title(f"Reportes de {titulo} - {fecha_hoy}", 
                fontsize=16, fontweight='bold', color=COLORES['text'],
                fontfamily='sans-serif', pad=15)
    
    # Leyenda
    legend_patch = mpatches.Patch(color=color, label=f'{titulo}: {len(gdf)} reportes')
    ax.legend(handles=[legend_patch], loc='lower left', fontsize=10,
             framealpha=0.9, edgecolor='none')
    
    # Quitar ejes
    ax.axis('off')
    
    # Watermark
    fig.text(0.98, 0.02, "Elaborado para Canal Meteo", 
             ha='right', va='bottom', fontsize=10, 
             color='#64748B', style='italic', alpha=0.8)
    
    # Guardar
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close()
    logger.info(f"Mapa generado: {output_path} ({len(gdf)} puntos)")

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
    
    # Añadir content-type según extensión
    ext = Path(local_path).suffix.lower()
    content_types = {
        '.json': 'application/json',
        '.csv': 'text/csv',
        '.png': 'image/png'
    }
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
    """Sube archivo a GoDaddy via SFTP usando sshpass."""
    # Leer contraseña del .env si existe
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
    
    # Crear directorio remoto si no existe
    mkdir_cmd = f"sshpass -p '{sftp_pass}' ssh -o StrictHostKeyChecking=no -p {CONFIG['sftp_port']} {CONFIG['sftp_user']}@{CONFIG['sftp_host']} 'mkdir -p {CONFIG['sftp_remote_base']}/{remote_dir}'"
    
    try:
        subprocess.run(mkdir_cmd, shell=True, capture_output=True, timeout=30)
    except:
        pass
    
    # Subir archivo
    cmd = f"sshpass -p '{sftp_pass}' scp -o StrictHostKeyChecking=no -P {CONFIG['sftp_port']} {local_path} {CONFIG['sftp_user']}@{CONFIG['sftp_host']}:{remote_path}"
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info(f"✅ Subido a SFTP: {remote_path}")
            return True
        else:
            logger.error(f"Error subiendo a SFTP: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error en subida SFTP: {e}")
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
    """Genera archivo CSV desde los datos."""
    rows = []
    
    # Temperaturas
    for temp in data.get('temperaturas', []):
        rows.append([
            'Máxima' if temp['tipo'] == 'temperatura_maxima' else 'Mínima',
            f"{temp['valor']}{temp['unidad']}",
            temp['ciudad'],
            temp['estado'],
            temp['fecha']
        ])
    
    # Reportes
    reportes = data.get('reportes', {})
    for tipo, info in reportes.items():
        rows.append([tipo.capitalize(), info['total'], '-', '-', info['fecha']])
    
    # Máximos
    for maximo in data.get('maximos', []):
        label = 'Viento máximo' if maximo['tipo'] == 'viento_maximo' else 'Granizo máximo'
        rows.append([
            label,
            f"{maximo['valor']}{maximo['unidad']}",
            maximo['ciudad'],
            maximo['estado'],
            maximo['fecha']
        ])
    
    # Alertas
    alertas = data.get('alertas', {})
    rows.append(['Alertas por tormenta', alertas.get('tormentas', 0), '-', '-', alertas.get('fecha', '')])
    rows.append(['Alertas por tornado', alertas.get('tornados', 0), '-', '-', alertas.get('fecha', '')])
    rows.append(['Alertas por inundación', alertas.get('inundaciones', 0), '-', '-', alertas.get('fecha', '')])
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Variable', 'Valor', 'Ciudad', 'Estado', 'Fecha'])
        writer.writerows(rows)
    
    logger.info(f"CSV generado: {output_path}")

# =========================
# FUNCIÓN PRINCIPAL
# =========================
def ejecutar():
    """Ejecuta la recolección de datos y generación de salidas."""
    logger.info("=" * 50)
    logger.info("Iniciando recolección de datos meteorológicos")
    logger.info("=" * 50)
    
    # Crear directorio de salida
    output_dir = Path(CONFIG['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Recolectar datos
    logger.info("📊 Extrayendo temperaturas del WPC...")
    temperaturas = extraer_temperaturas_wpc()
    
    logger.info("🌪️ Extrayendo reportes del SPC...")
    reportes = extraer_reportes_spc()
    
    logger.info("🏆 Extrayendo máximos del día...")
    maximos = extraer_maximos_spc()
    
    logger.info("🚨 Contando alertas del NWS...")
    alertas = extraer_alertas_nws()
    
    # Estructura de datos completa
    data = {
        'generado': datetime.now(timezone.utc).isoformat(),
        'fecha_local': get_fecha_hoy(),
        'temperaturas': temperaturas,
        'reportes': reportes,
        'maximos': maximos,
        'alertas': alertas,
        'mapas': {
            'tornado': f"https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CONFIG['s3_base_path']}/{CONFIG['map_tornado']}",
            'granizo': f"https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CONFIG['s3_base_path']}/{CONFIG['map_hail']}",
            'viento': f"https://canalmeteo-public.sfo3.digitaloceanspaces.com/{CONFIG['s3_base_path']}/{CONFIG['map_wind']}"
        }
    }
    
    # Generar archivos locales
    json_path = output_dir / CONFIG['json_filename']
    csv_path = output_dir / CONFIG['csv_filename']
    
    generar_json(data, json_path)
    generar_csv(data, csv_path)
    
    # Generar mapas
    logger.info("🗺️ Generando mapas de reportes...")
    map_tornado_path = output_dir / CONFIG['map_tornado']
    map_hail_path = output_dir / CONFIG['map_hail']
    map_wind_path = output_dir / CONFIG['map_wind']
    
    generar_mapa_reportes(map_tornado_path, "Tornados", 
                         CONFIG['spc_tornado_csv'], COLORES['tornado'], '^')
    generar_mapa_reportes(map_hail_path, "Granizo",
                         CONFIG['spc_hail_csv'], COLORES['hail'], 'o')
    generar_mapa_reportes(map_wind_path, "Viento",
                         CONFIG['spc_wind_csv'], COLORES['wind'], 's')
    
    # Subir a DigitalOcean Spaces
    logger.info("☁️ Subiendo a DigitalOcean Spaces...")
    subir_a_spaces(json_path, CONFIG['json_filename'])
    subir_a_spaces(map_tornado_path, CONFIG['map_tornado'])
    subir_a_spaces(map_hail_path, CONFIG['map_hail'])
    subir_a_spaces(map_wind_path, CONFIG['map_wind'])
    
    # Subir CSV a SFTP (GoDaddy)
    logger.info("📤 Subiendo CSV a GoDaddy SFTP...")
    subir_a_sftp(csv_path, 'csv', CONFIG['csv_filename'])
    subir_a_sftp(map_tornado_path, 'mapas', CONFIG['map_tornado'])
    subir_a_sftp(map_hail_path, 'mapas', CONFIG['map_hail'])
    subir_a_sftp(map_wind_path, 'mapas', CONFIG['map_wind'])
    
    logger.info("✅ Proceso completado")
    return data

def main():
    parser = argparse.ArgumentParser(description='Recolector de récords meteorológicos')
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
