#!/usr/bin/env python3
"""
nhc_outlook.py — Canal Meteo · outlooks tropicales de 7 días (Atlántico y Pacífico)
═══════════════════════════════════════════════════════════════════════════════
Sustituye a los NHC_{ATL,PAC}_Tropical_Outlook_7_Day.jpg de lynx-hub (11/09/2026).
La gráfica es la oficial del NHC (dominio público, se cita la fuente): se recorta
a 16:9, se escala a 1280×720 y se le pone la barra de Canal Meteo, igual que el
resto de mapas. No se re-dibuja nada del contenido meteorológico.

Uso:  nhc_outlook.py [--no-upload] [--out DIR]
Lo llama scripts/conus_lynx.py; se puede correr suelto para probar.
"""
import argparse
import io
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path("/opt/canalmeteo/scripts/parques_lynx_assets")   # Montserrat (OFL)
FONT = ASSETS / "Montserrat-VF.ttf"
BUCKET, PREFIX = "canalmeteo-public", "lynx/conus"
AWS = ["--profile", "do-tor1", "--endpoint-url", "https://sfo3.digitaloceanspaces.com"]
UA = {"User-Agent": "CanalMeteo-conus/1.0 (+https://canalmeteo.tv)"}

CUENCAS = [
    ("atl", "NHC_ATL_Tropical_Outlook_7_Day.jpg", "TRÓPICO ATLÁNTICO", "PRÓXIMOS 7 DÍAS"),
    ("pac", "NHC_PAC_Tropical_Outlook_7_Day.jpg", "TRÓPICO PACÍFICO", "PRÓXIMOS 7 DÍAS"),
]
URL = "https://www.nhc.noaa.gov/xgtwo/two_{b}_7d0.png"

W, H = 1280, 720
BAR_H, BAR_X, BAR_Y = 58, 300, 112   # a la derecha del rótulo del NHC, bajo su cabecera
AZUL, CLARO, NARANJA = (31, 69, 88), (201, 214, 223), (243, 156, 18)


def log(m):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {m}", flush=True)


def fuente(size, weight):
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_name(weight)
    return f


def componer(src: Image.Image, topic: str, sub: str) -> Image.Image:
    # 16:9 centrado (las gráficas del NHC son 4:3 o 3:2) y escala a 1280×720
    w, h = src.size
    if w / h > 16 / 9:
        nw = round(h * 16 / 9)
        src = src.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = round(w * 9 / 16)
        top = 0   # sin recorte superior: la cabecera y el rótulo del NHC van pegados al borde
        src = src.crop((0, top, w, top + nh))
    im = src.convert("RGB").resize((W, H), Image.LANCZOS)

    dr = ImageDraw.Draw(im, "RGBA")
    f_topic, f_sub = fuente(26, "Bold"), fuente(18, "SemiBold")
    tw = dr.textlength(topic, font=f_topic)
    sw = dr.textlength(sub, font=f_sub)
    ancho_t, ancho_s = int(tw) + 44, int(sw) + 40
    # Barra: bloque naranja con el tema + bloque azul con el subtítulo
    dr.rounded_rectangle((BAR_X, BAR_Y, BAR_X + ancho_t, BAR_Y + BAR_H), 12, fill=NARANJA)
    dr.rounded_rectangle(
        (BAR_X + ancho_t + 8, BAR_Y, BAR_X + ancho_t + 8 + ancho_s, BAR_Y + BAR_H), 12, fill=AZUL
    )
    dr.text((BAR_X + 22, BAR_Y + BAR_H / 2), topic, font=f_topic, fill=(255, 255, 255), anchor="lm")
    dr.text(
        (BAR_X + ancho_t + 28, BAR_Y + BAR_H / 2), sub, font=f_sub, fill=CLARO, anchor="lm"
    )
    # Crédito de la fuente, abajo a la derecha
    f_cr = fuente(13, "Medium")
    dr.text((W - 16, H - 14), "Fuente: NOAA/NHC", font=f_cr, fill=(255, 255, 255, 200), anchor="rs")
    return im


def jpeg(im: Image.Image) -> bytes:
    for q in (85, 80, 75):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() < 1_000_000:
            return buf.getvalue()
    return buf.getvalue()


def upload(path: Path, key: str) -> tuple[bool, str]:
    cmd = ["aws", "s3", "cp", str(path), f"s3://{BUCKET}/{key}", *AWS, "--acl", "public-read",
           "--content-type", "image/jpeg", "--cache-control", "public, max-age=300",
           "--only-show-errors"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode == 0, (r.stderr or "").strip()[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--out", default="/opt/canalmeteo/data/temp/conus_lynx")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ok = fail = 0
    for cuenca, clave, topic, sub in CUENCAS:
        try:
            r = requests.get(URL.format(b=cuenca), headers=UA, timeout=60)
            r.raise_for_status()
            src = Image.open(io.BytesIO(r.content))
        except Exception as e:
            log(f"⏭  {cuenca}: no se pudo bajar ({e.__class__.__name__}) → se queda la anterior")
            fail += 1
            continue
        f = out / clave
        f.write_bytes(jpeg(componer(src, topic, sub)))
        if args.no_upload:
            log(f"✓ {clave} {f.stat().st_size // 1024} KB (sin subir)")
            ok += 1
            continue
        good, err = upload(f, f"{PREFIX}/{clave}")
        log(f"{'✓' if good else '✗'} {clave} {f.stat().st_size // 1024} KB {'OK' if good else err}")
        ok += good
        fail += not good
    log(f"fin NHC: {ok} ok, {fail} fallidos")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
