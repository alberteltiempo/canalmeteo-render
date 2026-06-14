#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tornado_broadcast.py D8.6 — fetch + normalize + render + capture + upload + email + cleanup"""

import argparse, base64, hashlib, json, logging, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR    = Path(__file__).resolve().parent
TPL_DIR     = BASE_DIR / "templates"
WEB_DIR     = BASE_DIR / "web"
LOG_DIR     = Path("/var/log/canalmeteo")
AUDIT_LOG   = LOG_DIR / "tornado_broadcast.audit.jsonl"

WARNINGS_URL = "https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/tornado-warnings.json"
ALERTAS_URL  = "https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/alertas/alertas_nws.json"
LOGO_URL     = "https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png"
MAPBOX_TOKEN = "pk.eyJ1IjoiYWxiZXJ0ZWx0aWVtcG8iLCJhIjoiY21rM2pqa29zMGd6NjNncHdlMWZ1NTNlayJ9.0d2lAZ-CmqEuoPe_h2JEHA"

REQUEST_TIMEOUT = 15
USER_AGENT      = "CanalMeteo-TornadoBroadcast/1.0 (contacto@canalmeteo.tv)"

# ═══ Spaces / CDN ═══
SPACES_PROFILE  = "do-tor1"
SPACES_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
SPACES_BUCKET   = "canalmeteo-public"
SPACES_PREFIX   = "alertas/tornados-broadcast"
CDN_BASE        = "https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com"

# State + Email
STATE_FILE      = BASE_DIR / "state.json"
MAX_EMAIL_ATTACHMENTS = 5

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    sg_env = BASE_DIR / "sendgrid.env"
    if sg_env.exists():
        load_dotenv(sg_env)
except ImportError:
    pass

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
FROM_EMAIL       = os.getenv("FROM_EMAIL", "").strip()
TO_EMAILS        = [e.strip() for e in os.getenv("TO_EMAILS", "").split(",") if e.strip()]

PALETTE = {
    "warning": {"bg_dark":"#8B0000","bg_mid":"#FF0000","accent":"#FF0000","accent_text":"#FF6666","icon_grad":"linear-gradient(135deg,#FF0000 0%,#B30000 100%)","icon_shadow":"rgba(255,0,0,.55)","icon_svg_color":"#fff","poly_color":"#FF0000","poly_glow":"#FF3333"},
    "watch": {"bg_dark":"#713f12","bg_mid":"#a16207","accent":"#facc15","accent_text":"#fde047","icon_grad":"linear-gradient(135deg,#facc15 0%,#ca8a04 100%)","icon_shadow":"rgba(250,204,21,.55)","icon_svg_color":"#422006","poly_color":"#facc15","poly_glow":"#fde047","emoji_bg_grad":"linear-gradient(135deg,#facc15 0%,#ca8a04 100%)","accent_shadow":"rgba(250,204,21,.6)"},
    "emergency": {"bg_dark":"#7B0078","bg_mid":"#FF00FF","accent":"#FF00FF","accent_text":"#FF66FF","icon_grad":"linear-gradient(135deg,#FF00FF 0%,#B300B3 100%)","icon_shadow":"rgba(255,0,255,.55)","icon_svg_color":"#fff","poly_color":"#FF00FF","poly_glow":"#FF66FF"},
}

RECS_WARNING = [
    "Busca refugio ya en tu sitio seguro, habitación céntrica y lejos de puertas y ventanas.",
]
RECS_EMERGENCY = [
    "PELIGRO EXTREMO. Tornado destructivo en tierra. Refúgiese de inmediato.",
    "Diríjase a un sótano o al nivel más bajo del edificio.",
    "Si no hay sótano, una habitación interior pequeña y sin ventanas.",
]
RECS_WATCH = [
    {"emoji":"📡","title":"Manténgase informado","desc":"Atento a las actualizaciones del NWS y al radar local. Active alertas en su teléfono."},
    {"emoji":"🚪","title":"Plan de refugio listo","desc":"Sepa exactamente a dónde ir si se emite un aviso por tornado."},
    {"emoji":"🔒","title":"Asegure objetos exteriores","desc":"Muebles, basura, decoración: lo que pueda volar con el viento."},
    {"emoji":"🛡️","title":"Identifique su lugar más seguro","desc":"Sótano o habitación interior sin ventanas en la planta baja."},
]

