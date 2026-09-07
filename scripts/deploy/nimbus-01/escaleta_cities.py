#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ciudades AÑADIDAS desde el editor de escaletas (intranet) para los
pipelines de nimbus (cities_weather / uv / aqi / nbm_tmax / faa_airports).

Contrato: data/escaleta/<slug>.json → cities.<juego>.extra = [{id, label, name,
key, lon, lat, custom, city, state}]. Las entradas `custom` no están en ningún
catálogo de Remotion NI en las tablas de los pipelines: el pipeline debe
PRODUCIR su dato (por lat/lon, o por city/state para EPA-UV, o estación NWS
para condiciones). Las no-custom ya las cubren las tablas (unión regional).

Uso en un pipeline (siempre dentro de try/except: la antena no depende de esto):
    from escaleta_cities import extra_cities
    for e in extra_cities('aqi'):
        CITIES.setdefault(e['id'], (e['lat'], e['lon']))

Desplegado por scp en /opt/canalmeteo/scripts/ (nimbus no es git). Fuente en
el repo: scripts/deploy/nimbus-01/escaleta_cities.py.
"""
from __future__ import annotations

import json
import time
import urllib.request

CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/escaleta"
SLUGS = ["tiempo-conus", "tiempo-fl", "tiempo-se", "tiempo-ne", "tiempo-sp",
         "tiempo-mw", "tiempo-np", "tiempo-nw", "tiempo-sw"]
UA = "canalmeteo-pipelines (albert@canalmeteo.tv)"

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}


def _get_json(url: str, timeout: float = 6) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def extra_cities(setname: str) -> list[dict]:
    """Unión (por id) de las ciudades `custom` añadidas al juego `setname` en
    los 9 productos. Nunca lanza: ante cualquier fallo devuelve lo que haya."""
    out: dict[str, dict] = {}
    for slug in SLUGS:
        try:
            cfg = _get_json(f"{CDN}/{slug}.json?ts={int(time.time())}")
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        extras = ((cfg.get("cities") or {}).get(setname) or {}).get("extra") or []
        for e in extras:
            try:
                if not (isinstance(e, dict) and e.get("custom") and isinstance(e.get("id"), str)):
                    continue
                lat, lon = float(e["lat"]), float(e["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                out.setdefault(e["id"], {
                    "id": e["id"], "label": str(e.get("label") or e["id"]),
                    "city": str(e.get("city") or e.get("label") or e["id"]),
                    "state": str(e.get("state") or "").upper()[:2],
                    "lat": lat, "lon": lon, "key": str(e.get("key") or e["id"]),
                })
            except Exception:
                continue
    return list(out.values())


def nws_stations(lat: float, lon: float, user_agent: str = UA, max_stations: int = 3) -> tuple[str, list[str]]:
    """(zona horaria IANA, [ids de estación NWS más cercanos]) para un punto,
    vía api.weather.gov/points. ('America/New_York', []) si falla."""
    try:
        pt = _get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", timeout=15)
        props = (pt or {}).get("properties") or {}
        tz = props.get("timeZone") or "America/New_York"
        url = props.get("observationStations")
        if not url:
            return tz, []
        st = _get_json(url, timeout=15) or {}
        ids = [f.get("properties", {}).get("stationIdentifier") for f in st.get("features") or []]
        return tz, [i for i in ids if isinstance(i, str)][:max_stations]
    except Exception:
        return "America/New_York", []


if __name__ == "__main__":
    for s in ("condiciones", "aeropuertos", "uv", "aqi", "tmax"):
        print(s, extra_cities(s))
