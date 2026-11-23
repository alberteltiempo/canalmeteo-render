#!/usr/bin/env python3
"""
01_distritos.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Datos FIJOS de distritos escolares. Se ejecuta una vez (y cada otoño, cuando
el NCES publica límites nuevos).

Entrada (nieve/fuentes):
  distritos_tl25_sy2425/  NCES EDGE, límites de distritos escolares 2024-25
  condados_cb2024_500k/   Census, condados
  estados_cb2024_5m/      Census, estados

Salida (nieve/fijos):
  distritos.gpkg      geometría completa, 48 estados contiguos + DC
  distritos.csv       tabla: leaid, nombre, estado, condado, lat, lon, tz,
                      area_km2, tipo, grados, vecinos
  search.json         {"d":[[leaid, nombre, estado, condado], …]} para el buscador
  states.json         GeoJSON de estados simplificado (fondo del mapa)
  distritos.geojsonl  una línea por distrito (i, n, s) para tippecanoe

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 01_distritos.py
"""
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from timezonefinder import TimezoneFinder

BASE = Path('/opt/canalmeteo/nieve')
SRC = BASE / 'fuentes'
OUT = BASE / 'fijos'
OUT.mkdir(exist_ok=True)

# FIPS fuera de alcance: Alaska, Hawái y territorios
FUERA = {'02', '15', '60', '66', '69', '72', '78'}
N_VECINOS = 8


def log(msg):
    print(msg, flush=True)


def nombre_corto(nombre):
    """Quita la coletilla administrativa: el buscador y la ficha van más limpios."""
    n = re.sub(r'\s+(Unified |Public |Independent |Consolidated )?School District( \d+)?$', r'\2', nombre).strip()
    return n or nombre


# Clase de entidad del Census: los de primaria y secundaria se solapan entre sí
MTFCC_TIPO = {'G5400': 'primaria', 'G5410': 'secundaria', 'G5420': 'unificado'}


def main():
    shp = next((SRC / 'distritos_tl25_sy2425').rglob('*.shp'))
    log(f'Leyendo {shp.name} …')
    d = gpd.read_file(shp)
    total = len(d)
    d = d[~d['STATEFP'].isin(FUERA)]
    # «School District Not Defined»: relleno del Census, sin escuelas
    d = d[~d['GEOID'].str.endswith('99997')]
    d = d[~d['NAME'].str.contains('Not Defined', case=False, na=False)]
    d = d.drop_duplicates('GEOID').reset_index(drop=True)
    log(f'  {total} en el fichero → {len(d)} en los 48 estados contiguos + DC')

    d['geometry'] = d.geometry.make_valid()
    d['leaid'] = d['GEOID']
    d['nombre'] = d['NAME'].map(nombre_corto)
    d['tipo'] = d['MTFCC'].map(MTFCC_TIPO).fillna('otro')
    d['lat'] = d['INTPTLAT'].astype(float)
    d['lon'] = d['INTPTLON'].astype(float)
    d['area_km2'] = (d['ALAND'].astype(float) / 1e6).round(1)

    log('Estados y condados …')
    est = gpd.read_file(next((SRC / 'estados_cb2024_5m').rglob('*.shp')))
    fips2usps = dict(zip(est['STATEFP'], est['STUSPS']))
    d['estado'] = d['STATEFP'].map(fips2usps)

    cond = gpd.read_file(next((SRC / 'condados_cb2024_500k').rglob('*.shp')))[['NAMELSAD', 'STATEFP', 'geometry']]
    pts = gpd.GeoDataFrame(d[['leaid', 'STATEFP']], geometry=gpd.points_from_xy(d['lon'], d['lat']), crs=d.crs)
    j = gpd.sjoin(pts, cond.to_crs(d.crs), how='left', predicate='within')
    j = j[~j.index.duplicated()]
    d['condado'] = j['NAMELSAD'].reindex(d.index).fillna('')
    sin = int((d['condado'] == '').sum())
    if sin:
        # Punto interior sobre agua o en el borde: condado más cercano del mismo estado
        log(f'  {sin} sin condado por punto interior; se asigna el más cercano')
        c5070 = cond.to_crs(5070)
        p5070 = pts.to_crs(5070)
        for i in d.index[d['condado'] == '']:
            cs = c5070[c5070['STATEFP'] == d.at[i, 'STATEFP']]
            if len(cs):
                d.at[i, 'condado'] = cs.loc[cs.distance(p5070.geometry[i]).idxmin(), 'NAMELSAD']

    log('Zona horaria …')
    tf = TimezoneFinder()
    d['tz'] = [tf.timezone_at(lng=x, lat=y) or '' for x, y in zip(d['lon'], d['lat'])]

    log('Vecinos …')
    xy = np.column_stack([pts.to_crs(5070).geometry.x, pts.to_crs(5070).geometry.y])
    _, idx = cKDTree(xy).query(xy, k=N_VECINOS + 1)
    ids = d['leaid'].to_numpy()
    d['vecinos'] = [' '.join(ids[k] for k in fila[1:]) for fila in idx]

    cols = ['leaid', 'nombre', 'estado', 'condado', 'lat', 'lon', 'tz', 'area_km2',
            'tipo', 'LOGRADE', 'HIGRADE', 'vecinos']
    tabla = d[cols].rename(columns={'LOGRADE': 'grado_min', 'HIGRADE': 'grado_max'})
    tabla.to_csv(OUT / 'distritos.csv', index=False)
    d[cols[:9] + ['geometry']].to_file(OUT / 'distritos.gpkg', driver='GPKG')

    busca = {'d': tabla[['leaid', 'nombre', 'estado', 'condado']].values.tolist()}
    (OUT / 'search.json').write_text(json.dumps(busca, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    e = est[est['STATEFP'].isin(set(d['STATEFP']))][['STUSPS', 'NAME', 'geometry']].to_crs(4326)
    e['geometry'] = e.geometry.simplify(0.01)
    e.to_file(OUT / 'states.json', driver='GeoJSON', COORDINATE_PRECISION=3)

    log('GeoJSON por líneas para tippecanoe …')
    g = d[['leaid', 'nombre', 'estado', 'geometry']].rename(columns={'leaid': 'i', 'nombre': 'n', 'estado': 's'}).to_crs(4326)
    g.to_file(OUT / 'distritos.geojsonl', driver='GeoJSONSeq', COORDINATE_PRECISION=5)

    log('── Resumen ──')
    log(f'  distritos: {len(d)}')
    log('  por tipo: ' + ', '.join(f'{k} {v}' for k, v in d['tipo'].value_counts().items()))
    log(f'  estados: {d["estado"].nunique()} · zonas horarias: {d["tz"].nunique()} · sin zona: {(d["tz"] == "").sum()}')
    log(f'  sin condado: {(d["condado"] == "").sum()} · sin estado: {d["estado"].isna().sum()}')
    log('  más distritos: ' + ', '.join(f'{k} {v}' for k, v in d['estado'].value_counts().head(6).items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
