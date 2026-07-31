"""Composición vertical 1080×1920 con ffmpeg.

- chroma=True: recorta al presentador del fondo verde (chromakey+despill) y lo
  compone sobre un fondo vertical (imagen de marca o color generado).
- chroma=False: reencuadre con fondo difuminado del propio vídeo.
En ambos casos quema los subtítulos ASS si se pasan.
"""
from __future__ import annotations

import os

from studio.shared import config as cfg
from . import ffmpeg_utils as ff


def _subs_filter(subs: str | None) -> str:
    # Se ejecuta ffmpeg con cwd=workdir, así referenciamos el .ass por nombre.
    return f",subtitles={os.path.basename(subs)}" if subs else ""


def vertical(in_path: str, workdir: str, chroma: bool, subs: str | None = None) -> str:
    out = os.path.join(workdir, "short.mp4")
    W, H = cfg.VERT_W, cfg.VERT_H
    inputs = ["-i", in_path]

    if chroma:
        # Fondo: imagen de marca si existe, si no un color sólido generado.
        if cfg.VERTICAL_BG and os.path.exists(cfg.VERTICAL_BG):
            inputs += ["-loop", "1", "-i", cfg.VERTICAL_BG]
            bg = f"[1:v]scale={W}:{H},setsar=1[bg];"
        else:
            inputs += ["-f", "lavfi", "-i", f"color=c={cfg.BG_COLOR}:s={W}x{H}:r=25"]
            bg = "[1:v]setsar=1[bg];"
        fc = (
            f"{bg}"
            f"[0:v]chromakey={cfg.CHROMA_COLOR}:{cfg.CHROMA_SIMILARITY}:{cfg.CHROMA_BLEND},"
            f"despill[ck];"
            f"[ck]scale={W}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[c];"
            f"[c]format=yuv420p{_subs_filter(subs)}[v]"
        )
    else:
        fc = (
            f"[0:v]split[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:3[bg];"
            f"[b]scale={W}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[c];"
            f"[c]format=yuv420p{_subs_filter(subs)}[v]"
        )

    cmd = (
        ["ffmpeg", "-y", *inputs,
         "-filter_complex", fc,
         "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         "-shortest", out]
    )
    ff.run(cmd, cwd=workdir)
    return out
