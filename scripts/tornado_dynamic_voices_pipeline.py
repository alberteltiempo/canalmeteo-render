#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tornado_dynamic_voices_pipeline.py
==================================
Canal Meteo TV — pipeline de voces dinámicas para Tornado Warnings.

Lee tornado-warnings.json del CDN, filtra por población y genera MP3 con ElevenLabs.
Tres niveles de detalle:

  - poblacion <  10.000  → no genera (frontend usa voz genérica estática)
  - poblacion 10k-50k    → frase MEDIA (~150 chars, ~5s):
        "Aviso por tornado activo en Oklahoma, condados de Pittsburg y Pushmataha.
         Unas trece mil personas en la zona afectada. Refúgiese de inmediato."

  - poblacion >  50.000  → frase LARGA (~280 chars, ~10s):
        "Aviso por tornado activo en Oklahoma, condados de Pittsburg, Pushmataha y Atoka.
         Unas ochenta y cinco mil personas en la zona afectada.
         Tornado indicado por radar.
         Vigente hasta las nueve y cuarenta y cinco de la noche, hora local.
         Refúgiese de inmediato."

Deploy:
  /opt/canalmeteo/scripts/tornado_dynamic_voices_pipeline.py
Cron:
  */2 * * * * flock -n /tmp/tornado_voices.lock /opt/canalmeteo/venv/bin/python3 \
      /opt/canalmeteo/scripts/tornado_dynamic_voices_pipeline.py \
      >> /opt/canalmeteo/logs/tornado_voices.log 2>&1
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════
CDN_BASE = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
WARNINGS_URL = f"{CDN_BASE}/data/tornado-warnings.json"
INDEX_URL    = f"{CDN_BASE}/voices/warnings_index.json"

# DigitalOcean Spaces (subida vía aws cli)
S3_BUCKET    = "canalmeteo-public"
S3_PROFILE   = "do-tor1"
S3_ENDPOINT  = "https://sfo3.digitaloceanspaces.com"
S3_DYNAMIC_PREFIX = "voices/dynamic"
S3_STATIC_PREFIX  = "voices/static"     # voces fijas que no cambian
S3_INDEX_KEY      = "voices/warnings_index.json"

# ── VOCES ESTÁTICAS (frases que no cambian, se generan UNA vez y persisten) ──
# clave = nombre del archivo (sin .mp3)
# valor = texto que se locuta
STATIC_PHRASES = {
    "diferencia_aviso_vigilancia": (
        "Es importante conocer la diferencia. "
        "Un aviso por tornado significa que el tornado ya está ocurriendo. "
        "Ha sido detectado por radar o avistado por observadores, y hay peligro inmediato. "
        "Refúgiese ya, vaya al sótano o a una habitación interior sin ventanas. "
        "Una vigilancia por tornado significa que las condiciones son favorables "
        "para que se formen tornados en las próximas horas, "
        "pero todavía no hay ningún tornado en marcha. "
        "Manténgase atento al pronóstico y tenga listo su plan de refugio."
    ),
}

# ── Cargar credenciales desde /opt/canalmeteo/.env_elevenlabs ─────────
# Mismo patrón que voice_warnings.py: si el archivo existe, exporta las
# variables al entorno antes de leerlas. Permite ejecutar manualmente sin
# tener que hacer `source ...` cada vez.
ENV_FILE = Path("/opt/canalmeteo/.env_elevenlabs")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ElevenLabs
ELEVENLABS_API_KEY  = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL    = "eleven_multilingual_v2"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# Umbrales de población
POBLACION_MIN_DINAMICA = 10_000   # debajo → voz genérica
POBLACION_LARGA        = 50_000   # encima → frase larga con hora + detección

