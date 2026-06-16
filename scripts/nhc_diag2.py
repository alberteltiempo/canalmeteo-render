#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico: por qué génesis(0)/prob(394) no resuelven hojas. Importa el pipeline real."""
import json
import sys
import urllib.request

sys.path.insert(0, "/opt/canalmeteo/scripts")
import nhc_gis_pipeline as p

MAP = p.MAPSERVER


def g(url):
    req = urllib.request.Request(url, headers={"User-Agent": "diag/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))

print("== Entradas crudas de /layers para 0, 1, 394, 399 ==")
raw = g(MAP + "/layers?f=pjson")
layers = raw.get("layers", [])
print(f"total capas: {len(layers)}")
idx = {ly.get("id"): ly for ly in layers}
for lid in (0, 1, 394, 399):
    ly = idx.get(lid)
    if not ly:
        print(f"  id={lid}: NO PRESENTE en /layers")
        continue
    print(f"  id={lid}: name={ly.get('name')!r} type={ly.get('type')!r} "
          f"geom={ly.get('geometryType')!r} parent={ly.get('parentLayerId')!r} "
          f"sub={ly.get('subLayerIds')!r}")

print("\n== ¿Qué capas dicen tener parent 0 o 394? ==")
for ly in layers:
    if ly.get("parentLayerId") in (0, 394):
        print(f"  id={ly.get('id')} parent={ly.get('parentLayerId')} name={ly.get('name')!r}")

print("\n== Resolución con las funciones del pipeline ==")
tree = p.get_layer_tree()
ch = p.build_children(tree)
print("children[0]   =", ch.get(0))
print("children[394] =", ch.get(394))
print("children[399] =", ch.get(399))
print("descendant_leaves(0)   =", p.descendant_leaves(tree, ch, 0))
print("descendant_leaves(394) =", p.descendant_leaves(tree, ch, 394))

print("\n== Sondear hojas vía /MapServer/0 y /MapServer/394 directamente ==")
for gid in (0, 399, 394):
    meta = g(f"{MAP}/{gid}?f=pjson")
    subs = meta.get("subLayers") or []
    print(f"  /{gid} subLayers (metadata directa):",
          [(s.get('id'), s.get('name')) for s in subs])
