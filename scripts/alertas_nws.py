#!/usr/bin/env python3
"""
Script para obtener alertas del NWS, calcular población afectada
y generar JSON para el dashboard de Canal Meteo.

Ubicación: /opt/canalmeteo/scripts/alertas_nws.py
Sube a S3 via AWS CLI

Uso:
    python alertas_nws.py         # Loop continuo
    python alertas_nws.py --once  # Una sola ejecución
    
CAMBIOS v3:
- Warnings se mantienen individuales (urgentes, específicos)
- Watches y Advisories se agrupan por tipo de evento
- Cálculo de población mejorado usando geometría real del polígono
- Prioridad: Tornado Warning > Severe Thunderstorm Warning > Tornado Watch > 
  Severe Thunderstorm Watch > Flash Flood Warning > Flood Warning > otros
- Traducción completa al español
"""

import json
import requests
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from datetime import datetime, timezone
from pathlib import Path
import time
import logging
import argparse
import subprocess
import re

# Configuración
CONFIG = {
    'nws_api': 'https://api.weather.gov/alerts/active?status=actual&message_type=alert',
    'zonas_shp': '/home/canalmeteo/lynx/data/shapefiles/z_18mr25.shp',
    'fire_zones_shp': '/home/canalmeteo/lynx/data/shapefiles/fz18mr25.shp',
    'condados_shp': '/home/canalmeteo/lynx/data/shapefiles/tl_2023_us_county.shp',
    'poblacion_csv': '/home/canalmeteo/lynx/data/census/poblacion_ready.csv',
    'output_json': '/mnt/canalmeteo_data_01/alertas/alertas_nws.json',
    
    # AWS/Spaces config
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_path': 'data/alertas/alertas_nws.json',
    's3_url': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/alertas/alertas_nws.json',
    
    'intervalo_segundos': 15,
    'max_alertas': 60,  # subido de 15: el tope ordenado por prioridad descartaba
    'user_agent': 'CanalMeteoApp/1.0 (contacto@canalmeteo.tv)',
}

# Estados CONUS (48 estados contiguos + DC)
ESTADOS_CONUS = {
    'AL', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'ID', 'IL', 'IN', 'IA',
    'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV',
    'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD',
    'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
}

# Códigos excluidos (marinos, Alaska, Hawaii, territorios)
CODIGOS_EXCLUIDOS = {'AK', 'HI', 'PR', 'VI', 'GU', 'AS', 'MP', 'PZ', 'AM', 'GM', 
                     'PH', 'PS', 'PM', 'AN', 'SL', 'LC', 'LM', 'LH', 'LE', 'LO', 'LS', 'PK', 'AR'}

# FIPS de estado
ESTADO_A_FIPS = {
    'AL': '01', 'AZ': '04', 'AR': '05', 'CA': '06', 'CO': '08', 'CT': '09', 'DE': '10',
    'FL': '12', 'GA': '13', 'ID': '16', 'IL': '17', 'IN': '18', 'IA': '19', 'KS': '20',
    'KY': '21', 'LA': '22', 'ME': '23', 'MD': '24', 'MA': '25', 'MI': '26', 'MN': '27',
    'MS': '28', 'MO': '29', 'MT': '30', 'NE': '31', 'NV': '32', 'NH': '33', 'NJ': '34',
    'NM': '35', 'NY': '36', 'NC': '37', 'ND': '38', 'OH': '39', 'OK': '40', 'OR': '41',
    'PA': '42', 'RI': '44', 'SC': '45', 'SD': '46', 'TN': '47', 'TX': '48', 'UT': '49',
    'VT': '50', 'VA': '51', 'WA': '53', 'WV': '54', 'WI': '55', 'WY': '56', 'DC': '11'
}

NOMBRES_ESTADOS = {
    'AL': 'Alabama', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California', 'CO': 'Colorado',
    'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas', 'KY': 'Kentucky',
    'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan',
    'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska',
    'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon',
    'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota',
    'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia',
    'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
}

# Prioridad de eventos (menor número = mayor prioridad)
PRIORIDAD_EVENTOS = {
    # Tornados - máxima prioridad
    'Tornado Emergency': 1,
    'Tornado Warning': 2,
    'Tornado Watch': 10,
    
    # Tormentas severas
    'Severe Thunderstorm Warning': 3,
    'Severe Thunderstorm Watch': 11,
    
    # Inundaciones
    'Flash Flood Emergency': 4,
    'Flash Flood Warning': 5,
    'Flash Flood Watch': 12,
    'Flood Warning': 6,
    'Flood Watch': 13,
    'Flood Advisory': 20,
    'Coastal Flood Warning': 7,
    'Coastal Flood Watch': 14,
    'Coastal Flood Advisory': 21,
    
    # Huracanes/Tropicales
    'Hurricane Warning': 8,
    'Hurricane Watch': 15,
    'Tropical Storm Warning': 9,
    'Tropical Storm Watch': 16,
    'Storm Surge Warning': 8,
    'Storm Surge Watch': 15,
    
    # Invierno
    'Blizzard Warning': 30,
    'Ice Storm Warning': 31,
    'Winter Storm Warning': 32,
    'Winter Storm Watch': 40,
    'Winter Weather Advisory': 50,
    'Wind Chill Warning': 33,
    'Wind Chill Watch': 41,
    'Wind Chill Advisory': 51,
    'Freeze Warning': 34,
    'Freeze Watch': 42,
    'Frost Advisory': 52,
    'Hard Freeze Warning': 34,
    'Hard Freeze Watch': 42,
    'Lake Effect Snow Warning': 35,
    'Lake Effect Snow Watch': 43,
    
    # Viento
    'Extreme Wind Warning': 36,
    'High Wind Warning': 37,
    'High Wind Watch': 44,
    'Wind Advisory': 53,
    
    # Calor/Fuego
    'Excessive Heat Warning': 38,
    'Excessive Heat Watch': 45,
    'Extreme Heat Warning': 38,
    'Extreme Heat Watch': 45,
    'Heat Advisory': 54,
    'Red Flag Warning': 39,
    'Fire Weather Watch': 46,
    
    # Otros
    'Dense Fog Advisory': 55,
    'Dust Storm Warning': 56,
    'Special Weather Statement': 60,
}

