#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
tornado_dynamic_voices_pipeline.py — Canal Meteo
============================================================================
Genera audios TTS dinámicos para Tornado Warnings/Emergencies cuando la
población afectada > 10,000 personas. Para warnings con menos población,
no se genera audio dinámico (el HTML usa fallback estático genérico).

Flujo cada minuto vía cron:
    1. Lee tornado-warnings.json del CDN (publicado por tornado_warnings_pipeline.py)
    2. Para cada warning:
        - Si population > 10,000: genera texto detallado + TTS dinámico
        - Si population <= 10,000: skip (fallback estático en HTML)
    3. Cachea por warning_id+hash de texto: si ya existe, no regenera
    4. Traduce description al español con Claude API
    5. Genera MP3 con ElevenLabs (voz Albert)
    6. Sube MP3 individual al CDN: /voices/dynamic/{warning_id}.mp3
    7. Actualiza /voices/warnings_index.json con índice de URLs

Crontab:
    * * * * * /usr/bin/flock -n /tmp/tor_voices.lock /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/tornado_dynamic_voices_pipeline.py >> /var/log/canalmeteo/tor_voices.log 2>&1

Credenciales necesarias:
    /opt/canalmeteo/.env_elevenlabs   (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID)
    /opt/canalmeteo/.env_anthropic_key (Claude API key, una sola línea)
