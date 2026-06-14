#!/usr/bin/env python3
"""
voice_mvp.py — Genera las 8 frases MVP de Canal Meteo

Uso en el droplet:
    ssh root@sfo3-a
    /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/voice_mvp.py

Credenciales en /opt/canalmeteo/.env_elevenlabs:
    ELEVENLABS_API_KEY=sk_xxx
    ELEVENLABS_VOICE_ID=xxx

Resultado:
    8 MP3s en https://canalmeteo-public.sfo3.digitaloceanspaces.com/voices/static/
"""
import os
import sys
import subprocess
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

CDN_BUCKET   = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
CDN_BASE_URL = 'https://canalmeteo-public.sfo3.digitaloceanspaces.com'
AWS_PROFILE  = 'do-tor1'

OUT_DIR = Path('/tmp/voice_mvp')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# LAS 8 FRASES MVP
# ═══════════════════════════════════════════════════════════════
PHRASES = {
    'radar_intro':
        "Última hora del radar nacional. Seguimiento en tiempo real de la actividad de tormentas en Estados Unidos.",

    'risk_intro':
        "Storm Prediction Center. Observamos las zonas de riesgo convectivo para las próximas veinticuatro horas.",

    'prep_general':
        "Antes de que lleguen las tormentas, prepárese con tiempo. Estas medidas pueden salvar vidas hoy.",

    'prep_tornado':
        "El riesgo principal de hoy es de tornados. Identifique ya su refugio y manténgase informado.",

    'prep_hail':
        "Se espera granizo significativo. Proteja sus vehículos y asegure los vidrios de su casa.",

    'prep_wind':
        "Vientos fuertes en camino. Guarde objetos sueltos y evite estacionar bajo árboles.",

    'lsr_intro':
        "Reportes de tiempo severo recibidos en las últimas horas por el Servicio Nacional de Meteorología.",

    'safety_tornado':
        "Proteja su vida. Siga estas recomendaciones inmediatamente. Refúgiese ahora mismo en un sótano o en una habitación interior del nivel más bajo. Aléjese de ventanas, puertas y paredes exteriores. Si está en un vehículo o casa móvil, abandónelo de inmediato. Y sobre todo, cubra siempre su cabeza y cuello.",

    # Avisos y vigilancias (se reproducen durante el zoom del radar, no en el slide intro)
    'watch_tornado':
        "Vigilancia por tornado activa. Las condiciones atmosféricas podrían generar tornados en las próximas horas. Revise su plan de emergencia y tenga identificado su refugio más cercano.",

    'watch_severe':
        "Vigilancia por tormenta severa. Se esperan condiciones propicias para tormentas fuertes con vientos intensos, granizo y abundante lluvia. Manténgase atento a posibles avisos.",

    'warn_tornado':
        "Aviso por tornado activo emitido por el Servicio Nacional de Meteorología. Tornado detectado o indicado por radar. Si está en la zona afectada, refúgiese de inmediato en un sótano o habitación interior. Aléjese de ventanas y paredes exteriores.",

    'warn_severe':
        "Aviso por tormenta severa en efecto. Se reportan vientos destructivos y posible granizo de gran tamaño. Manténgase en interiores, aléjese de ventanas y de objetos que puedan caer o romperse.",
}

# ═══════════════════════════════════════════════════════════════

def tts(text: str, output: Path) -> bool:
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
        print(f"  ⬇️  ElevenLabs ({len(text)} chars)...", end=' ', flush=True)
        r = requests.post(url, json=data, headers=headers, timeout=60)
        if r.status_code != 200:
            print(f"\n  ❌ Error {r.status_code}: {r.text[:200]}")
            return False
        output.write_bytes(r.content)
        print(f"✅ {len(r.content)/1024:.1f} KB")
        return True
    except Exception as e:
        print(f"\n  ❌ {e}")
        return False


def cdn_exists(cdn_key: str) -> bool:
    """Check if file already exists in CDN to avoid regenerating"""
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


def upload_cdn(local: Path, cdn_key: str) -> bool:
    cmd = [
        'aws', 's3', 'cp', str(local),
        f's3://{CDN_BUCKET}/{cdn_key}',
        '--profile', AWS_PROFILE,
        '--acl', 'public-read',
        '--content-type', 'audio/mpeg',
        '--cache-control', 'public, max-age=604800',
        '--endpoint-url', CDN_ENDPOINT,
    ]
    try:
        print(f"  📤 CDN → /{cdn_key}...", end=' ', flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if r.returncode == 0:
            print("✅")
            return True
        print(f"\n  ❌ {r.stderr[:200]}")
        return False
    except Exception as e:
        print(f"\n  ❌ {e}")
        return False


def main():
    print("═" * 62)
    print("  VOICE MVP — Canal Meteo (8 frases)")
    print("═" * 62)

    if not API_KEY:
        print("❌ ELEVENLABS_API_KEY no configurado")
        print("   Crea /opt/canalmeteo/.env_elevenlabs con tu API key")
        return 1
    if not VOICE_ID:
        print("❌ ELEVENLABS_VOICE_ID no configurado")
        return 1

    print(f"✓ API Key: {API_KEY[:12]}...")
    print(f"✓ Voice ID: {VOICE_ID}")
    print(f"✓ Output local: {OUT_DIR}")
    print(f"✓ CDN: {CDN_BASE_URL}/voices/static/")

    total_chars = sum(len(t) for t in PHRASES.values())
    print(f"📊 Total caracteres: {total_chars} (Free plan: 10.000/mes)\n")

    total = len(PHRASES)
    ok = 0
    skipped = 0

    for i, (key, text) in enumerate(PHRASES.items(), 1):
        print(f"[{i}/{total}] {key}")
        short = text if len(text) <= 75 else text[:72] + '...'
        print(f"  \"{short}\"")

        local = OUT_DIR / f"{key}.mp3"
        cdn_key = f"voices/static/{key}.mp3"

        # Skip si ya existe en el CDN (ahorra créditos)
        if cdn_exists(cdn_key):
            print(f"  ⏭️  Ya existe en CDN, saltando")
            print(f"  🔗 {CDN_BASE_URL}/{cdn_key}")
            skipped += 1
            ok += 1
            print()
            continue

        if not tts(text, local):
            continue
        if not upload_cdn(local, cdn_key):
            continue

        print(f"  🔗 {CDN_BASE_URL}/{cdn_key}")
        ok += 1
        print()

    print("═" * 62)
    print(f"  RESUMEN: {ok}/{total} completados ({skipped} saltados por ya existir)")
    print("═" * 62)

    if ok == total:
        print("\n✅ MVP generado con éxito!\n")
        print("Pasos siguientes:")
        print("  1. Prueba cada URL en el navegador")
        print("  2. Integra el snippet JS en radar-tornado.html y movil")
        return 0
    print(f"\n⚠️  {total - ok} frases fallaron.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
