#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nhc_genesis.py — Descarga las áreas de génesis (zonas en vigilancia) del
Graphical Tropical Weather Outlook (GTWO) del NHC y las normaliza al esquema
que consume el video (active_storms.json -> "genesis": {"areas": [...]}).

Fuente: MapServer ArcGIS de NOAA (GeoJSON directo, sin shapefile):
  https://mapservices.weather.noaa.gov/tropical/rest/services/tropical/NHC_tropical_weather/MapServer
Capas relevantes: "2 Day Outlook" y "7 Day Outlook" (polígonos de formación).

Integración en tropical_pipeline.py:
    from nhc_genesis import fetch_genesis_areas
    genesis = fetch_genesis_areas()              # {"areas": [...], "updated": "..."}
    data["genesis"] = genesis                    # antes de volcar active_storms.json

Uso directo (debug):
    python3 nhc_genesis.py            # imprime resumen + cuenta por cuenca
    python3 nhc_genesis.py --json     # vuelca el GeoJSON normalizado
"""
import json
import sys
import datetime
import urllib.request
import urllib.parse

SERVICES = [
    "https://mapservices.weather.noaa.gov/tropical/rest/services/"
    "tropical/NHC_tropical_weather/MapServer",
    "https://mapservices.weather.noaa.gov/tropical/rest/services/"
    "tropical/NHC_tropical_weather_summary/MapServer",
]
MAPSERVER = SERVICES[0]
TIMEOUT = 25
UA = "CanalMeteoTV/1.0 (+https://canalmeteo.tv)"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _genesis_layer_ids() -> list:
    """
    IDs de la(s) capa(s) de polígono de génesis. La capa real del NHC se llama
    'Seven-Day: Potential Development Region' (id 3 hoy). Se busca por nombre
    para resistir cambios de id, con respaldo al id 3.
    """
    meta = _get_json(f"{MAPSERVER}?f=json")
    ids = []
    for lyr in meta.get("layers", []):
        if lyr.get("type") == "Group Layer":
            continue
        name = str(lyr.get("name", "")).lower()
        if "potential development region" in name or (
            "development region" in name and "seven" in name
        ):
            ids.append(lyr["id"])
    return ids or [3]


def _query_geojson(layer_id: int, svc: str = MAPSERVER) -> dict:
    params = urllib.parse.urlencode(
        {
            "where": "1=1",
            "outFields": "*",
            "outSR": "4326",
            "returnGeometry": "true",
            "f": "geojson",
        }
    )
    return _get_json(f"{svc}/{layer_id}/query?{params}")


def _num(*vals):
    """Primer valor convertible a número (admite '30', '30%', 30)."""
    for v in vals:
        if v is None:
            continue
        s = str(v).strip().replace("%", "")
        try:
            return int(round(float(s)))
        except (ValueError, TypeError):
            continue
    return None


def _risk(prob, *labels):
    """Nivel de riesgo a partir de etiqueta del NHC o del % de formación."""
    for lab in labels:
        t = str(lab or "").lower()
        if "high" in t or "alto" in t:
            return "high"
        if "medium" in t or "moder" in t or "media" in t:
            return "medium"
        if "low" in t or "baja" in t:
            return "low"
    if prob is None:
        return None
    if prob >= 60:
        return "high"
    if prob >= 40:
        return "medium"
    return "low"


def _centroid(geometry: dict):
    """Centroide aproximado (promedio de todos los vértices)."""
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (list, tuple)):
            if len(c) >= 2 and all(isinstance(n, (int, float)) for n in c[:2]):
                xs.append(c[0])
                ys.append(c[1])
            else:
                for x in c:
                    walk(x)

    walk(geometry.get("coordinates"))
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _basin_of(props: dict, geometry: dict):
    """Cuenca: por código/campo si existe; si no, por geografía del centroide."""
    code = str(props.get("basin") or props.get("BASIN") or "").strip().lower()
    if code in ("al", "atl", "natl", "atlantic"):
        return "atlantic"
    if code in ("ep", "cp", "epac", "pac", "east_pacific", "eastpac"):
        return "epac"
    tag = " ".join(
        str(props.get(k, "")) for k in ("BASIN", "basin", "AREA", "area")
    ).lower()
    if "atl" in tag:
        return "atlantic"
    if "pac" in tag or "epac" in tag or "east" in tag:
        return "epac"
    c = _centroid(geometry)
    if c:
        lon, lat = c
        if lon <= -100 or (lon <= -84 and lat <= 16):
            return "epac"
        return "atlantic"
    return None


def _debug():
    """Recorre ambas services, lista capas y cuenta features por capa."""
    for svc in SERVICES:
        print("\n" + "=" * 78)
        print(svc.rsplit("/services/", 1)[-1])
        print("=" * 78)
        try:
            meta = _get_json(f"{svc}?f=json")
        except Exception as e:  # noqa: BLE001
            print(f"  (no accesible: {e})")
            continue
        layers = meta.get("layers", [])
        if not layers:
            print("  (sin capas)")
            continue
        for lyr in layers:
            lid = lyr.get("id")
            name = lyr.get("name", "")
            ltype = lyr.get("type", "")
            if ltype == "Group Layer":
                print(f"  [{lid:>2}] {name}   <grupo>")
                continue
            n = "?"
            sample = ""
            try:
                params = urllib.parse.urlencode(
                    {"where": "1=1", "returnCountOnly": "true", "f": "json"}
                )
                cnt = _get_json(f"{svc}/{lid}/query?{params}")
                n = cnt.get("count", "?")
                if n not in ("?", 0):
                    gj = _query_geojson(lid, svc)
                    feats = gj.get("features", [])
                    if feats:
                        props = feats[0].get("properties", {})
                        gtype = (feats[0].get("geometry") or {}).get("type", "—")
                        keys = ", ".join(list(props.keys())[:12])
                        sample = f"\n        geom={gtype}  campos: {keys}"
            except Exception as e:  # noqa: BLE001
                n = f"err: {e}"
            print(f"  [{lid:>2}] {name}   features={n}{sample}")


def fetch_genesis_areas() -> dict:
    """
    Devuelve {"areas": [Feature,...], "updated": iso}.
    Cada Feature lleva properties normalizadas:
      basin, prob2day, risk2day, prob7day, risk7day, id
    Fuente: capa 'Seven-Day: Potential Development Region' del NHC.
    Campos reales: basin, prob2day, risk2day, prob7day, risk7day.
    """
    feats = []
    for lid in _genesis_layer_ids():
        try:
            gj = _query_geojson(lid)
            feats.extend(gj.get("features", []) or [])
        except Exception as e:  # noqa: BLE001
            print(f"[genesis] capa {lid} falló: {e}", file=sys.stderr)

    areas = []
    for f in feats:
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        if not geom.get("coordinates"):
            continue
        p2 = _num(props.get("prob2day"), props.get("PROB2DAY"))
        p7 = _num(props.get("prob7day"), props.get("PROB7DAY"))
        areas.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "basin": _basin_of(props, geom),
                    "prob2day": p2,
                    "risk2day": _risk(p2, props.get("risk2day"), props.get("RISK2DAY")),
                    "prob7day": p7,
                    "risk7day": _risk(p7, props.get("risk7day"), props.get("RISK7DAY")),
                    "id": props.get("objectid") or props.get("OBJECTID"),
                },
            }
        )

    return {"areas": areas, "updated": _now_iso()}


if __name__ == "__main__":
    if "--debug" in sys.argv:
        _debug()
        sys.exit(0)
    g = fetch_genesis_areas()
    if "--json" in sys.argv:
        print(json.dumps(g, indent=2))
    else:
        areas = g["areas"]
        print(f"Áreas de génesis: {len(areas)}  (actualizado {g['updated']})")
        for a in areas:
            pr = a["properties"]
            print(
                f"  · cuenca={pr['basin']:8}  "
                f"2d={pr['prob2day']}% ({pr['risk2day']})  "
                f"7d={pr['prob7day']}% ({pr['risk7day']})"
            )
