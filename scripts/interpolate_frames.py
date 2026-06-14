#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
interpolate_frames.py v1.4 — Interpolación temporal HRRR con .npz fastpath.

CAMBIOS vs v1.3:
- Lee .npz directamente si está disponible (skip decode = ~10× más rápido)
- Fallback automático a decode PNG si no hay .npz
- Genera .npz también para los sub-frames interpolados

REQUIERE patch v5.3 en model_pipeline.py para máximo rendimiento.
Si no está parcheado, sigue funcionando con decode PNG (más lento).

Tiempo esperado en droplet 2 cores:
  - Sin .npz (decode PNG): ~15-20 min
  - Con .npz fastpath:     ~2-3 min  ⚡

Uso:
    python interpolate_frames.py --product hrrr-18h \\
        --run-dir /opt/canalmeteo/data/hrrr_output/hrrr-18h
"""

import argparse
import json
import logging
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

# ═══════════════════════════════════════════════════════════════════════════
# Importar paletas reales de hrrr_variables.py
# ═══════════════════════════════════════════════════════════════════════════
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import hrrr_variables as hv
    HRRR_VARS_AVAILABLE = True
except ImportError as e:
    print(f'⚠ No se pudo importar hrrr_variables: {e}', file=sys.stderr)
    HRRR_VARS_AVAILABLE = False


def get_variable_cmap(var_key):
    """Devuelve el cmap (matplotlib Colormap object) para una variable."""
    if HRRR_VARS_AVAILABLE and hasattr(hv, 'VARIABLES'):
        cfg = hv.VARIABLES.get(var_key)
        if cfg and 'cmap' in cfg:
            cmap = cfg['cmap']
            if isinstance(cmap, str):
                import matplotlib
                if hasattr(matplotlib, 'colormaps'):
                    return matplotlib.colormaps[cmap]
                else:
                    import matplotlib.cm as cm
                    return cm.get_cmap(cmap)
            return cmap

    import matplotlib
    if hasattr(matplotlib, 'colormaps'):
        return matplotlib.colormaps['viridis']
    else:
        import matplotlib.cm as cm
        return cm.get_cmap('viridis')


# ═══════════════════════════════════════════════════════════════════════════
# Variables interpolables vs no
# ═══════════════════════════════════════════════════════════════════════════
INTERPOLATE_VARS = {
    # Temperatura y derivadas
    'tmp_2m', 'dpt_2m', 'apt', 'apt_2m', 'rh_2m',
    # Presión
    'mslp', 'prmsl', 'pres_sfc',
    # Viento
    'uwnd_10m', 'vwnd_10m', 'wspd_10m', 'wind_10m',
    # Acumuladas (monotónicas)
    'apcp_tot', 'apcp', 'asnow_tot', 'asnow',
    # Cobertura
    'tcc', 'tcdc', 'lcdc', 'mcdc', 'hcdc',
    # Topes y CAPE
    'cape_sfc', 'cape', 'cin_sfc', 'cin', 'lftx',
    # Isobáricos
    'tmp_500mb', 'tmp_850mb', 'hgt_500mb', 'hgt_850mb',
    'uwnd_500mb', 'vwnd_500mb', 'rh_700mb',
    # Radar (a 10 min de gap es OK)
    'refc', 'reti', 'retop',
    # Updraft helicity
    'mxuphl',
    # Precip rate
    'prate',
}

NO_INTERPOLATE_VARS = {
    'ptype', 'ldsf', 'ltng', 'gust',
    'hail', 'hail_max', 'vis', 'vis_sfc', 'frzr_sfc',
}

SUBFRAMES_PER_HOUR = 6


# ═══════════════════════════════════════════════════════════════════════════
# DENTRO DEL WORKER (cada proceso tiene su propio módulo)
# ═══════════════════════════════════════════════════════════════════════════
# Caché por-proceso: cada worker rellena su propio cache
_LUT_CACHE = {}


def build_inverse_lut(cmap, vmin, vmax, n_lut=512):
    """Construye LUT inversa cacheada (por-proceso)."""
    key = (id(cmap), float(vmin), float(vmax), n_lut)
    if key in _LUT_CACHE:
        return _LUT_CACHE[key]

    sample_t = np.linspace(0, 1, n_lut)
    palette_rgb = (cmap(sample_t)[:, :3] * 255).astype(np.uint8)
    palette_values = vmin + sample_t * (vmax - vmin)

    _LUT_CACHE[key] = (palette_rgb, palette_values.astype(np.float32))
    return _LUT_CACHE[key]


def decode_png_to_values(png_path, vmin, vmax, cmap):
    """
    Carga los valores físicos de un frame.

    Estrategia 1 (RÁPIDA): si existe el .npz junto al PNG, leerlo directo.
    Estrategia 2 (FALLBACK): decodificar el PNG con LUT inversa de la paleta.

    El .npz lo genera model_pipeline.py si tiene el patch v5.3 aplicado.
    """
    # Intentar leer el .npz primero (mucho más rápido que decode PNG)
    npz_path = Path(png_path).with_suffix('.npz')
    if npz_path.exists():
        try:
            arr = np.load(npz_path)
            values = arr['values'].astype(np.float32)
            # Para el alpha: derivado del PNG (los .npz no guardan alpha)
            # Donde values es NaN → alpha=0; donde no → alpha=255
            alpha = np.where(np.isnan(values), 0, 255).astype(np.uint8)
            return values, alpha
        except Exception:
            pass  # fallback al decode PNG

    # Fallback: decodificar el PNG con LUT inversa
    img = Image.open(png_path).convert('RGBA')
    arr = np.asarray(img)
    h, w = arr.shape[:2]

    alpha = arr[..., 3]
    rgb = arr[..., :3]

    palette_rgb, palette_values = build_inverse_lut(cmap, vmin, vmax)

    pixels = rgb.reshape(-1, 3).astype(np.int32)
    palette_int = palette_rgb.astype(np.int32)

    chunk = 200000
    nearest_idx = np.empty(pixels.shape[0], dtype=np.int32)
    for i in range(0, pixels.shape[0], chunk):
        end = min(i + chunk, pixels.shape[0])
        diff = pixels[i:end, None, :] - palette_int[None, :, :]
        dist = np.sum(diff * diff, axis=2)
        nearest_idx[i:end] = np.argmin(dist, axis=1)

    values = palette_values[nearest_idx].reshape(h, w).astype(np.float32)
    values[alpha < 10] = np.nan
    return values, alpha


def interpolate_arrays(arr_a, arr_b, t):
    """Interpolación lineal con manejo de NaN."""
    if not (np.isnan(arr_a).any() or np.isnan(arr_b).any()):
        return arr_a * (1 - t) + arr_b * t

    nan_a = np.isnan(arr_a)
    nan_b = np.isnan(arr_b)
    result = np.where(nan_a, arr_b,
                      np.where(nan_b, arr_a,
                               arr_a * (1 - t) + arr_b * t))
    both_nan = nan_a & nan_b
    result[both_nan] = np.nan
    return result


def encode_values_to_png(values, alpha, vmin, vmax, output_path, cmap, save_npz=True):
    """
    Encodea valores a PNG usando el cmap.
    Si save_npz=True, también guarda el .npz junto al PNG (para consistencia
    con los frames originales y para que futuras re-interpolaciones sean rápidas).
    """
    import matplotlib.colors as mcolors

    norm = mcolors.Normalize(vmin=vmin, vmax=vmax, clip=True)

    valid_mask = ~np.isnan(values)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if valid_mask.any():
        normed = norm(values[valid_mask])
        colors = cmap(normed) * 255
        rgba[valid_mask] = colors.astype(np.uint8)

    rgba[..., 3] = np.where(valid_mask, alpha.astype(np.uint8), 0)
    Image.fromarray(rgba, 'RGBA').save(output_path, 'PNG', optimize=True)

    # Guardar también .npz para uso futuro (consistente con model_pipeline patch)
    if save_npz:
        try:
            npz_path = Path(output_path).with_suffix('.npz')
            np.savez_compressed(npz_path, values=values.astype(np.float32))
        except Exception:
            pass  # no crítico


def resolve_png_path(base_dir, png_field):
    p = Path(png_field)
    if p.is_absolute():
        return p
    return base_dir / p


def build_subframe_path(original_png_field, sub_filename):
    p = Path(original_png_field)
    parent = p.parent
    if str(parent) == '.':
        return sub_filename
    return str(parent / sub_filename)


# ═══════════════════════════════════════════════════════════════════════════
# Función worker — corre en un proceso aparte
# ═══════════════════════════════════════════════════════════════════════════
def process_variable_worker(args):
    """
    Procesa UNA variable completa en un proceso aparte.
    Devuelve (var_key, new_frames, error_count, elapsed_seconds, status_msg)
    """
    var_key, var_data, run_dir_str, subframes, dry_run = args
    run_dir = Path(run_dir_str)

    start = time.time()

    frames = var_data.get('frames', [])

    if var_key in NO_INTERPOLATE_VARS:
        return (var_key, frames, 0, time.time() - start,
                f'saltado (categórico/abrupto)')

    if var_key not in INTERPOLATE_VARS:
        return (var_key, frames, 0, time.time() - start,
                f'no listado para interpolar')

    if len(frames) < 2:
        return (var_key, frames, 0, time.time() - start, 'muy pocos frames')

    vmin = var_data.get('vmin')
    vmax = var_data.get('vmax')

    if vmin is None or vmax is None:
        return (var_key, frames, 0, time.time() - start, 'vmin/vmax faltante')

    cmap = get_variable_cmap(var_key)

    frames_sorted = sorted(frames, key=lambda f: f['fxx'])
    new_frames = []
    interpolated_count = 0
    error_count = 0

    cache_fxx = None
    cache_values = None
    cache_alpha = None

    for i, frame in enumerate(frames_sorted):
        new_frames.append(frame)

        if i == len(frames_sorted) - 1:
            continue
        next_frame = frames_sorted[i + 1]

        gap = next_frame['fxx'] - frame['fxx']
        if abs(gap - 1.0) > 0.01:
            cache_fxx = None
            continue

        png_a = resolve_png_path(run_dir, frame['png'])
        png_b = resolve_png_path(run_dir, next_frame['png'])

        if not png_a.exists() or not png_b.exists():
            error_count += 1
            cache_fxx = None
            continue

        try:
            if cache_fxx == frame['fxx']:
                values_a, alpha_a = cache_values, cache_alpha
            else:
                values_a, alpha_a = decode_png_to_values(png_a, vmin, vmax, cmap)
            values_b, alpha_b = decode_png_to_values(png_b, vmin, vmax, cmap)
        except Exception as e:
            error_count += 1
            cache_fxx = None
            continue

        valid_time_a = frame.get('valid_time')
        original_path = Path(frame['png'])
        stem = original_path.stem

        if dry_run:
            for step in range(1, subframes):
                t = step / subframes
                min_part = int(round(t * 60))
                sub_filename = f'{stem}_{min_part:02d}.png'
                sub_relative = build_subframe_path(frame['png'], sub_filename)
                interpolated_count += 1
                # No añadimos al manifest en dry-run
        else:
            for step in range(1, subframes):
                t = step / subframes
                sub_fxx = round(frame['fxx'] + t, 4)

                min_part = int(round(t * 60))
                sub_filename = f'{stem}_{min_part:02d}.png'
                sub_relative = build_subframe_path(frame['png'], sub_filename)
                sub_absolute = resolve_png_path(run_dir, sub_relative)

                try:
                    interp_values = interpolate_arrays(values_a, values_b, t)
                    interp_alpha = (alpha_a.astype(np.float32) * (1 - t) +
                                    alpha_b.astype(np.float32) * t).astype(np.uint8)
                    sub_absolute.parent.mkdir(parents=True, exist_ok=True)
                    encode_values_to_png(interp_values, interp_alpha, vmin, vmax,
                                         sub_absolute, cmap)
                except Exception as e:
                    error_count += 1
                    continue

                vt_iso = None
                if valid_time_a:
                    try:
                        vta = datetime.fromisoformat(valid_time_a.replace('Z', '+00:00'))
                        vtb_str = next_frame.get('valid_time', '')
                        if vtb_str:
                            vtb = datetime.fromisoformat(vtb_str.replace('Z', '+00:00'))
                            vt_interp = vta + (vtb - vta) * t
                        else:
                            vt_interp = vta + timedelta(minutes=int(t * 60))
                        vt_iso = vt_interp.isoformat().replace('+00:00', 'Z')
                    except Exception:
                        pass

                new_frame = {
                    'fxx': sub_fxx,
                    'png': sub_relative,
                    'interpolated': True,
                }
                if vt_iso:
                    new_frame['valid_time'] = vt_iso

                new_frames.append(new_frame)
                interpolated_count += 1

        cache_fxx = next_frame['fxx']
        cache_values = values_b
        cache_alpha = alpha_b

    new_frames.sort(key=lambda f: f['fxx'])

    elapsed = time.time() - start
    status = (f'✓ {interpolated_count} sub-frames'
              + (f' | ⚠ {error_count} errores' if error_count else ''))
    return (var_key, new_frames, error_count, elapsed, status)


# ═══════════════════════════════════════════════════════════════════════════
# Orquestación con multiprocessing
# ═══════════════════════════════════════════════════════════════════════════
def setup_logger(verbose=False):
    logger = logging.getLogger('interpolate')
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S'))
    logger.addHandler(h)
    return logger


def process_manifest_parallel(manifest_path, run_dir, subframes, only_vars,
                                workers, logger, dry_run):
    with open(manifest_path) as f:
        manifest = json.load(f)

    var_items = list(manifest.get('variables', {}).items())
    logger.info(f'Variables en manifest: {len(var_items)}')
    logger.info(f'Procesando: {only_vars if only_vars else "TODAS las interpolables"}')
    logger.info(f'Workers: {workers}')
    logger.info('')

    # Preparar lista de tareas (var_key, var_data, run_dir, subframes, dry_run)
    # Filtrar las que no se procesan (saltarlas en el orquestador, no en el worker,
    # para no crear procesos innecesarios)
    tasks = []
    skipped = {}

    for var_key, var_data in var_items:
        if only_vars and var_key not in only_vars:
            skipped[var_key] = var_data
            continue
        if var_key in NO_INTERPOLATE_VARS:
            skipped[var_key] = var_data
            logger.info(f'  [{var_key:<10}] saltado (categórico/abrupto)')
            continue
        if var_key not in INTERPOLATE_VARS:
            skipped[var_key] = var_data
            logger.warning(f'  [{var_key:<10}] no listado para interpolar')
            continue
        tasks.append((var_key, var_data, str(run_dir), subframes, dry_run))

    logger.info(f'Tareas a procesar: {len(tasks)}')
    logger.info('')

    new_variables = dict(skipped)
    total_subframes = 0
    total_errors = 0
    total_start = time.time()

    if not tasks:
        logger.info('No hay variables que procesar')
        new_manifest = {**manifest, 'variables': new_variables}
        return new_manifest

    # Lanzar pool con N workers
    if workers > 1:
        with mp.Pool(processes=workers) as pool:
            # imap_unordered: results llegan a medida que terminan (no en orden)
            for result in pool.imap_unordered(process_variable_worker, tasks):
                var_key, new_frames, error_count, elapsed, status = result
                new_variables[var_key] = {**dict(manifest['variables'][var_key]),
                                          'frames': new_frames}

                added = len(new_frames) - len(manifest['variables'][var_key].get('frames', []))
                total_subframes += added
                total_errors += error_count

                logger.info(f'  [{var_key:<10}] {status} ({elapsed:.1f}s)')
    else:
        # Modo single-process (--workers 1) para debug
        for task in tasks:
            result = process_variable_worker(task)
            var_key, new_frames, error_count, elapsed, status = result
            new_variables[var_key] = {**dict(manifest['variables'][var_key]),
                                      'frames': new_frames}
            added = len(new_frames) - len(manifest['variables'][var_key].get('frames', []))
            total_subframes += added
            total_errors += error_count
            logger.info(f'  [{var_key:<10}] {status} ({elapsed:.1f}s)')

    new_manifest = {**manifest, 'variables': new_variables}
    new_manifest['interpolated'] = True
    new_manifest['subframes_per_hour'] = subframes

    total_elapsed = time.time() - total_start
    logger.info('')
    logger.info(f'═══ Total: {total_subframes} sub-frames en {total_elapsed:.1f}s'
                + (f' | ⚠ {total_errors} errores' if total_errors else '')
                + ' ═══')
    return new_manifest


def main():
    parser = argparse.ArgumentParser(description='Interpolación temporal HRRR (paralelizada)')
    parser.add_argument('--product', required=True, choices=['hrrr-18h', 'hrrr-48h'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--subframes', type=int, default=SUBFRAMES_PER_HOUR)
    parser.add_argument('--vars', nargs='+', default=None)
    parser.add_argument('--workers', type=int, default=None,
                        help='Número de procesos paralelos (default: cores-1)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    logger = setup_logger(verbose=args.verbose)

    if not args.run_dir.exists():
        logger.error(f'No existe el directorio: {args.run_dir}')
        return 1

    manifest_path = args.run_dir / 'manifest.json'
    if not manifest_path.exists():
        logger.error(f'No existe manifest: {manifest_path}')
        return 1

    # Auto-detectar workers (cores-1 para no saturar el sistema)
    if args.workers is None:
        n_cores = os.cpu_count() or 2
        args.workers = max(1, min(n_cores - 1, 8))

    logger.info(f'═══ Interpolación HRRR PARALELIZADA ═══')
    logger.info(f'Producto: {args.product}')
    logger.info(f'Run dir:  {args.run_dir}')
    logger.info(f'Sub-frames/hora: {args.subframes}')
    logger.info(f'CPU cores disponibles: {os.cpu_count()}')
    logger.info(f'Workers a usar: {args.workers}')
    if HRRR_VARS_AVAILABLE:
        logger.info('Paletas: importadas desde hrrr_variables.py ✓')
    else:
        logger.warning('Paletas: hrrr_variables.py NO disponible — usando viridis')

    # Detectar si hay .npz (fastpath)
    npz_count = sum(1 for _ in args.run_dir.rglob('*.npz'))
    if npz_count > 0:
        logger.info(f'Fastpath .npz: {npz_count} archivos detectados ⚡')
    else:
        logger.info('Fastpath .npz: NO detectado (usando decode PNG, más lento)')
        logger.info('  Para activar: aplicar patch_model_pipeline.py al model_pipeline.py')

    if args.dry_run:
        logger.info('Modo: DRY RUN (no genera PNGs)')
    logger.info('')

    new_manifest = process_manifest_parallel(
        manifest_path, args.run_dir, args.subframes,
        only_vars=args.vars, workers=args.workers,
        logger=logger, dry_run=args.dry_run
    )

    if not args.dry_run:
        backup_path = manifest_path.with_suffix('.json.pre-interp')
        if not backup_path.exists():
            import shutil
            shutil.copy(manifest_path, backup_path)
            logger.info(f'Backup manifest: {backup_path}')

        with open(manifest_path, 'w') as f:
            json.dump(new_manifest, f, indent=2, ensure_ascii=False)
        logger.info(f'Manifest actualizado: {manifest_path}')

    logger.info('')
    logger.info('✓ Interpolación completada')
    return 0


if __name__ == '__main__':
    # Necesario para multiprocessing en algunos sistemas
    mp.set_start_method('spawn', force=True)
    sys.exit(main())