# Cache local
CACHE_DIR = Path("/opt/canalmeteo/data/voice_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Logs
LOG_FILE = Path("/opt/canalmeteo/logs/tornado_voices.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [voice-warnings] %(levelname)s — %(message)s",
)
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# UTILIDADES TEXTO → ESPAÑOL
# ════════════════════════════════════════════════════════════════════

ESTADO_ES = {
    "Alabama":"Alabama","Alaska":"Alaska","Arizona":"Arizona","Arkansas":"Arkansas",
    "California":"California","Colorado":"Colorado","Connecticut":"Connecticut",
    "Delaware":"Delaware","Florida":"Florida","Georgia":"Georgia","Hawaii":"Hawái",
    "Idaho":"Idaho","Illinois":"Illinois","Indiana":"Indiana","Iowa":"Iowa",
    "Kansas":"Kansas","Kentucky":"Kentucky","Louisiana":"Luisiana","Maine":"Maine",
    "Maryland":"Maryland","Massachusetts":"Massachusetts","Michigan":"Michigan",
    "Minnesota":"Minnesota","Mississippi":"Misisipi","Missouri":"Misuri",
    "Montana":"Montana","Nebraska":"Nebraska","Nevada":"Nevada",
    "New Hampshire":"Nuevo Hampshire","New Jersey":"Nueva Jersey",
    "New Mexico":"Nuevo México","New York":"Nueva York",
    "North Carolina":"Carolina del Norte","North Dakota":"Dakota del Norte",
    "Ohio":"Ohio","Oklahoma":"Oklahoma","Oregon":"Oregón","Pennsylvania":"Pensilvania",
    "Rhode Island":"Rhode Island","South Carolina":"Carolina del Sur",
    "South Dakota":"Dakota del Sur","Tennessee":"Tennessee","Texas":"Texas",
    "Utah":"Utah","Vermont":"Vermont","Virginia":"Virginia","Washington":"Washington",
    "West Virginia":"Virginia Occidental","Wisconsin":"Wisconsin","Wyoming":"Wyoming",
    # códigos de 2 letras también
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawái","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas",
    "KY":"Kentucky","LA":"Luisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts",
    "MI":"Michigan","MN":"Minnesota","MS":"Misisipi","MO":"Misuri","MT":"Montana",
    "NE":"Nebraska","NV":"Nevada","NH":"Nuevo Hampshire","NJ":"Nueva Jersey",
    "NM":"Nuevo México","NY":"Nueva York","NC":"Carolina del Norte",
    "ND":"Dakota del Norte","OH":"Ohio","OK":"Oklahoma","OR":"Oregón",
    "PA":"Pensilvania","RI":"Rhode Island","SC":"Carolina del Sur",
    "SD":"Dakota del Sur","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont",
    "VA":"Virginia","WA":"Washington","WV":"Virginia Occidental","WI":"Wisconsin",
    "WY":"Wyoming",
}


def traducir_estado(s):
    if not s:
        return ""
    return ESTADO_ES.get(s, s)


# Conversión de número entero a texto en español
UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
            "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete",
            "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés",
            "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
            "veintinueve"]
DECENAS  = ["", "", "veinte", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta",
            "ochenta", "noventa"]
CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
            "seiscientos", "setecientos", "ochocientos", "novecientos"]


def _menor_de_mil(n):
    if n == 0: return ""
    if n == 100: return "cien"
    if n < 30: return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        if u == 0:
            return DECENAS[d]
        return f"{DECENAS[d]} y {UNIDADES[u]}"
    c, r = divmod(n, 100)
    base = CENTENAS[c]
    if r == 0:
        return base
    return f"{base} {_menor_de_mil(r)}"


