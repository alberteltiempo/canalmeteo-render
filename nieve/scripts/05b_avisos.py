#!/usr/bin/env python3
"""
05b_avisos.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Avisos de invierno del NWS que tocan a cada distrito. Lee el fichero que ya
publica alertas_nws.py en el CDN (no vuelve a consultar al NWS) y lo cruza con
las celdas donde están las escuelas.

Entrada:  CDN data/alertas/alertas_nws.json, fijos/pesos_escuelas.npz
Salida:   trabajo/avisos.csv   leaid, evento, evento_es, desde, hasta (UTC)

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 05b_avisos.py
"""
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

import nbm_comun as nc

URL = 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/alertas/alertas_nws.json'
# Avisos que cuentan y cuánto suman al índice (07_indice.py)
EVENTOS = {
    'Blizzard Warning': 0.6, 'Ice Storm Warning': 0.6, 'Winter Storm Warning': 0.4,
    'Lake Effect Snow Warning': 0.3, 'Extreme Cold Warning': 0.3, 'Wind Chill Warning': 0.3,
    'Winter Storm Watch': 0.15, 'Freezing Rain Advisory': 0.15,
    'Winter Weather Advisory': 0.1, 'Cold Weather Advisory': 0.1, 'Wind Chill Advisory': 0.1,
    'Extreme Cold Watch': 0.1, 'Lake Effect Snow Advisory': 0.1, 'Snow Squall Warning': 0.1,
}
COLS = ['leaid', 'evento', 'evento_es', 'desde', 'hasta']


def log(msg):
    print(msg, flush=True)


def geometria(a):
    partes = []
    try:
        if a.get('geometry'):
            partes.append(shape(a['geometry']))
    except Exception:
        pass
    if not partes:
        for anillo in a.get('zone_polygons') or []:
            try:
                partes.append(Polygon(anillo))
            except Exception:
                pass
    partes = [g.buffer(0) for g in partes if not g.is_empty]
    return unary_union(partes) if partes else None


def main():
    salida = nc.BASE / 'trabajo' / 'avisos.csv'
    j = requests.get(URL, timeout=60).json()
    filas = []
    for a in j.get('alertas', []):
        if a.get('evento') not in EVENTOS:
            continue
        g = geometria(a)
        if g is None:
            continue
        filas.append(dict(evento=a['evento'], evento_es=a.get('evento_es') or a['evento'],
                          desde=a.get('onset') or a.get('effective'),
                          hasta=a.get('ends') or a.get('expires'), geometry=g))
    log(f'Avisos del NWS: {len(j.get("alertas", []))} · de invierno con geometría: {len(filas)} · fichero de {j.get("timestamp")}')
    if not filas:
        pd.DataFrame(columns=COLS).to_csv(salida, index=False)
        return 0

    av = gpd.GeoDataFrame(filas, crs='EPSG:4326')
    for c in ('desde', 'hasta'):
        av[c] = pd.to_datetime(av[c], utc=True, errors='coerce')

    # Puntos: el centro de cada celda con escuelas (precisión de 2,5 km)
    p = nc.Pesos(nc.FIJOS / 'pesos_escuelas.npz')
    lat, lon = nc.latlon_celdas(p.rej)
    pts = gpd.GeoDataFrame({'leaid': np.repeat(p.leaid, p.n)},
                           geometry=gpd.points_from_xy(lon.ravel()[p.idx], lat.ravel()[p.idx]), crs='EPSG:4326')
    x = gpd.sjoin(pts, av, predicate='within')[COLS].drop_duplicates()
    x.to_csv(salida, index=False)
    log(f'  distritos con algún aviso de invierno: {x["leaid"].nunique()}')
    if len(x):
        log('  ' + ', '.join(f'{k}: {v}' for k, v in x.drop_duplicates(['leaid', 'evento'])['evento'].value_counts().items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
