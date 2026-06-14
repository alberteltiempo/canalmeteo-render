#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
generate_tornado_static_voices.py — Canal Meteo
============================================================================
Genera los MP3 estáticos requeridos por tornado-override.html con la voz
clonada de Albert (ElevenLabs).

Sube los archivos a:
    canalmeteo-public.sfo3.digitaloceanspaces.com/voices/static/
        ├── warn_tornado.mp3
        ├── warn_tornado_emergency.mp3
        └── safety_tornado.mp3

Credenciales: lee /opt/canalmeteo/.env_elevenlabs (ya existente)
    ELEVENLABS_API_KEY=sk_...
    ELEVENLABS_VOICE_ID=...

Uso:
    /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/generate_tornado_static_voices.py
============================================================================
"""

import os
import sys
import subprocess
from pathlib import Path

import requests

# ─── CONFIG ────────────────────────────────────────────────────────────
# Leer .env_elevenlabs (mismo patrón que voice_mvp.py)
ENV_FILE = Path('/opt/canalmeteo/.env_elevenlabs')
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
MODEL_ID = "eleven_multilingual_v2"  # mejor para español

OUT_DIR = Path("/tmp/tornado_voices")
OUT_DIR.mkdir(parents=True, exist_ok=True)

CDN_BUCKET = "canalmeteo-public"
CDN_KEY_PREFIX = "voices/static"
CDN_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CDN_PROFILE = "do-tor1"

# ElevenLabs API
ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

# ─── TEXTOS ────────────────────────────────────────────────────────────
VOICES = {
    "warn_tornado.mp3": (
        "Aviso por tornado emitido por el Servicio Nacional de Meteorología. "
        "Si está en la zona afectada, refúgiese de inmediato. "
        "Las próximas horas pueden ser peligrosas. "
        "Permanezca atento a Canal Meteo."
    ),
    "warn_tornado_emergency.mp3": (
        "Emergencia por tornado. "
        "Esta es una situación extremadamente peligrosa con un tornado confirmado. "
        "Refúgiese ahora mismo. "
        "No salga bajo ninguna circunstancia. "
        "Su vida puede estar en riesgo."
    ),
    "safety_tornado.mp3": (
        "Si está en la zona afectada del aviso por tornado, busque refugio inmediatamente. "
        "Diríjase al sótano o a una habitación interior sin ventanas en el nivel más bajo del edificio. "
        "Cúbrase con un colchón o mantas. "
        "Aléjese de las ventanas, los vidrios pueden romperse y causar lesiones graves. "
        "Si está conduciendo, no intente refugiarse bajo un puente. "
        "Si no puede llegar a un edificio sólido, salga del vehículo y diríjase a una zanja o terreno bajo. "
        "Manténgase informado a través de Canal Meteo y siga las indicaciones de las autoridades locales."
    ),
}

# ─── VOICE SETTINGS (broadcast professional) ───────────────────────────
VOICE_SETTINGS = {
    "stability": 0.55,         # 0.5-0.6 = balance natural/consistente
    "similarity_boost": 0.85,  # alta similitud con voz original
    "style": 0.30,             # ligera entonación dramática
    "use_speaker_boost": True
}

# ─── GENERATE ──────────────────────────────────────────────────────────
def generate_audio(text: str, out_path: Path) -> bool:
    """Genera un MP3 vía ElevenLabs API REST."""
    headers = {
        "xi-api-key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": VOICE_SETTINGS,
    }
    url = f"{ELEVEN_TTS_URL}/{VOICE_ID}?output_format=mp3_44100_128"
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code != 200:
            print(f"    ❌ ElevenLabs error {r.status_code}: {r.text[:200]}")
            return False
        with open(out_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"    ❌ Error: {e}")
        return False


def main():
    if not API_KEY:
        print("❌ ELEVENLABS_API_KEY no encontrada")
        print(f"   Asegúrate de que existe {ENV_FILE} con las credenciales")
        sys.exit(1)
    if not VOICE_ID:
        print("❌ ELEVENLABS_VOICE_ID no encontrada")
        print(f"   Asegúrate de que existe {ENV_FILE} con las credenciales")
        sys.exit(1)

    print("══════════════════════════════════════════════════════════════")
    print("  TORNADO STATIC VOICES — Canal Meteo")
    print("══════════════════════════════════════════════════════════════")
    print(f"✓ API Key:  {API_KEY[:10]}...")
    print(f"✓ Voice ID: {VOICE_ID[:12]}...")
    print(f"✓ Modelo:   {MODEL_ID}")
    print(f"✓ Output:   {OUT_DIR}")
    print(f"✓ CDN:      https://{CDN_BUCKET}.sfo3.digitaloceanspaces.com/{CDN_KEY_PREFIX}/")

    total_chars = sum(len(t) for t in VOICES.values())
    print(f"📊 Caracteres totales: {total_chars}")
    print()

    for i, (filename, text) in enumerate(VOICES.items(), 1):
        out_path = OUT_DIR / filename
        print(f"[{i}/{len(VOICES)}] {filename}")
        print(f"    Texto ({len(text)} chars): {text[:90]}...")

        if generate_audio(text, out_path):
            size_kb = out_path.stat().st_size / 1024
            print(f"    ✅ Guardado ({size_kb:.1f} KB)")
        else:
            print(f"    ⚠️  Saltando {filename}")

    print("\n📤 Subiendo a CDN...")
    for filename in VOICES.keys():
        local = OUT_DIR / filename
        if not local.exists():
            print(f"  ⚠️  {filename} no se generó, saltando")
            continue
        cdn_key = f"{CDN_KEY_PREFIX}/{filename}"
        cmd = [
            "aws", "s3", "cp", str(local),
            f"s3://{CDN_BUCKET}/{cdn_key}",
            "--profile", CDN_PROFILE,
            "--acl", "public-read",
            "--content-type", "audio/mpeg",
            "--cache-control", "public, max-age=86400",
            "--endpoint-url", CDN_ENDPOINT,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {filename}")
        else:
            print(f"  ❌ {filename}: {result.stderr.strip()}")

    print("\n🎉 Listo. URLs públicas:")
    for filename in VOICES.keys():
        print(f"   https://{CDN_BUCKET}.sfo3.digitaloceanspaces.com/{CDN_KEY_PREFIX}/{filename}")

if __name__ == "__main__":
    main()
