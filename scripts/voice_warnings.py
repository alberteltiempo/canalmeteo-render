#!/usr/bin/env python3
"""
voice_warnings.py — Genera voces dinámicas para avisos de tornado

Lee alertas_nws.json, filtra avisos de tornado con población >= 10.000,
compone una frase personalizada con estado + condados + población, y genera
el MP3 con ElevenLabs solo si no existe (caché por hash MD5 del texto).

Uso (cron cada 2 min):
    */2 * * * * flock -n /tmp/voice_warnings.lock /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/voice_warnings.py

Credenciales en /opt/canalmeteo/.env_elevenlabs:
    ELEVENLABS_API_KEY=sk_xxx
    ELEVENLABS_VOICE_ID=xxx

Salida:
    MP3s individuales en https://canalmeteo-public.sfo3.digitaloceanspaces.com/voices/dynamic/{hash}.mp3
    Índice: https://canalmeteo-public.sfo3.digitaloceanspaces.com/voices/warnings_index.json
"""
import os
import sys
import json
import hashlib
import subprocess
import time
from pathlib import Path

import requests

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

ENV_FILE = Path('/opt/canalmeteo/.env_elevenlabs')
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY  = os.environ.get('ELEVENLABS_API_KEY', '')
VOICE_ID = os.environ.get('ELEVENLABS_VOICE_ID', '')

MODEL = 'eleven_multilingual_v2'
VOICE_SETTINGS = {
    'stability': 0.55,
    'similarity_boost': 0.85,
    'style': 0.30,
    'use_speaker_boost': True,
}

# CDN
CDN_BUCKET   = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
CDN_BASE_URL = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com'
AWS_PROFILE  = 'do-tor1'

# Rutas / fuente de datos
# Leemos directamente del CDN (misma fuente que el frontend) para no depender
# de archivos locales del pipeline de alertas
ALERTAS_URL = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/alertas/alertas_nws.json'
OUT_DIR = Path('/tmp/voice_warnings')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Filtro
MIN_POPULATION = 10_000

# Límite de seguridad (por si alertas_nws.json viene corrupto con miles de avisos)
MAX_WARNINGS_PER_RUN = 30


# ═══════════════════════════════════════════════════════════════
# NUMERO A TEXTO (para que la voz suene natural)
# ═══════════════════════════════════════════════════════════════

def num_a_texto(n):
    """Convierte número a texto español, redondeando para que suene natural."""
    if n is None or n == 0:
        return ""
    n = int(n)

    # Redondeos por rango (más natural hablar en aproximaciones)
    if n >= 1_000_000:
        m = round(n / 1_000_000)
        if m == 1:
            return "un millón"
        return _num_simple(m) + " millones"
    elif n >= 100_000:
        # "cuatrocientas mil"
        aprox = round(n / 10_000) * 10_000
        return _num_simple(aprox)
    elif n >= 10_000:
        # "treinta y cinco mil" (redondeo a miles)
        aprox = round(n / 1000) * 1000
        return _num_simple(aprox)
    else:
        return _num_simple(n)


def _num_simple(n):
    """Convierte número a palabras en español (hasta millones)."""
    if n == 0: return "cero"

    unidades = ["", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]
    decenas_10_19 = ["diez", "once", "doce", "trece", "catorce", "quince", "dieciséis",
                     "diecisiete", "dieciocho", "diecinueve"]
    decenas = ["", "", "veinte", "treinta", "cuarenta", "cincuenta", "sesenta",
               "setenta", "ochenta", "noventa"]
    centenas = ["", "ciento", "doscientas", "trescientas", "cuatrocientas",
                "quinientas", "seiscientas", "setecientas", "ochocientas", "novecientas"]

    if n == 100:
        return "cien"
    if n == 1000:
        return "mil"
    if n == 1:
        return "una"

    resultado = []

    # Millones
    if n >= 1_000_000:
        m = n // 1_000_000
        if m == 1:
            resultado.append("un millón")
        else:
            resultado.append(_num_simple(m) + " millones")
        n = n % 1_000_000

    # Miles
    if n >= 1000:
        m = n // 1000
        if m == 1:
            resultado.append("mil")
        else:
            resultado.append(_num_simple(m).replace(" una", " una") + " mil")
        n = n % 1000

    # Centenas
    if n >= 100:
        c = n // 100
        if c == 1 and n > 100:
            resultado.append("ciento")
        else:
            resultado.append(centenas[c])
        n = n % 100

    # 10-19
    if n >= 10 and n < 20:
        resultado.append(decenas_10_19[n - 10])
        return " ".join(filter(None, resultado))

    # 20-99
    if n >= 20:
        d = n // 10
        u = n % 10
        if u == 0:
            resultado.append(decenas[d])
        elif d == 2:
            # "veintidós", "veintitrés"
            vei = {1:"veintiuna", 2:"veintidós", 3:"veintitrés", 4:"veinticuatro",
                   5:"veinticinco", 6:"veintiséis", 7:"veintisiete", 8:"veintiocho",
                   9:"veintinueve"}
            resultado.append(vei[u])
        else:
            resultado.append(decenas[d] + " y " + unidades[u])
        return " ".join(filter(None, resultado))

    # 1-9
    if n > 0:
        # "una" en femenino para "personas"
        if n == 1:
            resultado.append("una")
        else:
            resultado.append(unidades[n])

    return " ".join(filter(None, resultado))


