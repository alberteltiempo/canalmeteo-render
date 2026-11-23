#!/usr/bin/env python3
"""
06_clima_nieve.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Datos FIJOS: cuánto nieva normalmente en cada distrito. Es lo que dice si una
nevada es rara allí (una pulgada cierra Atlanta y no cierra Búfalo).

Entrada:  fuentes/normales_anuales/csv/*.csv
          «U.S. Climate Normals 1991-2020» anuales de NCEI, un fichero por estación
Salida:   fijos/clima_nieve.csv  leaid, nieve_anual_in, dias_1in, dias_3in,
                                 est_km (distancia a la estación más cercana)

Cada distrito toma la media de las 5 estaciones más cercanas, ponderada por la
distancia y por el parecido de altitud (en montaña, una estación del valle no
representa a un pueblo de la sierra).

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 06_clima_nieve.py
"""
import csv
import glob
import sys

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

import nbm_comun as nc

ORIGEN = nc.BASE / 'fuentes' / 'normales_anuales' / 'csv'
COLS = {'nieve_anual_in': 'ANN-SNOW-NORMAL', 'dias_1in': 'ANN-SNOW-AVGNDS-GE010TI',
        'dias_3in': 'ANN-SNOW-AVGNDS-GE030TI'}
K = 5
ESCALA_ALT = 300.0  # m: 300 m de diferencia de altitud pesan como duplicar la distancia


def log(msg):
    print(msg, flush=True)


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    if x == -7777:      # cantidad no nula que redondea a cero
        return 0.0
    return np.nan if x <= -99 else x


def main():
    filas = []
    for f in sorted(glob.glob(str(ORIGEN / '**' / '*.csv'), recursive=True)):
        with open(f, newline='', encoding='utf-8', errors='replace') as fh:
            r = next(csv.DictReader(fh), None)
        if not r or COLS['nieve_anual_in'] not in r:
            continue
        fila = dict(id=r['STATION'], lat=float(r['LATITUDE']), lon=float(r['LONGITUDE']), elev=num(r['ELEVATION']))
        fila.update({k: num(r.get(c)) for k, c in COLS.items()})
        filas.append(fila)
    e = pd.DataFrame(filas).dropna(subset=['lat', 'lon', 'nieve_anual_in'])
    e = e[(e['lat'] > 24) & (e['lat'] < 50) & (e['lon'] > -126) & (e['lon'] < -66)].reset_index(drop=True)
    e['elev'] = e['elev'].fillna(0)
    log(f'Estaciones con normal de nieve en los 48 estados: {len(e)}')

    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})
    rel = pd.read_csv(nc.FIJOS / 'relieve.csv', dtype={'leaid': str})
    assert (d['leaid'] == rel['leaid']).all()
    tr = Transformer.from_crs('EPSG:4326', 'EPSG:5070', always_xy=True)
    ex, ey = tr.transform(e['lon'].to_numpy(), e['lat'].to_numpy())
    dx, dy = tr.transform(d['lon'].to_numpy(), d['lat'].to_numpy())
    # Se buscan 12 candidatas y se queda con las 5 más «parecidas» (distancia + altitud)
    dist, idx = cKDTree(np.column_stack([ex, ey])).query(np.column_stack([dx, dy]), k=12)
    dist_km = dist / 1000.0
    dalt = np.abs(e['elev'].to_numpy()[idx] - rel['elev_escuelas_m'].to_numpy()[:, None])
    coste = (dist_km + 10.0) * (1.0 + dalt / ESCALA_ALT)
    orden = np.argsort(coste, axis=1)[:, :K]
    filas_i = np.arange(len(d))[:, None]
    idx_k, coste_k = idx[filas_i, orden], coste[filas_i, orden]
    w = 1.0 / coste_k ** 2

    out = pd.DataFrame({'leaid': d['leaid']})
    for k in COLS:
        v = e[k].to_numpy()[idx_k]
        ok = np.isfinite(v)
        out[k] = np.round(np.where(ok, v * w, 0).sum(axis=1) / np.maximum(np.where(ok, w, 0).sum(axis=1), 1e-12), 1)
    out['est_km'] = np.round(dist_km[:, 0], 0).astype(int)
    out.to_csv(nc.FIJOS / 'clima_nieve.csv', index=False)

    v = d.merge(out, on='leaid')
    log('── Resumen ──')
    log(out.describe().round(1).to_string())
    log('  nieve anual mediana por estado (in):')
    m = v.groupby('estado')['nieve_anual_in'].median().sort_values()
    log('   ' + ', '.join(f'{k} {x:.0f}' for k, x in m.items()))
    log('  comprobación:')
    for n, s in [('Buffalo City', 'NY'), ('Atlanta', 'GA'), ('Denver County 1', 'CO'), ('Minneapolis', 'MN'),
                 ('Houston', 'TX'), ('Tahoe-Truckee', 'CA'), ('Jefferson County', 'KY'), ('Chicago', 'IL'),
                 ('Boston', 'MA'), ('Dallas', 'TX'), ('Seattle', 'WA'), ('Syracuse City', 'NY')]:
        x = v[(v['estado'] == s) & v['nombre'].str.startswith(n)].head(1)
        if len(x):
            x = x.iloc[0]
            log(f'   {x["nombre"]:22s} {s}  {x["nieve_anual_in"]:6.1f} in/año · {x["dias_1in"]:4.1f} días ≥1 in · {x["dias_3in"]:4.1f} días ≥3 in · estación a {x["est_km"]} km')
    return 0


if __name__ == '__main__':
    sys.exit(main())
