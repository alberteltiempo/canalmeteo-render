#!/usr/bin/env python3
"""
Canal Meteo TV - Descarga de Incendios Activos
Fuente: National Interagency Fire Center (NIFC)
Actualización: Cada hora
"""

import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
import requests
import boto3
from botocore.exceptions import ClientError

# Configuración
CONFIG = {
    # NIFC Public Data - Fuentes que NO requieren autenticación
    # WFIGS Interagency Perimeters (la que funcionó antes) - filtrado por fecha reciente
    'nifc_incidents_url': 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0/query?where=poly_DateCurrent%20%3E%3D%20CURRENT_TIMESTAMP%20-%20INTERVAL%20%2730%27%20DAY&outFields=*&outSR=4326&f=geojson',
    # Alternativa sin filtro de fecha (filtramos en código)
    'nifc_perimeters_url': 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultRecordCount=100',
    # Tercera opción (limitada a 100 más recientes)
    'nifc_active_fires_url': 'https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&orderByFields=poly_DateCurrent%20DESC&resultRecordCount=100',
    'data_dir': '/opt/canalmeteo/data/fires',
    'raw_dir': '/opt/canalmeteo/data/fires/raw',
    'output_json': 'fires.json',
    'output_geojson': 'perimeters.geojson',
    's3_bucket': 'canalmeteo-public',
    's3_region': 'sfo3',
    's3_path': 'fires',
    's3_endpoint': 'https://sfo3.digitaloceanspaces.com',
    'log_file': '/opt/canalmeteo/logs/fires.log',
    'min_acres': 100,  # Solo incendios grandes (activos importantes)
    'days_back': 90,  # Últimos 90 días
    'only_active': True  # Solo incendios NO completamente contenidos
}

