#!/usr/bin/env python3
"""
astro-lunar.py v5 - Genera datos lunares y los sube a DigitalOcean Spaces
Para Canal Meteo TV

Estructura:
- Scripts: /opt/canalmeteo/scripts/
- Entorno Python: /opt/canalmeteo/env/
- Datos temporales: /mnt/canalmeteo_data_01/
- Publicación: s3://canalmeteo-public/ via AWS CLI
"""

import json
import math
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import sys
import calendar

# Configuración
CONFIG = {
    # Directorios locales
    'base_dir': '/mnt/canalmeteo_data_01',
    'data_dir': '/mnt/canalmeteo_data_01/astro',
    'output_file': 'lunar-data.json',
    'log_dir': '/mnt/canalmeteo_data_01/logs',
    'log_file': 'astro-lunar.log',
    
    # AWS/Spaces config
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_path': 'data/astro',  # s3://canalmeteo-public/data/astro/lunar-data.json
    
    # Parámetros de generación
    'days_range': 100,
    'months_range': 12,
    
    # NASA SVS
    'svs_base_url': 'https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/frames',
    'image_size_large': '730x730_1x1_30p',
    'image_size_small': '216x216_1x1_30p',
}

SYNODIC_MONTH = 29.530588853
EPOCH_NEW_MOON_JD = 2451550.1

PHASE_NAMES = {
    'New Moon': 'Luna nueva',
    'Waxing Crescent': 'Luna creciente',
    'First Quarter': 'Cuarto creciente',
    'Waxing Gibbous': 'Gibosa creciente',
    'Full Moon': 'Luna llena',
    'Waning Gibbous': 'Gibosa menguante',
    'Last Quarter': 'Cuarto menguante',
    'Waning Crescent': 'Luna menguante'
}

PHASE_DESCRIPTIONS = {
    'New Moon': 'La primera fase del ciclo lunar; cuando la Luna está entre la Tierra y el Sol, con su lado iluminado mirando hacia el Sol.',
    'Waxing Crescent': 'La segunda fase del ciclo lunar; ocurre después de la Luna Nueva. Una delgada franja de luz comienza a aparecer en el lado derecho.',
    'First Quarter': 'La tercera fase del ciclo lunar; la mitad derecha de la Luna está iluminada. Marca el primer cuarto del ciclo lunar.',
    'Waxing Gibbous': 'La cuarta fase del ciclo lunar; más de la mitad de la Luna está iluminada, creciendo hacia la Luna Llena.',
    'Full Moon': 'La quinta fase del ciclo lunar; la Luna está completamente iluminada porque está en el lado opuesto de la Tierra respecto al Sol.',
    'Waning Gibbous': 'La sexta fase del ciclo lunar; ocurre entre la Luna Llena y el último cuarto de Luna. Las fases menguantes representan a la Luna volviéndose menos iluminada.',
    'Last Quarter': 'La séptima fase del ciclo lunar; la mitad izquierda de la Luna está iluminada. Marca el tercer cuarto del ciclo lunar.',
    'Waning Crescent': 'La octava y última fase del ciclo lunar; solo una delgada franja de luz queda visible en el lado izquierdo antes de la Luna Nueva.'
}

DAY_NAMES_ES = {
    'Monday': 'lunes', 'Tuesday': 'martes', 'Wednesday': 'miércoles',
    'Thursday': 'jueves', 'Friday': 'viernes', 'Saturday': 'sábado',
    'Sunday': 'domingo'
}

MONTH_NAMES_ES = {
    1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
    5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
    9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
}

MONTH_NAMES_ES_CAPS = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
    5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
    9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}


