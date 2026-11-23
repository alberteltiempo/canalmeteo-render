#!/usr/bin/env python3
"""
nbm_comun.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Piezas compartidas para leer el NBM (CONUS, 2,5 km) desde AWS por rango de
bytes y resumirlo por distrito escolar. No guarda GRIB en disco.

  indice()      líneas del .idx de una hora de pronóstico
  rango()       bytes de un mensaje GRIB
  decodifica()  mensaje → matriz (Ny, Nx), fila 0 al sur, NaN en huecos
  Pesos         celdas del NBM de cada distrito → media / máximo / mínimo
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import eccodes as ec
import numpy as np

BASE = Path('/opt/canalmeteo/nieve')
FIJOS = BASE / 'fijos'
AWS_BUCKET = 'noaa-nbm-grib2-pds'
R_TIERRA = 6371200.0  # esfera del NBM


def _s3():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    if not hasattr(_s3, 'c'):
        _s3.c = boto3.client('s3', region_name='us-east-1',
                             config=Config(signature_version=UNSIGNED, max_pool_connections=32,
                                           retries={'max_attempts': 4}))
    return _s3.c


def clave(fecha, ciclo, fh):
    return f'blend.{fecha}/{ciclo:02d}/core/blend.t{ciclo:02d}z.core.f{fh:03d}.co.grib2'


def horas_disponibles(fecha, ciclo):
    """Horas de pronóstico ya publicadas de un ciclo (por su .idx)."""
    pref = f'blend.{fecha}/{ciclo:02d}/core/blend.t{ciclo:02d}z.core.f'
    horas = []
    for pag in _s3().get_paginator('list_objects_v2').paginate(Bucket=AWS_BUCKET, Prefix=pref):
        for o in pag.get('Contents', []):
            m = re.search(r'core\.f(\d{3})\.co\.grib2\.idx$', o['Key'])
            if m:
                horas.append(int(m.group(1)))
    return sorted(horas)


def ultimo_ciclo(fh_min=140, atras=12):
    """Ciclo más reciente ya completo hasta fh_min. Devuelve (fecha, ciclo, horas)."""
    t = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for k in range(atras):
        c = t - timedelta(hours=k)
        horas = horas_disponibles(c.strftime('%Y%m%d'), c.hour)
        if horas and horas[-1] >= fh_min:
            return c.strftime('%Y%m%d'), c.hour, horas
    raise RuntimeError('No hay ningún ciclo completo del NBM en las últimas horas')


def indice(fecha, ciclo, fh):
    """Registros del .idx: var, nivel, tr (ventana), det (determinista), off, fin."""
    key = clave(fecha, ciclo, fh) + '.idx'
    txt = _s3().get_object(Bucket=AWS_BUCKET, Key=key)['Body'].read().decode('utf-8', 'replace')
    recs = []
    for ln in txt.splitlines():
        p = ln.split(':')
        if len(p) < 6:
            continue
        # Determinista = la línea acaba justo tras la ventana (sin percentil ni probabilidad)
        recs.append(dict(off=int(p[1]), var=p[3], nivel=p[4], tr=p[5],
                         det=(len(p) == 7 and p[6] == '')))
    recs.sort(key=lambda r: r['off'])
    for a, b in zip(recs, recs[1:]):
        a['fin'] = b['off'] - 1
    if recs:
        recs[-1]['fin'] = ''
    return recs


def rango(fecha, ciclo, fh, off, fin):
    rng = f'bytes={off}-{fin}'
    return _s3().get_object(Bucket=AWS_BUCKET, Key=clave(fecha, ciclo, fh), Range=rng)['Body'].read()


def decodifica(msg):
    """Mensaje GRIB2 → (matriz float32 (Ny, Nx) con fila 0 al sur, rejilla)."""
    gid = ec.codes_new_from_message(msg)
    try:
        ec.codes_set(gid, 'missingValue', 1e30)
        nx = ec.codes_get(gid, 'Nx')
        ny = ec.codes_get(gid, 'Ny')
        v = ec.codes_get_values(gid).reshape(ny, nx).astype('float32')
        # El NBM va en boustrofedón y eccodes no lo deshace: voltear filas impares
        if ec.codes_get(gid, 'alternativeRowScanning'):
            v[1::2] = v[1::2, ::-1]
        if not ec.codes_get(gid, 'jScansPositively'):
            v = v[::-1]
        v[v > 1e29] = np.nan
        rej = dict(
            Nx=nx, Ny=ny,
            la1=ec.codes_get(gid, 'latitudeOfFirstGridPointInDegrees'),
            lo1=ec.codes_get(gid, 'longitudeOfFirstGridPointInDegrees'),
            lad=ec.codes_get(gid, 'LaDInDegrees'), lov=ec.codes_get(gid, 'LoVInDegrees'),
            lat1=ec.codes_get(gid, 'Latin1InDegrees'), lat2=ec.codes_get(gid, 'Latin2InDegrees'),
            dx=ec.codes_get(gid, 'DxInMetres'), dy=ec.codes_get(gid, 'DyInMetres'),
        )
    finally:
        ec.codes_release(gid)
    return v, rej


def proj_nbm(rej):
    """Cadena PROJ de la rejilla Lambert del NBM."""
    return (f"+proj=lcc +lat_1={rej['lat1']} +lat_2={rej['lat2']} +lat_0={rej['lad']} "
            f"+lon_0={rej['lov']} +R={R_TIERRA} +units=m +no_defs")


def origen_xy(rej):
    """x, y (m) del centro de la primera celda (esquina suroeste)."""
    from pyproj import Transformer
    tr = Transformer.from_crs('EPSG:4326', proj_nbm(rej), always_xy=True)
    lo = rej['lo1'] - 360 if rej['lo1'] > 180 else rej['lo1']
    return tr.transform(lo, rej['la1'])


def latlon_celdas(rej):
    """lat, lon (Ny, Nx) del centro de cada celda."""
    from pyproj import Transformer
    x0, y0 = origen_xy(rej)
    x = x0 + np.arange(rej['Nx']) * rej['dx']
    y = y0 + np.arange(rej['Ny']) * rej['dy']
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs(proj_nbm(rej), 'EPSG:4326', always_xy=True).transform(xx, yy)
    return lat, lon


class Pesos:
    """Celdas del NBM que caen en cada distrito (fijos/pesos_nbm.npz, de 03_rejilla.py)."""

    def __init__(self, ruta=FIJOS / 'pesos_nbm.npz'):
        z = np.load(ruta, allow_pickle=False)
        self.leaid = z['leaid']
        self.ptr = z['ptr']
        self.idx = z['idx']
        self.rej = json.loads(str(z['rejilla']))
        self._ini = self.ptr[:-1]
        self.n = np.diff(self.ptr)

    def comprueba(self, rej):
        for k in ('Nx', 'Ny'):
            if rej[k] != self.rej[k]:
                raise RuntimeError(f'La rejilla del NBM ha cambiado ({k}): rehacer 03_rejilla.py')
        for k in ('la1', 'lo1', 'dx'):
            if abs(rej[k] - self.rej[k]) > 1e-3:
                raise RuntimeError(f'La rejilla del NBM ha cambiado ({k}): rehacer 03_rejilla.py')

    def media(self, campo):
        v = campo.ravel()[self.idx]
        ok = np.isfinite(v)
        s = np.add.reduceat(np.where(ok, v, 0.0).astype('float64'), self._ini)
        c = np.add.reduceat(ok.astype('int32'), self._ini)
        return np.where(c > 0, s / np.maximum(c, 1), np.nan).astype('float32')

    def maximo(self, campo):
        return np.fmax.reduceat(campo.ravel()[self.idx], self._ini)

    def minimo(self, campo):
        return np.fmin.reduceat(campo.ravel()[self.idx], self._ini)