# ═══════════════════════════════════════════════════════════════
# COMPOSICIÓN DE FRASE
# ═══════════════════════════════════════════════════════════════

def componer_frase(warning):
    """Construye una frase dinámica ~180 chars para un aviso de tornado."""

    # Estado (traducido al español si viene en inglés)
    estado = warning.get('estado_nombre') or warning.get('estado') or ''
    estado_es = traducir_estado(estado)

    # Condados (máximo 3 para no alargar la frase)
    condados = (warning.get('condados_nombres')
                or warning.get('condados')
                or warning.get('counties')
                or [])
    if isinstance(condados, str):
        condados = [c.strip() for c in condados.split(',')]
    condados = [c for c in condados if c][:3]

    # Población
    pob = warning.get('poblacion') or warning.get('population') or 0
    pob_texto = num_a_texto(pob) if pob >= 1000 else ""

    # Construir la primera frase: "Aviso por tornado activo en [estado], [condados]."
    apertura = "Aviso por tornado activo"
    if estado_es:
        apertura += f" en {estado_es}"
    if condados:
        if len(condados) == 1:
            apertura += f", condado de {condados[0]}"
        elif len(condados) == 2:
            apertura += f", condados de {condados[0]} y {condados[1]}"
        else:
            apertura += f", condados de {condados[0]}, {condados[1]} y {condados[2]}"
    apertura += "."

    # Segunda frase: impacto poblacional
    impacto = ""
    if pob_texto:
        # Añadir "de" antes de personas cuando termina en millón/millones
        conector = " de " if pob_texto.endswith(("millón", "millones")) else " "
        if pob >= 100_000:
            impacto = f" Más de {pob_texto}{conector}personas en la zona afectada."
        else:
            impacto = f" Unas {pob_texto}{conector}personas en la zona afectada."

    # Cierre imperativo
    cierre = " Refúgiese de inmediato."

    return apertura + impacto + cierre


def formatear_hora_es(iso_str):
    """Convierte '2026-04-24T19:00:00-05:00' → 'las siete de la tarde hora del este'.
    Usa Eastern Time como referencia (la que muestra el producto en pantalla)."""
    if not iso_str:
        return ""
    try:
        from datetime import datetime, timezone, timedelta
        # Parse ISO con timezone
        if iso_str.endswith('Z'):
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(iso_str)
        # Convertir a Eastern Time (UTC-4 durante DST, UTC-5 en invierno)
        # Simplificación: abril-octubre es EDT (UTC-4), resto EST (UTC-5)
        mes = dt.astimezone(timezone.utc).month
        offset_et = -4 if 3 <= mes <= 10 else -5
        et = dt.astimezone(timezone(timedelta(hours=offset_et)))
        hora = et.hour
        minuto = et.minute

        # Parte del día
        if 0 <= hora < 6:
            franja = "de la madrugada"
        elif 6 <= hora < 12:
            franja = "de la mañana"
        elif 12 <= hora < 19:
            franja = "de la tarde"
        else:
            franja = "de la noche"

        # Hora en 12h
        h12 = hora % 12
        if h12 == 0:
            h12 = 12

        # Componer hora en palabras
        horas_palabra = {
            1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis",
            7: "siete", 8: "ocho", 9: "nueve", 10: "diez", 11: "once", 12: "doce"
        }
        art = "la" if h12 == 1 else "las"
        texto = f"{art} {horas_palabra[h12]}"

        # Añadir minutos si no es en punto
        if minuto == 0:
            pass  # "a las siete de la tarde"
        elif minuto == 15:
            texto += " y cuarto"
        elif minuto == 30:
            texto += " y media"
        elif minuto == 45:
            h_next = (h12 % 12) + 1
            art_next = "la" if h_next == 1 else "las"
            texto = f"{art_next} {horas_palabra[h_next]} menos cuarto"
        else:
            texto += f" y {_num_simple(minuto)}"

        return f"{texto} {franja} hora del este"
    except Exception as e:
        return ""