def setup_directories():
    """Crea la estructura de directorios necesaria."""
    dirs = [
        CONFIG['base_dir'],
        CONFIG['data_dir'],
        CONFIG['log_dir'],
        f"{CONFIG['base_dir']}/gribs",
        f"{CONFIG['base_dir']}/csv",
        f"{CONFIG['base_dir']}/maps",
        f"{CONFIG['base_dir']}/cache",
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def setup_logging():
    """Configura el sistema de logging."""
    log_path = Path(CONFIG['log_dir']) / CONFIG['log_file']
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def upload_to_spaces(local_file, s3_key, logger):
    """Sube un archivo a DigitalOcean Spaces usando AWS CLI."""
    s3_uri = f"s3://{CONFIG['s3_bucket']}/{s3_key}"
    
    cmd = [
        'aws', '--profile', CONFIG['aws_profile'],
        's3', 'cp', str(local_file), s3_uri,
        '--endpoint-url', CONFIG['aws_endpoint'],
        '--acl', 'public-read',
        '--content-type', 'application/json'
    ]
    
    logger.info(f"Subiendo {local_file} a {s3_uri}...")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            public_url = f"https://{CONFIG['s3_bucket']}.sfo3.digitaloceanspaces.com/{s3_key}"
            logger.info(f"Subido correctamente: {public_url}")
            return public_url
        else:
            logger.error(f"Error al subir: {result.stderr}")
            return None
    except subprocess.TimeoutExpired:
        logger.error("Timeout al subir archivo")
        return None
    except Exception as e:
        logger.error(f"Excepción al subir: {e}")
        return None


def datetime_to_julian(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.timestamp() / 86400.0 + 2440587.5


def get_frame_number(dt, year=2026):
    year_start = datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    
    if dt.year != year:
        day_of_year = dt.timetuple().tm_yday
        hour = dt.hour
        frame = (day_of_year - 1) * 24 + hour + 1
    else:
        hours_since_start = int((dt - year_start).total_seconds() / 3600)
        frame = hours_since_start + 1
    
    return max(1, min(frame, 8760))


def get_moon_image_url(dt, size='large'):
    frame = get_frame_number(dt)
    size_path = CONFIG['image_size_large'] if size == 'large' else CONFIG['image_size_small']
    return f"{CONFIG['svs_base_url']}/{size_path}/moon.{frame:04d}.jpg"


def calculate_moon_phase(dt):
    jd = datetime_to_julian(dt)
    age = (jd - EPOCH_NEW_MOON_JD) % SYNODIC_MONTH
    phase = age / SYNODIC_MONTH
    illumination = 0.5 * (1 - math.cos(2 * math.pi * phase))
    
    phase_names_ordered = [
        "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
        "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"
    ]
    phase_index = int(phase * 8 + 0.5) % 8
    phase_name = phase_names_ordered[phase_index]
    is_waxing = phase < 0.5
    days_to_full = (0.5 - phase) * SYNODIC_MONTH if phase < 0.5 else (1.5 - phase) * SYNODIC_MONTH
    
    return {
        'phase': phase,
        'age': age,
        'illumination': illumination,
        'illumination_percent': round(illumination * 100, 1),
        'phase_name': phase_name,
        'phase_name_es': PHASE_NAMES.get(phase_name, phase_name),
        'phase_description': PHASE_DESCRIPTIONS.get(phase_name, ''),
        'is_waxing': is_waxing,
        'days_to_full_moon': round(days_to_full, 1),
    }


def calculate_moon_distance(dt):
    reference_perigee = datetime(2024, 1, 13, tzinfo=timezone.utc)
    anomalistic_month = 27.55455
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days_since = (dt - reference_perigee).total_seconds() / 86400
    phase = (days_since % anomalistic_month) / anomalistic_month
    mean_distance_km = 384400
    variation_km = 21000
    distance_km = mean_distance_km + variation_km * math.cos(2 * math.pi * phase + math.pi)
    distance_miles = distance_km * 0.621371
    angular_diameter = 2 * math.atan(3474 / (2 * distance_km)) * (180 / math.pi) * 3600
    
    return {
        'distance_km': round(distance_km),
        'distance_miles': round(distance_miles),
        'angular_diameter': round(angular_diameter, 1)
    }


def calculate_moonrise_moonset(dt, lat=29.76, lon=-95.37):
    phase_data = calculate_moon_phase(dt)
    phase = phase_data['phase']
    base_rise = 6 + phase * 12
    base_set = 18 + phase * 12
    lon_offset = (lon + 95.37) * 4 / 60
    rise_hour = (base_rise - lon_offset) % 24
    set_hour = (base_set - lon_offset) % 24
    
    def fmt(h):
        return f"{int(h):02d}:{int((h % 1) * 60):02d}"
    
    rise_azimuth = 90 + (phase - 0.5) * 60
    set_azimuth = 270 - (phase - 0.5) * 60
    
    return {
        'moonrise': fmt(rise_hour),
        'moonrise_azimuth': round(rise_azimuth % 360, 1),
        'moonset': fmt(set_hour),
        'moonset_azimuth': round(set_azimuth % 360, 1),
        'transit': fmt((rise_hour + 6) % 24),
        'transit_altitude': round(45 + lat * 0.3, 1)
    }


def find_all_phases(start_year, end_year):
    phases = []
    dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    phase_data = calculate_moon_phase(dt)
    current_new = dt - timedelta(days=phase_data['age'])
    end_dt = datetime(end_year + 1, 1, 31, tzinfo=timezone.utc)
    
    while current_new < end_dt:
        for offset, name, name_es in [
            (0, 'New Moon', 'Luna nueva'),
            (0.25, 'First Quarter', 'Cuarto creciente'),
            (0.5, 'Full Moon', 'Luna llena'),
            (0.75, 'Last Quarter', 'Cuarto menguante')
        ]:
            phase_dt = current_new + timedelta(days=SYNODIC_MONTH * offset)
            if start_year <= phase_dt.year <= end_year:
                phases.append({
                    'phase': name,
                    'phase_es': name_es,
                    'date': phase_dt.strftime('%Y-%m-%d'),
                    'day': phase_dt.day,
                    'month': phase_dt.month,
                    'year': phase_dt.year,
                    'time': phase_dt.strftime('%H:%M'),
                    'image': get_moon_image_url(phase_dt, 'small'),
                    'frame': get_frame_number(phase_dt),
                })
        current_new += timedelta(days=SYNODIC_MONTH)
    
    phases.sort(key=lambda x: x['date'])
    return phases


def generate_annual_calendar(year, phases):
    annual = {}
    for month in range(1, 13):
        month_phases = [p for p in phases if p['month'] == month and p['year'] == year]
        phase_order = {'New Moon': 0, 'First Quarter': 1, 'Full Moon': 2, 'Last Quarter': 3}
        month_phases.sort(key=lambda x: (x['day'], phase_order.get(x['phase'], 4)))
        annual[month] = {
            'month': month,
            'month_name': MONTH_NAMES_ES_CAPS[month],
            'phases': month_phases[:5]
        }
    return annual


def generate_daily_data(today, days_range, logger=None):
    daily_data = []
    
    for delta in range(-days_range, days_range + 1):
        dt = today + timedelta(days=delta)
        dt_noon = dt.replace(hour=12, minute=0, second=0)
        
        phase_data = calculate_moon_phase(dt_noon)
        distance_data = calculate_moon_distance(dt_noon)
        times_data = calculate_moonrise_moonset(dt_noon)
        
        weekday = dt.strftime('%A')
        
        day_data = {
            'date': dt.strftime('%Y-%m-%d'),
            'day': dt.day,
            'month': dt.month,
            'month_name': MONTH_NAMES_ES[dt.month],
            'year': dt.year,
            'day_of_week': weekday,
            'day_of_week_es': DAY_NAMES_ES.get(weekday, weekday),
            'delta_days': delta,
            'is_today': delta == 0,
            
            'phase': phase_data['phase_name'],
            'phase_es': phase_data['phase_name_es'],
            'phase_description': phase_data['phase_description'],
            'illumination': round(phase_data['illumination_percent'], 1),
            'is_waxing': phase_data['is_waxing'],
            'age_days': round(phase_data['age'], 1),
            'days_to_full_moon': phase_data['days_to_full_moon'],
            
            'moonrise': times_data['moonrise'],
            'moonrise_azimuth': times_data['moonrise_azimuth'],
            'moonset': times_data['moonset'],
            'moonset_azimuth': times_data['moonset_azimuth'],
            'transit': times_data['transit'],
            'transit_altitude': times_data['transit_altitude'],
            
            'distance_km': distance_data['distance_km'],
            'distance_miles': distance_data['distance_miles'],
            'angular_diameter': distance_data['angular_diameter'],
            
            'image_large': get_moon_image_url(dt_noon, 'large'),
            'image_small': get_moon_image_url(dt_noon, 'small'),
            'frame_number': get_frame_number(dt_noon),
        }
        
        daily_data.append(day_data)
        
        if logger and delta % 50 == 0:
            logger.info(f"  Día {delta}: {dt.strftime('%Y-%m-%d')}")
    
    return daily_data


def generate_month_calendar(year, month, phases):
    cal = calendar.Calendar(firstweekday=0)
    month_days = list(cal.itermonthdates(year, month))
    
    month_phases = {}
    for phase in phases:
        if phase['month'] == month and phase['year'] == year:
            month_phases[phase['day']] = phase
    
    weeks = []
    week = []
    for date in month_days:
        dt_noon = datetime(date.year, date.month, date.day, 12, 0, 0, tzinfo=timezone.utc)
        phase_data = calculate_moon_phase(dt_noon)
        
        day_data = {
            'day': date.day,
            'in_month': date.month == month,
            'date': date.strftime('%Y-%m-%d'),
            'phase': month_phases.get(date.day, {}).get('phase_es', '') if date.month == month else '',
            'illumination': round(phase_data['illumination_percent'], 1),
            'image': get_moon_image_url(dt_noon, 'small'),
            'frame': get_frame_number(dt_noon),
        }
        week.append(day_data)
        if len(week) == 7:
            weeks.append(week)
            week = []
    
    if week:
        while len(week) < 7:
            week.append({'day': 0, 'in_month': False, 'date': '', 'phase': '', 'image': ''})
        weeks.append(week)
    
    return {
        'year': year,
        'month': month,
        'month_name': MONTH_NAMES_ES_CAPS[month],
        'weeks': weeks,
    }


def generate_all_month_calendars(today, months_range, phases, logger=None):
    calendars = []
    
    for delta in range(-months_range, months_range + 1):
        target_month = today.month + delta
        target_year = today.year
        
        while target_month > 12:
            target_month -= 12
            target_year += 1
        while target_month < 1:
            target_month += 12
            target_year -= 1
        
        cal = generate_month_calendar(target_year, target_month, phases)
        cal['delta_months'] = delta
        cal['is_current'] = delta == 0
        calendars.append(cal)
        
        if logger and delta % 6 == 0:
            logger.info(f"  Calendario: {cal['month_name']} {target_year}")
    
    return calendars


def main():
    # Crear directorios
    setup_directories()
    
    # Configurar logging
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info("Iniciando generación de datos lunares v5")
    logger.info("=" * 60)
    
    today = datetime.now(timezone.utc)
    current_year = today.year
    
    # Generar datos
    logger.info(f"Generando datos para ±{CONFIG['days_range']} días...")
    daily_data = generate_daily_data(today, CONFIG['days_range'], logger)
    
    logger.info("Calculando fases lunares (2025-2027)...")
    all_phases = find_all_phases(current_year - 1, current_year + 1)
    
    logger.info("Generando calendario anual...")
    annual_calendar = generate_annual_calendar(current_year, all_phases)
    
    logger.info(f"Generando ±{CONFIG['months_range']} meses de calendarios...")
    month_calendars = generate_all_month_calendars(today, CONFIG['months_range'], all_phases, logger)
    
    # Encontrar próximas fases
    today_str = today.strftime('%Y-%m-%d')
    next_full = next((p for p in all_phases if p['phase'] == 'Full Moon' and p['date'] >= today_str), None)
    next_new = next((p for p in all_phases if p['phase'] == 'New Moon' and p['date'] >= today_str), None)
    
    today_data = next((d for d in daily_data if d.get('is_today')), None)
    
    # Construir JSON
    output_data = {
        'generated_at': today.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'current_year': current_year,
        'is_waxing': today_data.get('is_waxing', True) if today_data else True,
        'daily_data': daily_data,
        'phases': all_phases,
        'annual_calendar': annual_calendar,
        'month_calendars': month_calendars,
        'next_full_moon': next_full,
        'next_new_moon': next_new,
        'nasa_svs': {
            'visualization_id': '5587',
            'year': current_year,
            'source': 'NASA Scientific Visualization Studio',
            'url': 'https://svs.gsfc.nasa.gov/5587/'
        },
        'metadata': {
            'days_range': CONFIG['days_range'],
            'months_range': CONFIG['months_range'],
            'version': '5.0'
        }
    }
    
    # Guardar localmente
    local_path = Path(CONFIG['data_dir']) / CONFIG['output_file']
    with open(local_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Datos guardados localmente: {local_path}")
    logger.info(f"Total días: {len(daily_data)}, Fases: {len(all_phases)}, Calendarios: {len(month_calendars)}")
    
    # Subir a DigitalOcean Spaces
    s3_key = f"{CONFIG['s3_path']}/{CONFIG['output_file']}"
    public_url = upload_to_spaces(local_path, s3_key, logger)
    
    if public_url:
        logger.info(f"URL pública: {public_url}")
    else:
        logger.error("No se pudo subir el archivo a Spaces")
        return 1
    
    logger.info("=" * 60)
    logger.info("Generación completada exitosamente")
    logger.info("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
