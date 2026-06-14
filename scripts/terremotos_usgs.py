#!/usr/bin/env python3
"""
Canal Meteo TV - Descargador de datos de terremotos del USGS
Descarga terremotos de las últimas 24 horas y genera JSON para la web

Instalación:
    pip install requests boto3 --break-system-packages

Uso:
    python3 terremotos_usgs.py --once       # Ejecutar una vez
    python3 terremotos_usgs.py              # Ejecutar en loop cada 10 minutos

Cron (cada 10 minutos):
    */10 * * * * /usr/bin/python3 /opt/canalmeteo/scripts/terremotos_usgs.py --once >> /var/log/canalmeteo/terremotos.log 2>&1
"""

import requests
import json
import logging
import argparse
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# =========================
# CONFIGURACIÓN
# =========================
CONFIG = {
    # API del USGS - Terremotos últimas 24 horas, todos (magnitud >= 1.0)
    'usgs_url': 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson',
    
    # DigitalOcean Spaces
    'spaces_bucket': 'canalmeteo-public',
    'spaces_region': 'sfo3',
    'spaces_path': 'lynx/datos/terremotos.json',
    'aws_profile': 'do-tor1',
    
    # Intervalo de actualización (segundos)
    'update_interval': 600,  # 10 minutos
    
    # Directorio temporal
    'temp_dir': '/tmp/canalmeteo',
}

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# =========================
# TRADUCCIONES
# =========================
TRADUCCION_TIPOS = {
    'earthquake': 'Terremoto',
    'quarry blast': 'Explosión en cantera',
    'explosion': 'Explosión',
    'ice quake': 'Sismo de hielo',
    'mining explosion': 'Explosión minera',
    'rock burst': 'Estallido de roca',
    'sonic boom': 'Estampido sónico',
    'nuclear explosion': 'Explosión nuclear',
    'landslide': 'Deslizamiento',
    'volcanic eruption': 'Erupción volcánica',
}

TRADUCCION_ALERTA = {
    'green': 'Verde',
    'yellow': 'Amarillo',
    'orange': 'Naranja',
    'red': 'Rojo',
}

TRADUCCION_ESTADO = {
    'automatic': 'Automático',
    'reviewed': 'Revisado',
    'deleted': 'Eliminado',
}

TRADUCCION_TSUNAMI = {
    0: 'No',
    1: 'Sí',
}

# =========================
# FUNCIONES AUXILIARES
# =========================
def get_fecha_hora_local(timestamp_ms):
    """Convierte timestamp en milisegundos a fecha/hora legible."""
    if not timestamp_ms:
        return None, None
    
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    fecha = dt.strftime('%Y-%m-%d')
    hora = dt.strftime('%H:%M:%S UTC')
    return fecha, hora

def get_fecha_es(timestamp_ms):
    """Convierte timestamp a fecha en español."""
    if not timestamp_ms:
        return None
    
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
             'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return f"{dt.day} de {meses[dt.month - 1]} de {dt.year}"

def clasificar_magnitud(mag):
    """Clasifica la magnitud del terremoto."""
    if mag is None:
        return 'desconocido', 'Desconocido'
    
    if mag < 2.0:
        return 'micro', 'Micro'
    elif mag < 4.0:
        return 'menor', 'Menor'
    elif mag < 5.0:
        return 'ligero', 'Ligero'
    elif mag < 6.0:
        return 'moderado', 'Moderado'
    elif mag < 7.0:
        return 'fuerte', 'Fuerte'
    elif mag < 8.0:
        return 'mayor', 'Mayor'
    else:
        return 'gran', 'Gran terremoto'

def get_color_magnitud(mag):
    """Retorna color hexadecimal basado en magnitud."""
    if mag is None:
        return '#808080'  # Gris
    
    if mag < 2.0:
        return '#22c55e'  # Verde
    elif mag < 3.0:
        return '#84cc16'  # Lima
    elif mag < 4.0:
        return '#eab308'  # Amarillo
    elif mag < 5.0:
        return '#f97316'  # Naranja
    elif mag < 6.0:
        return '#ef4444'  # Rojo
    elif mag < 7.0:
        return '#dc2626'  # Rojo oscuro
    else:
        return '#991b1b'  # Rojo muy oscuro

def calcular_radio(mag):
    """Calcula el radio del marcador basado en magnitud."""
    if mag is None:
        return 3
    
    # Radio proporcional a la magnitud
    return max(3, min(20, mag * 2.5))

