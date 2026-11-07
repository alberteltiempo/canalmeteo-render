#!/usr/bin/env python3
"""
parques_lynx.py — Canal Meteo · capturas fijas de las 15 cámaras de parques
═══════════════════════════════════════════════════════════════════════════
Sustituye a lynx-hub (apagado 11/09/2026). Desde el 12/09 NO se compone la barra
con PIL: cada captura es un frame del proyecto Remotion `parques-webcams`
(composición `Mockup-camara`), es decir el MISMO look que el vídeo de parques —
foto grande + tarjeta METAR + mini-radar — en español y en inglés.

Contrato (lo consumen la app y /v1/cams — config/cams.json de nimbus-api):
  ES  s3://canalmeteo-public/lynx/parques/<image>           (MISMAS 15 claves)
  EN  s3://canalmeteo-public/lynx/parques/en/<image>        (image_url_en)
  ES  s3://canalmeteo-public/lynx/parques/simple/<image>    (image_url_simple)
  EN  s3://canalmeteo-public/lynx/parques/simple/en/<image> (image_url_simple_en)
  La versión «simple» (app) es foto a pantalla completa + logo + nombre del
  parque y cortesía del NPS: sin panel METAR ni mini-radar.
  PUT directo sobre la clave (atómico; nunca borrar+subir), --acl public-read,
  --content-type image/jpeg, --cache-control "public, max-age=300".
  Webcam negra/congelada/caída o sin METAR → NO se sube (se queda la anterior).

Por qué --frame=180: WebcamSlide se desvanece por frame en los dos extremos
(opacity = enterOpacity(0..15) · exitOpacity(dur-12..dur)); se captura por el
medio de una composición de 360 frames, donde ambas rampas valen 1.

Uso:  parques_lynx.py [--no-upload] [--out DIR] [--only ca_yosemite,hawai]
Cron (canalmeteo, nimbus-03): 6,21,36,51 * * * * con flock.
"""
import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from PIL import Image, ImageStat

PROYECTO = Path("/opt/canalmeteo/remotion/parques-webcams")
COMPOSICION = "Mockup-camara"              # completa: foto + METAR + radar
COMPOSICION_SIMPLE = "Mockup-camara-simple"  # simple (app): foto + nombre + cortesía
FRAME = 180                      # mitad de la diapositiva (ver cabecera)
GPU_LOCK = "/tmp/canalmeteo-render.lock"   # mismo lock que los render.sh
LOTE_JS = PROYECTO / "capturas_parques.js"  # compila 1 vez y reutiliza Chrome

CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
NPS_URL = "https://www.nps.gov/featurecontent/ard/webcams/images/{code}.jpg"
BUCKET, PREFIX = "canalmeteo-public", "lynx/parques"
AWS = ["--profile", "do-tor1", "--endpoint-url", "https://sfo3.digitaloceanspaces.com"]
UA = {"User-Agent": "CanalMeteo-parques/2.0 (+https://canalmeteo.tv)"}

MAX_WEBCAM_AGE_H = 3       # Last-Modified de la foto en el CDN más viejo → congelada
MAX_METAR_AGE_MIN = 150

# id de cams.json → (clave de imagen, código NPS/Remotion)
PARQUES = [
    ("ak_denali", "Camera_Parque_AK_Denali.jpg", "dena"),
    ("az_grand_canyon", "Camera_Parque_AZ_Grand_Canyon.jpg", "grca"),
    ("ca_joshua_tree", "Camera_Parque_CA_Joshua_Tree.jpg", "jotr"),
    ("ca_sequoia", "Camera_Parque_CA_Sequoia.jpg", "seki"),
    ("ca_yosemite", "Camera_Parque_CA_Yosemite.jpg", "yose"),
    ("dc_washington", "Camera_Parque_DC_Washington.jpg", "wash"),
    ("hawai", "Camera_Parque_Hawai.jpg", "havo"),
    ("me_acadia", "Camera_Parque_ME_Acadia.jpg", "acad"),
    ("nd_theodore_roosevelt", "Camera_Parque_ND_Theodore_Roosevelt.jpg", "thro"),
    ("tn_great_smoky", "Camera_Parque_TN_Great_Smoky.jpg", "grsm"),
    ("tx_big_bend", "Camera_Parque_TX_Big_Bend.jpg", "bibe"),
    ("va_shenandoah", "Camera_Parque_VA_Shenandoah.jpg", "shen"),
    ("wa_mount_rainier", "Camera_Parque_WA_Mount_Rainier.jpg", "mora"),
    ("wy_dinosaur", "Camera_Parque_WY_Dinosaur.jpg", "dino"),
    ("wy_grand_teton", "Camera_Parque_WY_Grand_Teton.jpg", "grte"),
]

