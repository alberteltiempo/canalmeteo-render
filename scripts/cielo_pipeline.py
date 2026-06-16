#!/usr/bin/env python3
"""
cielo_pipeline.py - Canal Meteo TV (v1.1)
Genera /opt/canalmeteo/data/astro/cielo.json combinando:
- Luna (de lunar-data.json local)
- Sol: salida/puesta calculados localmente (algoritmo NOAA) para 60 ciudades
- Auroras: Kp actual + pronóstico + hemispheric power
- Eventos: lluvias de meteoritos 2026 + eclipses (hardcoded, datos USNO estables)
- Planetas visibles: del módulo planetas_2026.py

Sube el resultado a CDN como data/astro/cielo.json
Cron sugerido: cada hora a y media
"""

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Importar tabla de planetas ───────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from planetas_2026 import obtener_visibilidad as planetas_del_mes
except ImportError:
    def planetas_del_mes(mes):
        return []

# ── Rutas ─────────────────────────────────────────────────────────
LUNAR_JSON = '/mnt/canalmeteo_data_01/astro/lunar-data.json'
SPACE_DIR = '/opt/canalmeteo/data/space-weather'
CITIES_JSON_CDN = 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/cities/weather.json'
OUTPUT_LOCAL = '/opt/canalmeteo/data/astro/cielo.json'
OUTPUT_CDN_KEY = 'data/astro/cielo.json'
LOG_FILE = '/var/log/canalmeteo/cielo_pipeline.log'

ENV_FILE = '/opt/canalmeteo/.env'
SPACES_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
SPACES_BUCKET = 'canalmeteo-public'

# ── Logging ───────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass

# ── Eventos astronómicos 2026 (datos estables, USNO/IMO) ─────────
LLUVIAS_METEORITOS_2026 = [
    {'nombre': 'Cuadrántidas', 'inicio': '2026-12-28', 'pico': '2026-01-04', 'fin': '2026-01-12', 'tasa': 110, 'descripcion': 'Una de las lluvias más intensas del año, ideal para observar antes del amanecer.'},
    {'nombre': 'Líridas',      'inicio': '2026-04-16', 'pico': '2026-04-22', 'fin': '2026-04-25', 'tasa': 18,  'descripcion': 'Activa en primavera, con meteoros rápidos y brillantes.'},
    {'nombre': 'Eta Acuáridas','inicio': '2026-04-19', 'pico': '2026-05-06', 'fin': '2026-05-28', 'tasa': 50,  'descripcion': 'Restos del cometa Halley. Mejor visible desde el hemisferio sur.'},
    {'nombre': 'Delta Acuáridas','inicio': '2026-07-12', 'pico': '2026-07-30', 'fin': '2026-08-23', 'tasa': 25, 'descripcion': 'Activa toda la segunda mitad del verano.'},
    {'nombre': 'Perseidas',    'inicio': '2026-07-17', 'pico': '2026-08-12', 'fin': '2026-08-24', 'tasa': 100, 'descripcion': 'La lluvia más popular del verano boreal. Meteoros brillantes y rápidos.'},
    {'nombre': 'Oriónidas',    'inicio': '2026-10-02', 'pico': '2026-10-21', 'fin': '2026-11-07', 'tasa': 20,  'descripcion': 'Otra lluvia ligada al cometa Halley, con meteoros muy rápidos.'},
    {'nombre': 'Leónidas',     'inicio': '2026-11-06', 'pico': '2026-11-17', 'fin': '2026-11-30', 'tasa': 15,  'descripcion': 'Meteoros muy rápidos. Cada 33 años produce lluvias intensas.'},
    {'nombre': 'Gemínidas',    'inicio': '2026-12-04', 'pico': '2026-12-14', 'fin': '2026-12-17', 'tasa': 150, 'descripcion': 'La lluvia más intensa del año. Meteoros lentos y coloridos.'},
    {'nombre': 'Úrsidas',      'inicio': '2026-12-17', 'pico': '2026-12-22', 'fin': '2026-12-26', 'tasa': 10,  'descripcion': 'Pequeña lluvia justo antes de Navidad.'},
]