def num_a_texto(n):
    """Convierte un entero a texto en español, redondeando para TTS amigable.

    Reglas:
      - <1.000:        exacto
      - 1k-10k:        redondeo a múltiplos de 500   ("dos mil quinientas")
      - 10k-100k:      redondeo a múltiplos de 1.000 ("ochenta y cinco mil")
      - 100k-1M:       redondeo a múltiplos de 5.000 ("cuatrocientos veinticinco mil")
      - >=1M:          siempre con un decimal en millones ("uno coma cinco millones")
    """
    n = int(n)
    if n < 0:
        return ""
    if n == 0:
        return "cero"
    if n >= 1_000_000:
        m = round(n / 100_000) / 10  # un decimal
        if m == int(m):
            ent = int(m)
            return "un millón" if ent == 1 else f"{_menor_de_mil(ent)} millones"
        ent = int(m)
        dec = int(round((m - ent) * 10))
        return f"{_menor_de_mil(ent)} coma {UNIDADES[dec]} millones"
    # Determinar paso de redondeo según escala
    if n >= 100_000:
        n = round(n / 5_000) * 5_000
    elif n >= 10_000:
        n = round(n / 1_000) * 1_000
    elif n >= 1_000:
        n = round(n / 500) * 500
    # Construir texto miles + resto
    miles = n // 1_000
    resto = n - miles * 1_000
    parts = []
    if miles == 1:
        parts.append("mil")
    elif miles > 0:
        parts.append(f"{_menor_de_mil(miles)} mil")
    if resto > 0:
        parts.append(_menor_de_mil(resto))
    return " ".join(parts)


# Hora del día en español
def hora_a_texto(dt_local):
    """Convierte datetime local a 'las nueve y cuarenta y cinco de la noche'."""
    h = dt_local.hour
    m = dt_local.minute
    # Período del día
    if 5 <= h < 12:
        periodo = "de la mañana"
    elif 12 <= h < 20:
        periodo = "de la tarde"
    else:
        periodo = "de la noche"
    # Hora 12h
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    if h12 == 1:
        hora_txt = "la una"
        prefijo = ""
    else:
        hora_txt = f"las {UNIDADES[h12]}" if h12 < 30 else f"las {_menor_de_mil(h12)}"
        prefijo = ""
    # Minutos
    if m == 0:
        return f"{prefijo}{hora_txt} en punto {periodo}"
    if m == 15:
        return f"{prefijo}{hora_txt} y cuarto {periodo}"
    if m == 30:
        return f"{prefijo}{hora_txt} y media {periodo}"
    if m == 45:
        # "diez menos cuarto"
        h_sig = (h12 % 12) + 1
        if h_sig == 1:
            sig = "la una"
        else:
            sig = f"las {UNIDADES[h_sig]}" if h_sig < 30 else f"las {_menor_de_mil(h_sig)}"
        return f"{prefijo}{sig} menos cuarto {periodo}"
    if m < 30:
        return f"{prefijo}{hora_txt} y {_menor_de_mil(m)} {periodo}"
    # 31-44, 46-59 → leemos directos: "las nueve cuarenta y siete"
    return f"{prefijo}{hora_txt} {_menor_de_mil(m)} {periodo}"


# ════════════════════════════════════════════════════════════════════
# DETECCIÓN DEL TIPO DE TORNADO (radar, observado, etc.)
# ════════════════════════════════════════════════════════════════════

def detectar_fuente(warning):
    """Devuelve un texto descriptivo en español del origen del tornado.

    Prefiere el campo estructurado 'parameters.tornadoDetection'; si no
    está, intenta parsear el campo 'description' buscando 'SOURCE...'.
    """
    params = warning.get("parameters", {}) or {}

    # Lista o string?
    def _first(v):
        if isinstance(v, list) and v:
            return str(v[0])
        return str(v) if v else ""

    detection = _first(params.get("tornadoDetection")) or _first(params.get("eventMotionDescription"))
    detection = (detection or "").upper().strip()

    if detection:
        if "RADAR" in detection and ("INDIC" in detection or "INDICATED" in detection):
            return "Tornado indicado por radar"
        if "OBSERV" in detection:
            return "Tornado observado"
        if "POSSIBLE" in detection:
            return "Tornado posible"
        if "CONFIRMED" in detection:
            return "Tornado confirmado"

    # Fallback: parsear description con regex sobre "SOURCE..."
    desc = (warning.get("description") or "").upper()
    m = re.search(r"SOURCE[\.\s]+([A-Z ]+?)\.", desc)
    if m:
        src = m.group(1).strip()
        if "RADAR" in src and "INDIC" in src:
            return "Tornado indicado por radar"
        if "TRAINED" in src or "SPOTTER" in src:
            return "Tornado avistado por meteorólogo"
        if "LAW ENFORCEMENT" in src:
            return "Tornado avistado por las autoridades"
        if "PUBLIC" in src:
            return "Tornado avistado por testigos"
        if "EMERGENCY MANAGEMENT" in src:
            return "Tornado confirmado por gestión de emergencias"

    return ""  # sin info → la frase omite esta parte


