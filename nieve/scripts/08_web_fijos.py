#!/usr/bin/env python3
"""
08_web_fijos.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Ficheros FIJOS que necesita la web, solo con los distritos que tienen escuelas.
Se ejecuta una vez (y cuando cambien los distritos).

Entrada:  fijos/distritos.csv, escuelas.csv, distritos.geojsonl, states.json
Salida:   salida/web/search.json       {"d":[[leaid, nombre, estado, condado, lat, lon], …]}
          salida/web/zips.json         {"<código postal>": "leaid leaid …"}
          salida/web/states.json
          salida/web/counties.json     condados simplificados (n = nombre)
          salida/web/clima.json        {leaid: [nieve anual in, días ≥1 in, días ≥3 in, escuelas, % rural]}
          salida/web/districts.pmtiles (tippecanoe, capa «d»: i, n, s)

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 08_web_fijos.py
"""
import json
import shutil
import subprocess
import sys
from collections import defaultdict

import pandas as pd

import nbm_comun as nc


def main():
    web = nc.BASE / 'salida' / 'web'
    web.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str}).merge(
        pd.read_csv(nc.FIJOS / 'escuelas.csv', dtype={'leaid': str}), on='leaid')
    d = d[d['n_escuelas'] > 0]
    con = set(d['leaid'])

    filas = [[r.leaid, r.nombre, r.estado, r.condado, round(r.lat, 3), round(r.lon, 3)] for r in d.itertuples()]
    (web / 'search.json').write_text(json.dumps({'d': filas}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    z = defaultdict(list)
    for r in d.itertuples():
        for c in str(r.zips).split():
            z[c[:5]].append(r.leaid)
    (web / 'zips.json').write_text(json.dumps({k: ' '.join(v) for k, v in sorted(z.items())}, separators=(',', ':')), encoding='utf-8')
    shutil.copy(nc.FIJOS / 'states.json', web / 'states.json')

    # Condados (líneas y nombre) para el mapa, simplificados
    import geopandas as gpd
    cond = gpd.read_file(next((nc.BASE / 'fuentes' / 'condados_cb2024_500k').rglob('*.shp')))
    cond = cond[cond['STUSPS'].isin(set(d['estado']))][['NAME', 'geometry']].rename(columns={'NAME': 'n'}).to_crs(4326)
    cond['geometry'] = cond.geometry.simplify(0.004)
    cond.to_file(web / 'counties.json', driver='GeoJSON', COORDINATE_PRECISION=3)

    # Lo fijo de cada distrito para su ficha: nieve anual, días con ≥1 in y ≥3 in, escuelas, % rural
    c = d.merge(pd.read_csv(nc.FIJOS / 'clima_nieve.csv', dtype={'leaid': str}), on='leaid')
    clima = {r.leaid: [round(r.nieve_anual_in), round(r.dias_1in, 1), round(r.dias_3in, 1), int(r.n_escuelas), int(r.rural_pct)]
             for r in c.itertuples()}
    (web / 'clima.json').write_text(json.dumps(clima, separators=(',', ':')), encoding='utf-8')

    tmp = nc.BASE / 'trabajo' / 'distritos_web.geojsonl'
    n = 0
    with open(nc.FIJOS / 'distritos.geojsonl', encoding='utf-8') as fi, open(tmp, 'w', encoding='utf-8') as fo:
        for ln in fi:
            k = ln.find('"i": "')
            if k < 0:
                k = ln.find('"i":"') - 1
            if ln[k + 6:k + 13] in con:
                fo.write(ln)
                n += 1
    assert n == len(con), f'{n} líneas frente a {len(con)} distritos'
    subprocess.run(['tippecanoe', '-o', str(web / 'districts.pmtiles'), '--force', '-l', 'd', '-Z2', '-z10',
                    '--no-feature-limit', '--no-tile-size-limit', '--detect-shared-borders', '--simplification=8',
                    '--read-parallel', '-q', str(tmp)], check=True)
    tmp.unlink()
    print(f'distritos: {len(con)} · códigos postales: {len(z)}')
    for f in sorted(web.iterdir()):
        print(f'  {f.name:22s} {f.stat().st_size / 1e6:6.2f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
