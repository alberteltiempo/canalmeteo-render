#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica en catalog.json los "plots" editables por producto y escena, para el
editor de posición de la intranet (placement.php).

Por cada proyecto Remotion extrae los catálogos curados de cdn.ts
(CONDITION_CITIES, AIRPORT_CATALOG, SERVICE_CITIES, TMAX_CITY_CATALOG) y las
fórmulas boxSize REALES de cada escena (difieren entre CONUS y regionales), y
sube products[slug].plots = {escena: [{id, label, lon, lat, w, h}]}. El editor
usa w/h para dibujar el contorno de la caja a escala y lon/lat para pintar el
punto de la ciudad (reproyección mercator en JS).

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


def box_fn(base, mn, mult, add, h):
    base, mn, mult, add, h = (float(x) for x in (base or 0, mn, mult, add, h))
    return lambda label: {"w": round(base + max(mn, len(label) * mult + add)), "h": round(h)}


def plots_for(proj: str) -> dict:
    cdn = (ROOT / proj / "src/lib/cdn.ts").read_text()
    svc = (ROOT / proj / "src/scenes/ServicesMockups.tsx").read_text()
    fc = (ROOT / proj / "src/scenes/ForecastMockups.tsx").read_text()

    # boxSize por orden de aparición: services = aeropuertos, uv, aqi; forecast = tmax, tvar.
    svc_boxes = BOX_RE.findall(svc)
    fc_boxes = BOX_RE.findall(fc)
    assert len(svc_boxes) == 3 and len(fc_boxes) == 2, (proj, len(svc_boxes), len(fc_boxes))
    air_box, uv_box, aqi_box = (box_fn(*b) for b in svc_boxes)
    tmax_box = box_fn(*fc_boxes[0])

    # estimateBox de condiciones (lib/conditions.ts): w = 33 + max(210, len*18+34, 132), h = 170.
    cond = (ROOT / proj / "src/lib/conditions.ts").read_text()
    m = re.search(r"const nameW = name\.length \* (\d+) \+ (\d+);\s*\n\s*return \{ w: (\d+) \+ Math\.max\((\d+), nameW, \d+\), h: (\d+) \}", cond)
    assert m, (proj, "estimateBox")
    c_mult, c_add, c_base, c_min, c_h = (int(x) for x in m.groups())
    cond_box = lambda label: {"w": c_base + max(c_min, len(label) * c_mult + c_add), "h": c_h}

    conds = entries(const_block(cdn, "CONDITION_CITIES"), ["name", "lon", "lat"])
    airs = entries(const_block(cdn, "AIRPORT_CATALOG"), ["iata", "city", "lon", "lat"])
    svcs = entries(const_block(cdn, "SERVICE_CITIES"), ["id", "name", "lon", "lat"])
    tmaxs = entries(const_block(cdn, "TMAX_CITY_CATALOG"), ["id", "name", "lon", "lat"])
    assert conds and airs and svcs and tmaxs, proj

    def rows(items, id_f, label_f, box, label_fmt=None):
        return [
            {"id": it[id_f], "label": label_fmt(it) if label_fmt else it[label_f],
             "lon": it["lon"], "lat": it["lat"], **box(it[label_f])}
            for it in items
        ]

    uv_aqi = lambda box: rows(svcs, "id", "name", box)
    tmax_rows = rows(tmaxs, "id", "name", tmax_box)
    return {
        "condiciones": rows(conds, "name", "name", cond_box),
        "aeropuertos": rows(airs, "iata", "city", air_box, label_fmt=lambda it: f"{it['city']} ({it['iata']})"),
        "uv": uv_aqi(uv_box),
        "aqi": uv_aqi(aqi_box),
        "tmax_today": tmax_rows,
        "tmax_tomorrow": tmax_rows,
        "tvar": tmax_rows,
    }


def main() -> None:
    r = subprocess.run(AWS + ["s3", "cp", f"{BUCKET}/data/escaleta/catalog.json", "-"],
                       capture_output=True, text=True, check=True)
    cat = json.loads(r.stdout)
    for slug, proj in SLUG2PROJ.items():
        pl = plots_for(proj)
        cat["products"][slug]["plots"] = pl
        cat["products"][slug].pop("cities", None)  # formato antiguo (solo condiciones)
        print(f"{slug}: " + ", ".join(f"{k}={len(v)}" for k, v in pl.items()))
    out = Path("/tmp/escaleta_catalog.json")
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n")
    subprocess.run(AWS + ["s3", "cp", str(out), f"{BUCKET}/data/escaleta/catalog.json",
                          "--content-type", "application/json", "--acl", "public-read",
                          "--cache-control", "no-cache", "--quiet"], check=True)
    print("catalog.json publicado")


if __name__ == "__main__":
    main()
