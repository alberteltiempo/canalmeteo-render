#!/usr/bin/env python3
"""
verify_run_complete.py — Verifica si un run HRRR está completo antes de sync.

Exit codes:
  0 = Run completo, OK para sync
  1 = Run incompleto, NO sincronizar
  2 = Manifest no encontrado o corrupto
"""
import json
import sys
from pathlib import Path

# Esperado por producto
EXPECTED = {
    'hrrr-18h': {
        'forecast_hours': 19,    # F00-F18
        'variables_min': 18,     # casi todas (≥18 de 19)
        'min_total_frames': 280, # 19 vars × 15 frames mínimo
    },
    'hrrr-48h': {
        'forecast_hours': 49,    # F00-F48
        'variables_min': 11,     # casi todas (≥11 de 12)
        'min_total_frames': 480, # 12 vars × 40 frames mínimo
    }
}


def verify(product: str, run_dir: Path) -> int:
    manifest_path = run_dir / 'manifest.json'
    if not manifest_path.exists():
        print(f'❌ [{product}] Manifest no encontrado: {manifest_path}', file=sys.stderr)
        return 2

    try:
        with open(manifest_path) as f:
            m = json.load(f)
    except Exception as e:
        print(f'❌ [{product}] Manifest corrupto: {e}', file=sys.stderr)
        return 2

    expected = EXPECTED[product]
    variables = m.get('variables', {})

    if len(variables) < expected['variables_min']:
        print(f'⚠️  [{product}] Solo {len(variables)} variables (esperado ≥{expected["variables_min"]})')
        return 1

    total_frames = 0
    incomplete_vars = []
    for var_key, var_data in variables.items():
        frames = var_data.get('frames', [])
        total_frames += len(frames)
        # Cada variable debe tener al menos 15 frames base (de 19 esperados)
        if len(frames) < 15:
            incomplete_vars.append(f'{var_key}({len(frames)})')

    if total_frames < expected['min_total_frames']:
        print(f'⚠️  [{product}] Solo {total_frames} frames totales (esperado ≥{expected["min_total_frames"]})')
        return 1

    if len(incomplete_vars) > 3:
        # Más de 3 variables incompletas = run defectuoso
        print(f'⚠️  [{product}] {len(incomplete_vars)} variables incompletas: {", ".join(incomplete_vars[:5])}')
        return 1

    print(f'✅ [{product}] Run completo: {len(variables)} vars, {total_frames} frames')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Uso: verify_run_complete.py <product> <run_dir>', file=sys.stderr)
        sys.exit(2)
    product = sys.argv[1]
    run_dir = Path(sys.argv[2])
    if product not in EXPECTED:
        print(f'❌ Producto desconocido: {product}', file=sys.stderr)
        sys.exit(2)
    sys.exit(verify(product, run_dir))
