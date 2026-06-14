#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
planets_pipeline.py — Canal Meteo TV
========================================
Bloque 2: Planetas visibles a simple vista.

Calcula para Mercurio, Venus, Marte, Júpiter y Saturno:
  • Datos GLOBALES (no dependen de la ubicación): magnitud aparente,
    constelación, fase iluminada, distancia a la Tierra
  • Datos LOCALES por ciudad: hora de salida/tránsito/puesta con
    azimut/altitud, y visibilidad clasificada como
    "anochecer" / "antes del amanecer"

Cobertura: 100 ciudades × 35 días (mismas que ephemeris_pipeline)
Output: data/astro/planets-daily.json (CDN, comprimido con gzip)

Ejecución: una vez al día (cron 00:25 UTC, después de ephemeris)
Tiempo aprox: 2-4 minutos

Dependencias: pyephem, pytz
Venv: /opt/canalmeteo/venv

Uso:
    python3 planets_pipeline.py              # ejecución completa + upload
    python3 planets_pipeline.py --no-upload  # solo genera JSON local
    python3 planets_pipeline.py --days 7     # 7 días (debug rápido)
"""

import argparse
import gzip
import json
import logging
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import ephem
import pytz

# CITIES se importa del módulo compartido (astro_cities.py debe estar en el mismo directorio)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from astro_cities import CITIES
except ImportError:
    sys.stderr.write("ERROR: astro_cities.py no encontrado. Debe estar en el mismo directorio.\n")
    sys.exit(1)

# ===== CONFIGURACIÓN =====
SCRIPT_NAME = 'planets_pipeline'
LOG_DIR = '/var/log/canalmeteo'
LOG_FILE = f'{LOG_DIR}/astro_planets.log'
TMP_OUTPUT = '/tmp/planets-daily.json'

CDN_BUCKET = 'canalmeteo-public'
CDN_KEY = 'data/astro/planets-daily.json'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'

DEFAULT_DAYS = 35

# Umbral de magnitud para "visible a simple vista" (cielo razonablemente oscuro)
NAKED_EYE_MAG_LIMIT = 5.5
# Altitud mínima sobre el horizonte para considerar "visible" en la práctica
# (por debajo de 5° suele haber edificios, árboles o extinción atmosférica)
MIN_ALTITUDE_DEG = 5.0

# Planetas a procesar
PLANETS = [
    ('mercury', ephem.Mercury, {'es': 'Mercurio', 'en': 'Mercury', 'sym': '☿'}),
    ('venus',   ephem.Venus,   {'es': 'Venus',    'en': 'Venus',   'sym': '♀'}),
    ('mars',    ephem.Mars,    {'es': 'Marte',    'en': 'Mars',    'sym': '♂'}),
    ('jupiter', ephem.Jupiter, {'es': 'Júpiter',  'en': 'Jupiter', 'sym': '♃'}),
    ('saturn',  ephem.Saturn,  {'es': 'Saturno',  'en': 'Saturn',  'sym': '♄'}),
]

# Constelaciones IAU (88 oficiales) — abreviatura → nombre en español/inglés
# Permite localizar los planetas en el cielo en idioma del usuario
CONSTELLATIONS = {
    'And': {'es': 'Andrómeda',         'en': 'Andromeda'},
    'Ant': {'es': 'Máquina Neumática', 'en': 'Antlia'},
    'Aps': {'es': 'Ave del Paraíso',   'en': 'Apus'},
    'Aql': {'es': 'Águila',            'en': 'Aquila'},
    'Aqr': {'es': 'Acuario',           'en': 'Aquarius'},
    'Ara': {'es': 'Altar',             'en': 'Ara'},
    'Ari': {'es': 'Aries',             'en': 'Aries'},
    'Aur': {'es': 'Auriga',            'en': 'Auriga'},
    'Boo': {'es': 'Boyero',            'en': 'Boötes'},
    'CMa': {'es': 'Can Mayor',         'en': 'Canis Major'},
    'CMi': {'es': 'Can Menor',         'en': 'Canis Minor'},
    'CVn': {'es': 'Lebreles',          'en': 'Canes Venatici'},
    'Cae': {'es': 'Cincel',            'en': 'Caelum'},
    'Cam': {'es': 'Jirafa',            'en': 'Camelopardalis'},
    'Cap': {'es': 'Capricornio',       'en': 'Capricornus'},
    'Car': {'es': 'Quilla',            'en': 'Carina'},
    'Cas': {'es': 'Casiopea',          'en': 'Cassiopeia'},
    'Cen': {'es': 'Centauro',          'en': 'Centaurus'},
    'Cep': {'es': 'Cefeo',             'en': 'Cepheus'},
    'Cet': {'es': 'Ballena',           'en': 'Cetus'},
    'Cha': {'es': 'Camaleón',          'en': 'Chamaeleon'},
    'Cir': {'es': 'Compás',            'en': 'Circinus'},
    'Cnc': {'es': 'Cáncer',            'en': 'Cancer'},
    'Col': {'es': 'Paloma',            'en': 'Columba'},
    'Com': {'es': 'Coma Berenices',    'en': 'Coma Berenices'},
    'CrA': {'es': 'Corona Austral',    'en': 'Corona Australis'},
    'CrB': {'es': 'Corona Boreal',     'en': 'Corona Borealis'},
    'Crt': {'es': 'Copa',              'en': 'Crater'},
    'Cru': {'es': 'Cruz del Sur',      'en': 'Crux'},
    'Crv': {'es': 'Cuervo',            'en': 'Corvus'},
    'Cyg': {'es': 'Cisne',             'en': 'Cygnus'},
    'Del': {'es': 'Delfín',            'en': 'Delphinus'},
    'Dor': {'es': 'Pez Dorado',        'en': 'Dorado'},
    'Dra': {'es': 'Dragón',            'en': 'Draco'},
    'Equ': {'es': 'Caballo Menor',     'en': 'Equuleus'},
    'Eri': {'es': 'Erídano',           'en': 'Eridanus'},
    'For': {'es': 'Horno',             'en': 'Fornax'},
    'Gem': {'es': 'Géminis',           'en': 'Gemini'},
    'Gru': {'es': 'Grulla',            'en': 'Grus'},
    'Her': {'es': 'Hércules',          'en': 'Hercules'},
    'Hor': {'es': 'Reloj',             'en': 'Horologium'},
    'Hya': {'es': 'Hidra',             'en': 'Hydra'},
    'Hyi': {'es': 'Hidra Macho',       'en': 'Hydrus'},
    'Ind': {'es': 'Indio',             'en': 'Indus'},
    'LMi': {'es': 'León Menor',        'en': 'Leo Minor'},
    'Lac': {'es': 'Lagarto',           'en': 'Lacerta'},
    'Leo': {'es': 'Leo',               'en': 'Leo'},
    'Lep': {'es': 'Liebre',            'en': 'Lepus'},
    'Lib': {'es': 'Libra',             'en': 'Libra'},
    'Lup': {'es': 'Lobo',              'en': 'Lupus'},
    'Lyn': {'es': 'Lince',             'en': 'Lynx'},
    'Lyr': {'es': 'Lira',              'en': 'Lyra'},
    'Men': {'es': 'Mesa',              'en': 'Mensa'},
    'Mic': {'es': 'Microscopio',       'en': 'Microscopium'},
    'Mon': {'es': 'Unicornio',         'en': 'Monoceros'},
    'Mus': {'es': 'Mosca',             'en': 'Musca'},
    'Nor': {'es': 'Regla',             'en': 'Norma'},
    'Oct': {'es': 'Octante',           'en': 'Octans'},
    'Oph': {'es': 'Ofiuco',            'en': 'Ophiuchus'},
    'Ori': {'es': 'Orión',             'en': 'Orion'},
    'Pav': {'es': 'Pavo Real',         'en': 'Pavo'},
    'Peg': {'es': 'Pegaso',            'en': 'Pegasus'},
    'Per': {'es': 'Perseo',            'en': 'Perseus'},
    'Phe': {'es': 'Fénix',             'en': 'Phoenix'},
    'Pic': {'es': 'Caballete',         'en': 'Pictor'},
    'PsA': {'es': 'Pez Austral',       'en': 'Piscis Austrinus'},
    'Psc': {'es': 'Piscis',            'en': 'Pisces'},
    'Pup': {'es': 'Popa',              'en': 'Puppis'},
    'Pyx': {'es': 'Brújula',           'en': 'Pyxis'},
    'Ret': {'es': 'Retículo',          'en': 'Reticulum'},
    'Scl': {'es': 'Escultor',          'en': 'Sculptor'},
    'Sco': {'es': 'Escorpión',         'en': 'Scorpius'},
    'Sct': {'es': 'Escudo',            'en': 'Scutum'},
    'Ser': {'es': 'Serpiente',         'en': 'Serpens'},
    'Sex': {'es': 'Sextante',          'en': 'Sextans'},
    'Sge': {'es': 'Flecha',            'en': 'Sagitta'},
    'Sgr': {'es': 'Sagitario',         'en': 'Sagittarius'},
    'Tau': {'es': 'Tauro',             'en': 'Taurus'},
    'Tel': {'es': 'Telescopio',        'en': 'Telescopium'},
    'TrA': {'es': 'Triángulo Austral', 'en': 'Triangulum Australe'},
    'Tri': {'es': 'Triángulo',         'en': 'Triangulum'},
    'Tuc': {'es': 'Tucán',             'en': 'Tucana'},
    'UMa': {'es': 'Osa Mayor',         'en': 'Ursa Major'},
    'UMi': {'es': 'Osa Menor',         'en': 'Ursa Minor'},
    'Vel': {'es': 'Velas',             'en': 'Vela'},
    'Vir': {'es': 'Virgo',             'en': 'Virgo'},
    'Vol': {'es': 'Pez Volador',       'en': 'Volans'},
    'Vul': {'es': 'Zorra',             'en': 'Vulpecula'},
}


# ===== COLORES ANSI =====
class C:
    GRN = '\033[92m'; CYAN = '\033[96m'; YEL = '\033[93m'; RED = '\033[91m'
    BLU = '\033[94m'; DIM = '\033[2m'; RST = '\033[0m'; BOLD = '\033[1m'


def progress_bar(current, total, label='', start_time=None, width=36):
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = '█' * filled + '░' * (width - filled)
    eta = ''
    if start_time and current > 0:
        elapsed = time.time() - start_time
        rate = current / elapsed
        remaining = (total - current) / rate if rate > 0 else 0
        eta = f' · ETA {remaining:4.0f}s'
    label_trunc = (label[:28] + '…') if len(label) > 29 else label.ljust(29)
    print(
        f'\r{C.CYAN}[{bar}]{C.RST} {pct*100:5.1f}% · '
        f'{current:>5}/{total:<5} · {label_trunc}{eta}    ',
        end='', flush=True
    )
    if current == total:
        print()


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stderr),
        ]
    )


# ===== CÁLCULO ASTRONÓMICO =====
def rad_to_deg(rad):
    return float(rad) * 180.0 / math.pi


def compute_global_planet_day(date_local):
    """
    Datos del planeta independientes de la ubicación del observador:
    magnitud, constelación, fase iluminada, distancia geocéntrica.

    Se calcula al mediodía UTC del día para tener un valor representativo.
    """
    obs = ephem.Observer()
    obs.lat = '0'; obs.lon = '0'; obs.elevation = 0
    obs.date = datetime.combine(date_local, datetime.min.time()).replace(hour=12).strftime('%Y/%m/%d %H:%M:%S')

    out = {}
    for pid, PlanetClass, _ in PLANETS:
        p = PlanetClass()
        p.compute(obs)
        const_abbr = ephem.constellation(p)[0]
        rec = {
            'm':  round(float(p.mag), 1),
            'c':  const_abbr,
            'd':  round(float(p.earth_distance), 3),  # UA
        }
        # phase solo aplica a Mercurio/Venus/Marte (planetas interiores y Marte)
        if hasattr(p, 'phase'):
            try:
                rec['p'] = round(float(p.phase) / 100.0, 2)
            except Exception:
                pass
        out[pid] = rec
    return out


def compute_planet_city_day(city, date_local):
    """
    Por ciudad y día: rise/transit/set + azimut/altitud + visibilidad.

    Devuelve dict:
      {
        'p': { 'mercury': {r,ra,t,ta,s,sa}, ... },  # eventos por planeta
        'vt': [...]   # planetas visibles al anochecer (tras crepúsculo civil)
        'vm': [...]   # planetas visibles antes del amanecer
      }
    """
    obs = ephem.Observer()
    obs.lat = str(city['lat'])
    obs.lon = str(city['lon'])
    obs.elevation = 0
    obs.pressure = 1010
    tz = pytz.timezone(city['tz'])

    start_local = tz.localize(datetime.combine(date_local, datetime.min.time()))
    end_local = start_local + timedelta(days=1)
    obs_anchor_utc = start_local.astimezone(timezone.utc).strftime('%Y/%m/%d %H:%M:%S')

    out_planets = {}

    for pid, PlanetClass, _ in PLANETS:

        def to_local(t):
            return t.datetime().replace(tzinfo=timezone.utc).astimezone(tz)

        rec = {'r': None, 'ra': None, 't': None, 'ta': None, 's': None, 'sa': None}

        # Buscar el rise/transit/set "del día" (el próximo a partir de medianoche local)
        # Si la transición está fuera del día local, se ignora.
        for event_name, finder, alt_or_az in [
            ('r',  'next_rising',   'az'),
            ('t',  'next_transit',  'alt'),
            ('s',  'next_setting',  'az'),
        ]:
            obs.date = obs_anchor_utc
            p = PlanetClass()
            try:
                t = getattr(obs, finder)(p)
                t_local = to_local(t)
                if start_local <= t_local < end_local:
                    rec[event_name] = t_local.strftime('%H:%M')
                    # Calcular azimut o altitud en el momento del evento
                    obs.date = t
                    p2 = PlanetClass()
                    p2.compute(obs)
                    if alt_or_az == 'az':
                        rec[event_name + 'a'] = round(rad_to_deg(p2.az), 0)
                    else:
                        rec[event_name + 'a'] = round(rad_to_deg(p2.alt), 0)
            except (ephem.NeverUpError, ephem.AlwaysUpError, ephem.CircumpolarError):
                pass

        out_planets[pid] = rec

    # ===== Visibilidad: ¿qué planetas se ven al anochecer / antes del amanecer? =====
    # Anochecer: tomar 15 min después del crepúsculo civil vespertino (sun a -6°)
    # Amanecer: tomar 15 min antes del crepúsculo civil matutino
    obs.pressure = 0
    obs.horizon = '-6'
    sun = ephem.Sun()
    obs.date = obs_anchor_utc

    civil_dusk = None
    civil_dawn = None
    try:
        civil_dusk = obs.next_setting(sun, use_center=True)
        if to_local(civil_dusk).date() != date_local:
            civil_dusk = None
    except (ephem.NeverUpError, ephem.AlwaysUpError):
        pass
    obs.date = obs_anchor_utc
    try:
        civil_dawn = obs.next_rising(sun, use_center=True)
        if to_local(civil_dawn).date() != date_local:
            civil_dawn = None
    except (ephem.NeverUpError, ephem.AlwaysUpError):
        pass

    visible_tonight = []
    visible_morning = []

    if civil_dusk is not None:
        obs.date = civil_dusk + ephem.minute * 15
        for pid, PlanetClass, _ in PLANETS:
            p = PlanetClass()
            p.compute(obs)
            alt_deg = rad_to_deg(p.alt)
            if alt_deg >= MIN_ALTITUDE_DEG and float(p.mag) <= NAKED_EYE_MAG_LIMIT:
                visible_tonight.append(pid)

    if civil_dawn is not None:
        obs.date = civil_dawn - ephem.minute * 15
        for pid, PlanetClass, _ in PLANETS:
            p = PlanetClass()
            p.compute(obs)
            alt_deg = rad_to_deg(p.alt)
            if alt_deg >= MIN_ALTITUDE_DEG and float(p.mag) <= NAKED_EYE_MAG_LIMIT:
                visible_morning.append(pid)

    return {'p': out_planets, 'vt': visible_tonight, 'vm': visible_morning}


# ===== UPLOAD CDN =====
def upload_to_cdn(local_path, cdn_key, gzip_encoded=False):
    cmd = [
        'aws', 's3', 'cp', local_path,
        f's3://{CDN_BUCKET}/{cdn_key}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', 'application/json',
        '--cache-control', 'max-age=3600',
        '--endpoint-url', CDN_ENDPOINT,
    ]
    if gzip_encoded:
        cmd.extend(['--content-encoding', 'gzip'])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f'AWS CLI falló (rc={result.returncode}): {result.stderr.strip()}')
    return f'https://{CDN_BUCKET}.sfo3.cdn.digitaloceanspaces.com/{cdn_key}'


def compress_gzip(src_path, dst_path):
    with open(src_path, 'rb') as f_in, gzip.open(dst_path, 'wb', compresslevel=6) as f_out:
        while True:
            chunk = f_in.read(65536)
            if not chunk:
                break
            f_out.write(chunk)
    return os.path.getsize(dst_path)


# ===== MAIN =====
def main():
    parser = argparse.ArgumentParser(
        description='Pipeline de planetas visibles — Canal Meteo TV (Bloque 2)'
    )
    parser.add_argument('--no-upload', action='store_true', help='No subir al CDN (debug)')
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS,
                        help=f'Días a calcular (default {DEFAULT_DAYS})')
    parser.add_argument('--out', default=TMP_OUTPUT, help='Archivo JSON de salida')
    args = parser.parse_args()

    setup_logging()
    t_start = time.time()

    print(f'\n{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════╗')
    print(f'║   CANAL METEO TV — PLANETS PIPELINE (BLOQUE 2)   ║')
    print(f'╚══════════════════════════════════════════════════╝{C.RST}\n')

    print(f'{C.DIM}Configuración:{C.RST}')
    print(f'  • Ciudades:   {len(CITIES)}')
    print(f'  • Días:       {args.days}')
    print(f'  • Planetas:   {len(PLANETS)} (Mercurio, Venus, Marte, Júpiter, Saturno)')
    print(f'  • Output:     {args.out}')
    print(f'  • Upload CDN: {"NO" if args.no_upload else "SÍ"}\n')

    today = datetime.now(timezone.utc).date()
    dates = [today + timedelta(days=i) for i in range(args.days)]

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'valid_from': dates[0].isoformat(),
        'valid_until': dates[-1].isoformat(),
        'days_count': args.days,
        'naked_eye_mag_limit': NAKED_EYE_MAG_LIMIT,
        'min_altitude_deg': MIN_ALTITUDE_DEG,
        'planets': {pid: meta for pid, _, meta in PLANETS},
        'constellations': CONSTELLATIONS,
        'global': [],
        'cities': [],
    }

    # ===== FASE 1: Datos globales por día =====
    print(f'{C.YEL}● Calculando datos globales (magnitud, constelación, fase)...{C.RST}')
    for date_local in dates:
        gdata = compute_global_planet_day(date_local)
        out['global'].append({'d': date_local.isoformat(), 'p': gdata})
    print(f'{C.GRN}  ✓ {args.days} días procesados{C.RST}\n')

    # ===== FASE 2: Datos locales por ciudad =====
    total_ops = len(CITIES) * args.days
    op_count = 0
    pipeline_start = time.time()

    print(f'{C.YEL}● Calculando datos locales: {len(CITIES)} ciudades × {args.days} días = {total_ops} ops{C.RST}')

    for city in CITIES:
        city_t0 = time.time()
        city_data = {
            'id':    city['id'],
            'name':  city['name'],
            'state': city['state'],
            'lat':   city['lat'],
            'lon':   city['lon'],
            'tz':    city['tz'],
            'days':  [],
        }

        for date_local in dates:
            try:
                day_data = compute_planet_city_day(city, date_local)
                day_data['d'] = date_local.isoformat()
                city_data['days'].append(day_data)
            except Exception as e:
                logging.error(f"Error en {city['id']} {date_local}: {e}")
                city_data['days'].append({
                    'd': date_local.isoformat(),
                    'error': str(e),
                })

            op_count += 1
            progress_bar(op_count, total_ops, label=city['name'], start_time=pipeline_start)

        out['cities'].append(city_data)
        logging.info(f"{city['id']:<16} procesado en {time.time()-city_t0:.1f}s")

    # ===== Guardar JSON =====
    print(f'\n{C.YEL}● Guardando JSON...{C.RST}')
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(args.out) / 1024
    print(f'{C.GRN}  ✓ {args.out} ({size_kb:.1f} KB){C.RST}')

    # ===== Comprimir y subir =====
    if not args.no_upload:
        print(f'\n{C.YEL}● Comprimiendo con gzip...{C.RST}')
        gz_path = args.out + '.gz'
        size_gz = compress_gzip(args.out, gz_path)
        ratio = (size_gz / os.path.getsize(args.out)) * 100
        print(f'{C.GRN}  ✓ {size_gz/1024:.1f} KB ({ratio:.0f}% del original){C.RST}')

        print(f'\n{C.YEL}● Subiendo al CDN (Content-Encoding: gzip)...{C.RST}')
        try:
            cdn_url = upload_to_cdn(gz_path, CDN_KEY, gzip_encoded=True)
            print(f'{C.GRN}  ✓ {cdn_url}{C.RST}')
            logging.info(f'CDN OK: {cdn_url} ({size_gz/1024:.1f} KB gz)')
            os.unlink(gz_path)
        except Exception as e:
            print(f'{C.RED}  ✗ Error: {e}{C.RST}')
            logging.error(f'Error subiendo a CDN: {e}')
            sys.exit(1)

    total_elapsed = time.time() - t_start
    print(f'\n{C.BOLD}{C.GRN}═══════════════════════════════════════════════════')
    print(f'  ✓ COMPLETADO en {total_elapsed:.1f}s')
    print(f'  ✓ {len(CITIES)} ciudades · {args.days} días · {len(PLANETS)} planetas · {size_kb:.1f} KB')
    print(f'═══════════════════════════════════════════════════{C.RST}\n')
    logging.info(f'Pipeline completado en {total_elapsed:.1f}s')


if __name__ == '__main__':
    main()