def formatear_estados(watch):
    """Devuelve una expresión natural en español con todos los estados
    afectados por una watch. Usa 'estados_nombres' (array) si está disponible,
    cae en 'estado_nombre' (string) como fallback.

    Ejemplos:
      1 estado:   'Oklahoma'
      2 estados:  'Oklahoma y Texas'
      3-4:        'Oklahoma, Texas y Arkansas'
      5+:         'cinco estados incluyendo Oklahoma, Texas y Arkansas'
    """
    # Preferir lista de estados si existe
    lista = watch.get('estados_nombres') or watch.get('states_names') or []
    if not lista and watch.get('estados'):
        # Fallback: 'estados' son códigos tipo 'OK', 'TX' → traducir usando ESTADOS_ES invertido
        codigos = watch.get('estados') or []
        nombres_invert = {
            'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California',
            'CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia',
            'HI':'Hawái','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa','KS':'Kansas',
            'KY':'Kentucky','LA':'Luisiana','ME':'Maine','MD':'Maryland','MA':'Massachusetts',
            'MI':'Míchigan','MN':'Minesota','MS':'Misisipi','MO':'Misuri','MT':'Montana',
            'NE':'Nebraska','NV':'Nevada','NH':'Nuevo Hampshire','NJ':'Nueva Jersey',
            'NM':'Nuevo México','NY':'Nueva York','NC':'Carolina del Norte','ND':'Dakota del Norte',
            'OH':'Ohio','OK':'Oklahoma','OR':'Oregón','PA':'Pensilvania','RI':'Rhode Island',
            'SC':'Carolina del Sur','SD':'Dakota del Sur','TN':'Tennessee','TX':'Texas',
            'UT':'Utah','VT':'Vermont','VA':'Virginia','WA':'Washington','WV':'Virginia Occidental',
            'WI':'Wisconsin','WY':'Wyoming',
        }
        lista = [nombres_invert.get(c, c) for c in codigos if c]

    if not lista:
        # Último recurso: campo simple
        estado_simple = watch.get('estado_nombre') or watch.get('estado') or ''
        if estado_simple:
            return traducir_estado(estado_simple)
        return ""

    # Traducir cada estado por si alguno viene en inglés
    nombres = [traducir_estado(n) for n in lista if n]
    nombres = [n for n in nombres if n]

    n = len(nombres)
    if n == 0:
        return ""
    if n == 1:
        return nombres[0]
    if n == 2:
        return f"{nombres[0]} y {nombres[1]}"
    if n <= 4:
        # "Oklahoma, Texas y Arkansas"
        return f"{', '.join(nombres[:-1])} y {nombres[-1]}"
    # 5 o más: resumen
    cantidad_palabra = _num_simple(n)
    return f"{cantidad_palabra} estados incluyendo {nombres[0]}, {nombres[1]} y {nombres[2]}"


