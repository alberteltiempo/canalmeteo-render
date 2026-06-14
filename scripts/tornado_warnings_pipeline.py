#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
tornado_warnings_pipeline.py — Canal Meteo
============================================================================
Genera tornado-warnings.json en el CDN para el producto tornado-override.html

Lee NWS API → enriquece (población UGC, polígono, source) → sube a CDN.
Diseñado para correr cada 30s vía cron con flock guard.

Output: https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/tornado-warnings.json

Schema:
{
  "updated": "2026-04-25T14:30:00Z",
  "warnings": [
    {
      "id": "urn:oid:2.49.0.1.840.0.xxx",
      "event": "Tornado Warning" | "Tornado Emergency",
      "areaDesc": "Smith County, KS; Jewell County, KS",
      "counties": ["Smith County", "Jewell County"],
      "state": "KS",
      "polygon": { "type": "Polygon", "coordinates": [...] },
      "expires": "2026-04-25T15:00:00Z",
      "sent": "2026-04-25T14:25:00Z",
      "sender": "NWS Topeka KS",
      "description": "...",
      "instruction": "...",
      "population": 12450,
      "source": "radar indicated"
    }
  ]
}

Crontab:
*/1 * * * * /usr/bin/flock -n /tmp/tor_warn.lock /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/tornado_warnings_pipeline.py >> /var/log/canalmeteo/tor_warn.log 2>&1
============================================================================
"""

import os
import sys
import json
import re
import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

# ─── CONFIG ────────────────────────────────────────────────────────────
NWS_API = "https://api.weather.gov/alerts/active"
NWS_HEADERS = {
    "User-Agent": "CanalMeteoTV/1.0 (albert@canalmeteo.tv)",
    "Accept": "application/geo+json"
}
NWS_TIMEOUT = 15

OUT_PATH = "/tmp/tornado-warnings.json"
CDN_KEY = "data/tornado-warnings.json"
CDN_BUCKET = "canalmeteo-public"
CDN_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CDN_PROFILE = "do-tor1"

UGC_POP_FILE = "/opt/canalmeteo/data/ugc_population.csv"  # generated separately

LOG_PATH = "/var/log/canalmeteo/tor_warn.log"

# ─── UGC POPULATION LOOKUP ─────────────────────────────────────────────
_ugc_pop_cache = None

def load_ugc_population():
    """Load UGC code → population mapping from CSV (one-time setup)."""
    global _ugc_pop_cache
    if _ugc_pop_cache is not None:
        return _ugc_pop_cache
    _ugc_pop_cache = {}
    if not Path(UGC_POP_FILE).exists():
        log(f"⚠️  {UGC_POP_FILE} no existe — población siempre será None")
        return _ugc_pop_cache
    try:
        with open(UGC_POP_FILE, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ugc = row.get("ugc", "").strip()
                pop = row.get("population", "0").strip()
                try:
                    _ugc_pop_cache[ugc] = int(pop)
                except ValueError:
                    pass
        log(f"  → {len(_ugc_pop_cache)} UGCs cargados con población")
    except Exception as e:
        log(f"⚠️  Error cargando UGC pop: {e}")
    return _ugc_pop_cache

def estimate_population(alert_props):
    """Sum population across all UGC codes in this alert."""
    pop_lookup = load_ugc_population()
    if not pop_lookup:
        return None
    geocode = alert_props.get("geocode", {})
    ugcs = geocode.get("UGC", []) or []
    total = 0
    found = 0
    for ugc in ugcs:
        if ugc in pop_lookup:
            total += pop_lookup[ugc]
            found += 1
    if found == 0:
        return None
    return total

# ─── PARSING ───────────────────────────────────────────────────────────
def extract_state(area_desc):
    """Extract state abbrev from areaDesc string. Returns first match."""
    if not area_desc:
        return None
    m = re.search(r",\s*([A-Z]{2})\b", area_desc)
    return m.group(1) if m else None

def extract_counties(area_desc):
    """Split areaDesc semicolon-separated into list of clean county names."""
    if not area_desc:
        return []
    parts = [p.strip() for p in area_desc.split(";") if p.strip()]
    # Each part is like "Smith County, KS" — strip the ", XX" trailing
    out = []
    for p in parts:
        # Remove trailing ", XX"
        clean = re.sub(r",\s*[A-Z]{2}\s*$", "", p)
        out.append(clean)
    return out

def extract_source(description):
    """Detect source phrase in NWS description for display."""
    if not description:
        return None
    d = description.lower()
    if "radar indicated" in d or "radar-indicated" in d:
        return "radar indicated"
    if "observed" in d and ("spotter" in d or "weather spotter" in d):
        return "trained spotter"
    if "law enforcement" in d:
        return "law enforcement"
    if "spotter" in d:
        return "spotter"
    if "observed" in d:
        return "observed"
    return None

def is_tornado_emergency(alert):
    """
    Detect Tornado Emergency: NWS issues these as 'Tornado Warning' with
    'TORNADO EMERGENCY' in description. The 'event' field stays as 'Tornado Warning'.
    """
    props = alert.get("properties", {})
    if props.get("event") != "Tornado Warning":
        return False
    desc = (props.get("description") or "").upper()
    instr = (props.get("instruction") or "").upper()
    return "TORNADO EMERGENCY" in desc or "TORNADO EMERGENCY" in instr

def transform_alert(alert):
    """NWS alert → our schema."""
    props = alert.get("properties", {})
    geom = alert.get("geometry")  # GeoJSON geometry or null

    event = props.get("event", "")
    if event != "Tornado Warning":
        return None  # only process Tornado Warnings

    # Detect Emergency upgrade
    if is_tornado_emergency(alert):
        event = "Tornado Emergency"

    out = {
        "id": props.get("id") or alert.get("id"),
        "event": event,
        "areaDesc": props.get("areaDesc"),
        "counties": extract_counties(props.get("areaDesc")),
        "state": extract_state(props.get("areaDesc")),
        "polygon": geom,  # could be Polygon or null (some alerts are zone-based)
        "expires": props.get("expires"),
        "sent": props.get("sent"),
        "sender": props.get("senderName"),
        "description": props.get("description"),
        "instruction": props.get("instruction"),
        "population": estimate_population(props),
        "source": extract_source(props.get("description")),
        "nws_id": props.get("id"),  # alias for downstream voice matching
    }
    return out

# ─── FETCH ─────────────────────────────────────────────────────────────
def fetch_active_warnings():
    """Get all active Tornado Warnings (and Emergencies, which come as TW)."""
    params = {
        "status": "actual",
        "message_type": "alert,update",
        "event": "Tornado Warning",
    }
    r = requests.get(NWS_API, params=params, headers=NWS_HEADERS, timeout=NWS_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("features", []) or []

# ─── UPLOAD TO CDN ─────────────────────────────────────────────────────
def upload_to_cdn(local_path):
    """aws s3 cp via DigitalOcean Spaces."""
    cmd = [
        "aws", "s3", "cp", local_path,
        f"s3://{CDN_BUCKET}/{CDN_KEY}",
        "--profile", CDN_PROFILE,
        "--acl", "public-read",
        "--content-type", "application/json",
        "--cache-control", "max-age=15, public",
        "--endpoint-url", CDN_ENDPOINT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        log(f"❌ CDN upload error: {result.stderr.strip()}")
        return False
    return True

# ─── LOG ───────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ─── MAIN ──────────────────────────────────────────────────────────────
def main():
    log("─" * 60)
    log("Iniciando pipeline tornado warnings")

    try:
        features = fetch_active_warnings()
    except Exception as e:
        log(f"❌ Error consultando NWS: {e}")
        sys.exit(1)

    log(f"  → NWS reportó {len(features)} alertas activas")

    warnings = []
    for f in features:
        try:
            t = transform_alert(f)
            if t:
                warnings.append(t)
        except Exception as e:
            log(f"⚠️  Error transformando alerta: {e}")

    # Sort: Emergency first, then most recent
    warnings.sort(key=lambda w: (
        0 if w["event"] == "Tornado Emergency" else 1,
        -(datetime.fromisoformat(w["sent"].replace("Z","+00:00")).timestamp() if w.get("sent") else 0)
    ))

    n_emerg = sum(1 for w in warnings if w["event"] == "Tornado Emergency")
    n_warn = len(warnings) - n_emerg
    log(f"  → {n_warn} Tornado Warnings · {n_emerg} Tornado Emergencies")

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(warnings),
        "warnings": warnings
    }

    # Write local
    Path(OUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    # Upload to CDN
    if upload_to_cdn(OUT_PATH):
        log(f"✅ CDN actualizado: {len(warnings)} avisos")
    else:
        log("❌ Fallo en upload, JSON local guardado pero no publicado")
        sys.exit(2)

    log("─" * 60)

if __name__ == "__main__":
    main()
