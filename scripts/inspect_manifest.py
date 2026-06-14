#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_manifest.py — Diagnóstico rápido de estructura de un manifest HRRR.

Uso:
    /opt/canalmeteo/venv/bin/python inspect_manifest.py \
        /opt/canalmeteo/data/hrrr_output/hrrr-18h/manifest.json
"""

import json
import sys
from pathlib import Path


def inspect(manifest_path):
    p = Path(manifest_path)
    if not p.exists():
        print(f'ERROR: No existe {p}')
        return 1

    base_dir = p.parent
    print(f'═══ Inspección manifest ═══')
    print(f'Manifest: {p}')
    print(f'Base dir: {base_dir}')

    with open(p) as f:
        m = json.load(f)

    print(f'\n── Top-level keys ──')
    for k, v in m.items():
        if k == 'variables':
            print(f'  {k}: {len(v)} variables')
        elif isinstance(v, (list, dict)):
            print(f'  {k}: ({type(v).__name__} con {len(v)} items)')
        else:
            print(f'  {k}: {v!r}')

    if 'variables' not in m:
        print('⚠ El manifest no tiene "variables", formato inesperado')
        return 1

    print(f'\n── Variables disponibles ──')
    for var_key in list(m['variables'].keys())[:25]:
        var = m['variables'][var_key]
        n_frames = len(var.get('frames', []))
        vmin = var.get('vmin', '?')
        vmax = var.get('vmax', '?')
        cmap = var.get('cmap', '?')
        unit = var.get('unit', '?')
        print(f'  {var_key:<15}  frames={n_frames:>3}  vmin={vmin!r:>8} vmax={vmax!r:>8}  cmap={cmap!r:<14} unit={unit!r}')

    # Tomar la primera variable para inspeccionar los frames
    print(f'\n── Inspección de frames (primera variable) ──')
    first_key = list(m['variables'].keys())[0]
    first_var = m['variables'][first_key]
    frames = first_var.get('frames', [])
    print(f'Variable: {first_key}, total frames: {len(frames)}')

    if not frames:
        print('  ⚠ Sin frames')
        return 1

    print(f'\nPrimeros 3 frames del manifest:')
    for f in frames[:3]:
        print(f'  fxx={f.get("fxx")}, png={f.get("png")!r}, valid_time={f.get("valid_time")!r}')

    # Verificar que los PNGs existen
    print(f'\n── Verificación de rutas de PNG ──')
    print(f'Probando 3 estrategias de resolución de path:')
    sample = frames[0]
    png_field = sample.get('png', '')

    candidates = [
        ('Como está en manifest (relativo a manifest)', base_dir / png_field),
        ('Subdir variable (var/file.png)', base_dir / first_key / Path(png_field).name),
        ('Plano (solo nombre)', base_dir / Path(png_field).name),
    ]
    for desc, candidate in candidates:
        exists = candidate.exists()
        marker = '✓' if exists else '✗'
        print(f'  {marker} {desc}')
        print(f'      → {candidate}')

    # Listar el subdir de la variable para ver el formato real
    var_subdir = base_dir / first_key
    if var_subdir.is_dir():
        print(f'\n── Contenido de {var_subdir} (primeros 5 archivos) ──')
        files = sorted(var_subdir.iterdir())[:5]
        for f in files:
            print(f'  {f.name}')

    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f'Uso: {sys.argv[0]} <ruta_a_manifest.json>')
        sys.exit(1)
    sys.exit(inspect(sys.argv[1]))