# Traducción de eventos - CORREGIDO: "tiempo" en lugar de "clima"
TRADUCCION_EVENTOS = {
    # Tornados
    'Tornado Emergency': 'Emergencia de tornado',
    'Tornado Warning': 'Aviso de tornado',
    'Tornado Watch': 'Vigilancia de tornado',
    
    # Tormentas severas
    'Severe Thunderstorm Warning': 'Aviso de tormenta severa',
    'Severe Thunderstorm Watch': 'Vigilancia de tormenta severa',
    'Severe Weather Statement': 'Comunicado de tiempo severo',
    
    # Inundaciones
    'Flash Flood Emergency': 'Emergencia de inundación repentina',
    'Flash Flood Warning': 'Aviso de inundación repentina',
    'Flash Flood Watch': 'Vigilancia de inundación repentina',
    'Flash Flood Statement': 'Comunicado de inundación repentina',
    'Flood Warning': 'Aviso de inundación',
    'Flood Watch': 'Vigilancia de inundación',
    'Flood Advisory': 'Advertencia de inundación',
    'Flood Statement': 'Comunicado de inundación',
    'Coastal Flood Warning': 'Aviso de inundación costera',
    'Coastal Flood Watch': 'Vigilancia de inundación costera',
    'Coastal Flood Advisory': 'Advertencia de inundación costera',
    'Coastal Flood Statement': 'Comunicado de inundación costera',
    'River Flood Warning': 'Aviso de inundación fluvial',
    'River Flood Watch': 'Vigilancia de inundación fluvial',
    'River Flood Advisory': 'Advertencia de inundación fluvial',
    'River Flood Statement': 'Comunicado de inundación fluvial',
    'Areal Flood Warning': 'Aviso de inundación de área',
    'Areal Flood Watch': 'Vigilancia de inundación de área',
    'Areal Flood Advisory': 'Advertencia de inundación de área',
    'Urban And Small Stream Flood Advisory': 'Advertencia de inundación urbana',
    'Hydrologic Outlook': 'Perspectiva hidrológica',
    'Hydrologic Statement': 'Comunicado hidrológico',
    
    # Huracanes/Tropicales
    'Hurricane Warning': 'Aviso de huracán',
    'Hurricane Watch': 'Vigilancia de huracán',
    'Hurricane Statement': 'Comunicado de huracán',
    'Hurricane Local Statement': 'Comunicado local de huracán',
    'Tropical Storm Warning': 'Aviso de tormenta tropical',
    'Tropical Storm Watch': 'Vigilancia de tormenta tropical',
    'Tropical Storm Statement': 'Comunicado de tormenta tropical',
    'Tropical Depression Local Statement': 'Comunicado local de depresión tropical',
    'Storm Surge Warning': 'Aviso de marejada ciclónica',
    'Storm Surge Watch': 'Vigilancia de marejada ciclónica',
    'Extreme Wind Warning': 'Aviso de vientos extremos',
    'Typhoon Warning': 'Aviso de tifón',
    'Typhoon Watch': 'Vigilancia de tifón',
    
    # Invierno - CORREGIDO: "tiempo invernal" en lugar de "clima invernal"
    'Blizzard Warning': 'Aviso de ventisca',
    'Blizzard Watch': 'Vigilancia de ventisca',
    'Ice Storm Warning': 'Aviso de tormenta de hielo',
    'Winter Storm Warning': 'Aviso de tormenta invernal',
    'Winter Storm Watch': 'Vigilancia de tormenta invernal',
    'Winter Weather Advisory': 'Advertencia de tiempo invernal',
    'Wind Chill Warning': 'Aviso de sensación térmica extrema',
    'Wind Chill Watch': 'Vigilancia de sensación térmica',
    'Wind Chill Advisory': 'Advertencia de sensación térmica',
    'Freeze Warning': 'Aviso de helada',
    'Freeze Watch': 'Vigilancia de helada',
    'Frost Advisory': 'Advertencia de escarcha',
    'Hard Freeze Warning': 'Aviso de helada severa',
    'Hard Freeze Watch': 'Vigilancia de helada severa',
    'Lake Effect Snow Warning': 'Aviso de nieve por efecto lacustre',
    'Lake Effect Snow Watch': 'Vigilancia de nieve por efecto lacustre',
    'Lake Effect Snow Advisory': 'Advertencia de nieve por efecto lacustre',
    'Heavy Snow Warning': 'Aviso de nevada intensa',
    'Snow Squall Warning': 'Aviso de turbonada de nieve',
    'Freezing Rain Advisory': 'Advertencia de lluvia helada',
    'Freezing Spray Advisory': 'Advertencia de rocío helado',
    'Sleet Advisory': 'Advertencia de aguanieve',
    'Sleet Warning': 'Aviso de aguanieve',
    'Avalanche Warning': 'Aviso de avalancha',
    'Avalanche Watch': 'Vigilancia de avalancha',
    'Avalanche Advisory': 'Advertencia de avalancha',
    
    # Frío extremo
    'Extreme Cold Warning': 'Aviso de frío extremo',
    'Extreme Cold Watch': 'Vigilancia de frío extremo',
    'Cold Weather Advisory': 'Advertencia de tiempo frío',
    
    # Viento
    'High Wind Warning': 'Aviso de vientos fuertes',
    'High Wind Watch': 'Vigilancia de vientos fuertes',
    'Wind Advisory': 'Advertencia de viento',
    'Lake Wind Advisory': 'Advertencia de viento lacustre',
    'Dust Storm Warning': 'Aviso de tormenta de polvo',
    'Dust Storm Watch': 'Vigilancia de tormenta de polvo',
    'Dust Advisory': 'Advertencia de polvo',
    'Blowing Dust Warning': 'Aviso de polvo en suspensión',
    'Blowing Dust Advisory': 'Advertencia de polvo en suspensión',
    
    # Calor
    'Excessive Heat Warning': 'Aviso de calor excesivo',
    'Excessive Heat Watch': 'Vigilancia de calor excesivo',
    'Extreme Heat Warning': 'Aviso de calor extremo',
    'Extreme Heat Watch': 'Vigilancia de calor extremo',
    'Heat Advisory': 'Advertencia de calor',
    
    # Fuego - CORREGIDO: "tiempo propicio para incendios"
    'Red Flag Warning': 'Aviso de bandera roja',
    'Fire Warning': 'Aviso de incendio',
    'Fire Weather Watch': 'Vigilancia de tiempo propicio para incendios',
    
    # Niebla
    'Dense Fog Advisory': 'Advertencia de niebla densa',
    'Freezing Fog Advisory': 'Advertencia de niebla helada',
    'Dense Smoke Advisory': 'Advertencia de humo denso',
    
    # Oleaje y costa - NUEVO/CORREGIDO
    'High Surf Warning': 'Aviso de fuerte oleaje',
    'High Surf Advisory': 'Advertencia de fuerte oleaje',
    'Beach Hazards Statement': 'Comunicado de peligros en la playa',
    'Rip Current Statement': 'Comunicado de corrientes de resaca',
    'Sneaker Wave Warning': 'Aviso de olas traicioneras',
    'Tsunami Warning': 'Aviso de tsunami',
    'Tsunami Watch': 'Vigilancia de tsunami',
    'Tsunami Advisory': 'Advertencia de tsunami',
    
    # Marinos (por si acaso se filtran algunos)
    'Gale Warning': 'Aviso de temporal',
    'Gale Watch': 'Vigilancia de temporal',
    'Storm Warning': 'Aviso de tormenta',
    'Storm Watch': 'Vigilancia de tormenta',
    'Small Craft Advisory': 'Advertencia para embarcaciones menores',
    'Hazardous Seas Warning': 'Aviso de mar peligroso',
    'Hazardous Seas Watch': 'Vigilancia de mar peligroso',
    'Marine Weather Statement': 'Comunicado marítimo',
    'Special Marine Warning': 'Aviso marítimo especial',
    'Lakeshore Flood Warning': 'Aviso de inundación costera lacustre',
    'Lakeshore Flood Watch': 'Vigilancia de inundación costera lacustre',
    'Lakeshore Flood Advisory': 'Advertencia de inundación costera lacustre',
    'Lakeshore Flood Statement': 'Comunicado de inundación costera lacustre',
    
    # Aire y calidad
    'Air Quality Alert': 'Alerta de calidad del aire',
    'Air Stagnation Advisory': 'Advertencia de estancamiento del aire',
    
    # Otros comunicados
    'Special Weather Statement': 'Comunicado meteorológico especial',
    'Short Term Forecast': 'Pronóstico a corto plazo',
    'Hazardous Weather Outlook': 'Perspectiva de tiempo peligroso',
    'Local Area Emergency': 'Emergencia de área local',
    'Shelter In Place Warning': 'Aviso de refugio en el lugar',
    'Civil Danger Warning': 'Aviso de peligro civil',
    'Nuclear Power Plant Warning': 'Aviso de planta nuclear',
    'Radiological Hazard Warning': 'Aviso de peligro radiológico',
    'Hazardous Materials Warning': 'Aviso de materiales peligrosos',
    'Fire Warning': 'Aviso de incendio',
    'Civil Emergency Message': 'Mensaje de emergencia civil',
    'Law Enforcement Warning': 'Aviso policial',
    'Evacuation - Immediate': 'Evacuación inmediata',
    '911 Telephone Outage Emergency': 'Emergencia de interrupción del 911',
}