ECLIPSES_2026 = [
    {'tipo': 'Eclipse solar anular', 'fecha': '2026-02-17', 'descripcion': 'Visible parcialmente en la Antártida y sur de África.', 'visible_us': False},
    {'tipo': 'Eclipse lunar penumbral', 'fecha': '2026-03-03', 'descripcion': 'Visible en gran parte de América.', 'visible_us': True},
    {'tipo': 'Eclipse solar total', 'fecha': '2026-08-12', 'descripcion': 'Visible en Groenlandia, Islandia y España.', 'visible_us': False},
    {'tipo': 'Eclipse lunar parcial', 'fecha': '2026-08-28', 'descripcion': 'Visible en gran parte de América y Europa.', 'visible_us': True},
]

# ── Nombres tradicionales de lunas llenas ────────────────────────
NOMBRES_LUNA_LLENA = {
    1:  'Luna del Lobo',
    2:  'Luna de Nieve',
    3:  'Luna del Gusano',
    4:  'Luna Rosa',
    5:  'Luna de las Flores',
    6:  'Luna de Fresa',
    7:  'Luna del Ciervo',
    8:  'Luna del Esturión',
    9:  'Luna de la Cosecha',
    10: 'Luna del Cazador',
    11: 'Luna del Castor',
    12: 'Luna Fría',
}

# ── Cálculo de salida/puesta del Sol (algoritmo NOAA SPA simplificado) ────
def calcular_sol(lat, lon, fecha=None):
    """
    Calcula salida/puesta del sol para una latitud/longitud dada.
    Devuelve dict con sol_salida, sol_puesta (HH:MM en hora local del lugar),
    duracion_dia, y zona horaria asumida (UTC offset por lon).
    """
    if fecha is None:
        fecha = datetime.now(timezone.utc)
    
    # Día del año
    N = fecha.timetuple().tm_yday
    
    # Convertir latitud y longitud a radianes
    lat_rad = math.radians(lat)
    
    # Longitud media del sol (aproximación)
    M = math.radians((357.5291 + 0.98560028 * (N - 1)) % 360)
    
    # Ecuación del centro
    C = math.radians(1.9148 * math.sin(M) + 0.0200 * math.sin(2*M) + 0.0003 * math.sin(3*M))
    
    # Longitud eclíptica del sol
    lambda_sun = M + C + math.radians(102.9372) + math.pi
    
    # Declinación solar
    decl = math.asin(math.sin(lambda_sun) * math.sin(math.radians(23.44)))
    
    # Ángulo horario al amanecer/atardecer
    cos_omega = (math.sin(math.radians(-0.83)) - math.sin(lat_rad) * math.sin(decl)) / (math.cos(lat_rad) * math.cos(decl))
    
    if cos_omega > 1:
        # Sol no sale (noche polar)
        return {'sol_salida': '--:--', 'sol_puesta': '--:--', 'duracion_dia': '0h 0m', 'is_polar_night': True, 'is_midnight_sun': False}
    if cos_omega < -1:
        # Sol no se pone (día polar)
        return {'sol_salida': '--:--', 'sol_puesta': '--:--', 'duracion_dia': '24h', 'is_polar_night': False, 'is_midnight_sun': True}
    
    omega = math.acos(cos_omega)
    omega_h = math.degrees(omega) / 15.0  # horas
    
    # Mediodía solar en UTC (Julian Day fraction)
    # Para una fecha N: mediodía solar ~ 12:00 - 4*lon/60 horas (UTC)
    # Ecuación del tiempo aproximada
    B = math.radians(360.0 * (N - 81) / 365.0)
    EoT = 9.87 * math.sin(2*B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)  # minutos
    
    mediodia_utc = 12.0 - lon / 15.0 - EoT / 60.0
    
    sol_salida_utc = mediodia_utc - omega_h
    sol_puesta_utc = mediodia_utc + omega_h
    
    # Convertir a hora local asumiendo offset por longitud (NO usa DST, aproximado)
    # Mejor: para US usamos zonas horarias estándar por longitud
    offset = round(lon / 15.0)
    # Ajuste DST simple: mar-nov +1 (US DST aprox)
    mes = fecha.month
    if 3 <= mes <= 10:
        offset += 1
    
    sol_salida_local = (sol_salida_utc + offset) % 24
    sol_puesta_local = (sol_puesta_utc + offset) % 24
    
    duracion_h = (sol_puesta_utc - sol_salida_utc) % 24
    horas = int(duracion_h)
    minutos = int((duracion_h - horas) * 60)
    
    def fmt(t):
        h = int(t)
        m = int((t - h) * 60)
        return f'{h:02d}:{m:02d}'
    
    return {
        'sol_salida': fmt(sol_salida_local),
        'sol_puesta': fmt(sol_puesta_local),
        'duracion_dia': f'{horas}h {minutos}m',
        'is_polar_night': False,
        'is_midnight_sun': False,
    }