# ════════════════════════════════════════════════════════════════════
# COMPOSICIÓN DE FRASES
# ════════════════════════════════════════════════════════════════════

def parse_expires_local(warning):
    """Parsea expires y lo devuelve como datetime en zona local del aviso.

    Los avisos NWS ya vienen con offset, así que con fromisoformat ya tenemos
    el tiempo en hora local del aviso (la zona horaria que aplica).
    """
    expires = warning.get("expires") or ""
    if not expires:
        return None
    try:
        # Python 3.11+ acepta directamente; antes hay que normalizar 'Z'
        return datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except Exception:
        return None


def extraer_condados(warning):
    """Devuelve lista de nombres de condados (sin sufijo de estado)."""
    raw = (warning.get("condados_nombres")
           or warning.get("counties")
           or warning.get("areaDesc")
           or warning.get("areas")
           or "")
    if isinstance(raw, list):
        items = list(raw)
    else:
        s = str(raw)
        # areaDesc del NWS separa condados con ';'. Cada condado lleva ", XX" al final.
        # Si NO hay ';' pero el patrón es "Foo, XX" (un único condado), tratar como uno.
        if ";" in s:
            items = [p.strip() for p in s.split(";")]
        elif re.fullmatch(r"[^,]+,\s*[A-Z]{2}\s*", s.strip()):
            items = [s.strip()]
        else:
            # Lista plana de condados separada por comas (sin código de estado)
            items = [p.strip() for p in s.split(",")]
    nombres = []
    for it in items:
        if not it:
            continue
        # Quitar sufijo de estado: "Pittsburg, OK" → "Pittsburg", "Cleburne County, AR" → "Cleburne County"
        it = re.sub(r",\s*[A-Z]{2}\s*$", "", it).strip()
        # filtrar "(+24 zonas)" etc.
        if "(" in it or not it:
            continue
        nombres.append(it)
    # dedup preservando orden
    out, seen = [], set()
    for n in nombres:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


def componer_frase(warning):
    """Construye la frase TTS según el nivel de detalle por población."""
    pob = int(warning.get("population") or warning.get("poblacion") or 0)

    estado = (warning.get("estado_nombre")
              or warning.get("state")
              or warning.get("estado")
              or "")
    estado_es = traducir_estado(estado)

    condados = extraer_condados(warning)
    pob_txt = num_a_texto(pob) if pob >= 1_000 else ""

    # ─── Apertura común ───
    apertura = "Aviso por tornado activo"
    if estado_es:
        apertura += f" en {estado_es}"

    # ─── Frase MEDIA (10k-50k) ───
    if pob < POBLACION_LARGA:
        if condados:
            cs = condados[:3]
            if len(cs) == 1:
                apertura += f", condado de {cs[0]}"
            elif len(cs) == 2:
                apertura += f", condados de {cs[0]} y {cs[1]}"
            else:
                apertura += f", condados de {cs[0]}, {cs[1]} y {cs[2]}"
        apertura += "."
        impacto = ""
        if pob_txt:
            cuant = "Más de" if pob >= 100_000 else "Unas"
            impacto = f" {cuant} {pob_txt} personas en la zona afectada."
        return apertura + impacto + " Refúgiese de inmediato."

    # ─── Frase LARGA (>50k) ───
    # Estado + condados (hasta 3) + población + detección + hora vencimiento
    if condados:
        cs = condados[:3]
        if len(cs) == 1:
            apertura += f", condado de {cs[0]}"
        elif len(cs) == 2:
            apertura += f", condados de {cs[0]} y {cs[1]}"
        else:
            apertura += f", condados de {cs[0]}, {cs[1]} y {cs[2]}"
    apertura += "."

    # Población siempre presente en frase larga
    cuant = "Más de" if pob >= 100_000 else "Unas"
    poblacion_txt = f" {cuant} {pob_txt} personas se encuentran en la zona afectada."

    # Tipo de detección (si lo extraemos)
    fuente = detectar_fuente(warning)
    fuente_txt = f" {fuente}." if fuente else ""

    # Hora de vencimiento (en zona del aviso)
    expires_dt = parse_expires_local(warning)
    expires_txt = ""
    if expires_dt:
        try:
            expires_txt = f" El aviso permanece vigente hasta {hora_a_texto(expires_dt)}, hora local."
        except Exception:
            log.warning("hora_a_texto falló para %s", expires_dt)

    return apertura + poblacion_txt + fuente_txt + expires_txt + " Refúgiese de inmediato."


