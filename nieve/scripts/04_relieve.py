#!/usr/bin/env python3
"""
04_relieve.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Datos FIJOS: relieve de cada distrito, para medir la dificultad del transporte
escolar (cuestas). Se ejecuta una vez.

Entrada:  ETOPO 2022 60″ (ya está en nimbus-03) y fijos/pesos_nbm.npz
Salida:   fijos/relieve.csv   leaid, elev_m, elev_escuelas_m, elev_rango_m, pendiente_m_km, rugosidad_m

El relieve se lleva a la rejilla del NBM y se resume con las mismas celdas que
el pronóstico. «rugosidad» es la desviación de la altitud en un entorno de
12,5 km: sirve también para los distritos de una sola celda.

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 04_relieve.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.ndimage import map_coordinates, uniform_filter

import nbm_comun as nc

DEM = Path('/opt/canalmeteo/data/dem/ETOPO_2022_v1_60s_N90W180_surface.nc')
VENTANA = 5  # celdas (12,5 km)


def log(msg):
    print(msg, flush=True)


def main():
    p = nc.Pesos()
    rej = p.rej
    lat, lon = nc.latlon_celdas(rej)

    log('Leyendo ETOPO …')
    ds = xr.open_dataset(DEM)
    z = ds['z'].sel(lat=slice(lat.min() - 0.5, lat.max() + 0.5), lon=slice(lon.min() - 0.5, lon.max() + 0.5))
    zl, zo = z['lat'].to_numpy(), z['lon'].to_numpy()
    fi = (lat - zl[0]) / (zl[1] - zl[0])
    co = (lon - zo[0]) / (zo[1] - zo[0])
    elev = map_coordinates(z.to_numpy().astype('float32'), [fi, co], order=1, mode='nearest')
    elev = np.maximum(elev, 0).astype('float32')  # el mar no cuenta como desnivel

    gy, gx = np.gradient(elev, rej['dy'] / 1000.0, rej['dx'] / 1000.0)
    pend = np.hypot(gx, gy).astype('float32')  # m por km
    m1 = uniform_filter(elev.astype('float64'), VENTANA)
    m2 = uniform_filter(elev.astype('float64') ** 2, VENTANA)
    rug = np.sqrt(np.maximum(m2 - m1 ** 2, 0)).astype('float32')

    t = pd.DataFrame({
        'leaid': p.leaid,
        'elev_m': np.round(p.media(elev)).astype(int),
        'elev_escuelas_m': np.round(nc.Pesos(nc.FIJOS / 'pesos_escuelas.npz').media(elev)).astype(int),
        'elev_rango_m': np.round(p.maximo(elev) - p.minimo(elev)).astype(int),
        'pendiente_m_km': np.round(p.media(pend), 1),
        'rugosidad_m': np.round(p.media(rug), 1),
    })
    t.to_csv(nc.FIJOS / 'relieve.csv', index=False)

    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str}).merge(t, on='leaid')
    log('── Resumen ──')
    log(t.describe().round(1).to_string())
    log('  más abruptos:')
    log(d.nlargest(8, 'rugosidad_m')[['nombre', 'estado', 'elev_m', 'pendiente_m_km', 'rugosidad_m']].to_string(index=False))
    log('  rugosidad mediana por estado (extremos):')
    e = d.groupby('estado')['rugosidad_m'].median().sort_values()
    log('   llanos: ' + ', '.join(f'{k} {v:.0f}' for k, v in e.head(6).items()))
    log('   abruptos: ' + ', '.join(f'{k} {v:.0f}' for k, v in e.tail(6).items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