_metar_cache: dict | None = None


def log(msg):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# ── comprobaciones previas (no renderizar lo que no se puede publicar) ─────
def foto_utilizable(code: str) -> tuple[bool, str]:
    """La diapositiva pinta data/webcams/<code>/latest.jpg del CDN (la sube el
    scraper). Se comprueba aquí: negra, congelada o ausente → no se renderiza."""
    url = f"{CDN}/data/webcams/{code}/latest.jpg"
    try:
        r = requests.get(url, headers=UA, timeout=60)
    except requests.RequestException as e:
        return False, f"red: {e.__class__.__name__}"
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        return False, f"http {r.status_code}"
    lm = r.headers.get("Last-Modified")
    if lm and time.time() - parsedate_to_datetime(lm).timestamp() > MAX_WEBCAM_AGE_H * 3600:
        return False, f"congelada ({lm})"
    try:
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return False, "no decodifica"
    st = ImageStat.Stat(im.resize((160, 90)).convert("L"))
    if st.mean[0] < 15 or st.stddev[0] < 8:
        return False, f"negra/vacía (media {st.mean[0]:.0f}, std {st.stddev[0]:.0f})"
    return True, f"{im.width}×{im.height} sha {hashlib.sha1(r.content).hexdigest()[:8]}"


def metar_fresco(code: str, estaciones: dict) -> tuple[bool, str]:
    """El catálogo de Remotion manda: se comprueba la estación de ESA cámara."""
    est = estaciones.get(code)
    if not est:
        return False, "cámara fuera del catálogo"
    global _metar_cache
    if _metar_cache is None:
        try:
            r = requests.get(f"{CDN}/data/metar/surface_obs.geojson",
                             params={"ts": int(time.time())}, headers=UA, timeout=60)
            r.raise_for_status()
            _metar_cache = {
                f["properties"]["id"]: f["properties"]
                for f in r.json().get("features", [])
                if f.get("properties", {}).get("id")
            }
        except Exception as e:
            return False, f"METAR: {e.__class__.__name__}"
    p = _metar_cache.get(est)
    if not p or p.get("tempF") is None:
        return False, f"sin METAR en {est}"
    if (p.get("obsAge") or 9999) > MAX_METAR_AGE_MIN:
        return False, f"{est} rancio ({p.get('obsAge')} min)"
    return True, f"{est} {round(p['tempF'])}°F"


def catalogo_estaciones() -> dict:
    """code → id de estación, leído del catálogo del proyecto (fuente única)."""
    sys.path.insert(0, "/opt/canalmeteo/scripts")
    from nps_webcams_config import NPS_WEBCAMS
    return {c["code"]: c["metar"]["id"] for c in NPS_WEBCAMS}