# ════════════════════════════════════════════════════════════════════
# ELEVENLABS TTS
# ════════════════════════════════════════════════════════════════════

def hash_texto(texto):
    return hashlib.md5(texto.encode("utf-8")).hexdigest()[:16]


def generar_mp3(texto, output_path):
    """Llama a ElevenLabs y guarda el MP3 en output_path."""
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        log.error("ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID no configurados")
        return False

    url = ELEVENLABS_URL.format(voice_id=ELEVENLABS_VOICE_ID)
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": texto,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.4,
            "use_speaker_boost": True,
        },
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            log.error("ElevenLabs %s: %s", r.status_code, r.text[:200])
            return False
        output_path.write_bytes(r.content)
        log.info("MP3 generado: %s (%d bytes)", output_path.name, len(r.content))
        return True
    except Exception as e:
        log.error("Error TTS: %s", e)
        return False


def subir_a_cdn(local_path, key):
    """Sube un archivo al CDN vía aws cli."""
    cmd = [
        "aws", "s3", "cp", str(local_path), f"s3://{S3_BUCKET}/{key}",
        "--profile", S3_PROFILE,
        "--endpoint-url", S3_ENDPOINT,
        "--acl", "public-read",
    ]
    if str(local_path).endswith(".mp3"):
        cmd += ["--content-type", "audio/mpeg", "--cache-control", "public, max-age=86400"]
    elif str(local_path).endswith(".json"):
        cmd += ["--content-type", "application/json", "--cache-control", "no-cache, max-age=60"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.error("aws s3 cp falló: %s", result.stderr)
            return False
        return True
    except Exception as e:
        log.error("Error subiendo: %s", e)
        return False


# ════════════════════════════════════════════════════════════════════
# PROCESO PRINCIPAL
# ════════════════════════════════════════════════════════════════════

def prebake_static_voices():
    """Genera y sube las frases estáticas si no existen ya en el CDN.

    Estas voces son frases fijas (ej. la explicación 'Aviso vs Vigilancia')
    que solo cambian si modificamos el texto en STATIC_PHRASES. Para evitar
    regenerar y consumir cuota cada vez, comparamos el hash del texto actual
    con el almacenado localmente; si no coincide, regeneramos.
    """
    static_state_path = CACHE_DIR / "static_state.json"
    try:
        state = json.loads(static_state_path.read_text())
    except Exception:
        state = {}

    cambios = 0
    for nombre, texto in STATIC_PHRASES.items():
        h = hash_texto(texto)
        prev_hash = state.get(nombre, {}).get("hash")
        s3_key = f"{S3_STATIC_PREFIX}/{nombre}.mp3"
        cdn_url = f"{CDN_BASE}/{s3_key}"

        # Si el hash no ha cambiado, asumimos que el archivo ya está en CDN
        if prev_hash == h:
            log.info("[static] %s — sin cambios (hash %s)", nombre, h)
            continue

        log.info("[static] %s — regenerando (texto nuevo o no existía)", nombre)
        log.info("  (%d chars) %s", len(texto), texto)

        # Generar MP3
        local_path = CACHE_DIR / f"static_{nombre}.mp3"
        if not generar_mp3(texto, local_path):
            log.error("  Falló generación TTS para %s", nombre)
            continue

        # Subir al CDN
        if not subir_a_cdn(local_path, s3_key):
            log.error("  Falló subida CDN para %s", nombre)
            continue

        state[nombre] = {
            "hash": h,
            "url": cdn_url,
            "chars": len(texto),
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }
        cambios += 1

    if cambios:
        static_state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        log.info("[static] %d voces estáticas actualizadas", cambios)


def cargar_index_actual():
    """Lee el warnings_index.json actual del CDN para preservar otras secciones."""
    try:
        r = requests.get(INDEX_URL + f"?ts={int(datetime.now().timestamp())}", timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("No se pudo cargar index actual: %s", e)
    return {"updated": int(datetime.now().timestamp()), "warnings": {}}


def main():
    log.info("=== INICIO ciclo voces dinámicas tornado ===")

    # 0. Pre-generar voces estáticas si han cambiado o no existen
    prebake_static_voices()

    # 1. Descargar warnings activos
    try:
        r = requests.get(WARNINGS_URL + f"?ts={int(datetime.now().timestamp())}", timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error("No se pudo leer tornado-warnings.json: %s", e)
        sys.exit(1)

    warnings = data.get("warnings", [])
    activos_tornado = [w for w in warnings
                       if w.get("event") in ("Tornado Warning", "Tornado Emergency")]
    log.info("Avisos de tornado activos: %d", len(activos_tornado))

    # 2. Filtrar por población >= umbral mínimo
    candidatos = [w for w in activos_tornado
                  if int(w.get("population") or w.get("poblacion") or 0) >= POBLACION_MIN_DINAMICA]
    log.info("Candidatos a voz dinámica (>=%d hab): %d",
             POBLACION_MIN_DINAMICA, len(candidatos))

    # 3. Cargar index actual y preservar otras secciones
    index = cargar_index_actual()
    if "warnings" not in index:
        index["warnings"] = {}

    # Limpiar entradas obsoletas (warnings que ya no existen)
    ids_activos = {w.get("id") for w in candidatos}
    eliminadas = 0
    for wid in list(index["warnings"].keys()):
        if wid not in ids_activos:
            del index["warnings"][wid]
            eliminadas += 1
    if eliminadas:
        log.info("Eliminadas %d entradas obsoletas del index", eliminadas)

    # 4. Generar voces nuevas
    nuevas = 0
    reusadas = 0
    for w in candidatos:
        wid = w.get("id")
        if not wid:
            continue
        pob = int(w.get("population") or 0)
        nivel = "LARGA" if pob >= POBLACION_LARGA else "MEDIA"
        frase = componer_frase(w)
        h = hash_texto(frase)
        mp3_key = f"{S3_DYNAMIC_PREFIX}/{h}.mp3"
        url = f"{CDN_BASE}/{mp3_key}"

        # Si ya está en el index con el mismo hash, no regenerar
        prev = index["warnings"].get(wid)
        if prev and prev.get("hash") == h:
            reusadas += 1
            continue

        log.info("[%s] %s — %d hab — %d chars", nivel, wid[-12:], pob, len(frase))
        log.info("  Frase: %s", frase)

        # Cache local
        cache_path = CACHE_DIR / f"{h}.mp3"
        if not cache_path.exists():
            if not generar_mp3(frase, cache_path):
                log.error("  Falló generación TTS para %s", wid)
                continue
            if not subir_a_cdn(cache_path, mp3_key):
                log.error("  Falló subida CDN para %s", wid)
                continue
        else:
            log.info("  Reutilizado de cache local: %s", cache_path.name)

        index["warnings"][wid] = {
            "url":   url,
            "hash":  h,
            "nivel": nivel,
            "pob":   pob,
            "chars": len(frase),
            "ts":    int(datetime.now(timezone.utc).timestamp()),
        }
        nuevas += 1

    # 5. Subir index actualizado
    index["updated"] = int(datetime.now(timezone.utc).timestamp())
    index_path = CACHE_DIR / "warnings_index.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    if not subir_a_cdn(index_path, S3_INDEX_KEY):
        log.error("Falló subida del index")
    else:
        log.info("Index actualizado: %d nuevas, %d reutilizadas, %d obsoletas",
                 nuevas, reusadas, eliminadas)

    log.info("=== FIN ciclo ===")


if __name__ == "__main__":
    main()
