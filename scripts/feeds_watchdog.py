#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Watchdog de frescura de los feeds del CDN (Spaces).

Problema que vigila: si un pipeline de nimbus muere, los vídeos siguen
renderizando con datos viejos EN SILENCIO (p. ej. goes_ir_windy estuvo 79 h
parado sin que nadie lo viera). Este script hace HEAD al manifiesto/JSON de
cada producto en el CDN público (lo mismo que ven los renders), compara su
Last-Modified con la edad máxima esperada, y avisa por email (SendGrid, mismo
canal que enviar_terremoto.py) cuando algo se pasa — y cuando se recupera.

Anti-spam: guarda estado en logs/watchdog_state.json; un email cuando el
conjunto de feeds caídos CAMBIA (nuevo caído o recuperado) y recordatorio
cada REMIND_H horas mientras siga habiendo caídos.

Uso:
  feeds_watchdog.py           # comprueba y avisa si toca (para cron)
  feeds_watchdog.py --test    # imprime el estado de todo, sin emails

Cron sugerido (calamarsa):
  */30 * * * * /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/feeds_watchdog.py >> /opt/canalmeteo/logs/watchdog.log 2>&1
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import requests

CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
STATE_PATH = "/opt/canalmeteo/logs/watchdog_state.json"
SENDGRID_ENV = "/opt/canalmeteo/scripts/sendgrid.env"
REMIND_H = 12  # recordatorio si sigue caído

# (nombre, ruta en el CDN, edad máxima en horas)
# Umbrales = cadencia del pipeline × margen holgado ("muchas horas", no ruido).
FEEDS: list[tuple[str, str, float]] = [
    # Satélite (frames cada ~10-30 min)
    ("Satélite full-disk este",   "data/satellite-fd/disco-este/manifest.json",  3),
    ("Satélite full-disk oeste",  "data/satellite-fd/disco-oeste/manifest.json", 3),
    ("GOES IR windy conus",       "data/goes_ir_windy/conus/manifest.json",      3),
    ("GOES IR windy este",        "data/goes_ir_windy/este/manifest.json",       3),
    ("GOES IR windy oeste",       "data/goes_ir_windy/oeste/manifest.json",      3),
    # Radar / severo
    ("Radar CONUS",               "data/radar_conus/manifest.json",              2),
    ("MRMS",                      "data/mrms/manifest.json",                     2),
    # Modelos
    ("NBM precip (c/3h :40)",     "data/nbm/nbm_manifest.json",                  7),
    ("NBM temperatura (:25)",     "data/nbm/temp/conus/manifest.json",           3),
    # GFS sale 4×/día y tarda ~3-4 h en publicarse → edad normal hasta ~10 h
    ("GFS global",                "data/gfs_global/gfs_global_manifest.json",   14),
    # Feeds puntuales de los 9 segmentos + huracanes
    ("Ciudades weather.json",     "data/cities/weather.json",                    3),
    ("Alertas NWS",               "data/alertas/alertas_nws.json",               2),
    ("Alertas por estado",        "data/alerts/by-state.json",                   2),
    ("Frentes",                   "data/fronts/fronts.json",                     3),
    ("Reportes de tormenta",      "data/reports/storm_reports.json",             3),
    ("SPC outlook día 1",         "data/spc/outlook_day1.json",                 12),
    ("Tmax ciudades",             "data/tmax/cities.json",                       8),
    ("UV ciudades",               "data/uv/cities.json",                         8),
    ("AQI ciudades",              "data/aqi/cities.json",                        3),
    ("FAA aeropuertos",           "data/faa/airports.json",                      2),
    ("FAA retrasos",              "data/airports/delays.json",                   2),
    ("Trópico active_storms",     "data/tropical/active_storms.json",            7),
    # Lentos por naturaleza
    ("Sequía USDM (semanal)",     "data/drought/usdm_current.json",            200),
]