# Colores por evento
COLORES_EVENTOS = {
    'Tornado Warning': '#FF0000',
    'Tornado Emergency': '#FF00FF',
    'Tornado Watch': '#FFFF00',
    'Severe Thunderstorm Warning': '#FFA500',
    'Severe Thunderstorm Watch': '#DB7093',
    'Flash Flood Warning': '#8B0000',
    'Flash Flood Watch': '#2E8B57',
    'Flash Flood Emergency': '#8B0000',
    'Flood Warning': '#00FF00',
    'Flood Watch': '#2E8B57',
    'Flood Advisory': '#00FF7F',
    'Coastal Flood Warning': '#228B22',
    'Coastal Flood Watch': '#66CDAA',
    'Hurricane Warning': '#DC143C',
    'Hurricane Watch': '#FF00FF',
    'Tropical Storm Warning': '#B22222',
    'Tropical Storm Watch': '#F08080',
    'Storm Surge Warning': '#B22222',
    'Storm Surge Watch': '#DB7093',
    'Blizzard Warning': '#FF4500',
    'Winter Storm Warning': '#FF69B4',
    'Winter Storm Watch': '#4682B4',
    'Winter Weather Advisory': '#7B68EE',
    'Ice Storm Warning': '#8B008B',
    'Freeze Warning': '#483D8B',
    'Wind Chill Warning': '#B0C4DE',
    'High Wind Warning': '#DAA520',
    'Wind Advisory': '#D2B48C',
    'Red Flag Warning': '#FF1493',
    'Excessive Heat Warning': '#C71585',
    'Heat Advisory': '#FF6347',
    'High Surf Warning': '#228B22',
    'High Surf Advisory': '#3CB371',
}

# Traducción de hazards
TRADUCCION_HAZARDS = {
    'Tornado': 'Tornado',
    'Damaging winds': 'Vientos dañinos',
    'Large hail': 'Granizo grande',
    'Flash flooding': 'Inundación repentina',
    'Flooding': 'Inundación',
    'Severe thunderstorm': 'Tormenta severa',
    'Hail': 'Granizo',
    'Wind': 'Viento',
}

