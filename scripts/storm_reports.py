#!/usr/bin/env python3
"""
===============================================================================
STORM REPORTS v2 - Canal Meteo TV
===============================================================================
Descarga Local Storm Reports (LSR) del Iowa Environmental Mesonet.

Ubicación: /opt/canalmeteo/scripts/storm_reports.py
Entorno: /opt/canalmeteo/env/
Datos locales: /opt/canalmeteo/data/reports/
CDN: https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/reports/

Uso:
    python3 storm_reports.py              # Ejecutar una vez
    python3 storm_reports.py --daemon     # Ejecutar en bucle (cada 5 min)

Cron (cada 5 minutos):
    */5 * * * * /opt/canalmeteo/env/bin/python3 /opt/canalmeteo/scripts/storm_reports.py
===============================================================================
"""

import requests
import json
import subprocess
import argparse
import logging
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

CONFIG = {
    # URLs de datos - CORREGIDA: necesita wfo=ALL
    'iem_lsr_url': 'https://mesonet.agron.iastate.edu/cgi-bin/request/gis/lsr.py',
    
    # URL alternativa: GeoJSON directo (últimas 24h, actualizado cada 5 min)
    'iem_geojson_url': 'https://mesonet.agron.iastate.edu/geojson/lsr.geojson',
    
    # Rutas locales
    'data_dir': '/opt/canalmeteo/data/reports',
    'output_json': '/opt/canalmeteo/data/reports/storm_reports.json',
    
    # AWS/Spaces config
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_path': 'data/reports/storm_reports.json',
    's3_url': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/reports/storm_reports.json',
    
    # Parámetros
    'hours_back': 24,
    'update_interval': 300,
    'user_agent': 'CanalMeteoTV/1.0 (https://canalmeteo.tv)',
}

# Traducción de tipos
REPORT_TRANSLATIONS = {
    'SNOW': 'Nieve', 'HEAVY SNOW': 'Nieve intensa', 'SLEET': 'Aguanieve',
    'FREEZING RAIN': 'Lluvia helada', 'ICE STORM': 'Tormenta de hielo',
    'HEAVY RAIN': 'Lluvia intensa', 'FLASH FLOOD': 'Inundación repentina',
    'FLOOD': 'Inundación', 'BLIZZARD': 'Ventisca', 'LAKE EFFECT SNOW': 'Nieve efecto lago',
    'HAIL': 'Granizo', 'TORNADO': 'Tornado', 'TSTM WND GST': 'Ráfaga de viento',
    'TSTM WND DMG': 'Daño por viento', 'NON-TSTM WND GST': 'Ráfaga (no tormenta)',
    'NON-TSTM WND DMG': 'Daño por viento', 'DENSE FOG': 'Niebla densa',
    'EXTREME COLD': 'Frío extremo', 'EXTREME HEAT': 'Calor extremo',
}

REPORT_ICONS = {
    'SNOW': '❄️', 'HEAVY SNOW': '🌨️', 'SLEET': '🌧️', 'FREEZING RAIN': '🧊',
    'ICE STORM': '🧊', 'HEAVY RAIN': '🌧️', 'FLASH FLOOD': '🌊', 'FLOOD': '🌊',
    'BLIZZARD': '🌬️', 'LAKE EFFECT SNOW': '❄️', 'HAIL': '🧊', 'TORNADO': '🌪️',
    'TSTM WND GST': '💨', 'TSTM WND DMG': '💨', 'EXTREME COLD': '🥶', 'EXTREME HEAT': '🥵',
}

STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
    'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'Washington DC', 'PR': 'Puerto Rico',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class StormReportsCollector:
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': CONFIG['user_agent'],
            'Accept': 'application/json'
        })
        Path(CONFIG['data_dir']).mkdir(parents=True, exist_ok=True)
    
    def fetch_lsr_data(self, hours: int = 24):
        """Descarga LSR del IEM usando el formato correcto."""
        
        # Método 1: Usar la API con wfo=ALL y recent=segundos
        seconds = hours * 3600
        url = f"{CONFIG['iem_lsr_url']}?wfo=ALL&recent={seconds}&fmt=csv"
        
        logger.info(f"Descargando LSR de las últimas {hours} horas...")
        logger.info(f"URL: {url}")
        
        try:
            response = self.session.get(url, timeout=120)
            response.raise_for_status()
            
            # Parsear CSV
            lines = response.text.strip().split('\n')
            if len(lines) < 2:
                logger.warning("CSV vacío o sin datos")
                return []
            
            # Header
            headers = lines[0].split(',')
            features = []
            
            for line in lines[1:]:
                try:
                    values = self._parse_csv_line(line)
                    if len(values) < len(headers):
                        continue
                    
                    row = dict(zip(headers, values))
                    
                    # Crear feature GeoJSON-like
                    feature = {
                        'properties': {
                            'valid': row.get('VALID', ''),
                            'typetext': row.get('TYPETEXT', ''),
                            'magnitude': self._parse_float(row.get('MAG', '')),
                            'city': row.get('CITY', ''),
                            'county': row.get('COUNTY', ''),
                            'state': row.get('STATE', ''),
                            'source': row.get('SOURCE', ''),
                            'remark': row.get('REMARK', ''),
                            'wfo': row.get('WFO', ''),
                        },
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [
                                self._parse_float(row.get('LON', 0)),
                                self._parse_float(row.get('LAT', 0))
                            ]
                        }
                    }
                    features.append(feature)
                except Exception as e:
                    continue
            
            logger.info(f"Descargados {len(features)} reportes")
            return features
            
        except Exception as e:
            logger.error(f"Error descargando LSR: {e}")
            # Intentar método alternativo
            return self._fetch_geojson_alternative(hours)
    
    def _fetch_geojson_alternative(self, hours: int):
        """Método alternativo usando el endpoint GeoJSON directo."""
        logger.info("Intentando método alternativo (GeoJSON directo)...")
        
        # Calcular fechas
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        url = f"{CONFIG['iem_geojson_url']}?sts={start.strftime('%Y-%m-%dT%H:%MZ')}&ets={now.strftime('%Y-%m-%dT%H:%MZ')}"
        
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()
            features = data.get('features', [])
            logger.info(f"Descargados {len(features)} reportes (método alternativo)")
            return features
        except Exception as e:
            logger.error(f"Error en método alternativo: {e}")
            return []
    
    def _parse_csv_line(self, line):
        """Parsea una línea CSV manejando comillas."""
        values = []
        current = ''
        in_quotes = False
        
        for char in line:
            if char == '"':
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                values.append(current.strip())
                current = ''
            else:
                current += char
        values.append(current.strip())
        return values
    
    def _parse_float(self, value):
        """Parsea un valor float de forma segura."""
        try:
            if value and value not in ['M', 'T', '', 'None']:
                return float(value)
        except:
            pass
        return 0
    
    def process_reports(self, features):
        """Procesa los reportes y los organiza."""
        reports = []
        by_state = defaultdict(list)
        by_type = defaultdict(list)
        maximos = {'nieve': None, 'lluvia': None, 'granizo': None, 'viento': None}
        
        for feature in features:
            props = feature.get('properties', {})
            geom = feature.get('geometry', {})
            
            report_type = (props.get('typetext') or '').upper()
            magnitude = props.get('magnitude', 0) or 0
            city = props.get('city', '')
            county = props.get('county', '')
            state = props.get('state', '')
            source = props.get('source', '')
            remark = props.get('remark', '')
            valid_str = props.get('valid', '')
            wfo = props.get('wfo', '')
            
            coords = geom.get('coordinates', [0, 0])
            lon, lat = coords[0] if coords else 0, coords[1] if len(coords) > 1 else 0
            
            # Parsear fecha
            try:
                if 'T' in valid_str:
                    valid_dt = datetime.fromisoformat(valid_str.replace('Z', '+00:00'))
                else:
                    valid_dt = datetime.strptime(valid_str[:19], '%Y-%m-%d %H:%M:%S')
                valid_formatted = valid_dt.strftime('%d/%m %H:%M')
                valid_iso = valid_dt.isoformat()
            except:
                valid_formatted = valid_str[:16] if valid_str else ''
                valid_iso = valid_str
            
            type_es = REPORT_TRANSLATIONS.get(report_type, report_type.title())
            icon = REPORT_ICONS.get(report_type, '📋')
            
            # Unidades
            unit = unit_es = ''
            if 'SNOW' in report_type or 'SLEET' in report_type:
                unit, unit_es = 'in', 'pulg.'
            elif 'RAIN' in report_type or 'FLOOD' in report_type:
                unit, unit_es = 'in', 'pulg.'
            elif 'HAIL' in report_type:
                unit, unit_es = 'in', 'pulg.'
            elif 'WIND' in report_type or 'WND' in report_type:
                unit, unit_es = 'mph', 'mph'
            
            report = {
                'id': f"{wfo}_{valid_str}_{lat}_{lon}",
                'type': report_type, 'type_es': type_es, 'icon': icon,
                'magnitude': magnitude, 'unit': unit, 'unit_es': unit_es,
                'city': city.title() if city else '',
                'county': county.title() if county else '',
                'state': state, 'state_name': STATE_NAMES.get(state, state),
                'source': source, 'remark': remark,
                'valid': valid_iso, 'valid_formatted': valid_formatted,
                'wfo': wfo, 'lat': lat, 'lon': lon,
            }
            
            reports.append(report)
            by_state[state].append(report)
            by_type[report_type].append(report)
            
            # Máximos
            if magnitude and magnitude > 0:
                if 'SNOW' in report_type:
                    if not maximos['nieve'] or magnitude > maximos['nieve']['magnitude']:
                        maximos['nieve'] = report.copy()
                elif 'RAIN' in report_type or 'FLOOD' in report_type:
                    if not maximos['lluvia'] or magnitude > maximos['lluvia']['magnitude']:
                        maximos['lluvia'] = report.copy()
                elif 'HAIL' in report_type:
                    if not maximos['granizo'] or magnitude > maximos['granizo']['magnitude']:
                        maximos['granizo'] = report.copy()
                elif 'WIND' in report_type or 'WND' in report_type:
                    if not maximos['viento'] or magnitude > maximos['viento']['magnitude']:
                        maximos['viento'] = report.copy()
        
        reports.sort(key=lambda x: x['valid'], reverse=True)
        
        # Stats por tipo
        stats_by_type = {}
        for rt, reps in by_type.items():
            stats_by_type[rt] = {
                'type': rt,
                'type_es': REPORT_TRANSLATIONS.get(rt, rt.title()),
                'icon': REPORT_ICONS.get(rt, '📋'),
                'count': len(reps),
            }
        
        # Tipos invernales
        winter_types = ['SNOW', 'HEAVY SNOW', 'SLEET', 'FREEZING RAIN', 'ICE STORM', 'BLIZZARD', 'LAKE EFFECT SNOW']
        rain_types = ['HEAVY RAIN', 'FLASH FLOOD', 'FLOOD']
        
        winter_reports = [r for r in reports if r['type'] in winter_types]
        rain_reports = [r for r in reports if r['type'] in rain_types]
        
        return {
            'generated': datetime.now(timezone.utc).isoformat(),
            'hours_covered': CONFIG['hours_back'],
            'total_reports': len(reports),
            'reports': reports[:100],
            'winter_reports': winter_reports[:50],
            'rain_reports': rain_reports[:50],
            'maximos': {k: v for k, v in maximos.items() if v},
            'by_type': stats_by_type,
            'summary': {
                'total': len(reports),
                'snow': len([r for r in reports if 'SNOW' in r['type']]),
                'ice': len([r for r in reports if r['type'] in ['FREEZING RAIN', 'ICE STORM', 'SLEET']]),
                'rain': len([r for r in reports if r['type'] in rain_types]),
                'wind': len([r for r in reports if 'WIND' in r['type'] or 'WND' in r['type']]),
                'hail': len([r for r in reports if 'HAIL' in r['type']]),
                'tornado': len([r for r in reports if 'TORNADO' in r['type']]),
            }
        }
    
    def save_json(self, data):
        try:
            output_path = Path(CONFIG['output_json'])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"JSON guardado: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error guardando JSON: {e}")
            return False
    
    def upload_to_s3(self):
        s3_uri = f"s3://{CONFIG['s3_bucket']}/{CONFIG['s3_path']}"
        cmd = [
            'aws', '--profile', CONFIG['aws_profile'],
            's3', 'cp', str(CONFIG['output_json']), s3_uri,
            '--endpoint-url', CONFIG['aws_endpoint'],
            '--acl', 'public-read',
            '--content-type', 'application/json',
            '--cache-control', 'max-age=60'
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.info(f"JSON subido a S3: {CONFIG['s3_url']}")
                return True
            else:
                logger.error(f"Error subiendo a S3: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error en AWS CLI: {e}")
            return False
    
    def run_once(self, hours=None):
        hours = hours or CONFIG['hours_back']
        features = self.fetch_lsr_data(hours)
        
        if not features:
            logger.warning("No se obtuvieron reportes")
            data = {
                'generated': datetime.now(timezone.utc).isoformat(),
                'hours_covered': hours,
                'total_reports': 0,
                'reports': [], 'winter_reports': [], 'rain_reports': [],
                'maximos': {}, 'by_type': {},
                'summary': {'total': 0, 'snow': 0, 'ice': 0, 'rain': 0, 'wind': 0, 'hail': 0, 'tornado': 0}
            }
        else:
            data = self.process_reports(features)
        
        if self.save_json(data):
            self.upload_to_s3()
            return True
        return False
    
    def run_daemon(self):
        logger.info(f"Iniciando daemon (intervalo: {CONFIG['update_interval']}s)")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error en ciclo: {e}")
            logger.info(f"Esperando {CONFIG['update_interval']} segundos...")
            time.sleep(CONFIG['update_interval'])


def main():
    parser = argparse.ArgumentParser(description='Storm Reports Collector')
    parser.add_argument('--daemon', action='store_true', help='Ejecutar en bucle')
    parser.add_argument('--hours', type=int, default=24, help='Horas hacia atrás')
    args = parser.parse_args()
    
    collector = StormReportsCollector()
    
    if args.daemon:
        CONFIG['hours_back'] = args.hours
        collector.run_daemon()
    else:
        collector.run_once(args.hours)


if __name__ == '__main__':
    main()
