"""Genera subtítulos ASS en español a partir de los segmentos de Whisper.

Estilo pensado para vertical (1080×1920): texto blanco grande, borde negro,
abanzado abajo-centro para no tapar al presentador.
"""
from __future__ import annotations

import os

from studio.shared import config as cfg

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV
Style: Def,DejaVu Sans,72,&H00FFFFFF,&H00000000,&H64000000,1,5,2,2,80,80,300

[Events]
Format: Layer, Start, End, Style, Text
"""


def _ts(sec: float) -> str:
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec - int(sec)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap(text: str, max_chars: int = 26) -> str:
    """Parte en máx. 2 líneas para que no se salga en vertical."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\\N".join(lines[:2]) if len(lines) <= 2 else "\\N".join([lines[0], " ".join(lines[1:])])


def build(segments: list[dict], workdir: str) -> str:
    path = os.path.join(workdir, "subs.ass")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_ASS_HEADER.format(w=cfg.VERT_W, h=cfg.VERT_H))
        for s in segments:
            txt = _wrap(s["text"].replace("\n", " ").strip())
            if not txt:
                continue
            f.write(f"Dialogue: 0,{_ts(s['start'])},{_ts(s['end'])},Def,,{txt}\n")
    return path
