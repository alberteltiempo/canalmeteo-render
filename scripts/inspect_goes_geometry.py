#!/usr/bin/env python3
"""
inspect_goes_geometry.py — Canal Meteo TV / Tormenta
Paso 1 antes de construir los pipelines FD y Meso.

Baja el NetCDF más reciente de Full Disk y de Mesoescala (M1/M2) del bucket
publico noaa-goes19 (GOES-East / GOES19) y extrae la geometria EXACTA que
necesitan los LUT de reproyeccion: parametros de proyeccion geostationary,
scan-angle bounds (radianes) y, para meso, el bounding box geografico real
del frame (porque el sector se mueve).

Uso en nimbus-01:
    /opt/canalmeteo/venv/bin/python3 inspect_goes_geometry.py

Requisitos (verificar en el venv):
    aws cli con perfil que permita --no-sign-request (ya disponible)
    netCDF4   -> uv pip install netCDF4   (si falta)
    pyproj    -> ya en el venv

NO escribe nada en produccion. Solo descarga a /tmp e imprime.
"""

import subprocess
import sys
import os
from datetime import datetime, timezone, timedelta

try:
    from netCDF4 import Dataset
except ImportError:
    sys.exit("Falta netCDF4 en el venv: uv pip install netCDF4")

try:
    from pyproj import Transformer
except ImportError:
    sys.exit("Falta pyproj en el venv")

BUCKET = 'noaa-goes19'   # GOES-East. Para GOES-West cambiar a noaa-goes18
TMP = '/tmp'

# Productos a inspeccionar. CMIP = Cloud & Moisture Imagery (banda unica calibrada).
# C13 = IR limpio (10.3um), buena referencia de geometria a 2km.
TARGETS = [
    ('Full Disk',     'ABI-L2-CMIPF', 'CMIPF-M6C13'),
    ('Mesoescala M1', 'ABI-L2-CMIPM', 'CMIPM1-M6C13'),
    ('Mesoescala M2', 'ABI-L2-CMIPM', 'CMIPM2-M6C13'),
]


def latest_key(prefix_product, match):
    """Encuentra el objeto .nc mas reciente para un producto, retrocediendo
    horas si la hora actual aun no tiene datos."""
    now = datetime.now(timezone.utc)
    for back in range(0, 4):  # probar hasta 4 horas atras
        t = now - timedelta(hours=back)
        prefix = f"{prefix_product}/{t.year}/{t.timetuple().tm_yday:03d}/{t.hour:02d}/"
        cmd = ['aws', 's3', 'ls', f's3://{BUCKET}/{prefix}',
               '--no-sign-request']
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            continue
        keys = [ln.split()[-1] for ln in r.stdout.splitlines()
                if ln.strip() and match in ln and ln.strip().endswith('.nc')]
        if keys:
            keys.sort()  # nombre lleva timestamp -> el ultimo es el mas nuevo
            return prefix + keys[-1]
    return None


def download(key):
    dest = os.path.join(TMP, os.path.basename(key))
    cmd = ['aws', 's3', 'cp', f's3://{BUCKET}/{key}', dest,
           '--no-sign-request']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"    error descargando: {r.stderr.strip()[:200]}")
        return None
    return dest


def inspect(label, path):
    print(f"\n{'='*70}\n{label}\n  {os.path.basename(path)}\n{'='*70}")
    ds = Dataset(path)

    proj = ds.variables['goes_imager_projection']
    lon_0 = float(proj.longitude_of_projection_origin)
    H = float(proj.perspective_point_height)
    a = float(proj.semi_major_axis)
    b = float(proj.semi_minor_axis)
    sweep = str(proj.sweep_angle_axis)

    x = ds.variables['x'][:]   # radianes (scale_factor aplicado por netCDF4)
    y = ds.variables['y'][:]
    nx, ny = len(x), len(y)
    x_min, x_max = float(x.min()), float(x.max())
    y_min, y_max = float(y.min()), float(y.max())

    print(f"  Proyeccion geos:")
    print(f"    lon_0 = {lon_0:.4f}")
    print(f"    h     = {H:.1f}")
    print(f"    a     = {a:.4f}")
    print(f"    b     = {b:.6f}")
    print(f"    sweep = {sweep}")
    print(f"  Dimensiones NetCDF: {nx} x {ny}")
    print(f"  Scan-angle bounds (rad):")
    print(f"    x: [{x_min:.6f}, {x_max:.6f}]   (oeste -> este)")
    print(f"    y: [{y_min:.6f}, {y_max:.6f}]   (sur -> norte)")

    # Bounding box geografico: convertir las 4 esquinas + centro a lat/lon
    proj_str = (f"+proj=geos +lon_0={lon_0} +h={H} +a={a} +b={b} "
                f"+sweep={sweep} +units=rad")
    # geos en radianes: pyproj usa metros, asi que multiplicamos por H
    proj_m = (f"+proj=geos +lon_0={lon_0} +h={H} +a={a} +b={b} "
              f"+sweep={sweep} +units=m")
    tf = Transformer.from_crs(proj_m, "EPSG:4326", always_xy=True)

    corners = {
        'NO (top-left)':  (x_min * H, y_max * H),
        'NE (top-right)': (x_max * H, y_max * H),
        'SO (bot-left)':  (x_min * H, y_min * H),
        'SE (bot-right)': (x_max * H, y_min * H),
        'Centro':         ((x_min + x_max) / 2 * H, (y_min + y_max) / 2 * H),
    }
    print(f"  Bounding box geografico (lat/lon):")
    lons, lats = [], []
    for name, (gx, gy) in corners.items():
        lon, lat = tf.transform(gx, gy)
        flag = '' if (abs(lon) < 1e30 and abs(lat) < 1e30) else '  <-- fuera del disco'
        print(f"    {name:16s}: lat={lat:8.3f}  lon={lon:9.3f}{flag}")
        if abs(lon) < 1e30 and abs(lat) < 1e30:
            lons.append(lon); lats.append(lat)
    if lons:
        print(f"  OUT_BOUNDS sugerido para este frame:")
        print(f"    north={max(lats):.2f} south={min(lats):.2f} "
              f"west={min(lons):.2f} east={max(lons):.2f}")
    ds.close()


def main():
    print("Inspeccion geometria GOES19 — Canal Meteo TV")
    print(f"UTC ahora: {datetime.now(timezone.utc):%Y-%m-%d %H:%M}")
    for label, product, match in TARGETS:
        print(f"\nBuscando ultimo {label} ({product} / {match})...")
        key = latest_key(product, match)
        if not key:
            print(f"  sin datos recientes para {label}")
            continue
        print(f"  key: {key}")
        path = download(key)
        if path:
            try:
                inspect(label, path)
            except Exception as e:
                print(f"  error inspeccionando: {e}")


if __name__ == '__main__':
    main()
