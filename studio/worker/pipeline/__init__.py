"""Pipeline de procesado (calamarsa) — FASE 2.

Salida vertical 1080×1920 (Short/Reel). Operaciones activables por job:
  - remove_silences  (auto-editor)
  - subtitles        (faster-whisper → ASS quemado, ES)
  - chroma           (recorte de fondo verde + composición vertical)

El poller corre en su venv; los pasos pesados (Whisper, auto-editor) se invocan
en el venv dedicado studio/.venv por subproceso, y ffmpeg es del sistema.

Pendiente de fases siguientes: zooms (punch-ins), boxes (presentador+mapa,
Remotion), b-roll. Si se marcan, por ahora se ignoran (se registra en el log).
"""
from __future__ import annotations

import logging
import os

from studio.shared import config as cfg
from studio.shared import schemas, spaces
from . import silences, transcribe, subtitles, compose

log = logging.getLogger("studio.pipeline")


def process(job: dict, set_status) -> list[dict]:
    job_id = job["job_id"]
    ops = job.get("operations", {})
    lang = job.get("language", "es")
    work = os.path.join(cfg.WORK_DIR, job_id)
    os.makedirs(work, exist_ok=True)

    for skipped in ("zooms", "boxes", "broll"):
        if ops.get(skipped):
            log.info("job %s: '%s' marcado pero aún no implementado (se ignora)", job_id, skipped)

    # 1) Descargar origen
    set_status(schemas.STATE_EDITING, 10, "Descargando origen")
    ext = os.path.splitext(job["source_key"])[1].lstrip(".") or "mp4"
    src = os.path.join(work, f"source.{ext}")
    spaces.download(job["source_key"], src)

    # 2) Quitar silencios
    cur = src
    if ops.get("remove_silences"):
        set_status(schemas.STATE_EDITING, 25, "Quitando silencios")
        cur = silences.remove(cur, work)

    # 3) Subtítulos (transcribir → ASS)
    subs_path = None
    if ops.get("subtitles"):
        set_status(schemas.STATE_TRANSCRIBING, 45, "Transcribiendo (ES)")
        segs = transcribe.run(cur, work, lang)
        subs_path = subtitles.build(segs, work)

    # 4) Componer vertical (croma o reencuadre) + quemar subtítulos
    set_status(schemas.STATE_RENDERING, 70, "Componiendo vertical 1080×1920")
    final = compose.vertical(cur, work, chroma=bool(ops.get("chroma")), subs=subs_path)

    # 5) Subir resultado
    set_status(schemas.STATE_RENDERING, 92, "Subiendo resultado")
    out_key = cfg.output_key(job_id, "short.mp4")
    url = spaces.upload_file(final, out_key, public=True, content_type="video/mp4")
    log.info("job %s -> %s", job_id, out_key)
    return [schemas.output("Short vertical 1080×1920", out_key, url, cfg.VERT_W, cfg.VERT_H)]