def componer_frase_watch(watch):
    """Construye una frase dinámica para una VIGILANCIA de tornado."""

    # Estados afectados (soporta multi-estado)
    estados_texto = formatear_estados(watch)

    # Población
    pob = watch.get('poblacion') or watch.get('population') or 0
    pob_texto = num_a_texto(pob) if pob >= 1000 else ""

    # Hora de expiración
    expira_iso = watch.get('expires') or watch.get('expira') or ''
    hora_texto = formatear_hora_es(expira_iso)

    # Construir frase
    apertura = "Vigilancia por tornado activa"
    if estados_texto:
        apertura += f" en {estados_texto}"
    apertura += "."

    # Impacto poblacional
    impacto = ""
    if pob_texto:
        conector = " de " if pob_texto.endswith(("millón", "millones")) else " "
        if pob >= 100_000:
            impacto = f" Más de {pob_texto}{conector}personas en la zona bajo vigilancia."
        else:
            impacto = f" Unas {pob_texto}{conector}personas en la zona bajo vigilancia."

    # Vigencia
    vigencia = ""
    if hora_texto:
        vigencia = f" La vigilancia está en efecto hasta {hora_texto}."

    # Cierre informativo
    cierre = " Las condiciones son favorables para la formación de tornados. Manténgase alerta."

    return apertura + impacto + vigencia + cierre


def componer_frase_watch_severo(watch):
    """Construye una frase dinámica para una VIGILANCIA de tormenta severa."""

    estados_texto = formatear_estados(watch)

    pob = watch.get('poblacion') or watch.get('population') or 0
    pob_texto = num_a_texto(pob) if pob >= 1000 else ""

    expira_iso = watch.get('expires') or watch.get('expira') or ''
    hora_texto = formatear_hora_es(expira_iso)

    apertura = "Vigilancia por tormenta severa"
    if estados_texto:
        apertura += f" en {estados_texto}"
    apertura += "."

    impacto = ""
    if pob_texto:
        conector = " de " if pob_texto.endswith(("millón", "millones")) else " "
        if pob >= 100_000:
            impacto = f" Más de {pob_texto}{conector}personas en la zona bajo vigilancia."
        else:
            impacto = f" Unas {pob_texto}{conector}personas en la zona bajo vigilancia."

    vigencia = ""
    if hora_texto:
        vigencia = f" La vigilancia está en efecto hasta {hora_texto}."

    cierre = " Se esperan tormentas fuertes con vientos intensos, granizo y abundante lluvia. Manténgase atento."

    return apertura + impacto + vigencia + cierre


def componer_frase_severo(warning):
    """Construye una frase dinámica ~180 chars para un AVISO de tormenta severa.

    Mismo registro imperativo que el aviso de tornado (amenaza inmediata, no vigilancia).
    Usa los campos compartidos del feed (estado/condados/poblacion) y, si viene, el
    peligro concreto de warning['detalle']['hazard'] (viento / granizo)."""

    estado = warning.get('estado_nombre') or warning.get('estado') or ''
    estado_es = traducir_estado(estado)

    condados = (warning.get('condados_nombres')
                or warning.get('condados')
                or warning.get('counties')
                or [])
    if isinstance(condados, str):
        condados = [c.strip() for c in condados.split(',')]
    condados = [c for c in condados if c][:3]

    pob = warning.get('poblacion') or warning.get('population') or 0
    pob_texto = num_a_texto(pob) if pob >= 1000 else ""

    apertura = "Aviso por tormenta severa activo"
    if estado_es:
        apertura += f" en {estado_es}"
    if condados:
        if len(condados) == 1:
            apertura += f", condado de {condados[0]}"
        elif len(condados) == 2:
            apertura += f", condados de {condados[0]} y {condados[1]}"
        else:
            apertura += f", condados de {condados[0]}, {condados[1]} y {condados[2]}"
    apertura += "."

    impacto = ""
    if pob_texto:
        conector = " de " if pob_texto.endswith(("millón", "millones")) else " "
        if pob >= 100_000:
            impacto = f" Más de {pob_texto}{conector}personas en la zona afectada."
        else:
            impacto = f" Unas {pob_texto}{conector}personas en la zona afectada."

    # Peligro concreto si el feed lo trae (detalle.hazard suele venir en inglés)
    haz = str(((warning.get('detalle') or {}).get('hazard') or '')).lower()
    tiene_granizo = 'hail' in haz or 'granizo' in haz
    tiene_viento = 'wind' in haz or 'viento' in haz
    if tiene_viento and tiene_granizo:
        amenaza = " Se esperan vientos dañinos y granizo."
    elif tiene_viento:
        amenaza = " Se esperan vientos dañinos."
    elif tiene_granizo:
        amenaza = " Se espera granizo de gran tamaño."
    else:
        amenaza = " Se esperan vientos dañinos y granizo."

    cierre = " Busque refugio en un lugar seguro."

    return apertura + impacto + amenaza + cierre


