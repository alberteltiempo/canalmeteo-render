#!/usr/bin/env python3
"""
Borrasca - NWS Alerts Fetcher v2
================================
Obtiene alertas meteorológicas activas con polígonos completos.

La API del NWS a veces devuelve geometry=null y usa códigos UGC (zonas).
Este script resuelve esas zonas a polígonos reales.

Uso:
    python fetch_alerts.py

Cron (cada 2 minutos para alertas críticas):
    */2 * * * * python fetch_alerts.py
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import setup_logger, upload_to_spaces, DATA_DIR, utcnow

logger = setup_logger('alerts', 'alerts.log')

# =============================================
# CONFIGURACIÓN
# =============================================

NWS_ALERTS_API = 'https://api.weather.gov/alerts/active'
NWS_ZONES_API = 'https://api.weather.gov/zones'

HEADERS = {
    'User-Agent': '(Borrasca/canalmeteo.tv, contact@canalmeteo.tv)',
    'Accept': 'application/geo+json'
}

# Categorías de alertas
CATEGORIES = {
    'extreme': {
        'events': [
            'Tornado Warning', 'Tornado Emergency',
            'Flash Flood Emergency', 'Hurricane Warning',
            'Extreme Wind Warning', 'Storm Surge Warning',
            'Tsunami Warning', 'Blizzard Warning',
            'Excessive Heat Warning'
        ],
        'color_default': '#FF0000'
    },
    'severe': {
        'events': [
            'Tornado Watch', 'Severe Thunderstorm Warning',
            'Flash Flood Warning', 'Hurricane Watch',
            'Tropical Storm Warning', 'Storm Surge Watch',
            'Winter Storm Warning', 'Ice Storm Warning',
            'High Wind Warning', 'Red Flag Warning',
            'Flood Warning'
        ],
        'color_default': '#FFA500'
    },
    'flood': {
        'events': [
            'Flash Flood Warning', 'Flash Flood Watch',
            'Flood Warning', 'Flood Watch', 'Flood Advisory',
            'Coastal Flood Warning', 'Coastal Flood Watch',
            'Coastal Flood Advisory', 'River Flood Warning',
            'Areal Flood Warning', 'Areal Flood Advisory'
        ],
        'color_default': '#00FF00'
    },
    'winter': {
        'events': [
            'Blizzard Warning', 'Winter Storm Warning',
            'Winter Storm Watch', 'Winter Weather Advisory',
            'Ice Storm Warning', 'Freeze Warning',
            'Frost Advisory', 'Wind Chill Warning',
            'Wind Chill Watch', 'Wind Chill Advisory',
            'Lake Effect Snow Warning', 'Lake Effect Snow Watch'
        ],
        'color_default': '#00BFFF'
    }
}

# Colores específicos por evento
EVENT_COLORS = {
    'Tornado Warning': '#FF0000',
    'Tornado Watch': '#FFFF00',
    'Tornado Emergency': '#FF00FF',
    'Severe Thunderstorm Warning': '#FFA500',
    'Severe Thunderstorm Watch': '#DB7093',
    'Flash Flood Warning': '#8B0000',
    'Flash Flood Watch': '#2E8B57',
    'Flood Warning': '#00FF00',
    'Flood Watch': '#2E8B57',
    'Flood Advisory': '#00FF7F',
    'Coastal Flood Warning': '#228B22',
    'Coastal Flood Watch': '#66CDAA',
    'Blizzard Warning': '#FF4500',
    'Winter Storm Warning': '#FF69B4',
    'Winter Storm Watch': '#4682B4',
    'Winter Weather Advisory': '#7B68EE',
    'Ice Storm Warning': '#8B008B',
    'Freeze Warning': '#483D8B',
    'Wind Chill Warning': '#B0C4DE',
    'High Wind Warning': '#DAA520',
    'Wind Advisory': '#D2B48C',
    'Hurricane Warning': '#DC143C',
    'Hurricane Watch': '#FF00FF',
    'Tropical Storm Warning': '#B22222',
    'Tropical Storm Watch': '#F08080',
    'Red Flag Warning': '#FF1493',
    'Excessive Heat Warning': '#C71585',
    'Heat Advisory': '#FF6347',
}

# Cache de zonas (para no descargar repetidamente)
ZONE_CACHE = {}


def fetch_alerts_geojson() -> Optional[dict]:
    """Obtiene todas las alertas activas como GeoJSON."""
    logger.info("Obteniendo alertas del NWS...")
    
    try:
        response = requests.get(NWS_ALERTS_API, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
        count = len(data.get('features', []))
        logger.info(f"Obtenidas {count} alertas")
        return data
    except Exception as e:
        logger.error(f"Error obteniendo alertas: {e}")
        return None


def fetch_zone_geometry(zone_id: str) -> Optional[dict]:
    """Obtiene la geometría de una zona NWS."""
    if zone_id in ZONE_CACHE:
        return ZONE_CACHE[zone_id]
    
    # Determinar tipo de zona
    # Formato: XXC001 (county), XXZ001 (forecast zone)
    if len(zone_id) >= 6:
        state = zone_id[:2]
        zone_type = zone_id[2]
        
        if zone_type == 'C':
            url = f"https://api.weather.gov/zones/county/{zone_id}"
        elif zone_type == 'Z':
            url = f"https://api.weather.gov/zones/forecast/{zone_id}"
        else:
            url = f"https://api.weather.gov/zones/fire/{zone_id}"
    else:
        return None
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            geometry = data.get('geometry')
            ZONE_CACHE[zone_id] = geometry
            return geometry
    except:
        pass
    
    return None


def resolve_alert_geometry(feature: dict) -> Optional[dict]:
    """
    Resuelve la geometría de una alerta.
    Si tiene geometry directo, lo usa.
    Si no, intenta resolver desde las zonas UGC.
    """
    geometry = feature.get('geometry')
    
    if geometry and geometry.get('coordinates'):
        return geometry
    
    # Intentar resolver desde zonas
    props = feature.get('properties', {})
    geocode = props.get('geocode', {})
    ugc_codes = geocode.get('UGC', [])
    
    if not ugc_codes:
        # Intentar extraer de affectedZones
        affected = props.get('affectedZones', [])
        for zone_url in affected:
            # Extraer código de zona de la URL
            if '/zones/' in zone_url:
                parts = zone_url.split('/')
                if len(parts) >= 2:
                    ugc_codes.append(parts[-1])
    
    if not ugc_codes:
        return None
    
    # Obtener geometrías de todas las zonas y combinarlas
    polygons = []
    for ugc in ugc_codes[:10]:  # Limitar a 10 zonas por eficiencia
        geom = fetch_zone_geometry(ugc)
        if geom:
            if geom['type'] == 'Polygon':
                polygons.append(geom['coordinates'])
            elif geom['type'] == 'MultiPolygon':
                polygons.extend(geom['coordinates'])
    
    if not polygons:
        return None
    
    if len(polygons) == 1:
        return {'type': 'Polygon', 'coordinates': polygons[0]}
    else:
        return {'type': 'MultiPolygon', 'coordinates': polygons}


def get_alert_category(event: str) -> str:
    """Determina la categoría de una alerta."""
    event_lower = event.lower()
    
    if 'tornado' in event_lower:
        return 'tornado'
    elif 'flood' in event_lower:
        return 'flood'
    elif any(x in event_lower for x in ['winter', 'snow', 'ice', 'blizzard', 'freeze', 'frost', 'chill']):
        return 'winter'
    elif any(x in event_lower for x in ['hurricane', 'tropical', 'storm surge']):
        return 'tropical'
    elif any(x in event_lower for x in ['heat', 'excessive']):
        return 'heat'
    elif any(x in event_lower for x in ['fire', 'red flag']):
        return 'fire'
    elif any(x in event_lower for x in ['thunderstorm', 'severe']):
        return 'severe'
    elif any(x in event_lower for x in ['wind']):
        return 'wind'
    elif any(x in event_lower for x in ['marine', 'craft', 'gale', 'surf', 'rip']):
        return 'marine'
    else:
        return 'other'


def get_severity_level(event: str) -> str:
    """Determina el nivel de severidad."""
    if any(x in event for x in ['Warning', 'Emergency']):
        if any(x in event for x in ['Tornado', 'Hurricane', 'Tsunami', 'Extreme']):
            return 'extreme'
        return 'severe'
    elif 'Watch' in event:
        return 'moderate'
    elif 'Advisory' in event:
        return 'minor'
    else:
        return 'unknown'


def process_alerts(geojson: dict) -> dict:
    """
    Procesa las alertas y genera estructura con polígonos resueltos.
    - Warnings: se mantienen individuales (urgentes, específicos)
    - Watches y Advisories: se agrupan por tipo
    """
    features = geojson.get('features', [])
    
    # Separar warnings (individuales) de watches/advisories (agrupados)
    individual_alerts = []  # Warnings
    grouped_alerts = {}     # Watches y Advisories
    
    for feature in features:
        props = feature.get('properties', {})
        event = props.get('event', 'Unknown')
        
        # Resolver geometría
        geometry = resolve_alert_geometry(feature)
        
        # Calcular expiración
        expires = props.get('expires')
        expires_in = None
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                delta = exp_dt - now
                expires_in = max(0, int(delta.total_seconds() / 60))
            except:
                pass
        
        category = get_alert_category(event)
        severity = get_severity_level(event)
        color = EVENT_COLORS.get(event, '#808080')
        
        alert_data = {
            'id': props.get('id', ''),
            'event': event,
            'category': category,
            'severity': severity,
            'color': color,
            'headline': props.get('headline', ''),
            'description': props.get('description', ''),
            'instruction': props.get('instruction', ''),
            'areaDesc': props.get('areaDesc', ''),
            'effective': props.get('effective'),
            'onset': props.get('onset'),
            'expires': expires,
            'expires_in_minutes': expires_in,
            'sender': props.get('senderName', ''),
            'geometry': geometry
        }
        
        # Determinar si es warning (individual) o watch/advisory (agrupar)
        is_warning = 'Warning' in event or 'Emergency' in event
        
        if is_warning:
            # Warnings se mantienen individuales
            individual_alerts.append(alert_data)
        else:
            # Watches y Advisories se agrupan por tipo de evento
            if event not in grouped_alerts:
                grouped_alerts[event] = {
                    'event': event,
                    'category': category,
                    'severity': severity,
                    'color': color,
                    'alerts': [],
                    'geometries': [],
                    'areas': [],
                    'expires': expires,
                    'expires_in_minutes': expires_in,
                }
            
            grouped_alerts[event]['alerts'].append(alert_data)
            if geometry:
                grouped_alerts[event]['geometries'].append(geometry)
            
            area = props.get('areaDesc', '')
            if area:
                # Extraer condados/zonas individuales
                for part in area.split(';'):
                    part = part.strip()
                    if part and part not in grouped_alerts[event]['areas']:
                        grouped_alerts[event]['areas'].append(part)
    
    # Construir lista final de alertas
    processed_alerts = []
    alerts_by_category = {
        'tornado': [], 'severe': [], 'flood': [], 'winter': [],
        'tropical': [], 'heat': [], 'fire': [], 'wind': [],
        'marine': [], 'other': []
    }
    geojson_features = []
    
    # 1. Añadir warnings (individuales)
    for alert in individual_alerts:
        alert['has_geometry'] = alert['geometry'] is not None
        alert['area_count'] = 1
        processed_alerts.append(alert)
        alerts_by_category[alert['category']].append(alert)
        
        if alert['geometry']:
            geojson_features.append({
                'type': 'Feature',
                'geometry': alert['geometry'],
                'properties': {
                    'id': alert['id'],
                    'event': alert['event'],
                    'category': alert['category'],
                    'severity': alert['severity'],
                    'color': alert['color'],
                    'headline': alert['headline'],
                    'areaDesc': alert['areaDesc'],
                    'expires_in': alert['expires_in_minutes']
                }
            })
    
    # 2. Añadir watches/advisories (agrupados)
    for event, group in grouped_alerts.items():
        # Crear descripción de área combinada
        areas = group['areas']
        if len(areas) > 3:
            area_desc = '; '.join(areas[:3]) + f' (+{len(areas)-3} zonas más)'
        elif areas:
            area_desc = '; '.join(areas)
        else:
            area_desc = 'Múltiples zonas'
        
        # Combinar geometrías
        combined_geometry = None
        if group['geometries']:
            all_polygons = []
            for geom in group['geometries']:
                if geom['type'] == 'Polygon':
                    all_polygons.append(geom['coordinates'])
                elif geom['type'] == 'MultiPolygon':
                    all_polygons.extend(geom['coordinates'])
            
            if len(all_polygons) == 1:
                combined_geometry = {'type': 'Polygon', 'coordinates': all_polygons[0]}
            elif len(all_polygons) > 1:
                combined_geometry = {'type': 'MultiPolygon', 'coordinates': all_polygons}
        
        # Usar el ID del primer alert del grupo
        first_alert = group['alerts'][0] if group['alerts'] else {}
        
        grouped_alert = {
            'id': first_alert.get('id', event.replace(' ', '_')),
            'event': event,
            'category': group['category'],
            'severity': group['severity'],
            'color': group['color'],
            'headline': first_alert.get('headline', event),
            'description': first_alert.get('description', ''),
            'instruction': first_alert.get('instruction', ''),
            'areaDesc': area_desc,
            'area_count': len(areas),
            'effective': first_alert.get('effective'),
            'onset': first_alert.get('onset'),
            'expires': group['expires'],
            'expires_in_minutes': group['expires_in_minutes'],
            'sender': first_alert.get('sender', ''),
            'has_geometry': combined_geometry is not None,
            'is_grouped': True,
            'alert_count': len(group['alerts'])
        }
        
        processed_alerts.append(grouped_alert)
        alerts_by_category[group['category']].append(grouped_alert)
        
        if combined_geometry:
            geojson_features.append({
                'type': 'Feature',
                'geometry': combined_geometry,
                'properties': {
                    'id': grouped_alert['id'],
                    'event': event,
                    'category': group['category'],
                    'severity': group['severity'],
                    'color': group['color'],
                    'headline': grouped_alert['headline'],
                    'areaDesc': area_desc,
                    'expires_in': group['expires_in_minutes'],
                    'is_grouped': True,
                    'zone_count': len(areas)
                }
            })
    
    # Ordenar por severidad
    severity_order = {'extreme': 0, 'severe': 1, 'moderate': 2, 'minor': 3, 'unknown': 4}
    processed_alerts.sort(key=lambda x: (severity_order.get(x['severity'], 99), x['event']))
    
    return {
        'alerts': processed_alerts,
        'by_category': alerts_by_category,
        'geojson': {
            'type': 'FeatureCollection',
            'features': geojson_features
        },
        'counts': {
            'total': len(processed_alerts),
            'with_geometry': len(geojson_features),
            'tornado': len(alerts_by_category['tornado']),
            'severe': len(alerts_by_category['severe']),
            'flood': len(alerts_by_category['flood']),
            'winter': len(alerts_by_category['winter']),
            'tropical': len(alerts_by_category['tropical']),
        }
    }


def generate_category_geojson(alerts_by_category: dict, all_alerts: list) -> dict:
    """Genera GeoJSON separados por categoría."""
    category_geojsons = {}
    
    for category, alerts in alerts_by_category.items():
        features = []
        for alert in alerts:
            # Buscar el feature con geometría
            alert_id = alert['id']
            # La geometría ya está procesada arriba
            pass
        category_geojsons[category] = {
            'type': 'FeatureCollection',
            'features': features
        }
    
    return category_geojsons


def main():
    logger.info("=" * 60)
    logger.info("BORRASCA - NWS Alerts Fetcher v2")
    logger.info("=" * 60)
    
    # Obtener alertas
    geojson = fetch_alerts_geojson()
    if not geojson:
        logger.error("No se pudieron obtener las alertas")
        return
    
    # Procesar
    logger.info("Procesando alertas y resolviendo geometrías...")
    result = process_alerts(geojson)
    
    # Stats
    counts = result['counts']
    logger.info(f"Total: {counts['total']} alertas, {counts['with_geometry']} con geometría")
    logger.info(f"  Tornado: {counts['tornado']}, Severo: {counts['severe']}, Inundación: {counts['flood']}")
    logger.info(f"  Invierno: {counts['winter']}, Tropical: {counts['tropical']}")
    
    # Subir archivos
    timestamp = utcnow().isoformat() + 'Z'
    
    # Metadata principal
    metadata = {
        'updated_at': timestamp,
        'counts': counts,
        'alerts': result['alerts']
    }
    upload_to_spaces(metadata, 'alerts/alerts.json')
    
    # GeoJSON completo para el mapa
    upload_to_spaces(result['geojson'], 'alerts/alerts.geojson')
    
    # GeoJSON por categoría (para cargar solo lo necesario)
    for category, alerts in result['by_category'].items():
        if alerts:
            # Crear GeoJSON solo con las alertas de esta categoría
            cat_features = [
                f for f in result['geojson']['features']
                if f['properties']['category'] == category
            ]
            cat_geojson = {
                'type': 'FeatureCollection',
                'features': cat_features
            }
            upload_to_spaces(cat_geojson, f'alerts/by_category/{category}.geojson')
    
    logger.info("=" * 60)
    logger.info(f"COMPLETADO: {counts['total']} alertas procesadas")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