ORIGIN_TRANSLATIONS = {
    "radar indicated":"Indicado por radar","radar":"Indicado por radar","observed":"Observado",
    "spotter":"Avistado por observador","trained spotter":"Avistado por observador entrenado",
    "law enforcement":"Reportado por policía","emergency management":"Reportado por emergencias",
    "public":"Avistado por la ciudadanía","amateur radio":"Reportado por radioaficionado",
    "spc":"Storm Prediction Center",
}

US_STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado",
    "CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho",
    "IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana",
    "ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota",
    "MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada",
    "NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina",
    "ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania",
    "RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas",
    "UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia",
    "WI":"Wisconsin","WY":"Wyoming","DC":"Washington DC",
}

log = logging.getLogger("tornado_broadcast")

def setup_logging(verbose=False):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

def audit(event, **fields):
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("audit log error: %s", e)

def make_alert_id(raw_id):
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:10]

def classify_warning(event):
    return "emergency" if "emergency" in (event or "").lower() else "warning"

def fetch_json(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()

def format_population(n):
    """Formatea entero con separador de miles '.' estilo español."""
    if n is None: return "—"
    try:
        return f"{int(n):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(n)

def extract_tz_from_headline(headline):
    if not headline: return ""
    m = re.search(r'\b([CMPEAH][DS]T)\b', headline)
    return m.group(1) if m else ""

def format_time_pretty(iso_str, tz_hint=""):
    if not iso_str: return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        time_str = dt.strftime("%I:%M %p").lstrip("0")
        if tz_hint: return f"{time_str} {tz_hint}"
        offset = dt.utcoffset()
        if offset is None: return time_str
        h = int(offset.total_seconds() // 3600)
        tz_map = {-4:"EDT",-5:"CDT",-6:"MDT",-7:"PDT",-8:"AKDT",-10:"HST"}
        return f"{time_str} {tz_map.get(h, f'UTC{h:+d}')}"
    except Exception:
        return iso_str

def translate_origin(source):
    if not source: return "—"
    return ORIGIN_TRANSLATIONS.get(source.lower().strip(), source.capitalize())

def extract_polygon_coords(geom):
    if not geom or not isinstance(geom, dict): return None
    t = geom.get("type"); coords = geom.get("coordinates")
    if not coords: return None
    if t == "Polygon":
        return coords[0] if len(coords) > 0 else None
    if t == "MultiPolygon":
        if len(coords) > 0 and len(coords[0]) > 0:
            return coords[0][0]
    return None

def calc_max_zoom(poly, kind):
    if not poly: return 8
    lons = [c[0] for c in poly]; lats = [c[1] for c in poly]
    span = max(max(lons)-min(lons), max(lats)-min(lats))
    if kind == "watch":
        if span > 6: return 5
        if span > 4: return 6
        if span > 2: return 7
        return 8
    if span > 0.6: return 9
    return 10

def fetch_warnings():
    try:
        data = fetch_json(WARNINGS_URL)
    except Exception as e:
        log.error("Error warnings JSON: %s", e); audit("fetch_error", source="warnings", error=str(e))
        return []
    items = data.get("warnings", [])
    log.info("Warnings JSON: %d items, updated=%s", len(items), data.get("updated"))
    out = []
    for w in items:
        try:
            raw_id = w.get("id") or w.get("nws_id") or ""
            if not raw_id: continue
            out.append({
                "id": make_alert_id(raw_id), "raw_id": raw_id,
                "kind": classify_warning(w.get("event","")),
                "event": w.get("event",""), "areaDesc": w.get("areaDesc",""),
                "counties": w.get("counties", []), "state": w.get("state",""),
                "polygon": w.get("polygon"), "expires": w.get("expires"),
                "sent": w.get("sent"), "sender": w.get("sender"),
                "description": w.get("description",""), "instruction": w.get("instruction",""),
                "population": w.get("population"), "source": w.get("source",""),
                "headline": w.get("headline",""),
            })
        except Exception as e:
            log.warning("Error normalizando %s: %s", w.get("areaDesc"), e)
    return out

def fetch_watches():
    try:
        data = fetch_json(ALERTAS_URL)
    except Exception as e:
        log.error("Error alertas_nws: %s", e); audit("fetch_error", source="alertas_nws", error=str(e))
        return []
    candidates = data.get("alertas", []) if isinstance(data, dict) else []
    conteos = data.get("conteos", {}) if isinstance(data, dict) else {}
    log.info("Alertas NWS JSON: %d items | conteos=%s", len(candidates), conteos)
    out = []
    for w in candidates:
        if not isinstance(w, dict): continue
        if (w.get("evento") or "").strip().lower() != "tornado watch": continue
        raw_id = w.get("id") or ""
        if not raw_id: continue
        counties_str = w.get("condados") or ""
        counties = [c.strip() for c in counties_str.split(",") if c.strip()]
        # Filtrar el sufijo agregado "(+N más)" o "(+N zonas más)" que añade alertas_nws.py
        import re as _re
        counties = [_re.sub(r"\s*\(\+\d+\s*(zonas\s+)?m\u00e1s\)\s*$", "", c).strip() for c in counties]
        counties = [c for c in counties if c and not _re.match(r"^\+?\d+\s+(zonas\s+)?m\u00e1s$", c)]
        out.append({
            "id": make_alert_id(raw_id), "raw_id": raw_id, "kind": "watch",
            "event": w.get("evento"), "event_es": w.get("evento_es"),
            "areaDesc": w.get("area_desc",""), "counties": counties,
            "state": w.get("estado",""), "state_name": w.get("estado_nombre",""),
            "area_count": w.get("area_count"), "polygon": w.get("geometry"),
            "expires": w.get("expires"), "sent": w.get("effective"),
            "headline": w.get("headline",""), "description": w.get("description",""),
            "instruction": w.get("instruction",""), "population": w.get("poblacion"),
            "severity": w.get("severity"),
        })
    return out

def setup_jinja():
    return Environment(loader=FileSystemLoader(str(TPL_DIR)),
        autoescape=select_autoescape(['html', 'xml']), trim_blocks=False, lstrip_blocks=False)

def normalized_counties_for_warning(w):
    c = w.get("counties")
    if isinstance(c, list): return c
    if isinstance(c, str): return [x.strip() for x in c.split(",") if x.strip()]
    return []

def states_in_area_desc(area_desc):
    states = []
    for chunk in area_desc.split(";"):
        parts = chunk.split(",")
        if len(parts) >= 2:
            code = parts[-1].strip().upper()[:2]
            if code in US_STATE_NAMES and code not in states:
                states.append(code)
    return states

def build_state_pill(alert):
    state = alert.get("state", "")
    state_name = alert.get("state_name") or US_STATE_NAMES.get(state, state)
    if alert["kind"] == "watch":
        states_in = states_in_area_desc(alert.get("areaDesc",""))
        if len(states_in) > 1:
            return "Tornado Watch · " + " · ".join(states_in)
        if state: return f"{state} · {state_name}"
        return "Tornado Watch"
    if state: return f"{state} · {state_name}"
    return "Aviso oficial"

def build_head_counties(alert):
    area_desc = alert.get("areaDesc","")
    if alert["kind"] == "watch":
        count = alert.get("area_count") or len(alert.get("counties", []))
        states_in = states_in_area_desc(area_desc)
        if count and states_in:
            return f"{count} condados · " + " · ".join(states_in[:4])
        if count: return f"{count} condados"
        return area_desc[:80]
    return area_desc.replace(";", " ·")

def build_subtitle(alert):
    tz = extract_tz_from_headline(alert.get("headline",""))
    when = format_time_pretty(alert.get("expires",""), tz_hint=tz)
    return f"Vigente hasta las {when}" if when else "Vigente"

def alert_to_ctx_map(alert):
    kind = alert["kind"]; pal = PALETTE[kind]
    poly_ring = extract_polygon_coords(alert.get("polygon"))
    if not poly_ring or len(poly_ring) < 4:
        log.warning("Alerta %s sin polígono válido (kind=%s)", alert["id"], kind)
        return None

    if kind == "warning":
        title_html="Aviso por<br>Tornado"; title_label="Aviso por tornado"
        title_size="110px"; include_recs=True
        recs_title="Recomendaciones · Busque refugio"; recs=RECS_WARNING
    elif kind == "emergency":
        title_html="Emergencia por<br>Tornado"; title_label="Emergencia por tornado"
        title_size="90px"; include_recs=True
        recs_title="¡PELIGRO EXTREMO! · Refúgiese ahora"; recs=RECS_EMERGENCY
    else:
        title_html="Vigilancia por<br>Tornado"; title_label="Vigilancia por tornado"
        title_size="90px"; include_recs=False; recs_title=""; recs=[]

    if kind == "watch":
        counties_pills = (alert.get("counties") or [])[:8]
        origin = "Storm Prediction Center"
        issued_by = alert.get("sender") or "NWS / SPC Norman, OK"
    else:
        counties_pills = normalized_counties_for_warning(alert)[:8]
        origin = translate_origin(alert.get("source",""))
        issued_by = alert.get("sender") or "NWS"

    return {
        "logo_url": LOGO_URL, "mapbox_token": MAPBOX_TOKEN, **pal,
        "event_label_lower": title_label, "event_label_upper_html": title_html,
        "title_size": title_size, "subtitle": build_subtitle(alert),
        "state_pill": build_state_pill(alert), "head_counties": build_head_counties(alert),
        "counties": counties_pills, "population": format_population(alert.get("population")),
        "origin": origin, "issued_by": issued_by,
        "polygon_json": json.dumps(poly_ring), "max_zoom": calc_max_zoom(poly_ring, kind),
        "include_recs": include_recs, "recs_title": recs_title, "recs": recs,
    }

def alert_to_ctx_recs(alert):
    return {"logo_url": LOGO_URL, **PALETTE["watch"],
            "pretitle": "Vigilancia por Tornado",
            "title_html": "¿Qué debe<br>hacer?", "recs": RECS_WATCH}

def render_alerts(alerts, env):
    WEB_DIR.mkdir(exist_ok=True)
    tpl_map = env.get_template("alert_map.html.j2")
    tpl_recs = env.get_template("alert_recs.html.j2")
    out = []
    for a in alerts:
        kind = a["kind"]; aid = a["id"]
        ctx = alert_to_ctx_map(a)
        if ctx is None:
            audit("render_skipped", id=aid, kind=kind, reason="no_polygon")
            continue
        if kind == "watch":
            html_name = f"watch_{aid}_info.html"; png_name = f"watch_{aid}_info.png"
        else:
            html_name = f"{kind}_{aid}.html"; png_name = f"{kind}_{aid}.png"
        (WEB_DIR / html_name).write_text(tpl_map.render(**ctx), encoding="utf-8")
        out.append({"alert_id": aid, "kind": kind, "slot": "main",
                    "html_path": str(WEB_DIR / html_name), "png_path": str(WEB_DIR / png_name)})
        audit("rendered", id=aid, kind=kind, slot="main", file=html_name)
        if kind == "watch":
            ctx2 = alert_to_ctx_recs(a)
            html_name = f"watch_{aid}_recs.html"; png_name = f"watch_{aid}_recs.png"
            (WEB_DIR / html_name).write_text(tpl_recs.render(**ctx2), encoding="utf-8")
            out.append({"alert_id": aid, "kind": kind, "slot": "recs",
                        "html_path": str(WEB_DIR / html_name), "png_path": str(WEB_DIR / png_name)})
            audit("rendered", id=aid, kind=kind, slot="recs", file=html_name)
    return out

def capture_pngs(outputs):
    """Llama a capturar-playwright.js con todos los pares (html→png) en una sola pasada."""
    if not outputs:
        log.info("📷 No hay HTMLs a capturar")
        return []

    pairs = [{"in": o["html_path"], "out": o["png_path"]} for o in outputs]
    pairs_json = json.dumps(pairs)

    env = os.environ.copy()
    env["HTMLS_TO_CAPTURE"] = pairs_json

    timeout = 30 + 15 * len(pairs)
    log.info("📷 Capturando %d PNGs (timeout=%ds)...", len(pairs), timeout)

    proc = None
    try:
        proc = subprocess.Popen(
            ["node", "capturar-playwright.js"],
            cwd=str(BASE_DIR), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.info("   [pw] %s", line)
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        log.error("Playwright timeout tras %ds — matando proceso", timeout)
        if proc:
            try: proc.kill()
            except Exception: pass
        audit("capture_timeout", timeout=timeout, count=len(pairs))
        return []
    except FileNotFoundError:
        log.error("No se encontró 'node' en el PATH")
        audit("capture_error", error="node_not_found")
        return []
    except Exception as e:
        log.exception("Error inesperado en captura: %s", e)
        audit("capture_error", error=str(e))
        return []

    successful, failed = [], []
    for o in outputs:
        if Path(o["png_path"]).exists():
            successful.append(o)
            audit("captured", id=o["alert_id"], kind=o["kind"], slot=o["slot"],
                  file=Path(o["png_path"]).name,
                  size=Path(o["png_path"]).stat().st_size)
        else:
            failed.append(o)
            audit("capture_missing", id=o["alert_id"], kind=o["kind"], slot=o["slot"])
            log.warning("   ❌ No se generó: %s", Path(o["png_path"]).name)

    log.info("📷 Resultado: %d OK, %d fallidas (rc=%d)", len(successful), len(failed), rc)
    return successful


def spaces_upload(local_path, remote_key, content_type, cache_seconds=60):
    """Sube un archivo a Spaces vía aws s3 cp. Devuelve la URL CDN o None si falla."""
    s3_uri = f"s3://{SPACES_BUCKET}/{remote_key}"
    cmd = [
        "aws", "s3", "cp", local_path, s3_uri,
        "--profile", SPACES_PROFILE,
        "--endpoint-url", SPACES_ENDPOINT,
        "--acl", "public-read",
        "--content-type", content_type,
        "--cache-control", f"public, max-age={cache_seconds}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            url = f"{CDN_BASE}/{remote_key}"
            audit("uploaded", key=remote_key, url=url,
                  size=Path(local_path).stat().st_size if Path(local_path).exists() else 0)
            return url
        log.error("Upload falló: %s -> %s | stderr=%s", local_path, s3_uri, r.stderr.strip()[:300])
        audit("upload_failed", key=remote_key, error=r.stderr.strip()[:300])
        return None
    except subprocess.TimeoutExpired:
        log.error("Upload timeout: %s", remote_key)
        audit("upload_timeout", key=remote_key)
        return None
    except FileNotFoundError:
        log.error("aws CLI no encontrado en PATH")
        audit("upload_error", error="aws_not_found")
        return None


def upload_pngs(captured):
    """Sube los PNGs a Spaces y añade 'cdn_url' a cada output."""
    if not captured:
        return []
    log.info("☁️  Subiendo %d PNGs a Spaces (%s/)...", len(captured), SPACES_PREFIX)
    ok_count = 0
    for o in captured:
        png = Path(o["png_path"])
        if not png.exists():
            log.warning("   ✗ %s (archivo no existe)", png.name)
            continue
        key = f"{SPACES_PREFIX}/{png.name}"
        url = spaces_upload(str(png), key, "image/png", cache_seconds=60)
        if url:
            o["cdn_url"] = url
            ok_count += 1
            log.info("   ✓ %s", png.name)
        else:
            log.warning("   ✗ %s (upload error)", png.name)
    log.info("☁️  Subidos: %d/%d", ok_count, len(captured))
    return captured


def build_manifest(alerts, captured):
    """Combina alertas + URLs CDN en un manifest JSON para el index.html público."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cap_idx = {(o["alert_id"], o["slot"]): o for o in captured}

    kind_label_es = {
        "warning":   "Aviso por tornado",
        "emergency": "Emergencia por tornado",
        "watch":     "Vigilancia por tornado",
    }

    entries = []
    for a in alerts:
        aid = a["id"]; kind = a["kind"]
        counties = a.get("counties")
        if isinstance(counties, str):
            counties = [x.strip() for x in counties.split(",") if x.strip()]
        elif not isinstance(counties, list):
            counties = []
        # Limpiar sufijos tipo "Atchison (+56 más)" → "Atchison"
        counties = [re.sub(r"\s*\(\+\d+\s*m\u00e1s\)\s*$", "", c).strip() for c in counties]
        counties = [c for c in counties if c]

        # Lista de estados afectados (KS, MO, ...) sacados del area_desc
        states_afectados = states_in_area_desc(a.get("areaDesc", ""))
        # state_name: usar el del JSON, o derivarlo del código
        state_code = a.get("state", "")
        state_name = a.get("state_name") or US_STATE_NAMES.get(state_code, "")

        entry = {
            "id":             aid,
            "kind":           kind,
            "event":          a.get("event"),
            "event_es":       kind_label_es.get(kind, a.get("event_es") or kind),
            "areaDesc":       a.get("areaDesc", ""),
            "state":          state_code,
            "state_name":     state_name,
            "states_afectados": states_afectados,
            "counties":    counties[:20],
            "area_count":  a.get("area_count"),
            "population":  a.get("population"),
            "expires":     a.get("expires"),
            "sent":        a.get("sent"),
            "sender":      a.get("sender"),
            "headline":    a.get("headline", ""),
            "severity":    a.get("severity"),
        }

        if kind == "watch":
            info = cap_idx.get((aid, "main"))
            recs = cap_idx.get((aid, "recs"))
            if info and info.get("cdn_url"):
                entry["png_info_url"] = info["cdn_url"]
            if recs and recs.get("cdn_url"):
                entry["png_recs_url"] = recs["cdn_url"]
        else:
            main = cap_idx.get((aid, "main"))
            if main and main.get("cdn_url"):
                entry["png_url"] = main["cdn_url"]

        entries.append(entry)

    only_w  = [a for a in alerts if a["kind"] == "warning"]
    only_e  = [a for a in alerts if a["kind"] == "emergency"]
    only_wa = [a for a in alerts if a["kind"] == "watch"]

    return {
        "updated":  now,
        "count":    len(alerts),
        "by_kind": {
            "warning":   len(only_w),
            "emergency": len(only_e),
            "watch":     len(only_wa),
        },
        "alerts": entries,
    }


def upload_manifest(manifest):
    """Escribe manifest.json local y lo sube a Spaces."""
    local = WEB_DIR / "manifest.json"
    local.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    key = f"{SPACES_PREFIX}/manifest.json"
    url = spaces_upload(str(local), key, "application/json", cache_seconds=15)
    if url:
        log.info("📋 Manifest publicado: %s", url)
    return url


def load_state():
    if not STATE_FILE.exists():
        return {"last_run": None, "notified": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("state.json corrupto (%s), reseteando", e)
        return {"last_run": None, "notified": {}}


def save_state(state):
    state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_state(state, active_ids):
    notified = state.get("notified", {})
    active = set(active_ids)
    removed = [aid for aid in list(notified.keys()) if aid not in active]
    for aid in removed:
        del notified[aid]
    if removed:
        log.info("🧹 Limpiadas %d alertas expiradas del state", len(removed))
        audit("state_cleanup", removed=removed)
    state["notified"] = notified
    return state


def find_new_alerts(alerts, state):
    notified_ids = set(state.get("notified", {}).keys())
    return [a for a in alerts if a["id"] not in notified_ids]


def build_email_html(new_alerts, captured):
    cap_idx = {(o["alert_id"], o["slot"]): o for o in captured}
    LABEL = {"warning": "🟥 Aviso por tornado",
             "emergency": "🟪 Emergencia por tornado",
             "watch": "🟨 Vigilancia por tornado"}
    COLOR = {"warning": "#FF0000", "emergency": "#FF00FF", "watch": "#facc15"}

    parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>',
        '<body style="font-family:Arial,Helvetica,sans-serif;max-width:720px;margin:0 auto;padding:24px;background:#0a1628;color:#fff;">',
        '<h1 style="font-size:24px;margin:0 0 6px;">🌪️ Nuevas alertas de tornado</h1>',
        f'<p style="font-size:14px;color:#94a3b8;margin:0 0 24px;">{len(new_alerts)} alerta(s) nueva(s) detectada(s).</p>',
    ]

    for a in new_alerts:
        kind = a["kind"]
        label = LABEL.get(kind, kind)
        color = COLOR.get(kind, "#999")
        png_main = cap_idx.get((a["id"], "main"))
        png_recs = cap_idx.get((a["id"], "recs"))

        parts.append(
            f'<div style="background:#1a2942;border-left:4px solid {color};padding:18px;margin-bottom:18px;border-radius:8px;">'
            f'<div style="color:{color};font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;color:#fff;margin-bottom:12px;">{a.get("areaDesc", "—")}</div>'
            f'<div style="font-size:14px;color:#cbd5e1;line-height:1.6;">'
            f'<strong>Población:</strong> {format_population(a.get("population"))} personas<br>'
            f'<strong>Vigente hasta:</strong> {format_time_pretty(a.get("expires", ""), extract_tz_from_headline(a.get("headline", "")))}<br>'
            f'<strong>Emitido por:</strong> {a.get("sender") or "—"}'
            f'</div>'
        )
        if png_main and png_main.get("cdn_url"):
            parts.append(f'<img src="{png_main["cdn_url"]}" style="max-width:100%;border-radius:8px;margin-top:14px;display:block;" alt="Mapa de alerta">')
        if png_recs and png_recs.get("cdn_url"):
            parts.append(f'<img src="{png_recs["cdn_url"]}" style="max-width:100%;border-radius:8px;margin-top:10px;display:block;" alt="Recomendaciones">')
        parts.append('</div>')

    parts.append(
        '<p style="font-size:12px;color:#64748b;margin:28px 0 0;text-align:center;">'
        'Canal Meteo TV · Sistema de broadcast de tornados<br>'
        'Información del NWS (National Weather Service)'
        '</p></body></html>'
    )
    return "".join(parts)


def build_email_subject(new_alerts):
    only_e  = [a for a in new_alerts if a["kind"] == "emergency"]
    only_w  = [a for a in new_alerts if a["kind"] == "warning"]
    only_wa = [a for a in new_alerts if a["kind"] == "watch"]
    parts = []
    if only_e:  parts.append(f"{len(only_e)} Emergencia(s)")
    if only_w:  parts.append(f"{len(only_w)} Aviso(s)")
    if only_wa: parts.append(f"{len(only_wa)} Vigilancia(s)")
    return "🌪️ Tornado: " + " · ".join(parts)


def send_email(new_alerts, captured):
    if not SENDGRID_API_KEY or not FROM_EMAIL or not TO_EMAILS:
        log.info("📧 Email no configurado (falta SENDGRID_API_KEY/FROM_EMAIL/TO_EMAILS en .env)")
        audit("email_skipped", reason="not_configured", alerts=len(new_alerts))
        return False
    if not new_alerts:
        return False

    subject = build_email_subject(new_alerts)
    html = build_email_html(new_alerts, captured)

    cap_idx = {(o["alert_id"], o["slot"]): o for o in captured}
    attachments = []
    for a in new_alerts[:MAX_EMAIL_ATTACHMENTS]:
        main = cap_idx.get((a["id"], "main"))
        if main and Path(main["png_path"]).exists():
            with open(main["png_path"], "rb") as f:
                data_b64 = base64.b64encode(f.read()).decode("utf-8")
            attachments.append({
                "content": data_b64,
                "type": "image/png",
                "filename": Path(main["png_path"]).name,
                "disposition": "attachment",
            })

    payload = {
        "personalizations": [{"to": [{"email": e} for e in TO_EMAILS], "subject": subject}],
        "from": {"email": FROM_EMAIL},
        "content": [{"type": "text/html", "value": html}],
    }
    if attachments:
        payload["attachments"] = attachments

    log.info("📧 Enviando email a %d destinatario(s): %s", len(TO_EMAILS), subject)
    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        if 200 <= r.status_code < 300:
            log.info("📧 OK (status %d) · %d alerta(s) · %d adjunto(s)",
                     r.status_code, len(new_alerts), len(attachments))
            audit("email_sent", recipients=len(TO_EMAILS), alerts=len(new_alerts),
                  attachments=len(attachments), status=r.status_code)
            return True
        log.error("❌ SendGrid error %d: %s", r.status_code, r.text[:300])
        audit("email_failed", status=r.status_code, error=r.text[:300])
        return False
    except Exception as e:
        log.exception("Excepción enviando email: %s", e)
        audit("email_error", error=str(e))
        return False


def cleanup_web_dir(active_outputs):
    """
    Borra HTMLs/PNGs locales de alertas que ya no están activas.
    active_outputs es la lista de outputs del run actual (con html_path/png_path).
    Cualquier archivo en WEB_DIR que NO sea de una alerta activa se borra.
    Se preservan: manifest.json y .gitkeep si existe.
    """
    if not WEB_DIR.exists():
        return 0

    keep = set()
    for o in active_outputs:
        keep.add(Path(o["html_path"]).name)
        keep.add(Path(o["png_path"]).name)
    keep.add("manifest.json")
    keep.add(".gitkeep")

    removed = 0
    for f in WEB_DIR.iterdir():
        if f.is_file() and f.name not in keep:
            # Solo borrar HTML/PNG/json de alertas (warning_/emergency_/watch_)
            if any(f.name.startswith(p) for p in ("warning_", "emergency_", "watch_")):
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    log.warning("No se pudo borrar %s: %s", f.name, e)

    if removed:
        log.info("🧹 Limpiados %d archivos locales de alertas expiradas", removed)
        audit("cleanup_web", removed=removed)
    return removed


def cleanup_cdn(active_outputs):
    """
    Borra de Spaces los PNGs de alertas ya no activas.
    Lista los objetos en SPACES_PREFIX/ y borra los que no estén en active.
    """
    keep_keys = set()
    for o in active_outputs:
        keep_keys.add(f"{SPACES_PREFIX}/{Path(o['png_path']).name}")
    keep_keys.add(f"{SPACES_PREFIX}/manifest.json")

    # Listar el prefix
    try:
        r = subprocess.run(
            ["aws", "s3", "ls", f"s3://{SPACES_BUCKET}/{SPACES_PREFIX}/",
             "--profile", SPACES_PROFILE,
             "--endpoint-url", SPACES_ENDPOINT],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            log.warning("No se pudo listar Spaces para cleanup: %s", r.stderr.strip()[:200])
            return 0
    except Exception as e:
        log.warning("Error listando Spaces: %s", e)
        return 0

    removed = 0
    for line in r.stdout.splitlines():
        # Formato: "2026-05-18 04:30:28     544695 warning_5f0ed7f200.png"
        parts = line.split()
        if len(parts) < 4:
            continue
        filename = parts[-1]
        key = f"{SPACES_PREFIX}/{filename}"
        if key in keep_keys:
            continue
        # Solo borrar PNGs de alertas (no manifests ni nada inesperado)
        if not any(filename.startswith(p) for p in ("warning_", "emergency_", "watch_")):
            continue
        try:
            rd = subprocess.run(
                ["aws", "s3", "rm", f"s3://{SPACES_BUCKET}/{key}",
                 "--profile", SPACES_PROFILE,
                 "--endpoint-url", SPACES_ENDPOINT],
                capture_output=True, text=True, timeout=15
            )
            if rd.returncode == 0:
                removed += 1
                audit("cdn_removed", key=key)
        except Exception as e:
            log.warning("Error borrando %s: %s", key, e)

    if removed:
        log.info("🧹 Borrados %d PNGs del CDN", removed)
    return removed


def run(dry_run=False, render_only=False):
    log.info("=" * 60); log.info("🌪️  TORNADO BROADCAST"); log.info("=" * 60)
    alerts = fetch_warnings() + fetch_watches()
    only_w  = [a for a in alerts if a["kind"] == "warning"]
    only_e  = [a for a in alerts if a["kind"] == "emergency"]
    only_wa = [a for a in alerts if a["kind"] == "watch"]
    log.info("-" * 60)
    log.info("📊 Activas: %d warnings · %d emergencies · %d watches",
             len(only_w), len(only_e), len(only_wa))
    log.info("-" * 60)
    for a in only_w + only_e:
        log.info("%s [%s] %s · %s (pop=%s)",
                 "🟥" if a["kind"]=="warning" else "🟪",
                 a["id"], a["state"], a["areaDesc"], a.get("population"))
    for a in only_wa:
        log.info("🟨 WATCH [%s] · %d zonas · %s",
                 a["id"], a.get("area_count") or len(a.get("counties",[])),
                 (a.get("areaDesc") or "")[:80])
    log.info("-" * 60)
    audit("fetch_summary", warnings=len(only_w), emergencies=len(only_e),
          watches=len(only_wa), total=len(alerts), dry_run=dry_run)

    if dry_run:
        log.info("[DRY RUN] no se renderiza."); return 0

    env = setup_jinja()
    outputs = render_alerts(alerts, env)
    log.info("🎨 Renderizados %d HTMLs en %s", len(outputs), WEB_DIR)
    for o in outputs:
        log.info("   · %s/%s → %s", o["kind"], o["slot"], Path(o["html_path"]).name)

    if render_only:
        log.info("[RENDER ONLY] no se capturan PNGs."); return 0

    # ═══ D8.3: CAPTURE PNG ═══
    captured = capture_pngs(outputs)
    if not captured:
        log.warning("No hay capturas para subir.")
        return 0

    # ═══ D8.4: UPLOAD A SPACES + MANIFEST ═══
    uploaded = upload_pngs(captured)
    manifest = build_manifest(alerts, uploaded)
    manifest_url = upload_manifest(manifest)

    # ═══ D8.5: STATE + EMAIL DE ALERTAS NUEVAS ═══
    state = load_state()
    new_alerts = find_new_alerts(alerts, state)
    log.info("🆕 %d alerta(s) nueva(s) (no notificada(s) antes)", len(new_alerts))

    if new_alerts:
        if send_email(new_alerts, uploaded):
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for a in new_alerts:
                state.setdefault("notified", {})[a["id"]] = {
                    "kind":         a["kind"],
                    "notified_at":  now_iso,
                    "areaDesc":     a.get("areaDesc", ""),
                    "expires":      a.get("expires"),
                }

    # ═══ D8.6: CLEANUP ═══
    # State: quitar IDs ya no activos
    active_ids = [a["id"] for a in alerts]
    state = cleanup_state(state, active_ids)
    save_state(state)

    # Archivos locales y CDN: borrar restos de alertas no activas
    cleanup_web_dir(outputs)
    cleanup_cdn(outputs)

    audit("run_complete",
          alerts=len(alerts), rendered=len(outputs),
          captured=len(captured),
          uploaded=sum(1 for o in uploaded if o.get("cdn_url")),
          manifest=bool(manifest_url),
          new=len(new_alerts))

    log.info("✅ Pipeline completo.")
    return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)
    try:
        sys.exit(run(dry_run=args.dry_run, render_only=args.render_only))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        log.exception("Error fatal: %s", e)
        audit("fatal_error", error=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