# =========================
# DESCARGA Y PROCESAMIENTO
# =========================
def descargar_terremotos():
    """Descarga datos de terremotos del USGS."""
    try:
        logger.info("Descargando datos del USGS...")
        response = requests.get(CONFIG['usgs_url'], timeout=30)
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"Descargados {len(data.get('features', []))} terremotos")
        return data
    except Exception as e:
        logger.error(f"Error descargando datos: {e}")
        return None

def procesar_terremotos(data):
    """Procesa los datos del USGS y genera JSON para la web."""
    if not data or 'features' not in data:
        return None
    
    terremotos = []
    
    for feature in data['features']:
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        coords = geom.get('coordinates', [0, 0, 0])
        
        mag = props.get('mag')
        tiempo = props.get('time')
        fecha, hora = get_fecha_hora_local(tiempo)
        clase, clase_es = clasificar_magnitud(mag)
        
        # Extraer toda la información disponible
        terremoto = {
            # Identificación
            'id': feature.get('id', ''),
            'ids': props.get('ids', ''),
            'code': props.get('code', ''),
            
            # Ubicación
            'lugar': props.get('place', 'Ubicación desconocida'),
            'longitud': coords[0] if len(coords) > 0 else 0,
            'latitud': coords[1] if len(coords) > 1 else 0,
            'profundidad': round(coords[2], 1) if len(coords) > 2 else 0,
            'profundidad_unidad': 'km',
            
            # Magnitud
            'magnitud': round(mag, 1) if mag else None,
            'magnitud_tipo': props.get('magType', ''),
            'clase': clase,
            'clase_es': clase_es,
            'color': get_color_magnitud(mag),
            'radio': calcular_radio(mag),
            
            # Tiempo
            'timestamp': tiempo,
            'fecha': fecha,
            'hora': hora,
            'fecha_es': get_fecha_es(tiempo),
            'tiempo_actualizado': props.get('updated'),
            
            # Detalles técnicos
            'tipo': props.get('type', 'earthquake'),
            'tipo_es': TRADUCCION_TIPOS.get(props.get('type', ''), props.get('type', 'Terremoto')),
            'estado': props.get('status', ''),
            'estado_es': TRADUCCION_ESTADO.get(props.get('status', ''), props.get('status', '')),
            
            # Alertas y tsunami
            'alerta': props.get('alert'),
            'alerta_es': TRADUCCION_ALERTA.get(props.get('alert'), props.get('alert')),
            'tsunami': props.get('tsunami', 0),
            'tsunami_es': TRADUCCION_TSUNAMI.get(props.get('tsunami', 0), 'No'),
            
            # Impacto
            'felt': props.get('felt'),  # Número de reportes "lo sentí"
            'cdi': props.get('cdi'),    # Community Decimal Intensity
            'mmi': props.get('mmi'),    # Modified Mercalli Intensity
            'sig': props.get('sig'),    # Significancia (0-1000)
            
            # Precisión
            'nst': props.get('nst'),    # Número de estaciones
            'dmin': props.get('dmin'),  # Distancia mínima a estación
            'rms': props.get('rms'),    # Error RMS
            'gap': props.get('gap'),    # Gap azimutal
            'horizontalError': props.get('horizontalError'),
            'depthError': props.get('depthError'),
            'magError': props.get('magError'),
            'magNst': props.get('magNst'),
            
            # Red sísmica
            'net': props.get('net', ''),
            'sources': props.get('sources', ''),
            
            # Enlaces
            'url_detalle': props.get('url', ''),
            'url_evento': f"https://earthquake.usgs.gov/earthquakes/eventpage/{feature.get('id', '')}",
        }
        
        terremotos.append(terremoto)
    
    # Ordenar por tiempo (más reciente primero)
    terremotos.sort(key=lambda x: x['timestamp'] or 0, reverse=True)
    
    # Marcar el más reciente
    if terremotos:
        terremotos[0]['es_ultimo'] = True
    
    # Estadísticas
    stats = calcular_estadisticas(terremotos)
    
    # Generar JSON final
    resultado = {
        'generado': datetime.now(timezone.utc).isoformat(),
        'fuente': 'USGS Earthquake Hazards Program',
        'url_fuente': 'https://earthquake.usgs.gov/',
        'periodo': 'Últimas 24 horas',
        'total': len(terremotos),
        'estadisticas': stats,
        'ultimo': terremotos[0] if terremotos else None,
        'ultimos_5': terremotos[:5],
        'terremotos': terremotos,
    }
    
    return resultado

