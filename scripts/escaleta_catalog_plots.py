#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica en catalog.json los "plots" editables por producto y escena, para el
editor de posición de la intranet (placement.php).

Por cada proyecto Remotion extrae los catálogos curados de cdn.ts
(CONDITION_CITIES, AIRPORT_CATALOG, SERVICE_CITIES, TMAX_CITY_CATALOG) y las
fórmulas boxSize REALES de cada escena (difieren entre CONUS y regionales), y
sube:
  products[slug].plots = {escena: [{id, label, name, key, lon, lat, w, h}]}
      id    = clave de la posición fijada / on-off (nombre en condiciones, IATA
              en aeropuertos, id del feed en uv/aqi/tmax)
      key   = clave con la que el feed publica el valor (condiciones:
              "City|State" de weather.json; el resto = id)
      name  = texto que determina el ANCHO de la caja (fórmula boxSize)
      label = texto que muestra el editor
  products[slug].box   = {escena: {base, mn, mult, add, h}} — la fórmula
      w = base + max(mn, len(name)*mult + add), para ciudades añadidas.
  products[slug].layout = {escena: {top, force:{id:lado}, nudge:{id:[dx,dy]}}}
      — parámetros del colocador (placeChips) tal como los usa el render,
      para que el auto-placement en vivo del editor coincida con la antena.
  master = {escena: [{id, label, name, key, lon, lat}]} — UNIÓN de los
      catálogos de los 9 proyectos: las ciudades que se pueden AÑADIR a un
      producto desde el editor (los feeds ya publican todas ellas). Las 3
      escenas de temperatura comparten el juego "tmax".

Re-ejecutar cuando cambien los catálogos de ciudades o los boxSize:
  python3 scripts/escaleta_catalog_plots.py
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path("/opt/canalmeteo/remotion")
AWS = ["aws", "--profile", "do-tor1", "--endpoint-url", "https://sfo3.digitaloceanspaces.com"]
BUCKET = "s3://canalmeteo-public"

SLUG2PROJ = {
    "tiempo-conus": "tiempo_CONUS", "tiempo-fl": "tiempo_FL", "tiempo-se": "tiempo_SE",
    "tiempo-ne": "tiempo_NE", "tiempo-sp": "tiempo_SP", "tiempo-mw": "tiempo_MW",
    "tiempo-np": "tiempo_NP", "tiempo-nw": "tiempo_NW", "tiempo-sw": "tiempo_SW",
}

BOX_RE = re.compile(
    r"boxSize=\{\(\w+\) => \(\{ w: (?:(\d+) \+ )?Math\.max\((\d+), \w+\.(?:city|name)\.length \* ([\d.]+) \+ (\d+)\), h: (\d+) \}\)\}"
)

# Escena → juego de ciudades (las 3 de temperatura comparten "tmax").
CITY_SET = {
    "condiciones": "condiciones", "aeropuertos": "aeropuertos", "uv": "uv", "aqi": "aqi",
    "tmax_today": "tmax", "tmax_tomorrow": "tmax", "tvar": "tmax",
}


def const_block(src: str, name: str) -> str:
    m = re.search(rf"const {name}[^=]*=\s*\[(.*?)\n\];", src, re.S)
    assert m, name
    return m.group(1)


def entries(block: str, fields: list[str]) -> list[dict]:
    out = []
    for line in block.splitlines():
        row = {}
        for f in fields:
            m = re.search(rf'{f}:\s*(?:"([^"]+)"|(-?[\d.]+))', line)
            if not m:
                row = None
                break
            row[f] = m.group(1) if m.group(1) is not None else float(m.group(2))
        if row:
            out.append(row)
    return out


def box_params(base, mn, mult, add, h) -> dict:
    base, mn, mult, add, h = (float(x) for x in (base or 0, mn, mult, add, h))
    return {"base": base, "mn": mn, "mult": mult, "add": add, "h": h}


def box_fn(params: dict):
    p = params
    return lambda name: {"w": round(p["base"] + max(p["mn"], len(name) * p["mult"] + p["add"])), "h": round(p["h"])}