# Mapa de estados EEUU inglés → español
ESTADOS_ES = {
    'Alabama': 'Alabama', 'Alaska': 'Alaska', 'Arizona': 'Arizona',
    'Arkansas': 'Arkansas', 'California': 'California', 'Colorado': 'Colorado',
    'Connecticut': 'Connecticut', 'Delaware': 'Delaware', 'Florida': 'Florida',
    'Georgia': 'Georgia', 'Hawaii': 'Hawái', 'Idaho': 'Idaho',
    'Illinois': 'Illinois', 'Indiana': 'Indiana', 'Iowa': 'Iowa',
    'Kansas': 'Kansas', 'Kentucky': 'Kentucky', 'Louisiana': 'Luisiana',
    'Maine': 'Maine', 'Maryland': 'Maryland', 'Massachusetts': 'Massachusetts',
    'Michigan': 'Míchigan', 'Minnesota': 'Minesota', 'Mississippi': 'Misisipi',
    'Missouri': 'Misuri', 'Montana': 'Montana', 'Nebraska': 'Nebraska',
    'Nevada': 'Nevada', 'New Hampshire': 'Nuevo Hampshire',
    'New Jersey': 'Nueva Jersey', 'New Mexico': 'Nuevo México',
    'New York': 'Nueva York', 'North Carolina': 'Carolina del Norte',
    'North Dakota': 'Dakota del Norte', 'Ohio': 'Ohio', 'Oklahoma': 'Oklahoma',
    'Oregon': 'Oregón', 'Pennsylvania': 'Pensilvania',
    'Rhode Island': 'Rhode Island', 'South Carolina': 'Carolina del Sur',
    'South Dakota': 'Dakota del Sur', 'Tennessee': 'Tennessee', 'Texas': 'Texas',
    'Utah': 'Utah', 'Vermont': 'Vermont', 'Virginia': 'Virginia',
    'Washington': 'Washington', 'West Virginia': 'Virginia Occidental',
    'Wisconsin': 'Wisconsin', 'Wyoming': 'Wyoming',
}

def traducir_estado(estado):
    if not estado: return ""
    # Ya viene en español o es desconocido
    return ESTADOS_ES.get(estado, estado)


# ═══════════════════════════════════════════════════════════════
# CACHÉ + CDN
# ═══════════════════════════════════════════════════════════════

