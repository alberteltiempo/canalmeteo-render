#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_preview.py — Renderiza los 4 templates de tornado con datos hardcoded
para validar que producen HTMLs idénticos a los mockups aprobados.

Uso:
    /opt/canalmeteo/venv/bin/python3 render_preview.py

Output:
    web/preview_warning.html
    web/preview_watch_info.html
    web/preview_watch_recs.html
    web/preview_emergency.html
"""

import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).resolve().parent
TPL_DIR  = BASE_DIR / "templates"
OUT_DIR  = BASE_DIR / "web"
OUT_DIR.mkdir(exist_ok=True)

env = Environment(
    loader=FileSystemLoader(str(TPL_DIR)),
    autoescape=select_autoescape(['html', 'xml']),
    trim_blocks=False,
    lstrip_blocks=False,
)

COMMON = {
    "logo_url": "https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png",
    "mapbox_token": "pk.eyJ1IjoiYWxiZXJ0ZWx0aWVtcG8iLCJhIjoiY21rM2pqa29zMGd6NjNncHdlMWZ1NTNlayJ9.0d2lAZ-CmqEuoPe_h2JEHA",
}

PALETTE = {
    "warning": {
        "bg_dark": "#8B0000",
        "bg_mid": "#FF0000",
        "accent": "#FF0000",
        "accent_text": "#FF6666",
        "icon_grad": "linear-gradient(135deg,#FF0000 0%,#B30000 100%)",
        "icon_shadow": "rgba(255,0,0,.55)",
        "icon_svg_color": "#fff",
        "poly_color": "#FF0000",
        "poly_glow": "#FF3333",
    },
    "watch": {
        "bg_dark": "#713f12",
        "bg_mid": "#a16207",
        "accent": "#facc15",
        "accent_text": "#fde047",
        "icon_grad": "linear-gradient(135deg,#facc15 0%,#ca8a04 100%)",
        "icon_shadow": "rgba(250,204,21,.55)",
        "icon_svg_color": "#422006",
        "poly_color": "#facc15",
        "poly_glow": "#fde047",
        "emoji_bg_grad": "linear-gradient(135deg,#facc15 0%,#ca8a04 100%)",
        "accent_shadow": "rgba(250,204,21,.6)",
    },
    "emergency": {
        "bg_dark": "#7B0078",
        "bg_mid": "#FF00FF",
        "accent": "#FF00FF",
        "accent_text": "#FF66FF",
        "icon_grad": "linear-gradient(135deg,#FF00FF 0%,#B300B3 100%)",
        "icon_shadow": "rgba(255,0,255,.55)",
        "icon_svg_color": "#fff",
        "poly_color": "#FF00FF",
        "poly_glow": "#FF66FF",
    },
}

RECS_WARNING = [
    "Diríjase a un sótano o habitación interior en la planta baja.",
    "Aléjese de ventanas, puertas y muros exteriores.",
    "Cúbrase con mantas o un colchón para protegerse de escombros.",
    "No intente escapar de un tornado en un vehículo o casa móvil.",
]

RECS_EMERGENCY = [
    "PELIGRO EXTREMO. Tornado destructivo en tierra. Refúgiese de inmediato.",
    "Diríjase a un sótano o al nivel más bajo del edificio.",
    "Si no hay sótano, una habitación interior pequeña y sin ventanas.",
]

RECS_WATCH = [
    {"emoji": "📡", "title": "Manténgase informado",
     "desc": "Atento a las actualizaciones del NWS y al radar local. Active alertas en su teléfono."},
    {"emoji": "🚪", "title": "Plan de refugio listo",
     "desc": "Sepa exactamente a dónde ir si se emite un aviso por tornado."},
    {"emoji": "🔒", "title": "Asegure objetos exteriores",
     "desc": "Muebles, basura, decoración: lo que pueda volar con el viento."},
    {"emoji": "🛡️", "title": "Identifique su lugar más seguro",
     "desc": "Sótano o habitación interior sin ventanas en la planta baja."},
]

def render_map(event_type, data):
    tpl = env.get_template("alert_map.html.j2")
    ctx = {**COMMON, **PALETTE[event_type], **data}
    ctx["polygon_json"] = json.dumps(data["polygon"])
    return tpl.render(**ctx)

def render_recs(event_type, data):
    tpl = env.get_template("alert_recs.html.j2")
    ctx = {**COMMON, **PALETTE[event_type], **data}
    return tpl.render(**ctx)

# 1. WARNING
warning_html = render_map("warning", {
    "event_label_lower": "Aviso por tornado",
    "event_label_upper_html": "Aviso por<br>Tornado",
    "title_size": "110px",
    "subtitle": "Vigente hasta las 6:15 PM CDT",
    "state_pill": "MN · Minnesota",
    "head_counties": "Nobles, MN · Rock, MN",
    "counties": ["Nobles", "Rock"],
    "population": "31.853",
    "origin": "Indicado por radar",
    "issued_by": "NWS Sioux Falls, SD",
    "polygon": [[-96.08,43.58],[-96.11,43.73],[-95.59,43.84],[-95.52,43.65],[-96.08,43.58]],
    "max_zoom": 10,
    "include_recs": True,
    "recs_title": "Recomendaciones · Busque refugio",
    "recs": RECS_WARNING,
})
(OUT_DIR / "preview_warning.html").write_text(warning_html, encoding="utf-8")
print(f"✅ preview_warning.html ({len(warning_html):,} bytes)")

# 2. WATCH INFO
watch_info_html = render_map("watch", {
    "event_label_lower": "Vigilancia por tornado",
    "event_label_upper_html": "Vigilancia por<br>Tornado",
    "title_size": "90px",
    "subtitle": "Vigente hasta las 10:00 PM CDT",
    "state_pill": "Tornado Watch #234",
    "head_counties": "16 condados · IA · MN · NE · SD",
    "counties": ["Lyon", "Sioux", "Plymouth", "Cherokee", "O'Brien", "Clay", "Buena Vista", "Pocahontas"],
    "population": "847.219",
    "origin": "Storm Prediction Center",
    "issued_by": "NWS / SPC Norman, OK",
    "polygon": [[-97.5,42.5],[-94.2,42.7],[-93.8,44.5],[-97.2,44.6],[-97.5,42.5]],
    "max_zoom": 7,
    "include_recs": False,
    "recs_title": "",
    "recs": [],
})
(OUT_DIR / "preview_watch_info.html").write_text(watch_info_html, encoding="utf-8")
print(f"✅ preview_watch_info.html ({len(watch_info_html):,} bytes)")

# 3. WATCH RECS
watch_recs_html = render_recs("watch", {
    "pretitle": "Vigilancia por Tornado",
    "title_html": "¿Qué debe<br>hacer?",
    "recs": RECS_WATCH,
})
(OUT_DIR / "preview_watch_recs.html").write_text(watch_recs_html, encoding="utf-8")
print(f"✅ preview_watch_recs.html ({len(watch_recs_html):,} bytes)")

# 4. EMERGENCY
emergency_html = render_map("emergency", {
    "event_label_lower": "Emergencia por tornado",
    "event_label_upper_html": "Emergencia por<br>Tornado",
    "title_size": "90px",
    "subtitle": "Vigente hasta las 6:15 PM CDT",
    "state_pill": "MN · Minnesota",
    "head_counties": "Nobles, MN · Rock, MN",
    "counties": ["Nobles", "Rock"],
    "population": "31.853",
    "origin": "Tornado observado · Daño confirmado",
    "issued_by": "NWS Sioux Falls, SD",
    "polygon": [[-96.08,43.58],[-96.11,43.73],[-95.59,43.84],[-95.52,43.65],[-96.08,43.58]],
    "max_zoom": 10,
    "include_recs": True,
    "recs_title": "¡PELIGRO EXTREMO! · Refúgiese ahora",
    "recs": RECS_EMERGENCY,
})
(OUT_DIR / "preview_emergency.html").write_text(emergency_html, encoding="utf-8")
print(f"✅ preview_emergency.html ({len(emergency_html):,} bytes)")

print()
print(f"📂 Outputs en: {OUT_DIR}")