# Traducción de sources
TRADUCCION_SOURCES = {
    'Radar indicated': 'Indicado por radar',
    'Radar indicated rotation': 'Rotación indicada por radar',
    'Trained weather spotters': 'Observadores meteorológicos',
    'Law enforcement': 'Autoridades policiales',
    'Emergency management': 'Gestión de emergencias',
    'Public': 'Público',
    'Doppler radar': 'Radar Doppler',
    'Weather spotters': 'Observadores del tiempo',
    'Trained spotters': 'Observadores entrenados',
}

# Traducción de damage threat
TRADUCCION_DAMAGE_THREAT = {
    'CONSIDERABLE': 'CONSIDERABLE',
    'CATASTROPHIC': 'CATASTRÓFICO',
    'DESTRUCTIVE': 'DESTRUCTIVO',
    'SIGNIFICANT': 'SIGNIFICATIVO',
}

# Traducción de impacts comunes
TRADUCCION_IMPACTS = {
    'Expect damage to roofs, siding, and trees.': 'Se esperan daños en techos, revestimientos y árboles.',
    'Flying debris will be dangerous to those caught without shelter.': 'Los escombros voladores serán peligrosos para quienes no tengan refugio.',
    'Mobile homes will be damaged or destroyed.': 'Las casas móviles serán dañadas o destruidas.',
    'Damage to mobile homes, roofs, and outbuildings is possible.': 'Son posibles daños en casas móviles, techos y construcciones exteriores.',
    'People and animals outdoors will be injured.': 'Las personas y animales al aire libre resultarán heridos.',
    'Vehicles may be tossed.': 'Los vehículos pueden ser lanzados.',
    'Life-threatening flash flooding is possible.': 'Son posibles inundaciones repentinas que amenazan la vida.',
    'Localized flooding is expected.': 'Se esperan inundaciones localizadas.',
    'Minor flooding in low-lying areas.': 'Inundaciones menores en áreas bajas.',
    'Property damage is likely.': 'Es probable que haya daños materiales.',
    'Power outages are likely.': 'Es probable que haya cortes de energía.',
    'Tree limbs may fall.': 'Las ramas de los árboles pueden caer.',
    'Travel will be hazardous.': 'Viajar será peligroso.',
    'Some trees may be blown down.': 'Algunos árboles pueden ser derribados.',
}

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class AlertasNWS:
    def __init__(self):
        self.zonas_gdf = None
        self.fire_zones_gdf = None
        self.condados_gdf = None
        self.poblacion_df = None
        self.condados_con_poblacion = None
        self._cargar_datos()

    def _cargar_datos(self):
        """Carga shapefiles y datos de población una sola vez."""
        logger.info("Cargando datos geográficos...")
        
        # Cargar zonas forecast NWS (Z zones)
        try:
            self.zonas_gdf = gpd.read_file(CONFIG['zonas_shp'])
            logger.info(f"Zonas forecast cargadas: {len(self.zonas_gdf)}")
        except Exception as e:
            logger.error(f"Error cargando zonas forecast: {e}")
            self.zonas_gdf = None

        # Cargar fire weather zones (F zones)
        try:
            self.fire_zones_gdf = gpd.read_file(CONFIG['fire_zones_shp'])
            logger.info(f"Fire zones cargadas: {len(self.fire_zones_gdf)}")
        except Exception as e:
            logger.error(f"Error cargando fire zones: {e}")
            self.fire_zones_gdf = None

        # Cargar condados
        try:
            self.condados_gdf = gpd.read_file(CONFIG['condados_shp'])
            self.condados_gdf['FIPS5'] = self.condados_gdf['STATEFP'] + self.condados_gdf['COUNTYFP']
            logger.info(f"Condados cargados: {len(self.condados_gdf)}")
        except Exception as e:
            logger.error(f"Error cargando condados: {e}")
            self.condados_gdf = None

        # Cargar población
        try:
            self.poblacion_df = pd.read_csv(CONFIG['poblacion_csv'])
            self.poblacion_df['FIPS5'] = self.poblacion_df['FIPS6'].astype(str).str.zfill(5)
            logger.info(f"Población cargada: {len(self.poblacion_df)} registros")
            
            if self.condados_gdf is not None:
                self.condados_con_poblacion = self.condados_gdf.merge(
                    self.poblacion_df[['FIPS5', 'POPESTIMATE2023']],
                    on='FIPS5',
                    how='left'
                )
                # Calcular densidad de población por área
                self.condados_con_poblacion['area_km2'] = self.condados_con_poblacion.geometry.to_crs(epsg=5070).area / 1e6
                self.condados_con_poblacion['densidad'] = self.condados_con_poblacion['POPESTIMATE2023'] / self.condados_con_poblacion['area_km2']
        except Exception as e:
            logger.error(f"Error cargando población: {e}")
            self.poblacion_df = None

    def _es_alerta_conus(self, alerta):
        """Verifica si la alerta es de CONUS (48 estados contiguos)."""
        props = alerta.get('properties', {})
        geocode = props.get('geocode', {})
        ugc_codes = geocode.get('UGC', [])
        
        for code in ugc_codes:
            if len(code) >= 2:
                estado = code[:2]
                if estado in CODIGOS_EXCLUIDOS:
                    return False
                if estado in ESTADOS_CONUS:
                    return True
        return False

    def _extraer_estado(self, alerta):
        """Extrae el código de estado de una alerta."""
        props = alerta.get('properties', {})
        geocode = props.get('geocode', {})
        ugc_codes = geocode.get('UGC', [])
        
        for code in ugc_codes:
            if len(code) >= 2:
                estado = code[:2]
                if estado in ESTADOS_CONUS:
                    return estado
        return None

    def _extraer_estados_multiple(self, alerta):
        """Extrae todos los estados de una alerta."""
        props = alerta.get('properties', {})
        geocode = props.get('geocode', {})
        ugc_codes = geocode.get('UGC', [])
        
        estados = set()
        for code in ugc_codes:
            if len(code) >= 2:
                estado = code[:2]
                if estado in ESTADOS_CONUS:
                    estados.add(estado)
        return list(estados)

    def _obtener_geometria_alerta(self, alerta):
        """Obtiene la geometría de una alerta (del propio alerta o de las zonas UGC)."""
        props = alerta.get('properties', {})
        geometry = alerta.get('geometry')
        geocode = props.get('geocode', {})
        ugc_codes = geocode.get('UGC', [])
        
        # 1. Si la alerta tiene geometría propia, usarla
        if geometry and geometry.get('coordinates'):
            return geometry
        
        # 2. Buscar geometrías en los shapefiles
        geometrias = []
        
        for code in ugc_codes:
            if len(code) < 6:
                continue
                
            estado = code[:2]
            tipo = code[2]  # Z, C, o F
            numero = code[3:]
            
            found_geom = None
            
            # Buscar en zonas forecast (Z) o fire zones (números >= 200)
            if tipo == 'Z':
                zone_code = estado + numero
                
                # Primero buscar en forecast zones
                if self.zonas_gdf is not None:
                    match = self.zonas_gdf[self.zonas_gdf['STATE_ZONE'] == zone_code]
                    if len(match) > 0:
                        found_geom = match.iloc[0].geometry
                
                # Si no encontró y el número es >= 200, buscar en fire zones
                if found_geom is None and int(numero) >= 200 and self.fire_zones_gdf is not None:
                    match = self.fire_zones_gdf[self.fire_zones_gdf['STATE_ZONE'] == zone_code]
                    if len(match) > 0:
                        found_geom = match.iloc[0].geometry
            
            # Buscar en fire zones (F)
            elif tipo == 'F' and self.fire_zones_gdf is not None:
                zone_code = estado + numero
                match = self.fire_zones_gdf[self.fire_zones_gdf['STATE_ZONE'] == zone_code]
                if len(match) > 0:
                    found_geom = match.iloc[0].geometry
            
            # Buscar en condados (C)
            elif tipo == 'C' and self.condados_gdf is not None:
                fips = ESTADO_A_FIPS.get(estado, '') + numero
                match = self.condados_gdf[self.condados_gdf['FIPS5'] == fips]
                if len(match) > 0:
                    found_geom = match.iloc[0].geometry
            
            if found_geom is not None:
                geometrias.append(found_geom)
        
        # Unir todas las geometrías encontradas
        if geometrias:
            try:
                union = unary_union(geometrias)
                return mapping(union)
            except Exception as e:
                logger.warning(f"Error uniendo geometrías: {e}")
        
        return None

    def _calcular_poblacion_geometria(self, geometry):
        """
        Calcula la población afectada por una geometría.
        """
        if self.condados_con_poblacion is None or not geometry:
            return 0
        
        try:
            alert_shape = shape(geometry)
            
            # Crear GeoDataFrame temporal con la geometría
            alert_gdf = gpd.GeoDataFrame(
                geometry=[alert_shape], 
                crs='EPSG:4326'
            )
            
            # Proyectar a un CRS apropiado para cálculos de área (CONUS Albers)
            alert_projected = alert_gdf.to_crs(epsg=5070)
            condados_projected = self.condados_con_poblacion.to_crs(epsg=5070)
            
            poblacion_total = 0
            
            # Calcular intersección con cada condado
            for idx, condado in condados_projected.iterrows():
                if condado.geometry is None:
                    continue
                
                try:
                    intersection = alert_projected.iloc[0].geometry.intersection(condado.geometry)
                    
                    if not intersection.is_empty:
                        # Calcular proporción del condado afectada
                        area_interseccion = intersection.area / 1e6  # km²
                        area_condado = condado.geometry.area / 1e6  # km²
                        
                        if area_condado > 0:
                            proporcion = min(area_interseccion / area_condado, 1.0)
                            poblacion_condado = condado.get('POPESTIMATE2023', 0)
                            
                            if pd.notna(poblacion_condado):
                                poblacion_afectada = int(poblacion_condado * proporcion)
                                poblacion_total += poblacion_afectada
                except Exception:
                    continue
            
            return poblacion_total
                
        except Exception as e:
            logger.warning(f"Error calculando población por geometría: {e}")
            return 0

    def _calcular_poblacion(self, alerta):
        """Calcula la población afectada por una alerta."""
        geometry = self._obtener_geometria_alerta(alerta)
        
        if geometry:
            poblacion = self._calcular_poblacion_geometria(geometry)
            if poblacion > 0:
                return poblacion
        
        # Método fallback: usar códigos FIPS
        if self.condados_con_poblacion is None:
            return 0
            
        props = alerta.get('properties', {})
        geocode = props.get('geocode', {})
        fips_codes = geocode.get('SAME', [])
        
        poblacion_total = 0
        for fips in fips_codes:
            fips5 = fips[1:] if len(fips) == 6 else fips
            match = self.condados_con_poblacion[self.condados_con_poblacion['FIPS5'] == fips5]
            if len(match) > 0:
                pop = match.iloc[0].get('POPESTIMATE2023', 0)
                if pd.notna(pop):
                    poblacion_total += int(pop)
        
        return poblacion_total

    def _extraer_campos_descripcion(self, description):
        """Extrae campos específicos del texto de descripción."""
        if not description:
            return {}
        
        campos = {}
        
        patrones = {
            'hazard': r'HAZARD\.{3}(.+?)(?:\n\n|\*|$)',
            'impact': r'IMPACT\.{3}(.+?)(?:\n\n|\*|$)',
            'max_hail': r'MAX HAIL SIZE\.{3}(.+?)(?:\n|\*|$)',
            'max_wind': r'MAX WIND GUST\.{3}(.+?)(?:\n|\*|$)',
            'source': r'SOURCE\.{3}(.+?)(?:\n\n|\*|$)',
            'tornado': r'TORNADO\.{3}(.+?)(?:\n|\*|$)',
            'hail_threat': r'HAIL THREAT\.{3}(.+?)(?:\n|\*|$)',
            'wind_threat': r'WIND THREAT\.{3}(.+?)(?:\n|\*|$)',
            'damage_threat': r'TORNADO DAMAGE THREAT\.{3}(.+?)(?:\n|\*|$)',
        }
        
        patrones_alt = {
            'hazard': r'\* HAZARD\.{3}(.+?)(?:\n|$)',
            'impact': r'\* IMPACT\.{3}(.+?)(?:\n|$)',
            'source': r'\* SOURCE\.{3}(.+?)(?:\n|$)',
            'damage_threat': r'\* TORNADO DAMAGE THREAT\.{3}(.+?)(?:\n|$)',
        }
        
        for campo, patron in patrones.items():
            match = re.search(patron, description, re.IGNORECASE | re.DOTALL)
            if match:
                valor = match.group(1).strip()
                valor = ' '.join(valor.split())
                campos[campo] = valor
        
        for campo, patron in patrones_alt.items():
            if campo not in campos:
                match = re.search(patron, description, re.IGNORECASE)
                if match:
                    valor = match.group(1).strip()
                    valor = ' '.join(valor.split())
                    campos[campo] = valor
        
        return campos

    def _traducir_hazard(self, hazard):
        """Traduce el hazard al español."""
        if not hazard:
            return ''
        
        hazard_lower = hazard.lower()
        
        if 'tornado' in hazard_lower:
            return 'Tornado'
        if 'damaging wind' in hazard_lower or 'destructive wind' in hazard_lower:
            return 'Vientos destructivos'
        if 'wind' in hazard_lower and 'hail' in hazard_lower:
            return 'Viento y granizo'
        if 'large hail' in hazard_lower or 'giant hail' in hazard_lower:
            return 'Granizo grande'
        if 'hail' in hazard_lower:
            return 'Granizo'
        if 'wind' in hazard_lower:
            return 'Viento fuerte'
        if 'flash flood' in hazard_lower:
            return 'Inundación repentina'
        if 'flood' in hazard_lower:
            return 'Inundación'
        
        return hazard

    def _traducir_source(self, source):
        """Traduce la fuente al español."""
        if not source:
            return ''
        
        source_lower = source.lower()
        
        if 'radar indicated rotation' in source_lower:
            return 'Rotación indicada por radar'
        if 'radar indicated' in source_lower:
            return 'Indicado por radar'
        if 'doppler radar' in source_lower:
            return 'Radar Doppler'
        if 'trained spotter' in source_lower or 'weather spotter' in source_lower:
            return 'Observadores meteorológicos entrenados'
        if 'law enforcement' in source_lower:
            return 'Autoridades policiales'
        if 'emergency management' in source_lower:
            return 'Gestión de emergencias'
        if 'public' in source_lower:
            return 'Reportes del público'
        
        return source

    def _extraer_condados(self, area_desc):
        """Extrae los primeros 3 condados del área."""
        if not area_desc:
            return ''
        partes = area_desc.split(';')
        condados = [p.strip().split(',')[0].strip() for p in partes[:3]]
        total = len(partes)
        if total > 3:
            return ', '.join(condados) + f' (+{total - 3} más)'
        return ', '.join(condados)

    def _clasificar_evento(self, event):
        """Clasifica el evento para asignar tipo/icono."""
        if 'Tornado' in event:
            return 'tornado'
        if 'Severe Thunderstorm' in event:
            return 'tormenta'
        if 'Flood' in event:
            return 'inundacion'
        if 'Hurricane' in event or 'Tropical' in event or 'Storm Surge' in event:
            return 'huracan'
        if 'Ice Storm' in event or 'Freezing' in event:
            return 'hielo'
        if 'Blizzard' in event or 'Snow' in event or 'Winter Storm' in event:
            return 'invierno'
        if 'Freeze' in event or 'Frost' in event or 'Cold' in event or 'Wind Chill' in event:
            return 'frio'
        if 'Wind' in event or 'Dust Storm' in event:
            return 'viento'
        if 'Fog' in event:
            return 'niebla'
        if 'Heat' in event:
            return 'calor'
        if 'Red Flag' in event or 'Fire' in event:
            return 'fuego'
        if 'Gale' in event or 'Marine' in event:
            return 'marino'
        if 'Surf' in event or 'Rip Current' in event or 'Beach' in event:
            return 'oleaje'
        return 'otro'

    def _es_warning(self, event):
        """Determina si es un warning (individual) o watch/advisory (agrupar)."""
        return 'Warning' in event or 'Emergency' in event

    def _procesar_alerta_individual(self, alerta):
        """Procesa una alerta individual (warning)."""
        props = alerta.get('properties', {})
        
        event = props.get('event', '')
        estado = self._extraer_estado(alerta)
        poblacion = self._calcular_poblacion(alerta)
        geometry = self._obtener_geometria_alerta(alerta)
        
        effective = props.get('effective') or props.get('onset')
        expires = props.get('expires')
        
        # Calcular minutos restantes
        expires_in = None
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                delta = exp_dt - now
                expires_in = max(0, int(delta.total_seconds() / 60))
            except:
                pass
        
        description = props.get('description', '')
        campos_extra = self._extraer_campos_descripcion(description)
        
        # Preparar datos de detalle
        detalle = {}
        
        if campos_extra.get('hazard'):
            detalle['hazard'] = campos_extra['hazard']
            detalle['hazard_es'] = self._traducir_hazard(campos_extra['hazard'])
        
        if campos_extra.get('impact'):
            detalle['impact'] = campos_extra['impact']
            impact_original = campos_extra['impact'].strip()
            if impact_original in TRADUCCION_IMPACTS:
                detalle['impact_es'] = TRADUCCION_IMPACTS[impact_original]
        
        if campos_extra.get('max_hail'):
            detalle['max_hail'] = campos_extra['max_hail']
        
        if campos_extra.get('max_wind'):
            detalle['max_wind'] = campos_extra['max_wind']
        
        if campos_extra.get('damage_threat'):
            detalle['damage_threat'] = campos_extra['damage_threat']
            threat_upper = campos_extra['damage_threat'].upper()
            detalle['damage_threat_es'] = TRADUCCION_DAMAGE_THREAT.get(threat_upper, campos_extra['damage_threat'])
        
        if campos_extra.get('source'):
            detalle['source'] = campos_extra['source']
            detalle['source_es'] = self._traducir_source(campos_extra['source'])
        
        return {
            'id': props.get('id', ''),
            'evento': event,
            'evento_es': TRADUCCION_EVENTOS.get(event, event),
            'tipo': self._clasificar_evento(event),
            'color': COLORES_EVENTOS.get(event, '#808080'),
            'severity': props.get('severity', 'Unknown'),
            'estado': estado,
            'estado_nombre': NOMBRES_ESTADOS.get(estado, estado),
            'condados': self._extraer_condados(props.get('areaDesc', '')),
            'area_desc': props.get('areaDesc', ''),
            'area_count': 1,
            'poblacion': poblacion,
            'effective': effective,
            'expires': expires,
            'expires_in_minutes': expires_in,
            'headline': props.get('headline', ''),
            'description': description,
            'instruction': props.get('instruction', ''),
            'detalle': detalle,
            'geometry': geometry,
            'has_geometry': geometry is not None,
            'is_grouped': False,
            'prioridad': PRIORIDAD_EVENTOS.get(event, 99),
        }

    def _agrupar_alertas(self, alertas_por_evento):
        """
        Agrupa watches/advisories del mismo tipo.
        Combina geometrías y suma poblaciones.
        """
        alertas_agrupadas = []
        
        for event, alertas in alertas_por_evento.items():
            if len(alertas) == 0:
                continue
            
            # Combinar geometrías
            geometrias = []
            areas = []
            estados = set()
            poblacion_total = 0
            
            for alerta in alertas:
                props = alerta.get('properties', {})
                geom = self._obtener_geometria_alerta(alerta)
                
                if geom:
                    try:
                        geometrias.append(shape(geom))
                    except:
                        pass
                
                area = props.get('areaDesc', '')
                if area:
                    for part in area.split(';'):
                        part = part.strip()
                        if part and part not in areas:
                            areas.append(part)
                
                estados.update(self._extraer_estados_multiple(alerta))
            
            # Unir geometrías
            combined_geometry = None
            if geometrias:
                try:
                    union = unary_union(geometrias)
                    combined_geometry = mapping(union)
                    poblacion_total = self._calcular_poblacion_geometria(combined_geometry)
                except Exception as e:
                    logger.warning(f"Error uniendo geometrías para {event}: {e}")
            
            # Si no hay geometría combinada, sumar poblaciones individuales
            if poblacion_total == 0:
                for alerta in alertas:
                    poblacion_total += self._calcular_poblacion(alerta)
            
            # Crear descripción de área combinada
            if len(areas) > 5:
                area_desc = '; '.join(areas[:5]) + f' (+{len(areas)-5} zonas más)'
            elif areas:
                area_desc = '; '.join(areas)
            else:
                area_desc = 'Múltiples zonas'
            
            # Extraer condados para mostrar
            condados_lista = []
            for area in areas[:3]:
                condado = area.split(',')[0].strip()
                if condado:
                    condados_lista.append(condado)
            if len(areas) > 3:
                condados_str = ', '.join(condados_lista) + f' (+{len(areas) - 3} más)'
            else:
                condados_str = ', '.join(condados_lista)
            
            # Usar datos del primer alerta
            first_props = alertas[0].get('properties', {})
            expires = first_props.get('expires')
            
            # Calcular minutos restantes
            expires_in = None
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    delta = exp_dt - now
                    expires_in = max(0, int(delta.total_seconds() / 60))
                except:
                    pass
            
            # Lista de estados afectados
            estados_lista = sorted(list(estados))
            estados_nombres = [NOMBRES_ESTADOS.get(e, e) for e in estados_lista]
            
            alertas_agrupadas.append({
                'id': first_props.get('id', event.replace(' ', '_')),
                'evento': event,
                'evento_es': TRADUCCION_EVENTOS.get(event, event),
                'tipo': self._clasificar_evento(event),
                'color': COLORES_EVENTOS.get(event, '#808080'),
                'severity': first_props.get('severity', 'Unknown'),
                'estado': estados_lista[0] if estados_lista else None,
                'estado_nombre': estados_nombres[0] if estados_nombres else '',
                'estados': estados_lista,
                'estados_nombres': estados_nombres,
                'condados': condados_str,
                'area_desc': area_desc,
                'area_count': len(areas),
                'poblacion': poblacion_total,
                'effective': first_props.get('effective') or first_props.get('onset'),
                'expires': expires,
                'expires_in_minutes': expires_in,
                'headline': first_props.get('headline', ''),
                'description': first_props.get('description', ''),
                'instruction': first_props.get('instruction', ''),
                'detalle': {},
                'geometry': combined_geometry,
                'has_geometry': combined_geometry is not None,
                'is_grouped': True,
                'alert_count': len(alertas),
                'prioridad': PRIORIDAD_EVENTOS.get(event, 99),
            })
        
        return alertas_agrupadas

    def obtener_alertas(self):
        """Obtiene alertas del NWS y las procesa con agrupación."""
        try:
            headers = {
                'User-Agent': CONFIG['user_agent'],
                'Accept': 'application/geo+json'
            }
            
            response = requests.get(CONFIG['nws_api'], headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            features = data.get('features', [])
            
            # Filtrar alertas de CONUS (warnings y watches)
            alertas_conus = [
                f for f in features 
                if self._es_alerta_conus(f)
                and ('Warning' in f.get('properties', {}).get('event', '')
                     or 'Watch' in f.get('properties', {}).get('event', '')
                     or 'Advisory' in f.get('properties', {}).get('event', ''))
            ]
            
            logger.info(f"Total alertas CONUS: {len(alertas_conus)}")
            
            # Separar warnings (individuales) de watches/advisories (agrupar)
            warnings = []
            watches_por_evento = {}
            
            for alerta in alertas_conus:
                event = alerta.get('properties', {}).get('event', '')
                
                if self._es_warning(event):
                    # Warnings se procesan individualmente
                    warnings.append(self._procesar_alerta_individual(alerta))
                else:
                    # Watches y advisories se agrupan por tipo
                    if event not in watches_por_evento:
                        watches_por_evento[event] = []
                    watches_por_evento[event].append(alerta)
            
            # Agrupar watches/advisories
            watches_agrupados = self._agrupar_alertas(watches_por_evento)
            
            # Combinar todas las alertas
            todas_alertas = warnings + watches_agrupados
            
            # Ordenar por prioridad
            todas_alertas.sort(key=lambda x: x.get('prioridad', 99))
            
            # Limitar a max_alertas
            alertas_finales = todas_alertas[:CONFIG['max_alertas']]
            
            # Generar GeoJSON
            geojson_features = []
            for alerta in alertas_finales:
                if alerta.get('geometry'):
                    geojson_features.append({
                        'type': 'Feature',
                        'geometry': alerta['geometry'],
                        'properties': {
                            'id': alerta['id'],
                            'event': alerta['evento'],
                            'event_es': alerta['evento_es'],
                            'tipo': alerta['tipo'],
                            'color': alerta['color'],
                            'severity': alerta['severity'],
                            'headline': alerta['headline'],
                            'areaDesc': alerta['area_desc'],
                            'poblacion': alerta['poblacion'],
                            'expires_in': alerta['expires_in_minutes'],
                            'is_grouped': alerta['is_grouped'],
                            'area_count': alerta.get('area_count', 1),
                        }
                    })
            
            # Contar por tipo
            conteos = {
                'total': len(alertas_finales),
                'warnings': len([a for a in alertas_finales if not a['is_grouped']]),
                'watches': len([a for a in alertas_finales if a['is_grouped']]),
                'tornado': len([a for a in alertas_finales if a['tipo'] == 'tornado']),
                'tormenta': len([a for a in alertas_finales if a['tipo'] == 'tormenta']),
                'inundacion': len([a for a in alertas_finales if a['tipo'] == 'inundacion']),
                'invierno': len([a for a in alertas_finales if a['tipo'] == 'invierno']),
                'con_geometria': len(geojson_features),
            }
            
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'conteos': conteos,
                'alertas': alertas_finales,
                'geojson': {
                    'type': 'FeatureCollection',
                    'features': geojson_features
                }
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo alertas: {e}")
            import traceback
            traceback.print_exc()
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e),
                'conteos': {'total': 0},
                'alertas': [],
                'geojson': {'type': 'FeatureCollection', 'features': []}
            }

    def _subir_a_s3(self, archivo_local):
        """Sube el archivo a DigitalOcean Spaces via AWS CLI."""
        s3_uri = f"s3://{CONFIG['s3_bucket']}/{CONFIG['s3_path']}"
        
        cmd = [
            'aws', '--profile', CONFIG['aws_profile'],
            's3', 'cp', str(archivo_local), s3_uri,
            '--endpoint-url', CONFIG['aws_endpoint'],
            '--acl', 'public-read',
            '--content-type', 'application/json',
            '--cache-control', 'max-age=10'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.info(f"JSON subido a S3: {CONFIG['s3_url']}")
                return True
            else:
                logger.error(f"Error subiendo a S3: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("Timeout al subir archivo a S3")
            return False
        except Exception as e:
            logger.error(f"Error en AWS CLI: {e}")
            return False

    def guardar_json(self, datos):
        """Guarda los datos en JSON local y sube a S3."""
        try:
            output_path = Path(CONFIG['output_json'])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            
            conteos = datos.get('conteos', {})
            logger.info(f"JSON guardado: {conteos.get('total', 0)} alertas ({conteos.get('warnings', 0)} warnings, {conteos.get('watches', 0)} watches)")
            
            # Subir a S3 via AWS CLI
            self._subir_a_s3(output_path)
            
            return True
        except Exception as e:
            logger.error(f"Error guardando JSON: {e}")
            return False

    def ejecutar_una_vez(self):
        """Ejecuta una sola iteración."""
        datos = self.obtener_alertas()
        self.guardar_json(datos)
        return datos

    def ejecutar_loop(self):
        """Ejecuta en loop continuo."""
        logger.info(f"Iniciando loop (intervalo: {CONFIG['intervalo_segundos']}s)")
        
        while True:
            try:
                self.ejecutar_una_vez()
            except Exception as e:
                logger.error(f"Error en iteración: {e}")
            
            time.sleep(CONFIG['intervalo_segundos'])


def main():
    parser = argparse.ArgumentParser(description='Obtener alertas del NWS con agrupación')
    parser.add_argument('--once', action='store_true', help='Ejecutar una sola vez')
    parser.add_argument('--verbose', action='store_true', help='Mostrar JSON completo')
    args = parser.parse_args()
    
    alertas = AlertasNWS()
    
    if args.once:
        datos = alertas.ejecutar_una_vez()
        if args.verbose:
            print(json.dumps(datos, indent=2, ensure_ascii=False))
        else:
            conteos = datos.get('conteos', {})
            logger.info(f"✅ Procesadas {conteos.get('total', 0)} alertas")
            logger.info(f"   Warnings: {conteos.get('warnings', 0)}, Watches: {conteos.get('watches', 0)}")
            logger.info(f"   Tornado: {conteos.get('tornado', 0)}, Tormenta: {conteos.get('tormenta', 0)}")
            logger.info(f"   Inundación: {conteos.get('inundacion', 0)}, Invierno: {conteos.get('invierno', 0)}")
            
            for alerta in datos.get('alertas', [])[:5]:
                grupo = " (agrupado)" if alerta.get('is_grouped') else ""
                logger.info(f"   - {alerta.get('evento_es', 'N/A')}{grupo}: {alerta.get('poblacion', 0):,} personas")
    else:
        alertas.ejecutar_loop()


if __name__ == '__main__':
    main()
