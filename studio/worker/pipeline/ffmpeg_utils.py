"""Helpers de subproceso para ffmpeg / ffprobe / venv dedicado."""
from __future__ import annotations

import json
import logging
import subprocess

log = logging.getLogger("studio.pipeline.ff")


def run(cmd: list[str], cwd: str | None = None) -> str:
    """Ejecuta un comando; lanza RuntimeError con la cola del log si falla."""
    log.info("RUN %s", " ".join(str(c) for c in cmd))
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        tail = (p.stdout or "")[-2500:]
        raise RuntimeError(f"comando falló ({p.returncode}): {cmd[0]}\n{tail}")
    return p.stdout or ""


def probe_duration(path: str) -> float:
    out = run(["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", path])
    try:
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0
