#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Worker de vistas previas del editor de escaletas (calamarsa).

La intranet (nimbus-01) deja peticiones en el CDN (data/escaleta/requests/
preview_<slug>_<escena>.json, vía escaleta_push.sh). Este cron las atiende:
renderiza el Still Mockup-* correspondiente (con el lock GLOBAL de GPU para no
pisar los renders de producción) y sube el PNG a
data/escaleta/previews/<slug>/<escena>.png, que la web muestra.

Cron (canalmeteo@calamarsa):
  * * * * * flock -n /tmp/escaleta-preview.lock /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/escaleta_preview_worker.py >> /opt/canalmeteo/logs/escaleta_preview.log 2>&1
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
BUCKET = "s3://canalmeteo-public"
EP = "https://sfo3.digitaloceanspaces.com"
AWS = ["aws", "--profile", "do-tor1", "--endpoint-url", EP]
REMOTION_ROOT = Path("/opt/canalmeteo/remotion")
GPU_LOCK = "/tmp/canalmeteo-render.lock"
MAX_AGE_S = 45 * 60  # margen para tandas de "generar todas" (~1 min por escena)

PROJECT = {
    "tiempo-conus": "tiempo_CONUS", "tiempo-fl": "tiempo_FL", "tiempo-se": "tiempo_SE",
    "tiempo-ne": "tiempo_NE", "tiempo-sp": "tiempo_SP", "tiempo-mw": "tiempo_MW",
    "tiempo-np": "tiempo_NP", "tiempo-nw": "tiempo_NW", "tiempo-sw": "tiempo_SW",
    "tropico": "huracanes",
}
# Regiones ya servidas por el motor único remotion/tiempo (fase 2): el proyecto es
# "tiempo" y los stills llevan el prefijo "<región>-" (sp-Prev-condiciones).
# Añadir aquí el slug al cortar cada región (ver README-RENDER.md).
UNIFIED: set[str] = {"tiempo-sp"}

# Escena → Still (mismo mapa que lib.php de la intranet; mantener en sincronía).
# Desde la fase 7 TODAS las previews salen con datos reales: los Mockup-* los
# reciben por calculateMetadata y los Prev-* renderizan el Segment real con el
# plan reducido a esa escena.
STILL = {
    "condiciones": "Prev-condiciones", "reports": "Mockup-reportes", "uv": "Mockup-uv",
    "aqi": "Mockup-aqi", "aeropuertos": "Mockup-aeropuertos", "spc": "Mockup-spc",
    "drought": "Mockup-sequia", "tmax_today": "Mockup-tmax-hoy", "tvar": "Mockup-tvar-manana",
    "tmax_tomorrow": "Mockup-tmax-manana", "quake": "Mockup-quake", "quake_intro": "Mockup-quake-intro",
    # Escenas sin still propio: preview del Segment real (plan filtrado).
    "open": "Prev-open", "geocolor": "Prev-geocolor", "radar": "Prev-radar",
    # ids de composición sin "_" (Remotion no lo admite): precip va con guion.
    "alerts": "Prev-alerts", "precip_fcst": "Prev-precip-fcst",
    "precip_accum": "Prev-precip-accum", "outro": "Prev-outro",
    # solo CONUS:
    "lightning": "Mockup-rayos", "watches": "Mockup-vigilancias", "hail": "Mockup-granizo",
}

# El trópico tiene su propio juego de escenas (proyecto huracanes).
TROPICO_STILL = {
    s: f"Prev-{s}"
    for s in ("open", "satGlobal", "countIntro", "basinIntro", "stormSat", "stormTrack",
              "investStatus", "stormRain", "basinStatus", "nameList", "outro")
}


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def list_requests() -> list[str]:
    # `aws s3 ls` en vez de s3api: el s3api de aws-cli 2.31 falla con
    # "badly formed help string" contra Spaces.
    r = sh(AWS + ["s3", "ls", f"{BUCKET}/data/escaleta/requests/"])
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        name = line.split()[-1] if line.split() else ""
        if name.endswith(".json"):
            out.append(f"data/escaleta/requests/{name}")
    return out


def delete_request(key: str) -> None:
    sh(AWS + ["s3", "rm", f"{BUCKET}/{key}", "--quiet"])


def main() -> None:
    reqs = list_requests()
    if not reqs:
        return
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    for key in reqs:
        get = sh(AWS + ["s3", "cp", f"{BUCKET}/{key}", "-"])
        try:
            req = json.loads(get.stdout)
        except ValueError:
            print(f"{now} petición ilegible, borro: {key}")
            delete_request(key)
            continue
        slug, scene, ts = req.get("slug"), req.get("scene"), req.get("ts", 0)
        proj = PROJECT.get(slug)
        still = TROPICO_STILL.get(scene) if slug == "tropico" else STILL.get(scene)
        if slug in UNIFIED and still:
            proj = "tiempo"
            still = f"{slug.replace('tiempo-', '')}-{still}"
        if scene in ("lightning", "watches", "hail") and slug != "tiempo-conus":
            still = None
        if not proj or not still:
            print(f"{now} sin still para {slug}/{scene}, borro petición")
            delete_request(key)
            continue
        if time.time() - ts > MAX_AGE_S:
            print(f"{now} petición caducada {slug}/{scene}, borro")
            delete_request(key)
            continue
        # base=true → fondo LIMPIO (mapa + rótulos, sin chips) para el editor
        # visual, que pinta los chips en vivo encima: <escena>-base.png. El flag
        # viaja como input prop del Still (hideChips → RENDER_FLAGS en cdn.ts).
        base = bool(req.get("base"))
        suffix = "-base" if base else ""
        out = Path(f"/tmp/escaleta_prev_{slug}_{scene}{suffix}.png")
        print(f"{now} render preview {slug}/{scene}{suffix} ({still})…")
        cmd = ["flock", GPU_LOCK, "npx", "remotion", "still", still, str(out), "--gl=vulkan"]
        if base:
            cmd += ["--props", json.dumps({"hideChips": True})]
        r = sh(cmd, cwd=REMOTION_ROOT / proj, timeout=420)
        if r.returncode != 0 or not out.exists():
            print(f"{now} FALLO render {slug}/{scene}{suffix}: {r.stderr[-400:]}")
            delete_request(key)  # no reintentar en bucle: que el usuario re-pida
            continue
        up = sh(AWS + ["s3", "cp", str(out), f"{BUCKET}/data/escaleta/previews/{slug}/{scene}{suffix}.png",
                       "--content-type", "image/png", "--acl", "public-read",
                       "--cache-control", "no-cache", "--quiet"])
        print(f"{now} preview {slug}/{scene}{suffix} {'subida' if up.returncode == 0 else 'FALLO al subir'}")
        out.unlink(missing_ok=True)
        delete_request(key)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — cron: nunca dejar el lock roto
        print(f"escaleta_preview_worker: {e}", file=sys.stderr)
        sys.exit(1)
