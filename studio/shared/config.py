"""Configuración compartida de Canal Meteo Studio.

Reutiliza la misma convención de DO Spaces que el resto de pipelines
(ver scripts/radar_tile.py): perfil boto3 `do-tor1` con fallback a las
variables de entorno DO_SPACES_KEY / DO_SPACES_SECRET.
"""
from __future__ import annotations

import os

# ─── DO Spaces (CDN) ─────────────────────────────────────────────────
SPACES_BUCKET = os.environ.get("SPACES_BUCKET", "canalmeteo-public")
SPACES_REGION = os.environ.get("SPACES_REGION", "sfo3")
SPACES_ENDPOINT = os.environ.get(
    "AWS_ENDPOINT_URL", f"https://{SPACES_REGION}.digitaloceanspaces.com"
)
SPACES_PROFILE = os.environ.get("SPACES_PROFILE", "do-tor1")
CDN_BASE = f"https://{SPACES_BUCKET}.{SPACES_REGION}.digitaloceanspaces.com"

# Todos los objetos del editor cuelgan de este prefijo en el bucket.
STUDIO_PREFIX = os.environ.get("STUDIO_PREFIX", "studio")

# ─── Web (nimbus) ────────────────────────────────────────────────────
WEB_HOST = os.environ.get("STUDIO_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("STUDIO_WEB_PORT", "8787"))
# Registro local de trabajos (lado nimbus). El estado autoritativo de
# procesado vive en status.json dentro de Spaces.
DB_PATH = os.environ.get("STUDIO_DB_PATH", "/opt/canalmeteo/studio/web/studio.db")

# ─── Worker (calamarsa) ──────────────────────────────────────────────
# Carpeta de trabajo transitoria; se limpia tras subir el resultado al CDN.
WORK_DIR = os.environ.get("STUDIO_WORK_DIR", "/opt/canalmeteo/videos")
POLL_INTERVAL = int(os.environ.get("STUDIO_POLL_INTERVAL", "10"))  # segundos

# ─── Procesado (Fase 2) ──────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))     # studio/shared
STUDIO_DIR = os.path.dirname(_HERE)                    # studio/
VENV_BIN = os.path.join(STUDIO_DIR, ".venv", "bin")    # venv dedicado (aislado del de prod)
VENV_PY = os.path.join(VENV_BIN, "python")
AUTO_EDITOR = os.path.join(VENV_BIN, "auto-editor")
ASR_SCRIPT = os.path.join(STUDIO_DIR, "worker", "pipeline", "asr.py")

# Silencios (auto-editor): umbral de volumen para considerar "habla".
SILENCE_THRESHOLD = os.environ.get("STUDIO_SILENCE_THRESHOLD", "3%")

# Whisper (CPU; calamarsa es APU AMD, sin CUDA). small = rápido y decente en ES.
WHISPER_MODEL = os.environ.get("STUDIO_WHISPER_MODEL", "small")
WHISPER_COMPUTE = os.environ.get("STUDIO_WHISPER_COMPUTE", "int8")

# Salida vertical (Short/Reel)
VERT_W = 1080
VERT_H = 1920
VERTICAL_BG = os.environ.get("STUDIO_VERTICAL_BG", "")  # ruta a imagen; vacío = fondo generado
BG_COLOR = os.environ.get("STUDIO_BG_COLOR", "0x0B1F3A")  # azul oscuro de marca

# Croma (configurable; el verde real de la grabación se ajusta aquí)
CHROMA_COLOR = os.environ.get("STUDIO_CHROMA_COLOR", "0x00FF00")
CHROMA_SIMILARITY = os.environ.get("STUDIO_CHROMA_SIM", "0.30")
CHROMA_BLEND = os.environ.get("STUDIO_CHROMA_BLEND", "0.10")


# ─── Helpers de claves (keys) en Spaces ──────────────────────────────
def job_prefix(job_id: str) -> str:
    return f"{STUDIO_PREFIX}/jobs/{job_id}"


def job_doc_key(job_id: str) -> str:
    return f"{job_prefix(job_id)}/job.json"


def status_key(job_id: str) -> str:
    return f"{job_prefix(job_id)}/status.json"


def source_key(job_id: str, ext: str) -> str:
    ext = ext.lstrip(".").lower() or "mp4"
    return f"{job_prefix(job_id)}/source.{ext}"


def output_key(job_id: str, filename: str) -> str:
    return f"{job_prefix(job_id)}/out/{filename}"