# ── Carga de datos ────────────────────────────────────────────────
def cargar_lunar():
    """Lee lunar-data.json y extrae lo que necesitamos para HOY."""
    # Probar varias rutas conocidas
    candidates = [
        LUNAR_JSON,
        '/opt/canalmeteo/data/astro/lunar-data.json',
        '/var/www/html/geojson/lunar-data.json',
    ]
    path = None
    for c in candidates:
        if os.path.exists(c):
            path = c
            break
    if path is None:
        raise FileNotFoundError(f'lunar-data.json no encontrado en ninguna ruta: {candidates}')
    
    log(f'Leyendo {path}')
    with open(path) as f:
        data = json.load(f)
    
    # Encontrar el día de hoy
    hoy = None
    for day in data.get('daily_data', []):
        if day.get('is_today'):
            hoy = day
            break
    
    if not hoy and data.get('daily_data'):
        hoy = data['daily_data'][0]
    
    next_full = data.get('next_full_moon', {})
    next_new = data.get('next_new_moon', {})
    
    # Nombre tradicional de la próxima luna llena
    nombre_tradicional = None
    if next_full:
        mes_full = next_full.get('month')
        if mes_full and mes_full in NOMBRES_LUNA_LLENA:
            nombre_tradicional = NOMBRES_LUNA_LLENA[mes_full]
    
    luna = {
        'fase': hoy.get('phase_es', '--'),
        'fase_descripcion': hoy.get('phase_description', ''),
        'iluminacion': round(hoy.get('illumination', 0)),
        'es_creciente': hoy.get('is_waxing', False),
        'edad_dias': round(hoy.get('age_days', 0), 1),
        'dias_a_luna_llena': hoy.get('days_to_full_moon', 0),
        'distancia_km': hoy.get('distance_km', 0),
        'distancia_miles': hoy.get('distance_miles', 0),
        'luna_salida': hoy.get('moonrise', '--:--'),
        'luna_puesta': hoy.get('moonset', '--:--'),
        'imagen_grande': hoy.get('image_large', ''),
        'imagen_pequena': hoy.get('image_small', ''),
        'proxima_luna_llena': {
            'fecha': next_full.get('date', ''),
            'dia': next_full.get('day'),
            'mes': next_full.get('month'),
            'year': next_full.get('year'),
            'hora': next_full.get('time', ''),
            'imagen': next_full.get('image', ''),
            'nombre_tradicional': nombre_tradicional,
        },
        'proxima_luna_nueva': {
            'fecha': next_new.get('date', ''),
            'dia': next_new.get('day'),
            'mes': next_new.get('month'),
            'year': next_new.get('year'),
            'hora': next_new.get('time', ''),
        },
    }
    return luna

