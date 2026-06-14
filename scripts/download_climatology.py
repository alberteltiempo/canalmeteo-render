#!/usr/bin/env python3
"""
===============================================================================
download_climatology.py — Canal Meteo TV
===============================================================================
Descarga la climatología NCEI Daily Gridded Normals 1991-2020 y construye
un cubo NetCDF compacto (Tavg por día del año, regrillado al dominio CONUS
del pipeline) listo para calcular anomalías de temperatura en model_pipeline.py.

Ejecutar UNA sola vez (o ~1 vez al año si quieres re-actualizar).
Genera: /opt/canalmeteo/data/climatology/tavg_normals_1991_2020.nc

Uso:
  python download_climatology.py
  python download_climatology.py --force  # re-descarga aunque exista
===============================================================================
"""
import os
import sys
import argparse
import logging
import requests
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# Dominio CONUS del pipeline (mismo que BASE en model_pipeline.py)
LAT_MIN, LAT_MAX = 24.0, 50.0
LON_MIN, LON_MAX = -125.0, -66.0

# Resolución de salida — coincide con img_width/img_height del pipeline
OUT_W, OUT_H = 590, 260

NCEI_URL = ("https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/"
            "tavg-1991_2020-daily-normals-v1.0.nc")

OUT_DIR = "/opt/canalmeteo/data/climatology"
RAW_PATH = os.path.join(OUT_DIR, "tavg-1991_2020-daily-normals-v1.0.nc")
OUT_PATH = os.path.join(OUT_DIR, "tavg_normals_1991_2020.nc")


def download(url, dest):
    """Descarga con barra de progreso simple."""
    log.info(f"Descargando {url}")
    log.info(f"  → {dest}")
    r = requests.get(url, stream=True, timeout=300,
                     headers={'User-Agent': 'CanalMeteoTV/1.0'})
    r.raise_for_status()
    total = int(r.headers.get('content-length', 0))
    done = 0
    last_pct = -1
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = int(done * 100 / total)
                if pct != last_pct and pct % 5 == 0:
                    log.info(f"  {pct}% ({done // (1024*1024)} MB / {total // (1024*1024)} MB)")
                    last_pct = pct
    log.info(f"  ✅ Descargado: {done // (1024*1024)} MB")


def regrid_and_save(raw_path, out_path):
    """Lee el NetCDF original (1/24° CONUS), recorta al dominio y regrilla
    a (OUT_H × OUT_W) usando interpolación bilineal."""
    try:
        import xarray as xr
    except ImportError:
        log.error("xarray no instalado. Ejecuta: pip install xarray netcdf4")
        sys.exit(1)

    log.info(f"Abriendo {raw_path}")
    ds = xr.open_dataset(raw_path)
    log.info(f"  Variables: {list(ds.data_vars)}")
    log.info(f"  Dims: {dict(ds.sizes)}")

    # Identificar la variable de Tavg
    tavg_var = None
    for cand in ['tavg', 'TAVG', 'Tavg', 'tmean', 'tmp', 'temperature']:
        if cand in ds.data_vars:
            tavg_var = cand
            break
    if tavg_var is None:
        # Toma la primera variable con dim de tiempo y lat/lon
        for v in ds.data_vars:
            if ds[v].ndim == 3:
                tavg_var = v
                break
    if tavg_var is None:
        log.error("No se encontró variable Tavg")
        sys.exit(1)
    log.info(f"  Usando variable: {tavg_var}")

    # Identificar nombres de dimensiones
    lat_name = 'lat' if 'lat' in ds.coords else ('latitude' if 'latitude' in ds.coords else None)
    lon_name = 'lon' if 'lon' in ds.coords else ('longitude' if 'longitude' in ds.coords else None)
    time_name = 'time' if 'time' in ds.dims else ('day_of_year' if 'day_of_year' in ds.dims else None)
    if not lat_name or not lon_name:
        log.error(f"No se encontraron coords lat/lon. Coords: {list(ds.coords)}")
        sys.exit(1)

    # Recortar al dominio CONUS del pipeline
    da = ds[tavg_var]
    lat_vals = ds[lat_name].values
    lon_vals = ds[lon_name].values

    # Asegurar lat descendente (norte → sur)
    if lat_vals[0] < lat_vals[-1]:
        da = da.isel({lat_name: slice(None, None, -1)})
        lat_vals = lat_vals[::-1]

    # Convertir lons a -180..180 si vienen en 0..360
    if lon_vals.max() > 180:
        new_lons = np.where(lon_vals > 180, lon_vals - 360, lon_vals)
        order = np.argsort(new_lons)
        da = da.isel({lon_name: order})
        lon_vals = new_lons[order]

    # Subset por bounding box
    lat_mask = (lat_vals >= LAT_MIN) & (lat_vals <= LAT_MAX)
    lon_mask = (lon_vals >= LON_MIN) & (lon_vals <= LON_MAX)
    da = da.isel({lat_name: lat_mask, lon_name: lon_mask})
    log.info(f"  Subset CONUS: {da.shape}")

    # Detectar unidades — los NCEI normals están en °F; si vienen en °C los pasamos a °F
    units = da.attrs.get('units', '').lower()
    if 'celsius' in units or '°c' in units or units == 'c':
        log.info("  Conversión °C → °F")
        da = da * 9/5 + 32
        da.attrs['units'] = 'degF'
    elif 'fahrenheit' in units or '°f' in units or units == 'f':
        log.info("  Ya en °F")
    else:
        log.warning(f"  Unidades desconocidas '{units}' — se asume °F")

    # Regrillar a OUT_H × OUT_W con interpolación bilineal
    target_lats = np.linspace(LAT_MAX, LAT_MIN, OUT_H)
    target_lons = np.linspace(LON_MIN, LON_MAX, OUT_W)
    log.info(f"  Regrillando 365 días a {OUT_H}×{OUT_W}…")
    da_regrid = da.interp({lat_name: target_lats, lon_name: target_lons},
                          method='linear')

    # Guardar como NetCDF compacto (float32, compresión)
    out = da_regrid.rename('tavg_F').to_dataset()
    out.attrs['source'] = 'NCEI Daily Gridded Normals 1991-2020 v1.0'
    out.attrs['domain'] = 'CONUS'
    out.attrs['lat_min'] = LAT_MIN
    out.attrs['lat_max'] = LAT_MAX
    out.attrs['lon_min'] = LON_MIN
    out.attrs['lon_max'] = LON_MAX
    out.attrs['generated_by'] = 'Canal Meteo TV — download_climatology.py'

    encoding = {'tavg_F': {'dtype': 'float32', 'zlib': True, 'complevel': 4}}
    out.to_netcdf(out_path, encoding=encoding)
    log.info(f"  ✅ Guardado: {out_path} ({os.path.getsize(out_path) // 1024} KB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true', help='Re-descargar aunque exista')
    args = parser.parse_args()

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)

    if os.path.exists(OUT_PATH) and not args.force:
        log.info(f"Climatología ya existe: {OUT_PATH}")
        log.info("Usa --force para re-descargar")
        return

    if not os.path.exists(RAW_PATH) or args.force:
        download(NCEI_URL, RAW_PATH)
    else:
        log.info(f"Raw NetCDF ya descargado: {RAW_PATH}")

    regrid_and_save(RAW_PATH, OUT_PATH)

    # Limpieza opcional del raw (~1.2GB)
    try:
        os.remove(RAW_PATH)
        log.info(f"Limpieza: borrado {RAW_PATH}")
    except Exception:
        pass

    log.info("✅ Climatología lista para usar en model_pipeline.py")


if __name__ == '__main__':
    main()
