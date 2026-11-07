#!/usr/bin/env python3
"""
nhc_check_and_render.py — Autodisparo del render "Vistazo al Trópico" en calamarsa.

Corre por cron cada 5 min. Descarga active_storms.json del CDN, calcula una
firma (id + last_update + intensidad de cada tormenta + áreas de génesis) y,
si cambió respecto a la última vez, lanza render.sh. Como calamarsa no es
alcanzable desde la nube, es ella misma quien vigila y dispara.

- Lock con fcntl (no se solapan renders; si hay uno corriendo, salta).
- El estado SOLO se actualiza tras un render con éxito (returncode 0), así que
  si un boletín entra mientras se renderiza, el siguiente ciclo lo recoge.

Uso:
    python3 nhc_check_and_render.py            # comprueba y renderiza si cambió
    python3 nhc_check_and_render.py --force    # renderiza sí o sí
"""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import signal
import time
import urllib.request

CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
ACTIVE_URL = f"{CDN}/data/tropical/active_storms.json"
RENDER_SH = "/opt/canalmeteo/remotion/huracanes/render.sh"
STATE_FILE = "/opt/canalmeteo/data/render-status/tropico-last-signature.txt"
LOCK_FILE = "/tmp/render-farm.lock"  # compartido entre render farms de calamarsa
RENDER_TIMEOUT = 1800  # 30 min de techo por si algo se cuelga
EX_GPU_OCUPADA = 75    # render.sh no consiguió el lock de GPU en 15 min


def matar_arbol(pid: int) -> int:
    """Mata pid y TODOS sus descendientes (recorriendo ppid): Puppeteer lanza Chrome
    en otro grupo de procesos, así que ni kill() ni killpg() bastan. El 13/09 el
    timeout solo mató el bash y node + 276 Chrome quedaron huérfanos con el lock."""
    out = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True).stdout
    hijos = {}
    for linea in out.splitlines():
        p, pp = (int(x) for x in linea.split())
        hijos.setdefault(pp, []).append(p)
    arbol, pila = [pid], [pid]
    while pila:
        for h in hijos.get(pila.pop(), []):
            arbol.append(h)
            pila.append(h)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in arbol:
            try:
                os.kill(p, sig)
            except ProcessLookupError:
                pass
        time.sleep(10 if sig == signal.SIGTERM else 0)
    return len(arbol)

FORCE = "--force" in sys.argv[1:]


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def log(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


def fetch_active():
    # cache-bust para no leer un edge viejo del CDN
    url = f"{ACTIVE_URL}?ts={int(time.time())}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_json_rel(rel: str):
    """Descarga un GeoJSON del CDN dada su ruta relativa (con cache-bust)."""
    url = f"{CDN}/{str(rel).lstrip('/')}?ts={int(time.time())}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def genesis_features(data: dict):
    """Áreas de génesis (zonas a vigilar). El pipeline las publica como RUTA a un
    GeoJSON, pero podrían venir inline (lista de features). Devuelve siempre la
    lista de features, descargándola si hace falta."""
    g = (data.get("genesis") or {}).get("areas")
    if isinstance(g, list):
        return g
    if isinstance(g, str) and g:
        try:
            return fetch_json_rel(g).get("features", []) or []
        except Exception as e:
            log(f"⚠ No pude leer áreas de génesis ({g}): {e}")
            return []
    return []


def signature(data: dict) -> str:
    storms = data.get("storms", []) or []
    parts = []
    for s in sorted(storms, key=lambda x: str(x.get("id", ""))):
        parts.append(
            f"{s.get('id')}:{s.get('last_update')}:{s.get('intensity_kt')}"
        )
    # Zonas a vigilar: firmamos por contenido sustantivo (cuenca + probabilidad +
    # riesgo de cada área), no por la ruta del fichero —que es constante— para que
    # un cambio de outlook del NHC, aun sin tormentas activas, dispare re-render.
    gids = []
    for f in genesis_features(data):
        gp = f.get("properties", {}) if isinstance(f, dict) else {}
        gids.append(
            f"{gp.get('basin', '')}#{gp.get('objectid', '')}:"
            f"{gp.get('prob2day', '')}/{gp.get('prob7day', '')}:"
            f"{gp.get('risk2day', '')}/{gp.get('risk7day', '')}"
        )
    parts.append("genesis:" + ",".join(sorted(gids)) if gids else "genesis:0")
    raw = "|".join(parts) if parts else "none"
    return f"{len(storms)}storms#" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def read_state() -> str:
    try:
        with open(STATE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def write_state(sig: str) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        f.write(sig)


def main() -> int:
    try:
        data = fetch_active()
    except Exception as e:
        log(f"⚠ No pude leer active_storms.json: {e} — no renderizo.")
        return 0

    sig = signature(data)
    last = read_state()
    n = len(data.get("storms", []) or [])

    if sig == last and not FORCE:
        log(f"Sin cambios ({n} tormenta(s), firma {sig}). Nada que hacer.")
        return 0

    reason = "FORZADO" if FORCE else ("primer arranque" if not last else "boletín nuevo")
    log(f"Cambio detectado [{reason}]: {n} tormenta(s) · {last or '∅'} → {sig}")

    # Lock no bloqueante: si hay un render en curso, salimos (el siguiente ciclo reintenta)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Otro render en curso (lock ocupado). Reintento en el próximo ciclo.")
        return 0

    try:
        log("▶ Lanzando render.sh …")
        proc = subprocess.Popen(["bash", RENDER_SH, "--triggered-by=nhc-auto"])
        try:
            rc = proc.wait(timeout=RENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            n = matar_arbol(proc.pid)
            log(f"✗ render.sh superó el timeout: matados {n} procesos (render + Chrome). "
                "NO actualizo estado.")
            return 1
        if rc == 0:
            write_state(sig)
            log(f"✓ Render OK. Estado actualizado → {sig}")
        elif rc == EX_GPU_OCUPADA:
            log("GPU ocupada >15 min (render.sh desiste). NO actualizo estado; reintento en el próximo ciclo.")
        else:
            log(f"✗ render.sh devolvió {rc}. NO actualizo estado (se reintentará).")
        return rc
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