def load_sendgrid_env() -> None:
    """Carga scripts/sendgrid.env (KEY=VALUE) al entorno si no está ya."""
    if os.getenv("SENDGRID_API_KEY"):
        return
    try:
        with open(SENDGRID_ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def check_feed(path: str) -> tuple[float | None, str]:
    """Devuelve (edad_en_horas, detalle). Edad None = no accesible."""
    url = f"{CDN}/{path}"
    try:
        r = requests.head(url, timeout=20)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        lm = r.headers.get("Last-Modified")
        if not lm:
            return None, "sin Last-Modified"
        dt = datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return age, lm
    except requests.RequestException as e:
        return None, f"error de red: {e.__class__.__name__}"


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"stale": [], "last_alert": None}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_email(subject: str, html: str) -> bool:
    load_sendgrid_env()
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    to_emails = [e.strip() for e in os.getenv("TO_EMAILS", "").split(",") if e.strip()]
    if not api_key or not from_email or not to_emails:
        print("watchdog: faltan SENDGRID_API_KEY/FROM_EMAIL/TO_EMAILS (sendgrid.env)")
        return False
    payload = {
        "personalizations": [{"to": [{"email": e} for e in to_emails], "subject": subject}],
        "from": {"email": from_email},
        "content": [{"type": "text/html", "value": html}],
    }
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=30,
    )
    ok = 200 <= r.status_code < 300
    print(f"watchdog: email {'enviado' if ok else 'FALLÓ'} ({r.status_code})")
    return ok


def fmt_age(age: float | None) -> str:
    if age is None:
        return "—"
    return f"{age:.1f} h" if age < 48 else f"{age/24:.1f} días"


def main() -> None:
    test = "--test" in sys.argv
    now = datetime.now(timezone.utc)
    results = []  # (name, path, age, max_h, detail, is_stale)
    for name, path, max_h in FEEDS:
        age, detail = check_feed(path)
        stale = age is None or age > max_h
        results.append((name, path, age, max_h, detail, stale))

    stale_now = [r for r in results if r[5]]
    if test:
        for name, path, age, max_h, detail, stale in results:
            mark = "🔴" if stale else "✓ "
            print(f"{mark} {name:28} {fmt_age(age):>9}  (máx {max_h:g} h)  {detail if age is None else ''}")
        print(f"\n{len(stale_now)}/{len(results)} caídos")
        return

    state = load_state()
    prev = set(state.get("stale", []))
    cur = {r[1] for r in stale_now}
    last_alert = state.get("last_alert")
    last_dt = datetime.fromisoformat(last_alert) if last_alert else None
    remind_due = cur and (last_dt is None or (now - last_dt).total_seconds() > REMIND_H * 3600)

    ts = now.strftime("%Y-%m-%d %H:%M UTC")
    if cur != prev or remind_due:
        newly = cur - prev
        recovered = prev - cur
        rows = "".join(
            f"<tr><td>{'🔴' if r[5] else '🟢'}</td><td>{r[0]}</td><td>{r[1]}</td>"
            f"<td align=right>{fmt_age(r[2])}</td><td align=right>máx {r[3]:g} h</td><td>{r[4] if r[2] is None else ''}</td></tr>"
            for r in results
            if r[5] or r[1] in recovered
        )
        if cur:
            subject = f"⚠️ Canal Meteo: {len(cur)} feed(s) sin actualizar"
        else:
            subject = "✅ Canal Meteo: todos los feeds recuperados"
        parts = []
        if newly:
            parts.append(f"<p><b>Nuevos caídos:</b> {len(newly)}</p>")
        if recovered:
            parts.append(f"<p><b>Recuperados:</b> {len(recovered)}</p>")
        if not newly and not recovered and remind_due:
            parts.append(f"<p>Recordatorio: siguen caídos desde hace &gt;{REMIND_H} h.</p>")
        html = (
            f"<h3>Watchdog de feeds del CDN — {ts}</h3>"
            + "".join(parts)
            + f"<table border=1 cellpadding=6 cellspacing=0><tr><th></th><th>Producto</th><th>Ruta</th><th>Edad</th><th>Umbral</th><th>Detalle</th></tr>{rows}</table>"
            + "<p>Los pipelines corren en nimbus-01 (cron). Revisa /opt/canalmeteo/logs/ en nimbus.</p>"
        )
        if send_email(subject, html):
            state["last_alert"] = now.isoformat()
    state["stale"] = sorted(cur)
    save_state(state)
    print(f"{ts} · {len(cur)}/{len(results)} caídos" + (f" · {sorted(cur)}" if cur else ""))


if __name__ == "__main__":
    main()
