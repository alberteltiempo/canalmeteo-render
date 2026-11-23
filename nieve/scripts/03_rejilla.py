#!/usr/bin/env python3
"""
03_rejilla.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Datos FIJOS: qué celdas de la rejilla del NBM (CONUS, 2,5 km) caen dentro de
cada distrito escolar. Se ejecuta una vez (y si cambian los distritos o el NBM).

Entrada:  fijos/distritos.gpkg, fijos/distritos.csv y un campo del NBM (AWS)
Salida:   fijos/pesos_nbm.npz   leaid, ptr, idx (celdas en formato CSR), rejilla

Una celda pertenece al distrito si su centro cae dentro. Los distritos más
pequeños que una celda toman la celda más cercana a su punto interior.

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 03_rejilla.py
"""
import json
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from affine import Affine
from pyproj import Transformer
from rasterio.features import rasterize

import nbm_comun as nc


def log(msg):
    print(msg, flush=True)


def rejilla_nbm():
    fecha, ciclo, _ = nc.ultimo_ciclo()
    for r in nc.indice(fecha, ciclo, 1):
        if r['var'] == 'TMP' and r['nivel'] == '2 m above ground' and r['det']:
            _, rej = nc.decodifica(nc.rango(fecha, ciclo, 1, r['off'], r['fin']))
            log(f'Rejilla del NBM (ciclo {fecha} {ciclo:02d}z): {rej}')
            return rej
    raise RuntimeError('No encuentro TMP 2 m en el NBM')


def main():
    rej = rejilla_nbm()
    nx, ny, dx, dy = rej['Nx'], rej['Ny'], rej['dx'], rej['dy']
    x0, y0 = nc.origen_xy(rej)
    proj = nc.proj_nbm(rej)

    tabla = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})
    log('Leyendo distritos …')
    d = gpd.read_file(nc.FIJOS / 'distritos.gpkg')[['leaid', 'tipo', 'geometry']]
    d = d.set_index('leaid').loc[tabla['leaid']].reset_index().to_crs(proj)

    # Norte arriba para rasterizar; luego se voltea (fila 0 del NBM = sur)
    af = Affine(dx, 0, x0 - dx / 2, 0, -dy, y0 + (ny - 0.5) * dy)
    celdas = [None] * len(d)
    # Por tipo: primaria y secundaria se solapan entre sí; dentro de un tipo, no
    for tipo, g in d.groupby('tipo'):
        log(f'  rasterizando {tipo}: {len(g)}')
        r = rasterize(((geom, k + 1) for k, geom in zip(g.index, g.geometry)),
                      out_shape=(ny, nx), transform=af, fill=0, dtype='int32')[::-1].ravel()
        pos = np.flatnonzero(r)
        orden = pos[np.argsort(r[pos], kind='stable')]
        ks, ini = np.unique(r[orden], return_index=True)
        for k, trozo in zip(ks, np.split(orden, ini[1:])):
            celdas[k - 1] = trozo.astype('int32')

    # Distritos sin ninguna celda: la más cercana a su punto interior
    tr = Transformer.from_crs('EPSG:4326', proj, always_xy=True)
    px, py = tr.transform(tabla['lon'].to_numpy(), tabla['lat'].to_numpy())
    ci = np.clip(np.rint((px - x0) / dx).astype(int), 0, nx - 1)
    cj = np.clip(np.rint((py - y0) / dy).astype(int), 0, ny - 1)
    sin = [k for k, c in enumerate(celdas) if c is None]
    for k in sin:
        celdas[k] = np.array([cj[k] * nx + ci[k]], dtype='int32')

    n = np.array([len(c) for c in celdas])
    ptr = np.concatenate([[0], np.cumsum(n)]).astype('int64')
    idx = np.concatenate(celdas)
    np.savez_compressed(nc.FIJOS / 'pesos_nbm.npz', leaid=tabla['leaid'].to_numpy().astype('U7'),
                        ptr=ptr, idx=idx, rejilla=json.dumps(rej))

    # Comprobación: el centro de las celdas de cada distrito debe caer cerca de su punto interior
    lat, lon = nc.latlon_celdas(rej)
    p = nc.Pesos()
    dlat = np.abs(p.media(lat.astype('float32')) - tabla['lat'].to_numpy())
    dlon = np.abs(p.media(lon.astype('float32')) - tabla['lon'].to_numpy())
    lejos = (dlat > 0.5) | (dlon > 0.7)

    log('── Resumen ──')
    log(f'  distritos: {len(n)} · celdas asignadas: {len(idx)}')
    log(f'  celdas por distrito: mediana {int(np.median(n))}, mín {n.min()}, máx {n.max()}')
    log(f'  con 1 celda: {(n == 1).sum()} · con menos de 4: {(n < 4).sum()} · sin celda propia (la más cercana): {len(sin)}')
    log(f'  desvío medio celdas↔punto interior: {dlat.mean():.3f}° lat, {dlon.mean():.3f}° lon · lejos: {lejos.sum()}')
    if lejos.sum():
        log(tabla.loc[lejos, ['leaid', 'nombre', 'estado', 'area_km2']].head(10).to_string())
    return 0


if __name__ == '__main__':
    sys.exit(main())
