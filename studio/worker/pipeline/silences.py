"""Quitar silencios con auto-editor (venv dedicado, vía CLI)."""
from __future__ import annotations

import logging
import os

from studio.shared import config as cfg
from . import ffmpeg_utils as ff

log = logging.getLogger("studio.pipeline.silences")


def remove(in_path: str, workdir: str) -> str:
    """Devuelve la ruta del vídeo sin silencios. Best-effort: si auto-editor falla
    (p. ej. 'timeline vacío' cuando no detecta habla), sigue con el original."""
    out = os.path.join(workdir, "cut.mp4")
    try:
        ff.run([cfg.AUTO_EDITOR, in_path,
                "--edit", f"audio:threshold={cfg.SILENCE_THRESHOLD}",
                "--margin", "0.2s", "--no-open", "--output", out])
    except RuntimeError as e:
        last = (str(e).strip().splitlines() or ["?"])[-1]
        log.warning("auto-editor no recortó (%s); sigo con el original", last)
        return in_path
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    log.warning("auto-editor no produjo salida; uso el original")
    return in_path
