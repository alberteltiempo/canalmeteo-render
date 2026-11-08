#!/usr/bin/env python3
"""
conus_lynx.py — Canal Meteo · mapas CONUS de lynx/conus desde nimbus-03
═══════════════════════════════════════════════════════════════════════════
Sustituye a lynx-hub (11/09/2026), que era la única máquina que generaba
`s3://canalmeteo-public/lynx/conus/*.jpg`. Los consume la web /16
(pages/mapas.php). Cada mapa es un <Still> de Remotion del proyecto
tiempo_CONUS renderizado a 1280×720 JPEG y subido con SU NOMBRE DE SIEMPRE.

Reglas (contrato de Albert, mismas que las cámaras de parques):
  · PUT sobre la misma clave (atómico); nunca borrar+subir.
  · JPEG 1280×720 q85 < 1 MB, --acl public-read, --content-type image/jpeg,
    --cache-control "public, max-age=300".
  · Si el dato no está (p. ej. "hoy" vacío por la tarde), NO se sube: se queda
    la imagen anterior. Nunca un mapa en blanco.

Los 2 mapas tropicales salen del proyecto  (BasinStatus con las areas
de genesis del NHC): son nuestros, no la grafica oficial re-etiquetada.
NO se genera CONUS_Power_Out_State_Percent.jpg: no hay fuente pública fiable
(ODIN solo cubre unas pocas utilities; EIA no publica cortes).

Uso:  conus_lynx.py [--no-upload] [--only CONUS_Maximas_hoy,...] [--out DIR]
Cron sugerido (canalmeteo, nimbus-03): cada hora a :12.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROY_CONUS = Path("/opt/canalmeteo/remotion/tiempo")  # motor único (fase 2, 08/11/2026); stills con prefijo conus-
PROY_TROPICO = Path("/opt/canalmeteo/remotion/huracanes")
VENV_PY = "/opt/canalmeteo/venv/bin/python3"
CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
BUCKET, PREFIX = "canalmeteo-public", "lynx/conus"
AWS = ["--profile", "do-tor1", "--endpoint-url", "https://sfo3.digitaloceanspaces.com"]
GPU_LOCK = "/tmp/canalmeteo-render.lock"      # mismo lock que los render.sh
ESPERA_GPU_S = 300       # espera por el lock de GPU: los renders de video de
                         # :15/:21/:33/:45 la tienen a ratos. Con 900 s una tanda
                         # con la GPU ocupada se pasaba de los 2400 s del cron y
                         # moria a medias; con 300 s el peor caso cabe en la hora
                         # y el mapa que pierde la GPU se reintenta en la siguiente.
TIMEOUT_RENDER_S = 1200  # tope duro del still, SIEMPRE mayor que la espera del lock:
                         # asi el fallo es de UN mapa y no revienta la tanda entera.
                         # 26/09: esta linea vivia DENTRO de un comentario porque una
                         # edicion escribio los saltos de linea como \n literales, y
                         # el render llevaba 66 h cayendose con NameError.

# clave de lynx → (composición Remotion, comprobación de datos)
#   la comprobación devuelve (hay_datos, detalle)
MAPAS = [
    ("CONUS_Maximas_hoy.jpg", "Mockup-tmax-hoy", ("cities", "today")),
    ("CONUS_Minimas_hoy.jpg", "Mockup-tmin-hoy", ("cities", "tmin_today")),
    ("CONUS_SPC_Day_1_Wind.jpg", "Mockup-spc-viento", ("outlook", "spc_wind_d1")),
    ("CONUS_SPC_Day_1_Tornado.jpg", "Mockup-spc-tornado", ("outlook", "spc_torn_d1")),
    ("CONUS_SPC_Day_1_Hail.jpg", "Mockup-spc-granizo", ("outlook", "spc_hail_d1")),
    ("CONUS_CPC_Temps_6_10_Day.jpg", "Mockup-cpc-temp-610", ("outlook", "cpc_temp_610")),
    ("CONUS_CPC_Precip_6_10_Day.jpg", "Mockup-cpc-prcp-610", ("outlook", "cpc_prcp_610")),
    ("CONUS_Airport_Delay.jpg", "Mockup-aeropuertos", ("json", "data/obs/airport_delays.geojson")),
    ("CONUS_Fire_Smoke.jpg", "Mockup-humo", ("json", "data/fires/hms_smoke.json")),
    # Tropicales: proyecto `huracanes` (BasinStatus con las áreas del NHC).
    ("NHC_ATL_Tropical_Outlook_7_Day.jpg", "Mockup-cuenca-atlantico",
     ("json", "data/tropical/active_storms.json")),
    ("NHC_PAC_Tropical_Outlook_7_Day.jpg", "Mockup-cuenca-pacifico",
     ("json", "data/tropical/active_storms.json")),
]
# Mapas que NO salen del proyecto CONUS
PROYECTO_DE = {
    "Mockup-cuenca-atlantico": PROY_TROPICO,
    "Mockup-cuenca-pacifico": PROY_TROPICO,
}
MAX_EDAD_MIN = 24 * 60      # capa más vieja que esto = no se republica


def log(m):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {m}", flush=True)


def baja_json(url, timeout=45):
    req = urllib.request.Request(
        f"{url}?ts={int(time.time())}", headers={"User-Agent": "CanalMeteo-conus/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def hay_datos(check):
    """(bool, detalle). Evita renderizar (y publicar) un mapa vacío."""
    tipo, arg = check
    try:
        if tipo == "cities":
            d = baja_json(f"{CDN}/data/tmax/cities.json")
            n = len(d.get(arg) or [])
            return n > 0, f"{n} ciudades"
        if tipo == "outlook":
            d = baja_json(f"{CDN}/data/outlooks/{arg}/manifest.json")
            fr = d.get("frames") or []
            if not fr:
                return False, "sin frames"
            edad = (time.time() - fr[-1]["timestamp"]) / 60
            return edad <= MAX_EDAD_MIN, f"{d.get('n_areas', '?')} áreas, hace {edad:.0f} min"
        if tipo == "json":
            d = baja_json(f"{CDN}/{arg}")
            if isinstance(d, dict) and "storms" in d:
                # active_storms: vale aunque no haya tormentas (el mapa dice
                # "no hay sistemas activos"); solo se exige que el feed esté vivo.
                return True, f"{len(d.get('storms') or [])} tormenta(s)"
            n = len(d.get("features") or []) if isinstance(d, dict) else len(d or [])
            return n > 0, f"{n} elementos"
    except Exception as e:
        return False, f"{e.__class__.__name__}"
    return True, ""


def render(comp, destino: Path) -> tuple[bool, str]:
    """Still 1920×1080 escalado a 1280×720, esperando el lock de GPU."""
    # 23/09: la espera del lock (-w 900) era MAS LARGA que el timeout del
    # subprocess (600 s). Cuando el render de video de :33 o :45 tenia la GPU,
    # saltaba TimeoutExpired, nadie la recogia y se moria la pasada entera: los
    # mapas que faltaban no se publicaban (2 de cada 3 horas el 23/09). Ahora la
    # espera del lock es mas corta que el timeout y el fallo es de UN mapa.
    cmd = [
        "/usr/bin/flock", "-w", str(ESPERA_GPU_S), GPU_LOCK,
        "npx", "remotion", "still", "src/index.ts",
        (comp if comp in PROYECTO_DE else f"conus-{comp}"), str(destino),
        "--image-format=jpeg", "--jpeg-quality=85", "--scale=0.6667", "--gl=vulkan",
    ]
    try:
        r = subprocess.run(cmd, cwd=PROYECTO_DE.get(comp, PROY_CONUS),
                           capture_output=True, text=True, timeout=TIMEOUT_RENDER_S)
    except subprocess.TimeoutExpired:
        return False, "se paso de %ss (GPU ocupada?)" % TIMEOUT_RENDER_S
    if r.returncode != 0:
        cola = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["sin salida"]
        return False, cola[0][:160]
    if not destino.exists() or destino.stat().st_size < 20_000:
        return False, "salida vacía o diminuta"
    return True, f"{destino.stat().st_size // 1024} KB"


def upload(path: Path, clave: str) -> tuple[bool, str]:
    cmd = ["aws", "s3", "cp", str(path), f"s3://{BUCKET}/{PREFIX}/{clave}", *AWS,
           "--acl", "public-read", "--content-type", "image/jpeg",
           "--cache-control", "public, max-age=300", "--only-show-errors"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.returncode == 0, (r.stderr or "").strip()[:160]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="/opt/canalmeteo/data/temp/conus_lynx")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    ok = saltados = fallos = 0
    for clave, comp, check in MAPAS:
        if only and clave not in only and comp not in only:
            continue
        vale, detalle = hay_datos(check)
        if not vale:
            log(f"⏭  {clave}: sin datos ({detalle}) → se queda la anterior")
            saltados += 1
            continue
        destino = out / clave
        bien, info = render(comp, destino)
        if not bien:
            log(f"✗ {clave}: render falló ({info})")
            fallos += 1
            continue
        if args.no_upload:
            log(f"✓ {clave} ({detalle}) {info} — sin subir")
            ok += 1
            continue
        subido, err = upload(destino, clave)
        log(f"{'✓' if subido else '✗'} {clave} ({detalle}) {info}{'' if subido else ' — ' + err}")
        ok += subido
        fallos += not subido

    log(f"fin CONUS: {ok} publicados, {saltados} saltados, {fallos} fallidos")

    # Estado para el feed_watchdog de nimbus-01 (vigila el productor, no cada mapa:
    # de noche "hoy" se salta a propósito y daría falsas alarmas).
    if not args.no_upload and not only:
        est = out / "estado.json"
        est.write_text(json.dumps({
            "updated": int(time.time()),
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "publicados": ok, "saltados": saltados, "fallos": fallos,
            "total": len(MAPAS), "host": "nimbus-03",
        }, indent=1))
        cmd = ["aws", "s3", "cp", str(est), f"s3://{BUCKET}/{PREFIX}/estado.json", *AWS,
               "--acl", "public-read", "--content-type", "application/json",
               "--cache-control", "public, max-age=60", "--only-show-errors"]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
