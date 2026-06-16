#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nhc_probe.py — Sondeo de las fuentes GIS del NHC (NO escribe nada, solo inspecciona).

Objetivo: confirmar contra el servidor en vivo (desde nimbus, que sí alcanza NOAA)
  1) qué tormentas hay activas y su binNumber (AT1, EP2, ...),
  2) el árbol de capas del MapServer y los IDs hoja por bin,
  3) los campos reales y el tipo de geometría de cada capa relevante,
  4) que la consulta f=geojson&outSR=4326 funciona end-to-end.

Uso:
    python3 nhc_probe.py

Pega la salida completa para afinar el pipeline. No requiere dependencias externas.
"""

import json
import sys
import urllib.parse
import urllib.request

MAPSERVER = ("https://mapservices.weather.noaa.gov/tropical/rest/services/"
             "tropical/NHC_tropical_weather/MapServer")
CURRENT_STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"
UA = "CanalMeteoNHCProbe/1.0 (+https://canalmeteo.tv)"
TIMEOUT = 30

# Capas hoja "fijas" (siempre presentes, no dependen de tormentas activas)
STATIC_LEAVES = {
    1: "Two-Day: Current Location (génesis 2 días)",
    399: "Seven-Day Outlook (génesis 7 días)",
    394: "Probabilistic Winds (vientos probabilísticos)",
}


def http_json(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def hr(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def probe_current_storms():
    hr("1) CurrentStorms.json — tormentas activas")
    try:
        data = http_json(CURRENT_STORMS)
    except Exception as e:
        print(f"  ERROR alcanzando CurrentStorms.json: {e}")
        return []
    storms = data.get("activeStorms", []) or []
    if not storms:
        print("  Sin tormentas activas ahora mismo (activeStorms vacío).")
        return []
    bins = []
    for s in storms:
        b = s.get("binNumber")
        bins.append(b)
        print(f"  - {s.get('id')}  bin={b}  {s.get('name')} "
              f"[{s.get('classification')}]  {s.get('intensity')}kt  "
              f"{s.get('latitude')},{s.get('longitude')}")
        # qué productos trae el JSON (no null)
        prods = [k for k in (
            "trackCone", "forecastTrack", "windWatchesWarnings",
            "initialWindExtent", "forecastWindRadiiGIS",
            "earliestArrivalTimeTSWindsGIS", "mostLikelyTimeTSWindsGIS",
            "windSpeedProbabilitiesGIS", "stormSurgeWatchWarningGIS",
            "potentialStormSurgeFloodingGIS", "peakSurgeKML")
            if s.get(k)]
        print(f"      productos JSON disponibles: {', '.join(prods) or 'ninguno'}")
    return [b for b in bins if b]


def probe_layer_tree(active_bins):
    hr("2) Árbol de capas del MapServer (/layers)")
    try:
        tree = http_json(MAPSERVER + "/layers", {"f": "pjson"})
    except Exception as e:
        print(f"  ERROR alcanzando /layers: {e}")
        return {}
    layers = tree.get("layers", []) or []
    by_id = {}
    for ly in layers:
        by_id[ly.get("id")] = {
            "name": ly.get("name"),
            "parent": ly.get("parentLayerId"),
            "type": ly.get("type"),
            "geom": ly.get("geometryType"),
        }
    print(f"  Total de capas en el servicio: {len(by_id)}")

    # Hojas relacionadas con cada bin activo (match por prefijo de nombre)
    relevant = dict(STATIC_LEAVES)  # arranca con las fijas
    if active_bins:
        for lid, info in by_id.items():
            name = (info["name"] or "")
            for b in active_bins:
                if name.startswith(b + " ") or name == b:
                    relevant[lid] = name
    print(f"\n  Hojas relevantes a inspeccionar (fijas + bins activos):")
    for lid in sorted(relevant):
        info = by_id.get(lid, {})
        ltype = info.get("type") or "?"
        lgeom = info.get("geom") or "-"
        print(f"   id={lid:>4}  type={ltype:<12} "
              f"geom={lgeom:<22} name={relevant[lid]}")
    return relevant, by_id


def probe_leaf(lid, label):
    print(f"\n  --- capa {lid}: {label} ---")
    # metadata: campos + geometría
    try:
        meta = http_json(f"{MAPSERVER}/{lid}", {"f": "pjson"})
        gtype = meta.get("geometryType")
        ltype = meta.get("type")
        fields = [f.get("name") for f in (meta.get("fields") or [])]
        print(f"      type={ltype}  geometryType={gtype}")
        if ltype == "Group Layer":
            print("      (capa grupo — no consultable; sus hijas llevan la geometría)")
            return
        print(f"      campos ({len(fields)}): {', '.join(fields) if fields else 'ninguno'}")
    except Exception as e:
        print(f"      ERROR metadata: {e}")
        return
    # query geojson de muestra
    try:
        gj = http_json(f"{MAPSERVER}/{lid}/query", {
            "where": "1=1", "outFields": "*", "outSR": "4326",
            "returnGeometry": "true", "resultRecordCount": "3", "f": "geojson",
        })
        feats = gj.get("features", []) or []
        print(f"      f=geojson OK — features de muestra: {len(feats)}")
        if feats:
            g = feats[0].get("geometry") or {}
            props = feats[0].get("properties") or {}
            print(f"      geometría[0]: {g.get('type')}")
            sample = {k: props[k] for k in list(props)[:8]}
            print(f"      props[0] (8 primeras): {json.dumps(sample, ensure_ascii=False)}")
    except Exception as e:
        print(f"      ERROR query geojson: {e}")


def main():
    print("Sondeo NHC GIS — Canal Meteo")
    print("Servidor:", MAPSERVER)
    active = probe_current_storms()
    relevant, _ = probe_layer_tree(active)
    hr("3) Inspección de cada capa hoja relevante")
    for lid in sorted(relevant):
        probe_leaf(lid, relevant[lid])
    hr("FIN del sondeo — pega TODA esta salida")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
