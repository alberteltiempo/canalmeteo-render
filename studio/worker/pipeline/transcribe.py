"""Transcripción: lanza asr.py en el venv dedicado y devuelve los segmentos."""
from __future__ import annotations

import json
import logging
import os

from studio.shared import config as cfg
from . import ffmpeg_utils as ff

log = logging.getLogger("studio.pipeline.transcribe")


def run(media: str, workdir: str, lang: str = "es") -> list[dict]:
    out = os.path.join(workdir, "asr.json")
    ff.run([cfg.VENV_PY, cfg.ASR_SCRIPT, media, out, cfg.WHISPER_MODEL, lang or "es"])
    segs = json.load(open(out, encoding="utf-8"))
    log.info("transcripción: %d segmentos", len(segs))
    return segs
