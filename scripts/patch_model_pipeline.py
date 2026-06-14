#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_model_pipeline.py — Patch automático para añadir guardado de .npz.

Modifica in-place /opt/canalmeteo/scripts/model_pipeline.py:
  1. Añade un nuevo parámetro `save_npz` a render_to_png()
  2. Después de generar el PNG, también guarda los valores crudos como .npz
  3. El .npz va junto al PNG: si PNG es tmp_2m/f00.png → tmp_2m/f00.npz

El parche es idempotente (puedes correrlo múltiples veces).
Crea un backup del archivo original antes de modificarlo.

Uso:
    python patch_model_pipeline.py /opt/canalmeteo/scripts/model_pipeline.py
"""

import sys
import re
import shutil
from pathlib import Path
from datetime import datetime


def patch_file(target_path):
    target = Path(target_path)
    if not target.exists():
        print(f'❌ No existe: {target}')
        return 1

    content = target.read_text()

    # ─── Verificar si ya está parcheado ───
    if 'NPZ_PATCH_APPLIED_v53' in content:
        print(f'✓ El archivo ya está parcheado (NPZ_PATCH_APPLIED_v53 marker presente)')
        return 0

    # ─── Backup del original ───
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = target.with_suffix(f'.py.pre-npz-{timestamp}.bak')
    shutil.copy(target, backup)
    print(f'📦 Backup creado: {backup}')

    # ─── Patch 1: añadir parámetro save_npz a la firma ───
    old_signature = 'def render_to_png(data, lats, lons, var_config, output_path):'
    new_signature = 'def render_to_png(data, lats, lons, var_config, output_path, save_npz=True):'
    if old_signature not in content:
        print(f'⚠ No se encontró la firma esperada de render_to_png')
        print(f'  Buscando: {old_signature}')
        return 2
    content = content.replace(old_signature, new_signature, 1)
    print(f'✓ Patch 1: firma de render_to_png actualizada')

    # ─── Patch 2: guardar .npz después de fig.savefig ───
    # Buscamos el patrón: fig.savefig(...); plt.close(fig)
    # Y añadimos el guardado del .npz justo antes del plt.close
    old_savefig = '''    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, transparent=True, dpi=RENDER_DPI, pad_inches=0)
    plt.close(fig)'''

    new_savefig = '''    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, transparent=True, dpi=RENDER_DPI, pad_inches=0)
    plt.close(fig)

    # ─── NPZ_PATCH_APPLIED_v53: guardar valores crudos para interpolate_frames.py ───
    # Esto evita que interpolate_frames.py tenga que decodificar el PNG (lento).
    # El .npz se guarda junto al PNG con el mismo nombre.
    if save_npz:
        try:
            import numpy as _np_npz
            npz_path = output_path.with_suffix('.npz')
            # Guardamos los valores ya procesados (post-smoothing, post-zoom)
            # comprimidos para no inflar el disco
            _np_npz.savez_compressed(npz_path, values=data.astype(_np_npz.float32))
        except Exception as _e:
            # Si falla, no rompemos el pipeline (el PNG ya está guardado)
            import logging as _logging
            _logging.getLogger().warning(f'No se pudo guardar npz {npz_path}: {_e}')'''

    if old_savefig not in content:
        print(f'⚠ No se encontró el bloque de fig.savefig esperado')
        # Mostrar líneas alrededor para debug
        return 3
    content = content.replace(old_savefig, new_savefig, 1)
    print(f'✓ Patch 2: guardado de .npz añadido')

    # ─── Escribir archivo modificado ───
    target.write_text(content)
    print(f'✓ Archivo actualizado: {target}')
    print()
    print('═══ Resumen ═══')
    print(f'  Original respaldado en: {backup}')
    print(f'  Marker añadido: NPZ_PATCH_APPLIED_v53')
    print()
    print('Para revertir:')
    print(f'  cp {backup} {target}')
    print()
    print('Para verificar:')
    print(f'  grep -n NPZ_PATCH_APPLIED_v53 {target}')

    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f'Uso: {sys.argv[0]} <ruta_a_model_pipeline.py>')
        sys.exit(1)
    sys.exit(patch_file(sys.argv[1]))