def setup_logging():
    """Configurar logging"""
    os.makedirs(os.path.dirname(CONFIG['log_file']), exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(CONFIG['log_file']),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def download_nifc_data(url, logger):
    """Descargar datos del NIFC"""
    try:
        logger.info(f"Descargando datos de: {url[:100]}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Verificar que tiene la estructura esperada
        if isinstance(data, dict):
            # GeoJSON format
            if 'features' in data:
                logger.info(f"Descargados {len(data.get('features', []))} features (GeoJSON)")
                return data
            # IRWIN format (features en data.features)
            elif 'error' in data:
                logger.error(f"Error del API: {data.get('error')}")
                return None
        
        logger.warning(f"Respuesta inesperada del API (tipo: {type(data).__name__})")
        return data
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al descargar datos: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error al parsear JSON: {e}")
        return None

def process_fire_data(geojson_data, logger):
    """Procesar datos de incendios y crear JSON simplificado"""
    from datetime import datetime, timedelta
    
    fires = []
    
    if not geojson_data or 'features' not in geojson_data:
        logger.warning("No hay datos de incendios disponibles")
        return None, None
    
    features = geojson_data.get('features', [])
    logger.info(f"Procesando {len(features)} incendios...")
    
    # Calcular fecha límite (X días atrás)
    cutoff_date = datetime.now() - timedelta(days=CONFIG['days_back'])
    logger.info(f"Filtrando incendios desde: {cutoff_date.strftime('%Y-%m-%d')}")
    
    # Filtrar y procesar incendios activos
    active_count = 0
    filtered_by_date = 0
    filtered_by_acres = 0
    
    for feature in features:
        props = feature.get('properties', {})
        geom = feature.get('geometry', {})
        
        # Filtrar por fecha primero
        fire_date = None
        for field in ['attr_FireDiscoveryDateTime', 'FireDiscoveryDateTime', 'poly_DateCurrent', 'StartDate', 'DiscoveryDate', 'CreateDate', 'DateCurrent', 'poly_CreateDate']:
            if field in props and props[field]:
                try:
                    date_str = str(props[field])
                    # Intentar parsear fecha (puede estar en milisegundos epoch o ISO)
                    if date_str.isdigit():
                        # Epoch en milisegundos
                        fire_date = datetime.fromtimestamp(int(date_str) / 1000)
                    else:
                        # ISO o string de fecha
                        fire_date = datetime.fromisoformat(date_str.replace('Z', '+00:00').split('+')[0].split('.')[0])
                    break
                except:
                    continue
        
        # Si tiene fecha y es muy viejo, saltar
        if fire_date and fire_date < cutoff_date:
            filtered_by_date += 1
            continue
        
        # Intentar obtener acres de varios campos posibles (orden de prioridad)
        acres = 0
        acres_field_found = None
        for field in ['poly_GISAcres', 'attr_IncidentSize', 'GISAcres', 'DailyAcres', 
                      'CalculatedAcres', 'MapAcres', 'acres', 'ACRES', 'poly_Acres_AutoCalc',
                      'attr_DailyAcres', 'attr_GISAcres', 'IncidentSize', 'FireSize', 'Area']:
            if field in props and props[field] is not None:
                try:
                    val = float(props[field])
                    if val > 0:
                        acres = val
                        acres_field_found = field
                        break
                except (ValueError, TypeError):
                    continue
        
        # Solo incendios activos mayores al mínimo
        if acres < CONFIG['min_acres']:
            filtered_by_acres += 1
            continue
        
        # Obtener coordenadas (centroide si es polígono)
        coords = None
        if geom.get('type') == 'Point':
            coords = geom.get('coordinates', [])
        elif geom.get('type') == 'Polygon' and geom.get('coordinates'):
            # Calcular centroide simple del primer anillo
            ring = geom['coordinates'][0]
            if len(ring) > 0:
                lons = [c[0] for c in ring]
                lats = [c[1] for c in ring]
                coords = [sum(lons)/len(lons), sum(lats)/len(lats)]
        elif geom.get('type') == 'MultiPolygon' and geom.get('coordinates'):
            # Usar primer polígono
            if len(geom['coordinates']) > 0 and len(geom['coordinates'][0]) > 0:
                ring = geom['coordinates'][0][0]
                if len(ring) > 0:
                    lons = [c[0] for c in ring]
                    lats = [c[1] for c in ring]
                    coords = [sum(lons)/len(lons), sum(lats)/len(lats)]
        
        if not coords or len(coords) < 2:
            continue
        
        # Obtener nombre del incendio de varios campos posibles
        incident_name = None
        for field in ['poly_IncidentName', 'attr_IncidentName', 'IncidentName', 'FireName', 'Name', 'INCIDENTNAME']:
            if field in props and props[field] and str(props[field]).strip():
                incident_name = str(props[field]).strip()
                break
        
        if not incident_name or incident_name.lower() == 'none':
            incident_name = f'Incendio {active_count + 1}'
        
        # Obtener ID único
        fire_id = None
        for field in ['attr_IrwinID', 'poly_IRWINID', 'IRWINID', 'UniqueFireIdentifier', 'attr_UniqueFireIdentifier', 'IncidentID', 'ID', 'OBJECTID']:
            if field in props and props[field]:
                fire_id = str(props[field])
                break
        
        if not fire_id:
            fire_id = f"FIRE_{active_count}_{datetime.now().strftime('%Y%m%d')}"
        
        # Obtener estado
        state = None
        for field in ['attr_POOState', 'POOState', 'INCIWEBState', 'State', 'STATE', 'poly_State']:
            if field in props and props[field]:
                state = str(props[field])
                # Convertir formato US-WA a WA
                if state.startswith('US-'):
                    state = state[3:]
                break
        
        if not state:
            state = 'Unknown'
        
        # Obtener contención
        containment = 0
        for field in ['attr_PercentContained', 'PercentContained', 'PercentageContained', 'Containment', 'poly_PercentContained']:
            if field in props and props[field] is not None:
                try:
                    containment = int(float(props[field]))
                    break
                except (ValueError, TypeError):
                    continue
        
        # Si only_active está activado, filtrar incendios 100% contenidos
        if CONFIG.get('only_active', False) and containment >= 100:
            continue
        
        # Construir registro de incendio
        fire = {
            'id': fire_id,
            'name': incident_name,
            'state': state,
            'county': props.get('attr_POOCounty') or props.get('POOCounty') or props.get('County', ''),
            'lat': coords[1],
            'lng': coords[0],
            'acres': round(acres, 1),
            'containment': max(0, min(100, containment)),  # Limitar 0-100
            'start_date': fire_date.strftime('%Y-%m-%d') if fire_date else '',
            'cause': props.get('attr_FireCause') or props.get('FireCause', 'Under Investigation'),
            'personnel': 0,
            'structures_threatened': 0,
            'structures_destroyed': 0,
            'status': 'active' if containment < 100 else 'contained',
            'updated': props.get('CreateDate') or props.get('DateCurrent') or datetime.utcnow().isoformat()
        }
        
        # Intentar obtener personal
        for field in ['TotalIncidentPersonnel', 'Personnel', 'CrewsInvolved']:
            if field in props and props[field]:
                try:
                    fire['personnel'] = int(props[field])
                    break
                except (ValueError, TypeError):
                    pass
        
        fires.append(fire)
        active_count += 1
    
    logger.info(f"Incendios procesados: {active_count}")
    logger.info(f"Filtrados por fecha (>{CONFIG['days_back']} días): {filtered_by_date}")
    logger.info(f"Filtrados por tamaño (<{CONFIG['min_acres']} acres): {filtered_by_acres}")
    
    if active_count == 0:
        logger.warning("No se encontraron incendios activos que cumplan los criterios")
        logger.warning(f"Total features: {len(features)}, Filtrados por fecha: {filtered_by_date}, Filtrados por acres: {filtered_by_acres}")
        
        # Crear archivo vacío válido para que la web no falle
        logger.info("Creando archivo JSON vacío para la web...")
        output = {
            'updated': datetime.utcnow().isoformat() + 'Z',
            'total_fires': 0,
            'total_acres': 0,
            'avg_containment': 0,
            'fires': [],
            'message': f'No active fires found in last {CONFIG["days_back"]} days with minimum {CONFIG["min_acres"]} acres'
        }
        
        filtered_geojson = {
            'type': 'FeatureCollection',
            'updated': datetime.utcnow().isoformat() + 'Z',
            'features': []
        }
        
        return output, filtered_geojson
    
    # Crear JSON de salida
    output = {
        'updated': datetime.utcnow().isoformat() + 'Z',
        'total_fires': len(fires),
        'total_acres': round(sum(f['acres'] for f in fires), 1),
        'avg_containment': round(sum(f['containment'] for f in fires) / len(fires), 1) if fires else 0,
        'fires': sorted(fires, key=lambda x: x['acres'], reverse=True)  # Ordenar por tamaño
    }
    
    # Mantener GeoJSON original para perímetros (filtrado)
    filtered_geojson = {
        'type': 'FeatureCollection',
        'updated': datetime.utcnow().isoformat() + 'Z',
        'features': []
    }
    
    # Solo incluir features de incendios activos
    fire_ids = {f['id'] for f in fires}
    for feature in geojson_data['features']:
        props = feature.get('properties', {})
        fid = None
        for field in ['IRWINID', 'UniqueFireIdentifier', 'IncidentID', 'ID', 'OBJECTID']:
            if field in props and props[field]:
                fid = str(props[field])
                break
        
        if fid in fire_ids:
            filtered_geojson['features'].append(feature)
    
    return output, filtered_geojson

def save_data(data, filepath, logger):
    """Guardar datos en archivo JSON"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Datos guardados en: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar datos: {e}")
        return False

def upload_to_spaces(local_path, s3_key, logger):
    """Subir archivo a DigitalOcean Spaces"""
    try:
        # Configurar cliente S3 para DigitalOcean Spaces
        session = boto3.session.Session()
        client = session.client('s3',
                              region_name=CONFIG['s3_region'],
                              endpoint_url=CONFIG['s3_endpoint'],
                              aws_access_key_id=os.environ.get('SPACES_ACCESS_KEY'),
                              aws_secret_access_key=os.environ.get('SPACES_SECRET_KEY'))
        
        # Subir archivo
        logger.info(f"Subiendo {local_path} a Spaces...")
        client.upload_file(
            local_path,
            CONFIG['s3_bucket'],
            s3_key,
            ExtraArgs={
                'ACL': 'public-read',
                'ContentType': 'application/json'
            }
        )
        
        # Generar URL pública
        public_url = f"https://{CONFIG['s3_bucket']}.{CONFIG['s3_region']}.digitaloceanspaces.com/{s3_key}"
        logger.info(f"Archivo subido exitosamente")
        return public_url
    
    except ClientError as e:
        logger.error(f"Error al subir a Spaces: {e}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al subir: {e}")
        return None

def main():
    """Función principal"""
    logger = setup_logging()
    
    logger.info("=" * 60)
    logger.info("Descargando INCENDIOS ACTIVOS del NIFC")
    logger.info("Fuentes: IRWIN Active Incidents, InciWeb, Current Locations")
    logger.info("=" * 60)
    
    # Crear directorios
    os.makedirs(CONFIG['data_dir'], exist_ok=True)
    os.makedirs(CONFIG['raw_dir'], exist_ok=True)
    
    # Intentar descargar de múltiples fuentes
    geojson_data = None
    
    logger.info("Paso 1: Descargando incendios activos...")
    
    # Intentar primera URL (con filtro de fecha de últimos 30 días)
    logger.info("Intentando fuente 1: WFIGS Perimeters (últimos 30 días)...")
    geojson_data = download_nifc_data(CONFIG['nifc_incidents_url'], logger)
    
    # Si falla, intentar segunda URL (top 100 sin filtro de fecha)
    if not geojson_data or not geojson_data.get('features'):
        logger.info("Intentando fuente 2: WFIGS Perimeters (top 100)...")
        geojson_data = download_nifc_data(CONFIG['nifc_perimeters_url'], logger)
    
    # Si falla, intentar tercera URL (100 más recientes ordenados)
    if not geojson_data or not geojson_data.get('features'):
        logger.info("Intentando fuente 3: WFIGS Perimeters (100 más recientes)...")
        geojson_data = download_nifc_data(CONFIG['nifc_active_fires_url'], logger)
    
    if not geojson_data or not geojson_data.get('features'):
        logger.error("No se pudieron descargar datos de ninguna fuente. Abortando.")
        return 1
    
    logger.info(f"✓ Datos descargados exitosamente: {len(geojson_data.get('features', []))} features")
    
    # Guardar datos raw
    raw_geojson_path = os.path.join(CONFIG['raw_dir'], f"raw_fires_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson")
    save_data(geojson_data, raw_geojson_path, logger)
    
    # Procesar datos
    logger.info("Paso 2: Procesando datos...")
    fires_json, perimeters_geojson = process_fire_data(geojson_data, logger)
    
    if not fires_json:
        logger.error("Error crítico al procesar datos. Abortando.")
        return 1
    
    if fires_json['total_fires'] == 0:
        logger.warning("⚠️  No hay incendios activos actualmente")
        logger.info("Se creará un archivo JSON vacío para que la web muestre '0 incendios'")
    else:
        logger.info(f"Total de incendios activos: {fires_json['total_fires']}")
        logger.info(f"Total de acres quemados: {fires_json['total_acres']:,.0f}")
        logger.info(f"Contención promedio: {fires_json['avg_containment']}%")
    
    # Guardar JSON local
    logger.info("Paso 3: Guardando archivos locales...")
    json_path = os.path.join(CONFIG['data_dir'], CONFIG['output_json'])
    geojson_path = os.path.join(CONFIG['data_dir'], CONFIG['output_geojson'])
    
    if not save_data(fires_json, json_path, logger):
        return 1
    
    if perimeters_geojson:
        save_data(perimeters_geojson, geojson_path, logger)
    
    # Subir a DigitalOcean Spaces
    logger.info("Paso 4: Subiendo a DigitalOcean Spaces...")
    
    # Subir JSON
    s3_json_key = f"{CONFIG['s3_path']}/current.json"
    json_url = upload_to_spaces(json_path, s3_json_key, logger)
    
    if json_url:
        logger.info(f"JSON URL: {json_url}")
    else:
        logger.error("No se pudo subir JSON a Spaces")
        return 1
    
    # Subir GeoJSON de perímetros
    if perimeters_geojson:
        s3_geojson_key = f"{CONFIG['s3_path']}/perimeters.geojson"
        geojson_url = upload_to_spaces(geojson_path, s3_geojson_key, logger)
        
        if geojson_url:
            logger.info(f"GeoJSON URL: {geojson_url}")
    
    logger.info("=" * 60)
    logger.info("Descarga completada exitosamente")
    logger.info("=" * 60)
    return 0

if __name__ == '__main__':
    sys.exit(main())
