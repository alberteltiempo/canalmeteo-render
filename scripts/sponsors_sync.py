#!/usr/bin/env python3
"""
sponsors_sync.py
Lee sponsors.json de GoDaddy y regenera logos.json en el CDN DO Spaces.
Se puede llamar como script directo o desde el webhook HTTP.
"""

import json
import os
import sys
import urllib.request
import subprocess
import tempfile
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [sponsors_sync] %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/var/log/canalmeteo/sponsors_sync.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

SPONSORS_URL  = 'https://www.canalmeteo.tv/data/sponsors.json'
CDN_BUCKET    = 'canalmeteo-public'
CDN_KEY       = 'logos-rotativos/logos.json'
AWS_PROFILE   = 'do-tor1'
ENDPOINT_URL  = 'https://sfo3.digitaloceanspaces.com'


def fetch_sponsors():
    req = urllib.request.Request(
        SPONSORS_URL,
        headers={'User-Agent': 'CanalMeteo-Sync/1.0'}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def build_logos_json(data):
    sponsors = data.get('sponsors', [])
    # Solo activos, ordenados por peso descendente
    active = [s for s in sponsors if s.get('active', False)]
    active.sort(key=lambda s: s.get('weight', 1), reverse=True)
    logos = [s['logo_url'] for s in active if s.get('logo_url')]
    log.info(f'{len(logos)} logos activos de {len(sponsors)} totales')
    return {'logos': logos, 'updated_at': data.get('updated_at', '')}


def upload_to_cdn(logos_data):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(logos_data, f, ensure_ascii=False, indent=2)
        tmp_path = f.name

    try:
        cmd = [
            'aws', 's3', 'cp', tmp_path,
            f's3://{CDN_BUCKET}/{CDN_KEY}',
            '--profile', AWS_PROFILE,
            '--endpoint-url', ENDPOINT_URL,
            '--cache-control', 'public, max-age=60',
            '--content-type', 'application/json',
            '--acl', 'public-read',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        log.info(f'CDN actualizado: {CDN_KEY}')
    finally:
        os.unlink(tmp_path)


def sync():
    log.info('Iniciando sincronización de sponsors...')
    try:
        data = fetch_sponsors()
        logos_data = build_logos_json(data)
        upload_to_cdn(logos_data)
        log.info('Sincronización completada OK')
        return True
    except Exception as e:
        log.error(f'Error en sincronización: {e}')
        return False


if __name__ == '__main__':
    ok = sync()
    sys.exit(0 if ok else 1)