def calcular_estadisticas(terremotos):
    """Calcula estadísticas de los terremotos."""
    if not terremotos:
        return {}
    
    magnitudes = [t['magnitud'] for t in terremotos if t['magnitud'] is not None]
    
    stats = {
        'total': len(terremotos),
        'con_magnitud': len(magnitudes),
        'magnitud_maxima': max(magnitudes) if magnitudes else None,
        'magnitud_minima': min(magnitudes) if magnitudes else None,
        'magnitud_promedio': round(sum(magnitudes) / len(magnitudes), 1) if magnitudes else None,
        'por_clase': {
            'micro': len([t for t in terremotos if t['clase'] == 'micro']),
            'menor': len([t for t in terremotos if t['clase'] == 'menor']),
            'ligero': len([t for t in terremotos if t['clase'] == 'ligero']),
            'moderado': len([t for t in terremotos if t['clase'] == 'moderado']),
            'fuerte': len([t for t in terremotos if t['clase'] == 'fuerte']),
            'mayor': len([t for t in terremotos if t['clase'] == 'mayor']),
            'gran': len([t for t in terremotos if t['clase'] == 'gran']),
        },
        'con_alerta_tsunami': len([t for t in terremotos if t['tsunami'] == 1]),
        'reportados_sentidos': len([t for t in terremotos if t['felt'] and t['felt'] > 0]),
    }
    
    return stats

# =========================
# SUBIDA A SPACES
# =========================
def subir_a_spaces(data):
    """Sube el JSON a DigitalOcean Spaces."""
    try:
        # Crear directorio temporal
        temp_dir = Path(CONFIG['temp_dir'])
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Guardar JSON temporal
        temp_file = temp_dir / 'terremotos.json'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"JSON guardado en {temp_file} ({temp_file.stat().st_size / 1024:.1f} KB)")
        
        # Subir a Spaces con AWS CLI
        spaces_url = f"s3://{CONFIG['spaces_bucket']}/{CONFIG['spaces_path']}"
        
        cmd = [
            'aws', 's3', 'cp',
            str(temp_file),
            spaces_url,
            '--endpoint-url', f"https://{CONFIG['spaces_region']}.digitaloceanspaces.com",
            '--acl', 'public-read',
            '--content-type', 'application/json',
            '--profile', CONFIG['aws_profile']
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            public_url = f"https://{CONFIG['spaces_bucket']}.{CONFIG['spaces_region']}.digitaloceanspaces.com/{CONFIG['spaces_path']}"
            logger.info(f"✅ Subido a Spaces: {public_url}")
            return True
        else:
            logger.error(f"Error subiendo a Spaces: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error en subida: {e}")
        return False

# =========================
# EJECUCIÓN PRINCIPAL
# =========================
def ejecutar_una_vez():
    """Ejecuta el proceso una vez."""
    logger.info("=" * 50)
    logger.info("Iniciando descarga de terremotos USGS")
    logger.info("=" * 50)
    
    # Descargar datos
    data = descargar_terremotos()
    if not data:
        logger.error("No se pudieron descargar los datos")
        return None
    
    # Procesar
    resultado = procesar_terremotos(data)
    if not resultado:
        logger.error("Error procesando datos")
        return None
    
    logger.info(f"Procesados {resultado['total']} terremotos")
    
    if resultado['ultimo']:
        ultimo = resultado['ultimo']
        logger.info(f"Último terremoto: M{ultimo['magnitud']} - {ultimo['lugar']}")
    
    # Subir a Spaces
    if subir_a_spaces(resultado):
        logger.info("✅ Proceso completado exitosamente")
    else:
        logger.warning("⚠️ Proceso completado pero con errores en la subida")
    
    return resultado

def ejecutar_loop():
    """Ejecuta el proceso en loop continuo."""
    logger.info("Iniciando modo loop...")
    
    while True:
        try:
            ejecutar_una_vez()
        except Exception as e:
            logger.error(f"Error en iteración: {e}")
        
        logger.info(f"Esperando {CONFIG['update_interval']} segundos...")
        time.sleep(CONFIG['update_interval'])

def main():
    parser = argparse.ArgumentParser(description='Descargador de terremotos USGS')
    parser.add_argument('--once', action='store_true', help='Ejecutar una sola vez')
    parser.add_argument('--verbose', action='store_true', help='Mostrar JSON completo')
    args = parser.parse_args()
    
    if args.once:
        resultado = ejecutar_una_vez()
        if args.verbose and resultado:
            print(json.dumps(resultado, indent=2, ensure_ascii=False))
        elif resultado:
            stats = resultado.get('estadisticas', {})
            logger.info(f"📊 Estadísticas:")
            logger.info(f"   Total: {stats.get('total', 0)}")
            logger.info(f"   Magnitud máx: {stats.get('magnitud_maxima', 'N/A')}")
            logger.info(f"   Con alerta tsunami: {stats.get('con_alerta_tsunami', 0)}")
    else:
        ejecutar_loop()

if __name__ == '__main__':
    main()
