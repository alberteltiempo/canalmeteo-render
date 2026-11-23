#!/usr/bin/env python3
"""
03b_escuelas.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Datos FIJOS: dónde están las escuelas de cada distrito. El pronóstico se mide
ahí y no en la media de toda el área: muchos distritos del Oeste incluyen
montañas deshabitadas donde nieva mucho más que en el pueblo.

Entrada:  fuentes/escuelas/x/EDGE_GEOCODE_PUBLICSCH_2425.TXT (NCES, escuelas públicas)
          fijos/pesos_nbm.npz (03_rejilla.py)
Salida:   fijos/pesos_escuelas.npz  como pesos_nbm.npz, pero con la celda de cada
                                    escuela (repetida si hay varias en la misma)
          fijos/escuelas.csv        leaid, n_escuelas, rural_pct, zips

Los distritos sin escuelas en el fichero conservan las celdas de su área.

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 03b_escuelas.py
"""
import json
import sys

import numpy as np
import pandas as pd
from pyproj import Transformer

import nbm_comun as nc

ORIGEN = nc.BASE / 'fuentes' / 'escuelas' / 'x' / 'EDGE_GEOCODE_PUBLICSCH_2425.TXT'


def log(msg):
    print(msg, flush=True)


def main():
    e = pd.read_csv(ORIGEN, sep='|', header=None, dtype=str, usecols=[1, 7, 11, 12, 13],
                    names=['leaid', 'zip', 'locale', 'lat', 'lon'], encoding='latin-1')
    e['lat'] = e['lat'].astype(float)
    e['lon'] = e['lon'].astype(float)
    area = nc.Pesos()
    rej = area.rej
    pos = {l: k for k, l in enumerate(area.leaid)}
    total = len(e)
    e = e[e['leaid'].isin(pos)].copy()
    log(f'Escuelas públicas: {total} · en distritos con límites (48 estados + DC): {len(e)}')

    x0, y0 = nc.origen_xy(rej)
    px, py = Transformer.from_crs('EPSG:4326', nc.proj_nbm(rej), always_xy=True).transform(e['lon'].to_numpy(), e['lat'].to_numpy())
    ci = np.clip(np.rint((px - x0) / rej['dx']).astype(int), 0, rej['Nx'] - 1)
    cj = np.clip(np.rint((py - y0) / rej['dy']).astype(int), 0, rej['Ny'] - 1)
    e['celda'] = cj * rej['Nx'] + ci
    e['k'] = e['leaid'].map(pos)
    e['rural'] = e['locale'].str.startswith('4')

    por = e.groupby('k')['celda'].apply(lambda s: s.to_numpy(dtype='int32'))
    celdas = [por[k] if k in por.index else area.idx[area.ptr[k]:area.ptr[k + 1]] for k in range(len(area.leaid))]
    n = np.array([len(c) for c in celdas])
    np.savez_compressed(nc.FIJOS / 'pesos_escuelas.npz', leaid=area.leaid,
                        ptr=np.concatenate([[0], np.cumsum(n)]).astype('int64'),
                        idx=np.concatenate(celdas), rejilla=json.dumps(rej))

    g = e.groupby('leaid')
    t = pd.DataFrame({'leaid': area.leaid}).merge(pd.DataFrame({
        'n_escuelas': g.size(),
        'rural_pct': (g['rural'].mean() * 100).round(0).astype(int),
        'zips': g['zip'].agg(lambda s: ' '.join(sorted(set(s.dropna())))),
    }).reset_index(), on='leaid', how='left')
    t['n_escuelas'] = t['n_escuelas'].fillna(0).astype(int)
    t.to_csv(nc.FIJOS / 'escuelas.csv', index=False)

    log('── Resumen ──')
    log(f'  distritos con escuelas: {(t["n_escuelas"] > 0).sum()} · sin escuelas (usan su área): {(t["n_escuelas"] == 0).sum()}')
    log(f'  escuelas por distrito: mediana {int(t.loc[t["n_escuelas"] > 0, "n_escuelas"].median())}, máx {t["n_escuelas"].max()}')
    log(f'  distritos con todas sus escuelas en zona rural: {(t["rural_pct"] == 100).sum()} · códigos postales distintos: {e["zip"].nunique()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