FORCE_RE = re.compile(r'(?:"([^"]+)"|(\w+))\s*:\s*"(left|right|up|down)"')
NUDGE_RE = re.compile(r'(?:"([^"]+)"|(\w+))\s*:\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]')


def table(src: str, name: str, rx: re.Pattern, as_nudge: bool) -> dict:
    """Tabla `const NAME: ... = { id: "left", ... }` (o nudges [dx,dy]) → dict.
    Ausente → {} (no todos los proyectos definen todas)."""
    m = re.search(rf"const {name}\b[^=]*=\s*\{{(.*?)\}};", src, re.S)
    if not m:
        return {}
    body = re.sub(r"//[^\n]*", "", m.group(1))  # fuera comentarios de línea
    out = {}
    for g in rx.findall(body):
        key = g[0] or g[1]
        out[key] = [float(g[2]), float(g[3])] if as_nudge else g[2]
    return out


def layout_for(proj: str, cdn: str, svc: str, fc: str, cond_scene: str) -> dict:
    """Parámetros del colocador por escena, tal como los usa el render: margen
    superior (topPad), lados forzados y empujones. El editor los replica para
    que el auto-placement en vivo coincida con la antena."""
    # topPad de cada *Content (props del ServiceMap); ausente → 135 (default del
    # componente, p. ej. AirportsContent en SE).
    def top_of(src: str, comp: str) -> int:
        # Hasta el cierre del componente (`);` a columna 0): topPad puede ir
        # antes o después de renderChip según el proyecto.
        m = re.search(rf"const {comp}\b.*?\n\);", src, re.S)
        assert m, (proj, comp)
        t = re.search(r"topPad=\{(\d+)\}", m.group(0))
        return int(t.group(1)) if t else 135
    svc_top = [top_of(svc, c) for c in ("AirportsContent", "UvContent", "AqiContent")]
    fc_top = [top_of(fc, c) for c in ("TmaxContent", "TvarContent")]
    m = re.search(r"placeChips\(projected, width, height, (\d+), height - 56, (\w+|\{\})", cond_scene)
    assert m, (proj, "placeChips condiciones")
    cond_top = int(m.group(1))
    cond_force = table(cond_scene, m.group(2), FORCE_RE, False) if m.group(2) != "{}" else {}
    svc_force = table(svc, "SERVICE_FORCE", FORCE_RE, False)
    svc_nudge = table(svc, "SERVICE_NUDGE", NUDGE_RE, True)
    air_nudge = table(svc, "AIRPORT_NUDGE", NUDGE_RE, True)
    tmp_force = table(fc, "TEMP_FORCE", FORCE_RE, False)
    tmp_nudge = table(fc, "TEMP_NUDGE", NUDGE_RE, True)
    tmax = {"top": fc_top[0], "force": tmp_force, "nudge": tmp_nudge}
    return {
        "condiciones": {"top": cond_top, "force": cond_force, "nudge": {}},
        "aeropuertos": {"top": svc_top[0], "force": {}, "nudge": air_nudge},
        "uv": {"top": svc_top[1], "force": svc_force, "nudge": svc_nudge},
        "aqi": {"top": svc_top[2], "force": svc_force, "nudge": svc_nudge},
        "tmax_today": tmax, "tmax_tomorrow": tmax,
        "tvar": {"top": fc_top[1], "force": tmp_force, "nudge": tmp_nudge},
    }


