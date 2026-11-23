#!/usr/bin/env python3
"""
09_publica.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Publica en el CDN (canalmeteo-public, data/nieve/) lo que leen la web y la app.
Autorizado por Albert el 14-nov-2026.

  data/nieve/manifest.json          mañanas disponibles y hora del cálculo
  data/nieve/resumen.json           recuentos y distritos más altos (caja de www.canalmeteo.tv y L-bar)
  data/nieve/<AAAA-MM-DD>.json      una por mañana (de salida/actual, 07_indice.py)
  data/nieve/geo/…                  ficheros fijos (de salida/web, 08_web_fijos.py); solo con --fijos

Los JSON se suben comprimidos (gzip). El manifest va el último, para que nunca
apunte a una mañana que aún no está subida. Las mañanas que ya no están en el
manifest se borran del CDN.

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 09_publica.py [--fijos] [--ejemplo AAAA-MM-DD] [--aciertos]
"""
import gzip
import json
import re
import sys

import boto3

import nbm_comun as nc

BUCKET = 'canalmeteo-public'
PERFIL = 'do-tor1'
ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
BASE = 'data/nieve/'
TIPOS = {'.json': 'application/json; charset=utf-8', '.pmtiles': 'application/octet-stream'}


def log(msg):
    print(msg, flush=True)


def sube(s3, ruta, clave, edad):
    tipo = TIPOS[ruta.suffix]
    cuerpo = ruta.read_bytes()
    extra = {}
    if ruta.suffix == '.json':
        cuerpo = gzip.compress(cuerpo, 6)
        extra['ContentEncoding'] = 'gzip'
    s3.put_object(Bucket=BUCKET, Key=clave, Body=cuerpo, ACL='public-read', ContentType=tipo,
                  CacheControl=f'max-age={edad}', **extra)
    return len(cuerpo)


def main():
    s3 = boto3.Session(profile_name=PERFIL).client('s3', endpoint_url=ENDPOINT)
    if '--fijos' in sys.argv:
        for f in sorted((nc.BASE / 'salida' / 'web').iterdir()):
            if f.suffix in TIPOS:
                n = sube(s3, f, BASE + 'geo/' + f.name, 3600)
                log(f'  geo/{f.name}: {n / 1e6:.2f} MB')

    if '--aciertos' in sys.argv:
        # Resultado de las pruebas contra cierres reales (11_backtest_ky.py) → data/nieve/aciertos/
        for f in sorted((nc.BASE / 'salida' / 'backtest').glob('*_resumen.json')):
            sube(s3, f, BASE + 'aciertos/' + f.name.replace('_resumen', ''), 600)
            log(f'  aciertos/{f.name.replace("_resumen", "")} subido')
        return 0

    if '--ejemplo' in sys.argv:
        # Tormenta de ejemplo (del archivo del NBM): salida/prueba/<fecha>.json → data/nieve/ejemplo/
        fecha = sys.argv[sys.argv.index('--ejemplo') + 1]
        pr = nc.BASE / 'salida' / 'prueba'
        doc = json.loads((pr / f'{fecha}.json').read_text(encoding='utf-8'))
        (pr / 'manifest.json').write_text(json.dumps(dict(hecho=doc['meta']['hecho'], ciclo_nbm=doc['meta']['ciclo_nbm'],
                                                          modo='ejemplo', fechas=[fecha])), encoding='utf-8')
        sube(s3, pr / f'{fecha}.json', BASE + f'ejemplo/{fecha}.json', 3600)
        sube(s3, pr / 'manifest.json', BASE + 'ejemplo/manifest.json', 3600)
        log(f'  ejemplo/{fecha}.json subido')
        return 0

    act = nc.BASE / 'salida' / 'actual'
    manifest = json.loads((act / 'manifest.json').read_text(encoding='utf-8'))
    total = 0
    for fecha in manifest['fechas']:
        total += sube(s3, act / f'{fecha}.json', BASE + f'{fecha}.json', 300)
    if (act / 'resumen.json').exists():
        total += sube(s3, act / 'resumen.json', BASE + 'resumen.json', 120)
    total += sube(s3, act / 'manifest.json', BASE + 'manifest.json', 60)

    # Mañanas pasadas: fuera del CDN
    viejas = [o['Key'] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=BASE, Delimiter='/').get('Contents', [])
              if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', o['Key'][len(BASE):]) and o['Key'][len(BASE):-5] not in manifest['fechas']]
    for k in viejas:
        s3.delete_object(Bucket=BUCKET, Key=k)
    log(f'CDN {BASE}: {", ".join(manifest["fechas"])} · {total / 1e3:.0f} kB · ciclo {manifest["ciclo_nbm"]}'
        + (f' · borradas {len(viejas)}' if viejas else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