============================================================================
"""

import os
import sys
import json
import hashlib
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

# ─── CONFIG ────────────────────────────────────────────────────────────
WARNINGS_URL = "https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/tornado-warnings.json"

# Population threshold
POP_THRESHOLD = 10_000

# CDN
CDN_BUCKET = "canalmeteo-public"
CDN_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CDN_PROFILE = "do-tor1"
CDN_DYN_PREFIX = "voices/dynamic"
CDN_INDEX_KEY = "voices/warnings_index.json"
CDN_BASE_URL = f"https://{CDN_BUCKET}.sfo3.digitaloceanspaces.com"

# Local cache
CACHE_DIR = Path("/opt/canalmeteo/cache/tornado_voices")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
INDEX_LOCAL = CACHE_DIR / "warnings_index.json"

LOG_PATH = "/var/log/canalmeteo/tor_voices.log"

# ElevenLabs config
ENV_ELEVEN = Path("/opt/canalmeteo/.env_elevenlabs")
if ENV_ELEVEN.exists():
    for line in ENV_ELEVEN.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
ELEVEN_MODEL = "eleven_multilingual_v2"
ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVEN_VOICE_SETTINGS = {
    "stability": 0.55,
    "similarity_boost": 0.85,
    "style": 0.30,
    "use_speaker_boost": True,
}

# Claude (Anthropic) config
ENV_ANTHROPIC = Path("/opt/canalmeteo/.env_anthropic_key")
ANTHROPIC_API_KEY = ""
if ENV_ANTHROPIC.exists():
    ANTHROPIC_API_KEY = ENV_ANTHROPIC.read_text().strip()
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"

# State abbreviation → full Spanish name (for narration)
STATE_NAMES = {
    'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California',
    'CO':'Colorado','CT':'Connecticut','DE':'Delaware','FL':'Florida','GA':'Georgia',
    'HI':'Hawái','ID':'Idaho','IL':'Illinois','IN':'Indiana','IA':'Iowa',
    'KS':'Kansas','KY':'Kentucky','LA':'Luisiana','ME':'Maine','MD':'Maryland',
    'MA':'Massachusetts','MI':'Michigan','MN':'Minnesota','MS':'Mississippi','MO':'Missouri',
    'MT':'Montana','NE':'Nebraska','NV':'Nevada','NH':'Nuevo Hampshire','NJ':'Nueva Jersey',
    'NM':'Nuevo México','NY':'Nueva York','NC':'Carolina del Norte','ND':'Dakota del Norte',
    'OH':'Ohio','OK':'Oklahoma','OR':'Oregón','PA':'Pensilvania','RI':'Rhode Island',
    'SC':'Carolina del Sur','SD':'Dakota del Sur','TN':'Tennessee','TX':'Texas','UT':'Utah',
    'VT':'Vermont','VA':'Virginia','WA':'Washington','WV':'Virginia Occidental',
    'WI':'Wisconsin','WY':'Wyoming','DC':'Washington DC',
}

SOURCE_TRANSLATIONS = {
    "radar indicated": "indicado por radar",
    "radar": "indicado por radar",
    "observed": "observado en superficie",
    "spotter": "reportado por observadores de tormentas",
    "trained spotter": "reportado por observadores entrenados",
    "law enforcement": "reportado por las autoridades",
    "public": "reportado por ciudadanos",
}


# ─── LOG ───────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ─── CACHE INDEX ───────────────────────────────────────────────────────
def load_local_index():
    if INDEX_LOCAL.exists():
        try:
            return json.loads(INDEX_LOCAL.read_text())
        except Exception:
            return {}
    return {}


def save_local_index(index):
    INDEX_LOCAL.write_text(json.dumps(index, indent=2))


# ─── TEXT GENERATION ───────────────────────────────────────────────────
def format_expires_time(expires_iso):
    """Convert ISO timestamp to '2:30 de la tarde, hora local' style for narration."""
    try:
        # Parse and convert to UTC, then say "hora local" (don't translate timezone)
        dt = datetime.fromisoformat(expires_iso.replace("Z", "+00:00"))
        h = dt.hour
        m = dt.minute
        # Convert to 12h
        period = "de la mañana"
        h12 = h
        if h == 0:
            h12 = 12; period = "de la madrugada"
        elif h < 6:
            period = "de la madrugada"
        elif h < 12:
            period = "de la mañana"
        elif h == 12:
            period = "del mediodía"
        elif h < 19:
            h12 = h - 12; period = "de la tarde"
        else:
            h12 = h - 12; period = "de la noche"
        if m == 0:
            return f"las {h12} en punto {period}"
        else:
            return f"las {h12} y {m:02d} {period}"
    except Exception:
        return None


def build_narration_text(warning):
    """
    Construye el texto que se sintetizará. Solo se llama cuando población > 10K.
    Usa los datos del warning para una narración detallada en español.
    """
    event = warning.get("event", "Tornado Warning")
    is_emergency = (event == "Tornado Emergency")
    state_abbr = warning.get("state") or ""
    state_full = STATE_NAMES.get(state_abbr, state_abbr or "Estados Unidos")
    counties = warning.get("counties", []) or []
    population = warning.get("population")
    source = warning.get("source")
    expires_str = format_expires_time(warning.get("expires"))

    # Format counties list naturally
    if len(counties) == 0:
        county_phrase = ""
    elif len(counties) == 1:
        county_phrase = f" en {counties[0]}"
    elif len(counties) == 2:
        county_phrase = f" en los condados de {counties[0]} y {counties[1]}"
    else:
        head = ", ".join(counties[:-1])
        county_phrase = f" en los condados de {head} y {counties[-1]}"

    # Format source
    source_phrase = ""
    if source:
        s_es = SOURCE_TRANSLATIONS.get(str(source).lower(), source)
        source_phrase = f" El tornado ha sido {s_es}."

    # Format population
    pop_phrase = ""
    if population:
        if population >= 1_000_000:
            pop_str = f"{population/1_000_000:.1f} millones de personas".replace(".", ",")
            if pop_str.startswith("1,0 "):
                pop_str = "un millón de personas"
        elif population >= 1000:
            pop_str = f"{population:,}".replace(",", ".") + " personas"
        else:
            pop_str = f"{population} personas"
        pop_phrase = f" Bajo este aviso se encuentran cerca de {pop_str}."

    expires_phrase = ""
    if expires_str:
        expires_phrase = f" Vigente hasta {expires_str}, hora local."

    if is_emergency:
        intro = (
            f"Emergencia por tornado en {state_full}. "
            f"El Servicio Nacional de Meteorología ha confirmado un tornado extremadamente peligroso{county_phrase}."
        )
        urgency = " Esta es una situación que pone en peligro la vida. Refúgiese ahora mismo."
    else:
        intro = (
            f"Aviso por tornado en {state_full}. "
            f"El Servicio Nacional de Meteorología ha emitido un aviso{county_phrase}."
        )
        urgency = " Si está en la zona afectada, refúgiese de inmediato."

    text = intro + source_phrase + pop_phrase + expires_phrase + urgency
    text += " Permanezca atento a las indicaciones de Canal Meteo y de las autoridades locales."
    return text


# ─── ELEVENLABS TTS ────────────────────────────────────────────────────
def generate_tts_mp3(text: str, out_path: Path) -> bool:
    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        log("❌ Falta ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID")
        return False
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": ELEVEN_MODEL,
        "voice_settings": ELEVEN_VOICE_SETTINGS,
    }
    url = f"{ELEVEN_TTS_URL}/{ELEVEN_VOICE_ID}?output_format=mp3_44100_128"
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=90)
        if r.status_code != 200:
            log(f"❌ ElevenLabs {r.status_code}: {r.text[:200]}")
            return False
        with open(out_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        log(f"❌ ElevenLabs error: {e}")
        return False


# ─── CDN UPLOAD ────────────────────────────────────────────────────────
def upload_to_cdn(local_path: Path, cdn_key: str, content_type="audio/mpeg") -> bool:
    cmd = [
        "aws", "s3", "cp", str(local_path),
        f"s3://{CDN_BUCKET}/{cdn_key}",
        "--profile", CDN_PROFILE,
        "--acl", "public-read",
        "--content-type", content_type,
        "--cache-control", "public, max-age=3600",
        "--endpoint-url", CDN_ENDPOINT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode == 0


# ─── MAIN ──────────────────────────────────────────────────────────────
def safe_id_for_filename(warning_id: str) -> str:
    """Convert NWS warning ID (urn:oid:...) to safe filename."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", warning_id)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def main():
    log("─" * 60)
    log("Iniciando pipeline de voces dinámicas")

    # 1. Read tornado-warnings.json
    try:
        r = requests.get(WARNINGS_URL + "?t=" + str(int(datetime.now().timestamp())),
                         timeout=20, headers={"Cache-Control": "no-cache"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"❌ No se pudo leer warnings JSON: {e}")
        sys.exit(1)

    warnings_list = data.get("warnings", [])
    log(f"  → {len(warnings_list)} warnings totales en CDN")

    # 2. Filter by population threshold
    eligible = [w for w in warnings_list
                if (w.get("population") or 0) > POP_THRESHOLD]
    log(f"  → {len(eligible)} con población > {POP_THRESHOLD:,}")

    # 3. Load existing index (cache)
    index = load_local_index()
    if "warnings" not in index:
        index["warnings"] = {}

    # Track which warnings are still active to clean up index later
    active_ids = set()
    new_or_updated = 0

    # 4. For each eligible warning, generate or skip
    for w in eligible:
        wid = w.get("id") or w.get("nws_id")
        if not wid:
            continue
        active_ids.add(wid)

        text = build_narration_text(w)
        h = hash_text(text)

        existing = index["warnings"].get(wid)
        if existing and existing.get("hash") == h:
            # Already generated and unchanged
            log(f"  ✓ Cache hit: {wid[:40]}...")
            continue

        # Generate
        log(f"  ⚙ Generando para {wid[:40]}... (pop={w.get('population'):,})")
        log(f"    Texto ({len(text)} chars): {text[:100]}...")

        safe_id = safe_id_for_filename(wid)
        local_mp3 = CACHE_DIR / f"{safe_id}.mp3"

        if not generate_tts_mp3(text, local_mp3):
            log(f"  ❌ No se generó MP3 para {wid}")
            continue

        # Upload to CDN
        cdn_key = f"{CDN_DYN_PREFIX}/{safe_id}.mp3"
        if not upload_to_cdn(local_mp3, cdn_key):
            log(f"  ❌ Falló upload de {safe_id}.mp3")
            continue

        index["warnings"][wid] = {
            "url": f"{CDN_BASE_URL}/{cdn_key}",
            "hash": h,
            "text": text,
            "event": w.get("event"),
            "population": w.get("population"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        new_or_updated += 1
        log(f"  ✅ Subido: {cdn_key}")

    # 5. Clean up index: remove warnings no longer active
    before = len(index["warnings"])
    index["warnings"] = {wid: v for wid, v in index["warnings"].items() if wid in active_ids}
    removed = before - len(index["warnings"])
    if removed:
        log(f"  🧹 Removidos del índice: {removed} warnings ya no activos")

    # 6. Update updated timestamp
    index["updated"] = datetime.now(timezone.utc).isoformat()

    # 7. Save local index
    save_local_index(index)

    # 8. Upload merged index to CDN — preserve other sections (watches, severe)
    # First fetch existing CDN index to merge with our warnings section
    try:
        existing_remote = requests.get(
            f"{CDN_BASE_URL}/{CDN_INDEX_KEY}?t=" + str(int(datetime.now().timestamp())),
            timeout=15
        ).json()
    except Exception:
        existing_remote = {"warnings": {}, "watches": {}, "warnings_severe": {}, "watches_severe": {}}

    # Merge: our 'warnings' section overrides; preserve everything else
    merged = dict(existing_remote)
    merged["warnings"] = index["warnings"]
    merged["updated"] = index["updated"]

    # Ensure other sections exist (don't break HTMLs that read them)
    for section in ("watches", "warnings_severe", "watches_severe"):
        if section not in merged:
            merged[section] = {}

    # Write & upload
    tmp_index = CACHE_DIR / "merged_index.json"
    tmp_index.write_text(json.dumps(merged, separators=(",", ":")))
    if upload_to_cdn(tmp_index, CDN_INDEX_KEY, content_type="application/json"):
        log(f"✅ Índice CDN actualizado: {len(merged.get('warnings',{}))} warnings con voz dinámica")
    else:
        log("❌ Fallo al subir índice CDN")
        sys.exit(2)

    log(f"  Resumen: {new_or_updated} nuevos/actualizados, {removed} removidos")
    log("─" * 60)


if __name__ == "__main__":
    main()