# ── render + subida ────────────────────────────────────────────────────────
def render_lote(trabajos: list[dict]) -> dict:
    """Renderiza TODAS las capturas del ciclo en un solo proceso.

    Devuelve {ruta: (ok, detalle)}. Una sola compilación de webpack y un solo
    Chrome para las ~60 imágenes: antes cada `remotion still` recompilaba el
    proyecto entero (~6 s de los ~7 s de cada captura).
    """
    if not trabajos:
        return {}
    # Se borra el destino antes del lote: si el renderizador falla, que NO quede
    # el fichero del ciclo anterior haciéndose pasar por captura nueva.
    for t in trabajos:
        Path(t["out"]).unlink(missing_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(trabajos, fh)
        ruta_json = fh.name
    cmd = ["/usr/bin/flock", "-w", "900", GPU_LOCK, "node", str(LOTE_JS), ruta_json]
    try:
        r = subprocess.run(cmd, cwd=PROYECTO, capture_output=True, text=True, timeout=3600)
    finally:
        Path(ruta_json).unlink(missing_ok=True)

    for linea in (r.stderr or "").splitlines():
        if linea.startswith("[capturas]"):
            log(f"  {linea}")

    salida = {}
    if r.returncode == 2 or not (r.stdout or "").strip():
        motivo = next((l for l in (r.stderr or "").splitlines() if "ERROR" in l), "")
        log(f"✗ el lote no llegó a renderizar: {motivo[:160] or 'sin salida'}")
        return {t["out"]: (False, "lote abortado") for t in trabajos}
    for linea in (r.stdout or "").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        destino = Path(d["out"])
        if not d.get("ok"):
            salida[d["out"]] = (False, d.get("error", "error")[:150])
        elif not destino.exists() or destino.stat().st_size < 40_000:
            # < 40 KB = frame casi vacío (pasó al capturar el frame 0, con la
            # diapositiva aún transparente): mejor no publicarlo.
            tam = destino.stat().st_size if destino.exists() else 0
            salida[d["out"]] = (False, f"salida sospechosa ({tam} B)")
        else:
            salida[d["out"]] = (True, f"{destino.stat().st_size // 1024} KB")
    return salida


def upload(path: Path, key: str, ctype="image/jpeg", cache="public, max-age=300"):
    cmd = ["aws", "s3", "cp", str(path), f"s3://{BUCKET}/{key}", *AWS, "--acl", "public-read",
           "--content-type", ctype, "--cache-control", cache, "--only-show-errors"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.returncode == 0, (r.stderr or "").strip()[:160]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--out", default="/opt/canalmeteo/data/temp/parques_lynx")
    ap.add_argument("--only", default="")
    ap.add_argument("--incluso-oscuras", action="store_true",
                    help="renderiza tambien las webcams oscuras (solo para sembrar claves nuevas)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    estaciones = catalogo_estaciones()
    ok = saltados = fallos = 0

    # 1) Decidir qué se puede publicar (sin tocar la GPU todavía)
    trabajos, plan = [], []
    for pid, clave, code in PARQUES:
        if only and pid not in only and code not in only:
            continue
        vale, detalle = foto_utilizable(code)
        if not vale and args.incluso_oscuras and "negra" in detalle:
            log(f"⚠  {pid} ({code}): {detalle} — se renderiza igual (--incluso-oscuras)")
            vale = True
        if not vale:
            log(f"⏭  {pid} ({code}): {detalle} → se queda la anterior")
            saltados += 1
            continue
        hay_metar, det_metar = metar_fresco(code, estaciones)
        if not hay_metar:
            log(f"⏭  {pid} ({code}): {det_metar} → se queda la anterior")
            saltados += 1
            continue

        salidas = (
            (COMPOSICION, "es", f"{PREFIX}/{clave}", clave),
            (COMPOSICION, "en", f"{PREFIX}/en/{clave}", f"en_{clave}"),
            (COMPOSICION_SIMPLE, "es", f"{PREFIX}/simple/{clave}", f"simple_{clave}"),
            (COMPOSICION_SIMPLE, "en", f"{PREFIX}/simple/en/{clave}", f"simple_en_{clave}"),
        )
        for comp, lang, key, nombre in salidas:
            f = out / nombre
            trabajos.append({"code": code, "lang": lang, "comp": comp, "out": str(f)})
            plan.append((pid, code, detalle, det_metar, comp, lang, key, f))

    # 2) Un solo proceso para todas las capturas (una compilación, un Chrome)
    log(f"▶ {len(trabajos)} capturas en un solo proceso…")
    hechas = render_lote(trabajos)

    # 3) Subir lo que haya salido bien
    por_parque: dict[str, list[str]] = {}
    cabecera: dict[str, str] = {}
    for pid, code, detalle, det_metar, comp, lang, key, f in plan:
        etiqueta = lang if comp == COMPOSICION else f"{lang}·simple"
        cabecera[pid] = f"{code} {detalle}; {det_metar}"
        bien, info = hechas.get(str(f), (False, "sin resultado"))
        if not bien:
            log(f"✗ {pid} ({code}) {etiqueta}: render falló ({info})")
            fallos += 1
            por_parque.setdefault(pid, []).append(f"{etiqueta} FALLO")
            continue
        if args.no_upload:
            por_parque.setdefault(pid, []).append(f"{etiqueta} {info}")
            continue
        subido, err = upload(f, key)
        por_parque.setdefault(pid, []).append(f"{etiqueta} {'OK' if subido else 'FALLO ' + err}")
        fallos += not subido

    for pid, res in por_parque.items():
        if all("FALLO" not in x for x in res):
            ok += 1
        log(f"✓ {pid} ({cabecera[pid]}) → {', '.join(res)}")

    log(f"fin: {ok} publicados, {saltados} saltados, {fallos} fallos")

    # Estado para el feed_watchdog de nimbus-01 (vigila el productor, no cada
    # foto: de noche se saltan a propósito y daría falsas alarmas).
    if not args.no_upload and not only:
        est = out / "estado.json"
        est.write_text(json.dumps({
            "updated": int(time.time()),
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "generados": ok, "saltados": saltados, "fallos": fallos,
            "total": len(PARQUES), "host": "nimbus-03", "look": "remotion",
            "variantes": ["es", "en", "simple", "simple/en"],
        }, indent=1))
        good, err = upload(est, f"{PREFIX}/estado.json", "application/json", "public, max-age=60")
        if not good:
            log(f"⚠ estado.json no subido: {err}")

    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