def cargar_auroras():
    """Lee planetary-k-index y forecast y hemispheric-power. Devuelve resumen."""
    log('Cargando datos de auroras (Kp + hemispheric power)')
    
    # Kp actual: último valor observado
    kp_now = 0
    kp_now_time = ''
    try:
        with open(f'{SPACE_DIR}/planetary-k-index.json') as f:
            kp_data = json.load(f)
        if kp_data:
            ult = kp_data[-1]
            kp_now = ult.get('Kp', 0)
            kp_now_time = ult.get('time_tag', '')
    except Exception as e:
        log(f'  WARN al leer planetary-k-index: {e}')
    
    # Kp pronóstico próximas 72h: máximo
    kp_max_72h = kp_now
    kp_max_time = ''
    horizon_max = 0  # horas hasta el máximo
    try:
        with open(f'{SPACE_DIR}/planetary-k-index-forecast.json') as f:
            forecast = json.load(f)
        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        limit = ahora + timedelta(hours=72)
        for item in forecast:
            if item.get('observed') != 'predicted':
                continue
            try:
                t = datetime.fromisoformat(item['time_tag'].replace('Z', ''))
            except Exception:
                continue
            if ahora <= t <= limit:
                kp = item.get('kp', 0)
                if kp > kp_max_72h:
                    kp_max_72h = kp
                    kp_max_time = item['time_tag']
                    horizon_max = round((t - ahora).total_seconds() / 3600)
    except Exception as e:
        log(f'  WARN al leer forecast Kp: {e}')
    
    # Hemispheric power: último valor norte
    hpi_north = 0
    try:
        with open(f'{SPACE_DIR}/hemispheric-power.json') as f:
            hp_data = json.load(f)
        if hp_data:
            hpi_north = hp_data[-1].get('hpi_north', 0)
    except Exception as e:
        log(f'  WARN al leer hemispheric-power: {e}')
    
    # Latitud mínima visible según Kp
    # (referencias NOAA SWPC)
    visibility_lat_table = {
        0: 67, 1: 66, 2: 64, 3: 62, 4: 60, 5: 58, 6: 56, 7: 54, 8: 52, 9: 50
    }
    kp_round = min(9, max(0, int(round(kp_max_72h))))
    lat_min_visible = visibility_lat_table[kp_round]
    
    # Clasificación de tormenta
    if kp_max_72h >= 7:
        nivel = 'severa'
        nivel_label = 'Tormenta severa'
    elif kp_max_72h >= 6:
        nivel = 'fuerte'
        nivel_label = 'Tormenta fuerte'
    elif kp_max_72h >= 5:
        nivel = 'moderada'
        nivel_label = 'Tormenta moderada'
    elif kp_max_72h >= 4:
        nivel = 'menor'
        nivel_label = 'Tormenta menor'
    else:
        nivel = 'tranquilo'
        nivel_label = 'Sin tormenta'
    
    return {
        'kp_now': round(kp_now, 1),
        'kp_now_time': kp_now_time,
        'kp_max_72h': round(kp_max_72h, 1),
        'kp_max_72h_time': kp_max_time,
        'horizon_horas': horizon_max,
        'hpi_north_gw': hpi_north,
        'lat_min_visible': lat_min_visible,
        'nivel': nivel,
        'nivel_label': nivel_label,
    }

def cargar_ciudades():
    """Carga las 60 ciudades del CDN para tener su lat/lon.
    El JSON tiene la lista en 'data' y un dict 'by_key' indexado por 'City|State'."""
    log(f'Descargando lista de ciudades desde {CITIES_JSON_CDN}')
    import urllib.request
    try:
        with urllib.request.urlopen(CITIES_JSON_CDN, timeout=10) as resp:
            data = json.load(resp)
        ciudades = data.get('data', [])
        log(f'  {len(ciudades)} ciudades cargadas')
        return ciudades
    except Exception as e:
        log(f'  ERROR al cargar cities/weather.json: {e}')
        return []

# ── Eventos próximos ──────────────────────────────────────────────
def proximos_eventos(luna_actual):
    """Devuelve lista de los próximos 5 eventos astronómicos."""
    ahora = datetime.now()
    eventos = []
    
    # Lluvias de meteoritos: añadir las activas o futuras hasta 90 días
    for lluvia in LLUVIAS_METEORITOS_2026:
        try:
            pico = datetime.strptime(lluvia['pico'], '%Y-%m-%d')
        except Exception:
            continue
        # Mostrar lluvias cuyo pico es <= 90 días en el futuro o <= 7 días en el pasado
        delta = (pico - ahora).days
        if -7 <= delta <= 90:
            eventos.append({
                'tipo': 'meteoritos',
                'nombre': lluvia['nombre'],
                'fecha': lluvia['pico'],
                'dias_restantes': delta,
                'descripcion': lluvia['descripcion'],
                'tasa_por_hora': lluvia['tasa'],
            })
    
    # Eclipses
    for eclipse in ECLIPSES_2026:
        try:
            fecha = datetime.strptime(eclipse['fecha'], '%Y-%m-%d')
        except Exception:
            continue
        delta = (fecha - ahora).days
        if -7 <= delta <= 120:
            eventos.append({
                'tipo': 'eclipse',
                'nombre': eclipse['tipo'],
                'fecha': eclipse['fecha'],
                'dias_restantes': delta,
                'descripcion': eclipse['descripcion'],
                'visible_us': eclipse.get('visible_us', False),
            })
    
    # Luna llena
    plll = luna_actual.get('proxima_luna_llena', {})
    if plll.get('fecha'):
        try:
            fecha_full = datetime.strptime(plll['fecha'], '%Y-%m-%d')
            delta = (fecha_full - ahora).days
            if -1 <= delta <= 35:
                nombre = 'Luna Llena'
                if plll.get('nombre_tradicional'):
                    nombre = plll['nombre_tradicional']
                eventos.append({
                    'tipo': 'luna_llena',
                    'nombre': nombre,
                    'fecha': plll['fecha'],
                    'dias_restantes': delta,
                    'descripcion': f"Próxima luna llena del año. Salida cerca del atardecer.",
                })
        except Exception:
            pass
    
    # Ordenar por días restantes
    eventos.sort(key=lambda e: e['dias_restantes'])
    return eventos[:6]

