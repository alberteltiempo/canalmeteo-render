#!/usr/bin/env python3
"""
webcam_scraper.py — Canal Meteo
══════════════════════════════════════════════════════════════════════
Scraper horario de las 20 webcams de la red NPS Air Quality.

Función:
  • Descarga la imagen actual de las 20 cámaras NPS desde
    https://www.nps.gov/featurecontent/ard/webcams/images/{code}.jpg
  • Sube cada imagen al CDN con dos paths:
      - data/webcams/{code}/latest.jpg                 (siempre la última)
      - data/webcams/{code}/YYYY-MM-DDTHH-00Z.jpg      (histórico horario)
  • Mantiene rolling window de 24 imágenes por cámara
  • Limpia automáticamente imágenes >24h del CDN
  • Genera data/webcams/manifest.json con metadata global
  • Genera data/webcams/{code}/manifest.json con histórico individual

Configuración:
  Ubicación:  /opt/canalmeteo/scripts/webcam_scraper.py
  Entorno:    /opt/canalmeteo/venv/
  Datos:      /opt/canalmeteo/data/webcams/
  Logs:       /var/log/canalmeteo/webcam_scraper.log
  CDN:        canalmeteo-public.sfo3.digitaloceanspaces.com/data/webcams/

Cron (cada hora a HH:00, antes del render Remotion en HH:30):
  0 * * * * /usr/bin/flock -n /tmp/webcam_scraper.lock \\
            /opt/canalmeteo/venv/bin/python3 \\
            /opt/canalmeteo/scripts/webcam_scraper.py \\
            >> /var/log/canalmeteo/webcam_scraper.log 2>&1

Dependencias:
  pip install requests Pillow

Uso manual:
  # Descarga + upload normal
  /opt/canalmeteo/venv/bin/python3 webcam_scraper.py

  # Solo descarga local, sin subir al CDN (útil para test)
  /opt/canalmeteo/venv/bin/python3 webcam_scraper.py --no-upload

  # Solo una cámara específica (útil para debug)
  /opt/canalmeteo/venv/bin/python3 webcam_scraper.py --only acad

  # Verbose
  /opt/canalmeteo/venv/bin/python3 webcam_scraper.py --verbose

  # Skip cleanup de archivos viejos (más rápido en test)
  /opt/canalmeteo/venv/bin/python3 webcam_scraper.py --no-cleanup
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image

# Importar lista curada
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nps_webcams_config import NPS_WEBCAMS, get_image_url


# ═════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═════════════════════════════════════════════════════════════════════

CONFIG = {
    'user_agent': 'CanalMeteoTV/1.0 (https://canalmeteo.tv; webcam scraper)',

    # Rutas locales
    'data_dir': '/opt/canalmeteo/data/webcams',
    'log_dir': '/var/log/canalmeteo',

    # CDN — DigitalOcean Spaces
    'aws_profile': 'do-tor1',
    'cdn_bucket': 'canalmeteo-public',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',
    'cdn_prefix': 'data/webcams',
    'cdn_base_url': 'https://canalmeteo-public.sfo3.digitaloceanspaces.com',

    # Concurrency
    'max_download_workers': 8,
    'max_upload_workers': 6,

    # Timeouts (segundos)
    'download_timeout': 30,
    'upload_timeout': 60,

    # Rolling window (horas)
    'history_hours': 24,

    # Min image size para validar download (bytes)
    # Una webcam offline a veces devuelve un placeholder ~12-19KB
    # Por debajo de 30KB es muy probablemente un placeholder
    'min_image_bytes': 30000,
    # Threshold más estricto para advertencia (placeholder probable)
    'suspicious_image_bytes': 50000,
}


# ═════════════════════════════════════════════════════════════════════
# LOGGING
# ═════════════════════════════════════════════════════════════════════

def setup_logging(verbose: bool = False):
    log_dir = Path(CONFIG['log_dir'])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'webcam_scraper.log'

    level = logging.DEBUG if verbose else logging.INFO
    fmt = '%(asctime)s [%(levelname)s] %(message)s'
    datefmt = '%Y-%m-%d %H:%M:%S'

    # Reset handlers if re-running in same process
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger('webcam_scraper')


# ═════════════════════════════════════════════════════════════════════
# DESCARGA
# ═════════════════════════════════════════════════════════════════════

def download_webcam(cam: dict, log) -> dict:
    """
    Descarga la imagen de una webcam.
    Devuelve dict con: ok, code, local_path, size, error, dimensions.
    """
    code = cam['code']
    url = get_image_url(code)
    result = {
        'ok': False,
        'code': code,
        'url': url,
        'local_path': None,
        'size': 0,
        'error': None,
        'dimensions': None,
    }

    try:
        log.debug(f"[{code}] GET {url}")
        r = requests.get(
            url,
            headers={'User-Agent': CONFIG['user_agent']},
            timeout=CONFIG['download_timeout'],
            stream=True,
        )
        r.raise_for_status()

        # Validar content-type
        ctype = r.headers.get('Content-Type', '')
        if 'image' not in ctype.lower():
            raise ValueError(f"Not an image: Content-Type={ctype}")

        # Guardar a disco
        out_dir = Path(CONFIG['data_dir']) / code
        out_dir.mkdir(parents=True, exist_ok=True)
        local_path = out_dir / f"{code}-latest.jpg"

        size = 0
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)

        # Validar tamaño mínimo
        if size < CONFIG['min_image_bytes']:
            raise ValueError(f"Image too small ({size} bytes), likely offline placeholder")

        # Warning si es pequeña pero arriba del minimum (puede ser webcam degradada)
        if size < CONFIG['suspicious_image_bytes']:
            log.warning(f"  ⚠ [{code:9s}] suspiciously small ({size} bytes), possibly offline")

        # Validar JPEG y obtener dimensiones
        try:
            with Image.open(local_path) as img:
                result['dimensions'] = list(img.size)
                img.verify()
        except Exception as e:
            raise ValueError(f"Invalid JPEG: {e}")

        result['ok'] = True
        result['local_path'] = str(local_path)
        result['size'] = size
        log.info(f"  ✓ [{code:9s}] {size:>8,} bytes  {result['dimensions'][0]}x{result['dimensions'][1]}")

    except requests.exceptions.HTTPError as e:
        result['error'] = f"HTTP {e.response.status_code}"
        log.warning(f"  ✗ [{code:9s}] {result['error']}")
    except requests.exceptions.Timeout:
        result['error'] = f"timeout after {CONFIG['download_timeout']}s"
        log.warning(f"  ✗ [{code:9s}] {result['error']}")
    except Exception as e:
        result['error'] = str(e)[:100]
        log.warning(f"  ✗ [{code:9s}] {result['error']}")

    return result


def download_all(cams: list, log) -> list:
    """Descarga todas las cámaras en paralelo."""
    log.info(f"Descargando {len(cams)} webcams (workers={CONFIG['max_download_workers']})...")
    results = []
    with ThreadPoolExecutor(max_workers=CONFIG['max_download_workers']) as ex:
        futures = {ex.submit(download_webcam, cam, log): cam for cam in cams}
        for fut in as_completed(futures):
            results.append(fut.result())

    # Sort to keep consistent order in logs
    results.sort(key=lambda r: r['code'])
    success = sum(1 for r in results if r['ok'])
    log.info(f"Descargas: {success}/{len(cams)} OK")
    return results


# ═════════════════════════════════════════════════════════════════════
# UPLOAD CDN (AWS CLI con perfil do-tor1)
# ═════════════════════════════════════════════════════════════════════

def aws_s3_cp_file(local_path: str, s3_key: str, log,
                    cache_seconds: int = 600,
                    content_type: str = 'image/jpeg') -> bool:
    """Sube un archivo al CDN."""
    try:
        cmd = [
            'aws', 's3', 'cp',
            local_path,
            f"s3://{CONFIG['cdn_bucket']}/{s3_key}",
            '--profile', CONFIG['aws_profile'],
            '--endpoint-url', CONFIG['cdn_endpoint'],
            '--acl', 'public-read',
            '--content-type', content_type,
            '--cache-control', f'public, max-age={cache_seconds}',
            '--quiet',
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=CONFIG['upload_timeout']
        )
        if result.returncode != 0:
            log.warning(f"    upload failed [{s3_key}]: {result.stderr.strip()[:120]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log.warning(f"    upload timeout [{s3_key}]")
        return False
    except Exception as e:
        log.warning(f"    upload exception [{s3_key}]: {e}")
        return False


def aws_s3_cp_json(json_data: dict, s3_key: str, log,
                    cache_seconds: int = 60) -> bool:
    """Sube un JSON al CDN."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
            tmp_path = f.name

        ok = aws_s3_cp_file(
            tmp_path, s3_key, log,
            cache_seconds=cache_seconds,
            content_type='application/json'
        )
        return ok
    except Exception as e:
        log.warning(f"    json upload exception [{s3_key}]: {e}")
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def aws_s3_ls(s3_prefix: str, log) -> list:
    """Lista objetos con un prefijo. Devuelve list[{name, size, date}]."""
    try:
        cmd = [
            'aws', 's3', 'ls',
            f"s3://{CONFIG['cdn_bucket']}/{s3_prefix}",
            '--profile', CONFIG['aws_profile'],
            '--endpoint-url', CONFIG['cdn_endpoint'],
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return []

        items = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('PRE '):
                continue
            parts = line.split(None, 3)  # split on whitespace, max 4 parts
            if len(parts) >= 4:
                # "2026-04-27 18:00:05 12345 filename.jpg"
                date_str, time_str, size_str, name = parts
                try:
                    items.append({
                        'name': name,
                        'size': int(size_str),
                        'date': f"{date_str} {time_str}",
                    })
                except ValueError:
                    pass
        return items
    except Exception as e:
        log.debug(f"  ls exception: {e}")
        return []


def aws_s3_rm(s3_key: str, log) -> bool:
    """Elimina un objeto del CDN."""
    try:
        cmd = [
            'aws', 's3', 'rm',
            f"s3://{CONFIG['cdn_bucket']}/{s3_key}",
            '--profile', CONFIG['aws_profile'],
            '--endpoint-url', CONFIG['cdn_endpoint'],
            '--quiet',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except Exception:
        return False


def upload_webcam(download_result: dict, hour_key: str, log) -> dict:
    """
    Sube imagen al CDN en dos paths:
      - data/webcams/{code}/latest.jpg          (cache 5 min)
      - data/webcams/{code}/{hour_key}.jpg      (cache 24h)
    """
    code = download_result['code']
    out = {
        'code': code,
        'uploaded': False,
        'urls': None,
        'archive_key': None,
        'archive_filename': None,
    }

    if not download_result['ok']:
        return out

    local_path = download_result['local_path']
    cdn_prefix = f"{CONFIG['cdn_prefix']}/{code}"
    latest_key = f"{cdn_prefix}/latest.jpg"
    archive_filename = f"{hour_key}.jpg"
    archive_key = f"{cdn_prefix}/{archive_filename}"

    # Latest: cache corto (5 min) — siempre se actualiza
    ok_latest = aws_s3_cp_file(local_path, latest_key, log, cache_seconds=300)

    # Archive: cache largo (24h) — immutable
    ok_archive = aws_s3_cp_file(local_path, archive_key, log, cache_seconds=86400)

    if ok_latest and ok_archive:
        out['uploaded'] = True
        out['archive_key'] = archive_key
        out['archive_filename'] = archive_filename
        out['urls'] = {
            'latest': f"{CONFIG['cdn_base_url']}/{latest_key}",
            'archive': f"{CONFIG['cdn_base_url']}/{archive_key}",
        }
        log.info(f"  ↑ [{code:9s}] uploaded to CDN  ({hour_key})")
    elif ok_latest:
        out['urls'] = {'latest': f"{CONFIG['cdn_base_url']}/{latest_key}"}
        log.warning(f"  ⚠ [{code:9s}] only latest uploaded (archive failed)")
    else:
        log.warning(f"  ✗ [{code:9s}] upload failed")

    return out


def upload_all(download_results: list, hour_key: str, log) -> dict:
    """Sube todas las imágenes en paralelo. Devuelve dict {code: upload_result}."""
    log.info(f"Subiendo al CDN (workers={CONFIG['max_upload_workers']})...")
    upload_results = {}
    with ThreadPoolExecutor(max_workers=CONFIG['max_upload_workers']) as ex:
        futures = {
            ex.submit(upload_webcam, dr, hour_key, log): dr['code']
            for dr in download_results
        }
        for fut in as_completed(futures):
            r = fut.result()
            upload_results[r['code']] = r

    success = sum(1 for r in upload_results.values() if r['uploaded'])
    log.info(f"Uploads: {success}/{len(download_results)} OK")
    return upload_results


# ═════════════════════════════════════════════════════════════════════
# CLEANUP — Rolling window de 24h
# ═════════════════════════════════════════════════════════════════════

def parse_hour_filename(name: str):
    """
    Parse 'YYYY-MM-DDTHH-00Z.jpg' a datetime UTC.
    Devuelve None si no matchea el formato.
    """
    if not name.endswith('.jpg'):
        return None
    base = name[:-4]  # quitar .jpg
    # Formato: 2026-04-27T18-00Z
    try:
        # Convertir T18-00Z → T18:00:00+00:00
        if 'T' not in base or not base.endswith('Z'):
            return None
        date_part, time_part = base.split('T')
        time_part = time_part[:-1]  # quitar Z
        # time_part = "18-00"  → "18:00"
        time_part = time_part.replace('-', ':')
        iso = f"{date_part}T{time_part}:00+00:00"
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def cleanup_old_images(code: str, log) -> int:
    """
    Elimina imágenes >24h del CDN para una cámara.
    Devuelve número de archivos eliminados.
    """
    cdn_prefix = f"{CONFIG['cdn_prefix']}/{code}/"
    items = aws_s3_ls(cdn_prefix, log)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=CONFIG['history_hours'])
    deleted = 0

    for item in items:
        name = item['name']
        # Skip files que no son archivo histórico
        if name in ('latest.jpg', 'manifest.json'):
            continue

        ts = parse_hour_filename(name)
        if ts is None:
            continue

        if ts < cutoff:
            full_key = cdn_prefix + name
            if aws_s3_rm(full_key, log):
                deleted += 1
                log.debug(f"    deleted old [{code}]: {name}")

    if deleted > 0:
        log.info(f"  🗑 [{code:9s}] cleanup: removed {deleted} old files (>24h)")
    return deleted


def cleanup_all(codes: list, log) -> int:
    """Cleanup paralelo de todas las cámaras."""
    log.info(f"Cleanup de imágenes >24h en CDN...")
    total_deleted = 0
    with ThreadPoolExecutor(max_workers=CONFIG['max_upload_workers']) as ex:
        futures = [ex.submit(cleanup_old_images, code, log) for code in codes]
        for fut in as_completed(futures):
            total_deleted += fut.result()
    log.info(f"Cleanup total: {total_deleted} archivos eliminados")
    return total_deleted


# ═════════════════════════════════════════════════════════════════════
# MANIFEST GENERATION
# ═════════════════════════════════════════════════════════════════════

def generate_cam_manifest(cam: dict, upload_result: dict, log) -> dict:
    """Genera manifest individual con histórico de las últimas 24h."""
    code = cam['code']
    cdn_prefix_path = f"{CONFIG['cdn_prefix']}/{code}/"
    items = aws_s3_ls(cdn_prefix_path, log)

    # Histórico ordenado más reciente primero
    history = []
    for item in items:
        name = item['name']
        if name in ('latest.jpg', 'manifest.json'):
            continue
        ts = parse_hour_filename(name)
        if ts is None:
            continue
        history.append({
            'filename': name,
            'url': f"{CONFIG['cdn_base_url']}/{cdn_prefix_path}{name}",
            'size': item['size'],
            'datetime_utc': ts.isoformat(),
        })
    history.sort(key=lambda x: x['filename'], reverse=True)

    return {
        'code': code,
        'park_name_es': cam['park_name_es'],
        'park_name_en': cam['park_name_en'],
        'state': cam['state'],
        'state_abbr': cam['state_abbr'],
        'view_es': cam['view_es'],
        'lat': cam['lat'],
        'lon': cam['lon'],
        'elevation_ft': cam['elevation_ft'],
        'tz': cam['tz'],
        'tz_abbr': cam['tz_abbr'],
        'region': cam.get('region', cam.get('group')),
        'metar': cam['metar'],
        'urls': {
            'latest': f"{CONFIG['cdn_base_url']}/{cdn_prefix_path}latest.jpg",
        },
        'history_24h': history,
        'history_count': len(history),
        'last_updated_utc': datetime.now(timezone.utc).isoformat(),
    }


def generate_global_manifest(cams: list, download_results: dict,
                              upload_results: dict, run_started: datetime,
                              log) -> dict:
    """Genera manifest global con resumen de todas las cámaras."""
    cams_summary = []
    success_count = 0

    for cam in cams:
        code = cam['code']
        dr = download_results.get(code, {})
        ur = upload_results.get(code, {})
        is_ok = dr.get('ok', False) and ur.get('uploaded', False)
        if is_ok:
            success_count += 1

        cams_summary.append({
            'code': code,
            'park_name_es': cam['park_name_es'],
            'state': cam['state'],
            'state_abbr': cam['state_abbr'],
            'region': cam.get('region', cam.get('group')),
            'lat': cam['lat'],
            'lon': cam['lon'],
            'tz': cam['tz'],
            'metar_id': cam['metar']['id'],
            'status': 'ok' if is_ok else 'failed',
            'error': dr.get('error') if not is_ok else None,
            'urls': {
                'latest': f"{CONFIG['cdn_base_url']}/{CONFIG['cdn_prefix']}/{code}/latest.jpg",
                'manifest': f"{CONFIG['cdn_base_url']}/{CONFIG['cdn_prefix']}/{code}/manifest.json",
            },
        })

    return {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'run_started_utc': run_started.isoformat(),
        'duration_seconds': (datetime.now(timezone.utc) - run_started).total_seconds(),
        'total_cams': len(cams),
        'successful': success_count,
        'failed': len(cams) - success_count,
        'cams': cams_summary,
    }


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Canal Meteo NPS Webcam Scraper"
    )
    parser.add_argument('--no-upload', action='store_true',
                        help="Solo descarga local, sin subir al CDN")
    parser.add_argument('--no-cleanup', action='store_true',
                        help="No eliminar imágenes >24h del CDN")
    parser.add_argument('--no-manifest', action='store_true',
                        help="No generar manifests")
    parser.add_argument('--only', type=str, default=None,
                        help="Solo procesar la cámara con este código")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="Verbose logging (DEBUG)")
    args = parser.parse_args()

    log = setup_logging(verbose=args.verbose)
    run_started = datetime.now(timezone.utc)

    # Hour key: hora UTC actual redondeada al cambio de hora
    # Formato: YYYY-MM-DDTHH-00Z (ej: 2026-04-27T18-00Z)
    hour_key = run_started.strftime('%Y-%m-%dT%H-00Z')

    log.info("═" * 70)
    log.info(f"Canal Meteo Webcam Scraper — {run_started.isoformat()}")
    log.info(f"Hour key: {hour_key}")
    log.info("═" * 70)

    # Filtrar cámaras
    cams = NPS_WEBCAMS
    if args.only:
        cams = [c for c in NPS_WEBCAMS if c['code'] == args.only]
        if not cams:
            log.error(f"Cámara '{args.only}' no encontrada. Códigos disponibles:")
            log.error(f"  {[c['code'] for c in NPS_WEBCAMS]}")
            sys.exit(1)
        log.info(f"Modo --only: procesando solo '{args.only}'")

    # ─── Fase 1: Descarga ─────────────────────────────────────────
    download_results_list = download_all(cams, log)
    download_results = {r['code']: r for r in download_results_list}

    # ─── Fase 2: Upload al CDN ────────────────────────────────────
    upload_results = {}
    if not args.no_upload:
        upload_results = upload_all(download_results_list, hour_key, log)
    else:
        log.info("Modo --no-upload: omitiendo subida al CDN")

    # ─── Fase 3: Cleanup de imágenes viejas ───────────────────────
    if not args.no_upload and not args.no_cleanup:
        codes = [c['code'] for c in cams]
        cleanup_all(codes, log)

    # ─── Fase 4: Manifests ────────────────────────────────────────
    if not args.no_upload and not args.no_manifest:
        log.info("Generando manifests...")

        # Manifest individual por cámara EN PARALELO
        def _gen_and_upload_cam_manifest(cam):
            code = cam['code']
            ur = upload_results.get(code, {})
            cam_manifest = generate_cam_manifest(cam, ur, log)
            manifest_key = f"{CONFIG['cdn_prefix']}/{code}/manifest.json"
            return aws_s3_cp_json(cam_manifest, manifest_key, log, cache_seconds=60)

        with ThreadPoolExecutor(max_workers=CONFIG['max_upload_workers']) as ex:
            list(ex.map(_gen_and_upload_cam_manifest, cams))

        # Manifest global
        global_manifest = generate_global_manifest(
            cams, download_results, upload_results, run_started, log
        )
        global_key = f"{CONFIG['cdn_prefix']}/manifest.json"
        if aws_s3_cp_json(global_manifest, global_key, log, cache_seconds=60):
            log.info(f"  ✓ Manifest global subido: {CONFIG['cdn_base_url']}/{global_key}")

    # ─── Resumen final ─────────────────────────────────────────────
    duration = (datetime.now(timezone.utc) - run_started).total_seconds()
    success = sum(1 for r in download_results.values() if r['ok'])
    log.info("═" * 70)
    log.info(f"Completado en {duration:.1f}s")
    log.info(f"  Descargas OK: {success}/{len(cams)}")
    if not args.no_upload:
        uploaded = sum(1 for r in upload_results.values() if r['uploaded'])
        log.info(f"  Uploads OK:   {uploaded}/{len(cams)}")
    log.info("═" * 70)

    # Exit code: 0 si TODAS OK, 1 si alguna falla, 2 si todas fallan
    if success == len(cams):
        sys.exit(0)
    elif success > 0:
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
