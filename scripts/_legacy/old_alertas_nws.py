#!/usr/bin/env python3
"""
Script para obtener alertas del NWS, calcular población afectada
y generar JSON para el dashboard de Canal Meteo.

Ubicación: /opt/canalmeteo/scripts/alertas_nws.py
Sube a S3 via AWS CLI (igual que astronomía)

Uso:
    python alertas_nws.py         # Loop continuo
    python alertas_nws.py --once  # Una sola ejecución
    
CAMBIOS v2:
- Cálculo de población mejorado usando geometría real del polígono
- Extracción de Hazard, Impact, Max Hail, Max Wind, Source del description
- Traducción de campos adicionales al español
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
import urllib.parse

# Configuración
CONFIG = {
    'nws_api': 'https://api.weather.gov/alerts/active?status=actual&message_type=alert',
    'zonas_shp': '/home/canalmeteo/lynx/data/shapefiles/z_18mr25.shp',
    'fire_zones_shp': '/home/canalmeteo/lynx/data/shapefiles/fz18mr25.shp',
    'condados_shp': '/home/canalmeteo/lynx/data/shapefiles/tl_2023_us_county.shp',
    'poblacion_csv': '/home/canalmeteo/lynx/data/census/poblacion_ready.csv',
    'output_json': '/mnt/canalmeteo_data_01/alertas/alertas_nws.json',
    
    # AWS/Spaces config (igual que astronomía)
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_path': 'data/alertas/alertas_nws.json',
    's3_url': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/alertas/alertas_nws.json',
    
    'intervalo_segundos': 15,
    'max_alertas': 10,
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

# Traducción de eventos
TRADUCCION_EVENTOS = {
    'Severe Thunderstorm Warning': 'Aviso de tormenta severa',
    'Tornado Warning': 'Aviso de tornado',
    'Flash Flood Warning': 'Aviso de inundación repentina',
    'Flood Warning': 'Aviso de inundación',
    'Coastal Flood Warning': 'Aviso de inundación costera',
    'Hurricane Warning': 'Aviso de huracán',
    'Tropical Storm Warning': 'Aviso de tormenta tropical',
    'Storm Surge Warning': 'Aviso de marejada ciclónica',
    'Blizzard Warning': 'Aviso de ventisca',
    'Winter Storm Warning': 'Aviso de tormenta invernal',
    'Ice Storm Warning': 'Aviso de tormenta de hielo',
    'Heavy Snow Warning': 'Aviso de nevada intensa',
    'Lake Effect Snow Warning': 'Aviso de nieve de efecto lacustre',
    'High Wind Warning': 'Aviso de vientos fuertes',
    'Extreme Wind Warning': 'Aviso de vientos extremos',
    'Extreme Cold Warning': 'Aviso de frío extremo',
    'Extreme Cold Watch': 'Vigilancia de frío extremo',
    'Wind Chill Warning': 'Aviso de sensación térmica extrema',
    'Wind Chill Watch': 'Vigilancia de sensación térmica',
    'Wind Chill Advisory': 'Advertencia de sensación térmica',
    'Dust Storm Warning': 'Aviso de tormenta de polvo',
    'Red Flag Warning': 'Aviso de bandera roja',
    'Fire Weather Warning': 'Aviso de clima propicio para incendios',
    'Excessive Heat Warning': 'Aviso de calor excesivo',
    'Freeze Warning': 'Aviso de helada',
    'Hard Freeze Warning': 'Aviso de helada intensa',
    'Dense Fog Advisory': 'Advertencia de niebla densa',
    'Freezing Rain Advisory': 'Advertencia de lluvia engelante',
    'Frost Advisory': 'Advertencia de escarcha',
    'Heat Advisory': 'Advertencia de calor',
    'Wind Advisory': 'Advertencia de viento',
    'Winter Weather Advisory': 'Advertencia de clima invernal',
    'Lake Wind Advisory': 'Advertencia de viento lacustre',
    'Special Weather Statement': 'Comunicado meteorológico especial',
}

# Traducción de hazards comunes
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

# Traducción de sources comunes
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

    def _calcular_poblacion(self, alerta):
        """
        Calcula la población afectada por una alerta.
        
        MÉTODO MEJORADO:
        - Si la alerta tiene geometría propia (polígono), calcula la intersección
          con cada condado y estima la población proporcionalmente al área.
        - Si no tiene geometría, usa el método tradicional por FIPS.
        """
        if self.condados_con_poblacion is None:
            return 0
        
        props = alerta.get('properties', {})
        geometry = alerta.get('geometry')
        
        # Si la alerta tiene geometría propia (polígono específico)
        if geometry and geometry.get('coordinates'):
            try:
                alert_shape = shape(geometry)
                
                # Crear GeoDataFrame temporal con la geometría de la alerta
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
                
                if poblacion_total > 0:
                    return poblacion_total
                    
            except Exception as e:
                logger.warning(f"Error calculando población por geometría: {e}")
        
        # Método fallback: usar códigos FIPS
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
        """
        Extrae campos específicos del texto de descripción de la alerta.
        
        Campos extraídos:
        - HAZARD: El peligro (tornado, granizo, viento)
        - IMPACT: El impacto esperado
        - MAX HAIL SIZE: Tamaño máximo de granizo
        - MAX WIND GUST: Ráfaga máxima de viento
        - SOURCE: Fuente de la información
        - TORNADO: Tipo de detección de tornado
        - HAIL THREAT / WIND THREAT / DAMAGE THREAT: Niveles de amenaza
        """
        if not description:
            return {}
        
        campos = {}
        
        # Patrones para extraer campos
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
        
        # Patrones alternativos (algunos alertas usan formato diferente)
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
                # Limpiar saltos de línea internos
                valor = ' '.join(valor.split())
                campos[campo] = valor
        
        # Intentar patrones alternativos si no se encontró
        for campo, patron in patrones_alt.items():
            if campo not in campos:
                match = re.search(patron, description, re.IGNORECASE)
                if match:
                    valor = match.group(1).strip()
                    valor = ' '.join(valor.split())
                    campos[campo] = valor
        
        return campos

    def _traducir_texto(self, texto):
        """
        Traduce texto de inglés a español usando múltiples servicios con fallback.
        Orden de prioridad:
        1. MyMemory API (gratuita, 10K chars/día)
        2. LibreTranslate (instancias públicas gratuitas)
        3. Google Translate (no oficial)
        """
        if not texto or len(texto) < 5:
            return None
        
        texto_limpio = texto[:500].strip()
        
        # Intentar MyMemory primero
        traduccion = self._traducir_mymemory(texto_limpio)
        if traduccion:
            return traduccion
        
        # Fallback a LibreTranslate
        traduccion = self._traducir_libretranslate(texto_limpio)
        if traduccion:
            return traduccion
        
        # Último recurso: Google Translate (no oficial)
        traduccion = self._traducir_google(texto_limpio)
        if traduccion:
            return traduccion
        
        logger.warning(f"No se pudo traducir: {texto_limpio[:50]}...")
        return None

    def _traducir_mymemory(self, texto):
        """MyMemory API - 10,000 chars/día gratis, 30,000 con email."""
        try:
            url = "https://api.mymemory.translated.net/get"
            params = {
                'q': texto,
                'langpair': 'en|es',
                'de': 'contacto@canalmeteo.tv'
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('responseStatus') == 200:
                    traduccion = data.get('responseData', {}).get('translatedText', '')
                    if traduccion and traduccion.lower().strip() != texto.lower().strip():
                        logger.debug(f"MyMemory OK: {texto[:30]}...")
                        return traduccion
        except Exception as e:
            logger.debug(f"MyMemory error: {e}")
        return None

    def _traducir_libretranslate(self, texto):
        """LibreTranslate - Instancias públicas gratuitas."""
        # Lista de instancias públicas de LibreTranslate
        instancias = [
            'https://libretranslate.com',
            'https://translate.argosopentech.com',
            'https://translate.terraprint.co',
        ]
        
        for base_url in instancias:
            try:
                url = f"{base_url}/translate"
                payload = {
                    'q': texto,
                    'source': 'en',
                    'target': 'es',
                    'format': 'text'
                }
                headers = {'Content-Type': 'application/json'}
                
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    traduccion = data.get('translatedText', '')
                    if traduccion and traduccion.lower().strip() != texto.lower().strip():
                        logger.debug(f"LibreTranslate OK ({base_url}): {texto[:30]}...")
                        return traduccion
            except Exception as e:
                logger.debug(f"LibreTranslate error ({base_url}): {e}")
                continue
        return None

    def _traducir_google(self, texto):
        """Google Translate (API no oficial) - Sin límites conocidos."""
        try:
            # Usar la API web de Google Translate
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                'client': 'gtx',
                'sl': 'en',
                'tl': 'es',
                'dt': 't',
                'q': texto
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # El resultado viene en formato [[["traducción","original",...],...]...]
                if data and len(data) > 0 and len(data[0]) > 0:
                    traduccion = ''.join([parte[0] for parte in data[0] if parte[0]])
                    if traduccion and traduccion.lower().strip() != texto.lower().strip():
                        logger.debug(f"Google Translate OK: {texto[:30]}...")
                        return traduccion
        except Exception as e:
            logger.debug(f"Google Translate error: {e}")
        return None

    def _traducir_texto_mymemory(self, texto):
        """Wrapper para compatibilidad - usa el nuevo sistema multi-servicio."""
        return self._traducir_texto(texto)

    def _traducir_hazard(self, hazard):
        """Traduce el hazard al español."""
        if not hazard:
            return ''
        
        hazard_lower = hazard.lower()
        
        # Traducciones específicas
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
        """Clasifica el evento para asignar color/icono."""
        if 'Tornado' in event:
            return 'tornado'
        if 'Severe Thunderstorm' in event:
            return 'tormenta'
        if 'Flood' in event:
            return 'inundacion'
        if 'Hurricane' in event or 'Tropical' in event:
            return 'huracan'
        if 'Ice Storm' in event or 'Freezing' in event:
            return 'hielo'
        if 'Blizzard' in event or 'Snow' in event or 'Winter Storm' in event:
            return 'invierno'
        if 'Freeze' in event or 'Frost' in event or 'Cold' in event or 'Wind Chill' in event:
            return 'frio'
        if 'High Wind' in event or 'Dust Storm' in event or 'Extreme Wind' in event:
            return 'viento'
        if 'Fog' in event:
            return 'niebla'
        if 'Red Flag' in event or 'Fire' in event or 'Heat' in event:
            return 'fuego'
        if 'Gale' in event or 'Marine' in event:
            return 'marino'
        return 'otro'

    def _procesar_alerta(self, alerta):
        """Procesa una alerta y devuelve datos limpios."""
        props = alerta.get('properties', {})
        
        event = props.get('event', '')
        estado = self._extraer_estado(alerta)
        poblacion = self._calcular_poblacion(alerta)
        geometry = self._obtener_geometria_alerta(alerta)
        
        effective = props.get('effective') or props.get('onset')
        expires = props.get('expires')
        
        description = props.get('description', '')
        
        # Extraer campos adicionales
        campos_extra = self._extraer_campos_descripcion(description)
        
        # Preparar datos de detalle
        detalle = {}
        
        if campos_extra.get('hazard'):
            detalle['hazard'] = campos_extra['hazard']
            detalle['hazard_es'] = self._traducir_hazard(campos_extra['hazard'])
        
        if campos_extra.get('impact'):
            detalle['impact'] = campos_extra['impact']
            # Primero buscar en diccionario de impacts comunes
            impact_original = campos_extra['impact'].strip()
            if impact_original in TRADUCCION_IMPACTS:
                detalle['impact_es'] = TRADUCCION_IMPACTS[impact_original]
            else:
                # Si no está en el diccionario, traducir usando API
                impact_traducido = self._traducir_texto_mymemory(impact_original)
                if impact_traducido:
                    detalle['impact_es'] = impact_traducido
        
        if campos_extra.get('max_hail'):
            detalle['max_hail'] = campos_extra['max_hail']
        
        if campos_extra.get('max_wind'):
            detalle['max_wind'] = campos_extra['max_wind']
        
        if campos_extra.get('damage_threat'):
            detalle['damage_threat'] = campos_extra['damage_threat']
            # Traducir damage threat
            threat_upper = campos_extra['damage_threat'].upper()
            detalle['damage_threat_es'] = TRADUCCION_DAMAGE_THREAT.get(threat_upper, campos_extra['damage_threat'])
        
        if campos_extra.get('hail_threat'):
            detalle['hail_threat'] = campos_extra['hail_threat']
        
        if campos_extra.get('wind_threat'):
            detalle['wind_threat'] = campos_extra['wind_threat']
        
        if campos_extra.get('tornado'):
            detalle['tornado_detection'] = campos_extra['tornado']
        
        if campos_extra.get('source'):
            detalle['source'] = campos_extra['source']
            detalle['source_es'] = self._traducir_source(campos_extra['source'])
        
        return {
            'id': props.get('id', ''),
            'evento': event,
            'evento_es': TRADUCCION_EVENTOS.get(event, event),
            'tipo': self._clasificar_evento(event),
            'severity': props.get('severity', 'Unknown'),
            'estado': estado,
            'estado_nombre': NOMBRES_ESTADOS.get(estado, estado),
            'condados': self._extraer_condados(props.get('areaDesc', '')),
            'area_desc': props.get('areaDesc', ''),
            'poblacion': poblacion,
            'effective': effective,
            'expires': expires,
            'headline': props.get('headline', ''),
            'description': description,
            'detalle': detalle,  # Nuevo campo con hazard, impact, etc.
            'geometry': geometry,
        }

    def obtener_alertas(self):
        """Obtiene alertas del NWS y las procesa."""
        try:
            headers = {
                'User-Agent': CONFIG['user_agent'],
                'Accept': 'application/geo+json'
            }
            
            response = requests.get(CONFIG['nws_api'], headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            features = data.get('features', [])
            
            # Filtrar solo warnings de CONUS
            warnings = [
                f for f in features 
                if 'Warning' in f.get('properties', {}).get('event', '')
                and self._es_alerta_conus(f)
            ]
            
            # Ordenar por severidad
            orden_severidad = {'Extreme': 0, 'Severe': 1, 'Moderate': 2, 'Minor': 3}
            warnings.sort(key=lambda x: orden_severidad.get(x.get('properties', {}).get('severity', ''), 4))
            
            # Procesar top 10
            alertas_procesadas = []
            for alerta in warnings[:CONFIG['max_alertas']]:
                procesada = self._procesar_alerta(alerta)
                alertas_procesadas.append(procesada)
            
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'total_warnings_conus': len(warnings),
                'alertas': alertas_procesadas
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo alertas: {e}")
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e),
                'alertas': []
            }

    def _subir_a_s3(self, archivo_local):
        """Sube el archivo a DigitalOcean Spaces via AWS CLI.
        
        Usa el mismo método que el script de astronomía para mantener
        consistencia en todos los scripts de Canal Meteo.
        """
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
            
            logger.info(f"JSON guardado localmente: {len(datos.get('alertas', []))} alertas")
            
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
    parser = argparse.ArgumentParser(description='Obtener alertas del NWS')
    parser.add_argument('--once', action='store_true', help='Ejecutar una sola vez')
    parser.add_argument('--verbose', action='store_true', help='Mostrar JSON completo')
    args = parser.parse_args()
    
    alertas = AlertasNWS()
    
    if args.once:
        datos = alertas.ejecutar_una_vez()
        if args.verbose:
            print(json.dumps(datos, indent=2, ensure_ascii=False))
        else:
            # Solo mostrar resumen
            num_alertas = len(datos.get('alertas', []))
            logger.info(f"✅ Procesadas {num_alertas} alertas")
            for alerta in datos.get('alertas', [])[:5]:
                logger.info(f"  - {alerta.get('evento_es', alerta.get('evento', 'N/A'))}: {alerta.get('poblacion_afectada', 0):,} personas")
    else:
        alertas.ejecutar_loop()


if __name__ == '__main__':
    main()