# ── Subida a Spaces ───────────────────────────────────────────────
def cargar_credenciales_env():
    env = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        log(f'WARN: no se pudo leer {ENV_FILE}: {e}')
    return env

def subir_a_spaces(path_local, key_remoto):
    """Sube el archivo a DO Spaces vía AWS CLI con perfil do-tor1."""
    cmd = [
        'aws', 's3', 'cp', path_local,
        f's3://{SPACES_BUCKET}/{key_remoto}',
        '--profile', 'do-tor1',
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=300',
        '--endpoint-url', SPACES_ENDPOINT,
    ]
    log(f'Subiendo a Spaces: s3://{SPACES_BUCKET}/{key_remoto}')
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            log('  OK')
            return True
        log(f'  ERROR: {result.stderr}')
        return False
    except Exception as e:
        log(f'  EXCEPCION: {e}')
        return False

# ── Main ──────────────────────────────────────────────────────────
def main():
    log('=== Iniciando cielo_pipeline.py ===')
    
    # Asegurar carpeta de log
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(OUTPUT_LOCAL), exist_ok=True)
    
    # 1. Cargar luna
    luna = cargar_lunar()
    log(f'Luna: {luna["fase"]} ({luna["iluminacion"]}%)')
    
    # 2. Cargar auroras
    auroras = cargar_auroras()
    log(f'Auroras: Kp ahora {auroras["kp_now"]}, máx 72h {auroras["kp_max_72h"]}')
    
    # 3. Cargar ciudades y calcular sol
    ciudades = cargar_ciudades()
    por_ciudad = {}
    for c in ciudades:
        city_name = c.get('city')
        state = c.get('state')
        lat = c.get('lat')
        lon = c.get('lon') or c.get('lng')
        if not (city_name and state and lat is not None and lon is not None):
            continue
        key = f'{city_name}|{state}'
        sol = calcular_sol(lat, lon)
        # Visibilidad de aurora según lat
        auroras_visibles = abs(lat) >= auroras['lat_min_visible']
        por_ciudad[key] = {
            'sol_salida': sol['sol_salida'],
            'sol_puesta': sol['sol_puesta'],
            'duracion_dia': sol['duracion_dia'],
            'is_polar_night': sol.get('is_polar_night', False),
            'is_midnight_sun': sol.get('is_midnight_sun', False),
            'auroras_visibles': auroras_visibles,
            'lat': lat,
            'lon': lon,
        }
    log(f'Cálculos de sol para {len(por_ciudad)} ciudades completados')
    
    # 4. Eventos próximos
    eventos = proximos_eventos(luna)
    log(f'Próximos eventos: {len(eventos)}')
    for ev in eventos:
        log(f'  - {ev["nombre"]} ({ev["dias_restantes"]} días)')
    
    # 5. Planetas visibles este mes
    mes_actual = datetime.now().month
    planetas = planetas_del_mes(mes_actual)
    log(f'Planetas visibles ({len(planetas)}):')
    for p in planetas:
        log(f'  - {p["planeta"]} ({p["momento"]})')
    
    # 6. Empaquetar todo
    salida = {
        'generated_at': datetime.now(timezone.utc).isoformat() + 'Z',
        'luna': luna,
        'auroras': auroras,
        'eventos': eventos,
        'planetas': planetas,
        'por_ciudad': por_ciudad,
        'metadata': {
            'version': '1.1',
            'fuentes': ['NASA SVS', 'NOAA SWPC', 'USNO', 'IMO'],
            'cities_count': len(por_ciudad),
            'mes': mes_actual,
        }
    }
    
    # 7. Guardar local
    with open(OUTPUT_LOCAL, 'w') as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    log(f'Guardado en {OUTPUT_LOCAL} ({os.path.getsize(OUTPUT_LOCAL)} bytes)')
    
    # 8. Subir a Spaces
    if subir_a_spaces(OUTPUT_LOCAL, OUTPUT_CDN_KEY):
        log('=== OK: cielo.json subido al CDN ===')
        return 0
    else:
        log('=== ERROR: no se pudo subir ===')
        return 1

if __name__ == '__main__':
    sys.exit(main())