def catalogs_for(proj: str) -> tuple[dict, dict, dict]:
    """Devuelve ({juego: [ciudades]}, {escena: box_params}, {escena: layout})."""
    cdn = (ROOT / proj / "src/lib/cdn.ts").read_text()
    svc = (ROOT / proj / "src/scenes/ServicesMockups.tsx").read_text()
    fc = (ROOT / proj / "src/scenes/ForecastMockups.tsx").read_text()
    cond_scene = (ROOT / proj / "src/scenes/CondicionesNow.tsx").read_text()
    layout = layout_for(proj, cdn, svc, fc, cond_scene)

    # boxSize por orden de aparición: services = aeropuertos, uv, aqi; forecast = tmax, tvar.
    svc_boxes = BOX_RE.findall(svc)
    fc_boxes = BOX_RE.findall(fc)
    assert len(svc_boxes) == 3 and len(fc_boxes) == 2, (proj, len(svc_boxes), len(fc_boxes))
    air_p, uv_p, aqi_p = (box_params(*b) for b in svc_boxes)
    tmax_p = box_params(*fc_boxes[0])

    # estimateBox de condiciones (lib/conditions.ts): w = 33 + max(210, len*18+34, 132), h = 170.
    cond = (ROOT / proj / "src/lib/conditions.ts").read_text()
    m = re.search(r"const nameW = name\.length \* (\d+) \+ (\d+);\s*\n\s*return \{ w: (\d+) \+ Math\.max\((\d+), nameW, \d+\), h: (\d+) \}", cond)
    assert m, (proj, "estimateBox")
    c_mult, c_add, c_base, c_min, c_h = (int(x) for x in m.groups())
    cond_p = {"base": c_base, "mn": c_min, "mult": c_mult, "add": c_add, "h": c_h}

    conds = entries(const_block(cdn, "CONDITION_CITIES"), ["key", "name", "lon", "lat"])
    airs = entries(const_block(cdn, "AIRPORT_CATALOG"), ["iata", "city", "lon", "lat"])
    svcs = entries(const_block(cdn, "SERVICE_CITIES"), ["id", "name", "lon", "lat"])
    tmaxs = entries(const_block(cdn, "TMAX_CITY_CATALOG"), ["id", "name", "lon", "lat"])
    assert conds and airs and svcs and tmaxs, proj

    sets = {
        "condiciones": [{"id": c["name"], "label": c["name"], "name": c["name"], "key": c["key"],
                         "lon": c["lon"], "lat": c["lat"]} for c in conds],
        "aeropuertos": [{"id": a["iata"], "label": f"{a['city']} ({a['iata']})", "name": a["city"],
                         "key": a["iata"], "lon": a["lon"], "lat": a["lat"]} for a in airs],
        "uv": [{"id": s["id"], "label": s["name"], "name": s["name"], "key": s["id"],
                "lon": s["lon"], "lat": s["lat"]} for s in svcs],
        "tmax": [{"id": t["id"], "label": t["name"], "name": t["name"], "key": t["id"],
                  "lon": t["lon"], "lat": t["lat"]} for t in tmaxs],
    }
    sets["aqi"] = sets["uv"]
    boxes = {
        "condiciones": cond_p, "aeropuertos": air_p, "uv": uv_p, "aqi": aqi_p,
        "tmax_today": tmax_p, "tmax_tomorrow": tmax_p, "tvar": tmax_p,
    }
    return sets, boxes, layout


def main() -> None:
    r = subprocess.run(AWS + ["s3", "cp", f"{BUCKET}/data/escaleta/catalog.json", "-"],
                       capture_output=True, text=True, check=True)
    cat = json.loads(r.stdout)
    master: dict[str, dict[str, dict]] = {k: {} for k in ("condiciones", "aeropuertos", "uv", "aqi", "tmax")}
    for slug, proj in SLUG2PROJ.items():
        sets, boxes, layout = catalogs_for(proj)
        plots = {}
        for scene, setname in CITY_SET.items():
            box = box_fn(boxes[scene])
            plots[scene] = [{**c, **box(c["name"])} for c in sets[setname]]
        prod = cat["products"][slug]
        prod["plots"] = plots
        prod["box"] = boxes
        prod["layout"] = layout
        prod.pop("cities", None)  # formato antiguo (solo condiciones)
        for setname, rows in sets.items():
            for c in rows:
                master[setname].setdefault(c["id"], c)
        print(f"{slug}: " + ", ".join(f"{k}={len(v)}" for k, v in plots.items()))
    cat["master"] = {k: sorted(v.values(), key=lambda c: c["label"]) for k, v in master.items()}
    print("master: " + ", ".join(f"{k}={len(v)}" for k, v in cat["master"].items()))
    out = Path("/tmp/escaleta_catalog.json")
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n")
    subprocess.run(AWS + ["s3", "cp", str(out), f"{BUCKET}/data/escaleta/catalog.json",
                          "--content-type", "application/json", "--acl", "public-read",
                          "--cache-control", "no-cache", "--quiet"], check=True)
    print("catalog.json publicado")


if __name__ == "__main__":
    main()