def text_hash(text):
    """MD5 del texto — id único del MP3."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:16]


def cdn_exists(cdn_key):
    """Check if file already exists in CDN."""
    cmd = [
        'aws', 's3api', 'head-object',
        '--bucket', CDN_BUCKET,
        '--key', cdn_key,
        '--profile', AWS_PROFILE,
        '--endpoint-url', CDN_ENDPOINT,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def upload_cdn(local, cdn_key, content_type='audio/mpeg', cache_secs=86400):
    """Sube al CDN DigitalOcean Spaces."""
    cmd = [
        'aws', 's3', 'cp', str(local),
        f's3://{CDN_BUCKET}/{cdn_key}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', content_type,
        '--cache-control', f'public, max-age={cache_secs}',
        '--endpoint-url', CDN_ENDPOINT,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        return r.returncode == 0
    except Exception as e:
        print(f"  ❌ CDN upload: {e}", file=sys.stderr)
        return False


def tts(text, output):
    """Genera MP3 con ElevenLabs."""
    url = f'https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}'
    headers = {
        'Accept': 'audio/mpeg',
        'Content-Type': 'application/json',
        'xi-api-key': API_KEY,
    }
    data = {
        'text': text,
        'model_id': MODEL,
        'voice_settings': VOICE_SETTINGS,
    }
    try:
        r = requests.post(url, json=data, headers=headers, timeout=60)
        if r.status_code != 200:
            print(f"  ❌ ElevenLabs {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        output.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  ❌ TTS: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def cargar_alertas():
    """Carga avisos Y vigilancias de TORNADO y TORMENTA SEVERA desde el CDN.
    Retorna dict con 4 listas:
        - warnings_tor, watches_tor  (tipo == 'tornado')
        - warnings_svr, watches_svr  (tipo == 'tormenta' severa)
    """
    empty = {'warnings_tor': [], 'watches_tor': [],
             'warnings_svr': [], 'watches_svr': []}
    try:
        r = requests.get(ALERTAS_URL, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ Error descargando alertas del CDN: {e}", file=sys.stderr)
        return empty

    alertas = data.get('alertas', [])
    if not isinstance(alertas, list):
        print(f"⚠️  El campo 'alertas' no es una lista", file=sys.stderr)
        return empty

    # Estructura real:
    #   tipo:   "tornado" | "tormenta" | "inundacion" | "invierno"
    #   evento: "Tornado Warning" | "Tornado Watch" | "Severe Thunderstorm Warning" | ...
    result = {'warnings_tor': [], 'watches_tor': [],
              'warnings_svr': [], 'watches_svr': []}

    for a in alertas:
        if not isinstance(a, dict):
            continue
        tipo = str(a.get('tipo', '')).lower()
        evento = str(a.get('evento', '')).lower()
        is_warning = 'warning' in evento and 'watch' not in evento
        is_watch = 'watch' in evento

        if tipo == 'tornado':
            if is_warning:
                result['warnings_tor'].append(a)
            elif is_watch:
                result['watches_tor'].append(a)
        elif tipo == 'tormenta':
            # Severe Thunderstorm Warning/Watch
            if is_warning:
                result['warnings_svr'].append(a)
            elif is_watch:
                result['watches_svr'].append(a)

    return result


def warning_id(warning):
    """Identificador único — usa el campo 'id' (urn:oid) como canónico."""
    return (warning.get('id')
            or warning.get('nws_id')
            or warning.get('warning_id')
            or warning.get('numero')
            or str(hash(json.dumps(warning, sort_keys=True, default=str))))


def procesar_items(items, componedor, index_section, stats):
    """Procesa una lista de alertas con un componedor específico.
    Actualiza index_section (dict) y stats (dict con 'generados','skipped','chars')."""
    for item in items:
        wid = warning_id(item)
        frase = componedor(item)
        h = text_hash(frase)
        cdn_key = f'voices/dynamic/{h}.mp3'
        url = f'{CDN_BASE_URL}/{cdn_key}'

        print(f"\n[{wid[-40:]}] pob={item.get('poblacion', 0):,}")
        print(f"  \"{frase}\"")
        print(f"  hash={h}")

        if cdn_exists(cdn_key):
            print(f"  ⏭️  Ya en CDN")
            stats['skipped'] += 1
            index_section[wid] = {'url': url, 'hash': h, 'text': frase}
            continue

        local = OUT_DIR / f'{h}.mp3'
        if not tts(frase, local):
            continue
        if not upload_cdn(local, cdn_key):
            continue

        stats['chars'] += len(frase)
        stats['generados'] += 1
        index_section[wid] = {'url': url, 'hash': h, 'text': frase}
        print(f"  ✅ Generado ({len(frase)} chars)")


def cargar_index_actual():
    """Lee el warnings_index.json actual del CDN para FUSIONAR en vez de sobrescribir.

    Crítico: tornado_dynamic_voices_pipeline.py (cron :30) es el dueño de la sección
    'warnings' (avisos de tornado) y hace su propio read-merge. Si aquí reconstruyéramos
    el índice desde cero (como antes), pisaríamos esa sección cada 2 min. Por eso cargamos
    el índice vivo y solo reescribimos las secciones que este script posee.
    """
    url = f'{CDN_BASE_URL}/voices/warnings_index.json?ts={int(time.time())}'
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[voice-warnings] AVISO: no se pudo cargar index actual ({e}); "
              f"se publicará solo con las secciones propias", file=sys.stderr)
    return {}


def main():
    if not API_KEY or not VOICE_ID:
        print("❌ Credenciales de ElevenLabs faltan", file=sys.stderr)
        return 1

    t0 = time.time()
    alertas = cargar_alertas()
    warnings_tor = alertas['warnings_tor']
    watches_tor = alertas['watches_tor']
    warnings_svr = alertas['warnings_svr']
    watches_svr = alertas['watches_svr']

    print(f"[voice-warnings] "
          f"TOR: {len(warnings_tor)} avisos + {len(watches_tor)} vigilancias | "
          f"SVR: {len(warnings_svr)} avisos + {len(watches_svr)} vigilancias")

    # Filtrar por población
    def filtrar(items):
        return [w for w in items if (w.get('poblacion') or 0) >= MIN_POPULATION]

    warnings_tor = filtrar(warnings_tor)
    watches_tor = filtrar(watches_tor)
    warnings_svr = filtrar(warnings_svr)
    watches_svr = filtrar(watches_svr)

    print(f"[voice-warnings] Tras filtro pob>={MIN_POPULATION:,}: "
          f"TOR: {len(warnings_tor)}w + {len(watches_tor)}v | "
          f"SVR: {len(warnings_svr)}w + {len(watches_svr)}v")

    # Limitar por seguridad
    def limitar(items, nombre):
        if len(items) > MAX_WARNINGS_PER_RUN:
            print(f"[voice-warnings] LIMIT {nombre}: {len(items)} → {MAX_WARNINGS_PER_RUN}")
            return items[:MAX_WARNINGS_PER_RUN]
        return items

    warnings_tor = limitar(warnings_tor, 'warnings_tor')
    watches_tor  = limitar(watches_tor,  'watches_tor')
    warnings_svr = limitar(warnings_svr, 'warnings_svr')
    watches_svr  = limitar(watches_svr,  'watches_svr')

    # Index unificado: 4 secciones separadas (frontend busca por step.kind='tornado' vs 'severe')
    #   warnings        → tornado warnings  — PROPIEDAD de tornado_dynamic_voices_pipeline.py
    #   watches         → tornado watches   — propiedad de ESTE script
    #   warnings_severe → severe warnings   — propiedad de ESTE script
    #   watches_severe  → severe watches    — propiedad de ESTE script
    #
    # FUSIÓN (no sobrescritura): cargamos el índice vivo del CDN para preservar la única
    # sección que NO poseemos ('warnings', tornado). Este script y tornado_dynamic escriben
    # aquí; ambos hacen read-merge para no pisarse (offset cron :00 vs :30).
    index = cargar_index_actual()
    for k in ('warnings', 'watches', 'warnings_severe', 'watches_severe'):
        index.setdefault(k, {})
    # Reconstruimos en limpio nuestras 3 secciones (así caducan los items ya inactivos);
    # solo 'warnings' (tornado) se preserva tal cual venía del CDN.
    index['watches'] = {}
    index['warnings_severe'] = {}
    index['watches_severe'] = {}
    stats = {'generados': 0, 'skipped': 0, 'chars': 0}

    # NOTA: los avisos de tornado (warnings_tor) los genera tornado_dynamic_voices_pipeline.py
    # (dedicado: maneja Tornado Emergency, cachea y limpia obsoletos). Aquí NO se procesan para
    # no duplicar trabajo ni entrar en conflicto de escritura sobre la sección 'warnings'.

    if watches_tor:
        print(f"\n━━━ VIGILANCIAS TORNADO ━━━")
        procesar_items(watches_tor, componer_frase_watch, index['watches'], stats)

    if warnings_svr:
        print(f"\n━━━ AVISOS TORMENTA SEVERA ━━━")
        procesar_items(warnings_svr, componer_frase_severo, index['warnings_severe'], stats)

    if watches_svr:
        print(f"\n━━━ VIGILANCIAS TORMENTA SEVERA ━━━")
        procesar_items(watches_svr, componer_frase_watch_severo, index['watches_severe'], stats)

    # Publicar index
    index['updated'] = int(time.time())
    idx_path = OUT_DIR / 'warnings_index.json'
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    if upload_cdn(idx_path, 'voices/warnings_index.json',
                  content_type='application/json', cache_secs=60):
        total = (len(index['warnings']) + len(index['watches'])
                 + len(index['warnings_severe']) + len(index['watches_severe']))
        print(f"\n[voice-warnings] Index publicado: "
              f"TOR({len(index['warnings'])}w+{len(index['watches'])}v) + "
              f"SVR({len(index['warnings_severe'])}w+{len(index['watches_severe'])}v) = {total} entries")
    else:
        print(f"\n❌ Error publicando index", file=sys.stderr)

    dt = time.time() - t0
    print(f"\n[voice-warnings] DONE in {dt:.1f}s — "
          f"{stats['generados']} generados, {stats['skipped']} ya existían, "
          f"{stats['chars']} chars consumidos")
    return 0


if __name__ == '__main__':
    sys.exit(main())
