"""Contrato job.json / status.json — la única "interfaz" entre nimbus y calamarsa.

nimbus escribe job.json (qué hay que hacer). calamarsa escribe status.json
(por dónde va y dónde están los resultados). Ninguna otra conexión directa.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# Operaciones del checklist de la web. En Fase 1 el worker las ignora;
# se cablean en fases posteriores.
DEFAULT_OPERATIONS = {
    "chroma": False,         # sustituir fondo croma
    "remove_silences": True,  # quitar silencios / muletillas (auto-editor)
    "zooms": False,           # punch-ins / Ken Burns
    "subtitles": True,        # subtítulos ES quemados (desde guion + alineación)
    "boxes": False,           # presentador + mapa (Remotion)
    "broll": False,           # insertar gráficos Envato / mapas
}

# Estados de procesado (los escribe calamarsa en status.json).
STATE_PENDING = "pending"
STATE_CLAIMED = "claimed"
STATE_TRANSCRIBING = "transcribing"
STATE_EDITING = "editing"
STATE_RENDERING = "rendering"
STATE_DONE = "done"
STATE_ERROR = "error"

TERMINAL_STATES = {STATE_DONE, STATE_ERROR}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_doc(
    job_id: str,
    source_key: str,
    source_filename: str,
    script_text: str,
    operations: dict,
    language: str = "es",
) -> dict:
    ops = {**DEFAULT_OPERATIONS, **(operations or {})}
    return {
        "job_id": job_id,
        "created_at": now_iso(),
        "language": language,
        "source_key": source_key,
        "source_filename": source_filename,
        "script_text": script_text or "",
        "operations": ops,
    }


def new_status_doc(job_id: str, state: str = STATE_PENDING, message: str = "En cola") -> dict:
    return {
        "job_id": job_id,
        "state": state,
        "progress": 0,
        "message": message,
        "updated_at": now_iso(),
        "outputs": [],   # [{"label","key","url","width","height"}]
        "error": None,
    }


def output(label: str, key: str, url: str, width: int = 0, height: int = 0) -> dict:
    return {"label": label, "key": key, "url": url, "width": width, "height": height}
