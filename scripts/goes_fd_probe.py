#!/usr/bin/env python3
"""
goes_fd_probe.py - Sondeo de GOES-18 (GOES-West) ABI-L2-CMIPF banda 13 (Full Disk).
Confirma: (1) parametros de proyeccion geoestacionaria, (2) que Full Disk cubre
la zona tropical EPAC (bbox configurable) con >> 8% de pixeles validos.

No escribe nada en produccion: solo descarga el ultimo C13 a /tmp y reporta.
Requiere: boto3, numpy, xarray + netCDF4 (o h5netcdf) en el venv.

Uso:
    python3 goes_fd_probe.py
    python3 goes_fd_probe.py --bbox -120 5 -80 30 --stride 4
"""
import argparse, datetime as dt, sys, os, tempfile
import numpy as np

BUCKET = "noaa-goes18"          # GOES-West
PRODUCT = "ABI-L2-CMIPF"        # Cloud & Moisture Imagery, Full Disk
BAND = "C13"                    # IR limpio 10.3 um (dia+noche)


def s3_client():
    import boto3
    from botocore import UNSIGNED
    from botocore.client import Config
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def latest_key(s3, when=None):
    """Devuelve la key del ultimo C13 disponible buscando hacia atras por hora."""
    now = when or dt.datetime.now(dt.timezone.utc)
    for back in range(0, 6):  # mira hasta 5 horas atras
        t = now - dt.timedelta(hours=back)
        prefix = f"{PRODUCT}/{t:%Y}/{t:%j}/{t:%H}/"
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        keys = [o["Key"] for o in resp.get("Contents", []) if f"-M6{BAND}_" in o["Key"] or f"-M3{BAND}_" in o["Key"]]
        if keys:
            keys.sort()  # nombre incluye sYYYYDOYHHMMSS -> orden cronologico
            return keys[-1]
    return None


def geos_to_lonlat(x, y, lon_origin_deg, H, req, rpol):
    """Scan-angle (rad) -> lon/lat (deg). Formula NOAA ABI PUG. Off-disk -> NaN."""
    lon0 = np.deg2rad(lon_origin_deg)
    X, Y = np.meshgrid(x, y)
    with np.errstate(invalid="ignore"):
        a = np.sin(X)**2 + np.cos(X)**2 * (np.cos(Y)**2 + (req**2 / rpol**2) * np.sin(Y)**2)
        b = -2.0 * H * np.cos(X) * np.cos(Y)
        c = H**2 - req**2
        disc = b**2 - 4.0 * a * c
        disc = np.where(disc < 0, np.nan, disc)
        rs = (-b - np.sqrt(disc)) / (2.0 * a)
        sx = rs * np.cos(X) * np.cos(Y)
        sy = -rs * np.sin(X)
        sz = rs * np.cos(X) * np.sin(Y)
        lat = np.rad2deg(np.arctan((req**2 / rpol**2) * sz / np.sqrt((H - sx)**2 + sy**2)))
        lon = np.rad2deg(lon0 - np.arctan2(sy, (H - sx)))
    return lon, lat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, default=[-120, 5, -80, 30],
                    metavar=("W", "S", "E", "N"), help="bbox tropical EPAC (lon/lat)")
    ap.add_argument("--stride", type=int, default=4, help="submuestreo para ahorrar RAM")
    args = ap.parse_args()
    W, S, E, N = args.bbox

    s3 = s3_client()
    key = latest_key(s3)
    if not key:
        print("ERROR: no encontre ningun C13 en las ultimas horas.", file=sys.stderr)
        sys.exit(1)
    print(f"Ultimo archivo: s3://{BUCKET}/{key}")

    tmp = os.path.join(tempfile.gettempdir(), os.path.basename(key))
    s3.download_file(BUCKET, key, tmp)
    print(f"Descargado: {tmp} ({os.path.getsize(tmp)/1e6:.1f} MB)")

    import xarray as ds_mod
    # Los GOES suelen fallar con el engine netcdf4 (HDF error -101 con la libhdf5
    # empaquetada en el wheel). h5netcdf (via h5py) usa otra ruta y abre bien.
    ds = None
    for eng in ("h5netcdf", "netcdf4"):
        try:
            ds = ds_mod.open_dataset(tmp, engine=eng)
            print(f"Abierto con engine: {eng}")
            break
        except Exception as e:
            print(f"  (engine {eng} fallo: {type(e).__name__}: {e})")
    if ds is None:
        print("\nERROR: no pude abrir el NetCDF con ningun engine.", file=sys.stderr)
        print("Instala h5netcdf:  /opt/canalmeteo/venv/bin/python3 -m pip install h5netcdf h5py", file=sys.stderr)
        sys.exit(2)
    proj = ds["goes_imager_projection"].attrs
    pph = float(proj["perspective_point_height"])
    req = float(proj["semi_major_axis"])
    rpol = float(proj["semi_minor_axis"])
    lon0 = float(proj["longitude_of_projection_origin"])
    sweep = proj.get("sweep_angle_axis", "?")
    H = pph + req

    print("\n=== goes_imager_projection ===")
    print(f"  longitude_of_projection_origin = {lon0}")
    print(f"  perspective_point_height       = {pph}")
    print(f"  semi_major_axis (req)          = {req}")
    print(f"  semi_minor_axis (rpol)         = {rpol}")
    print(f"  sweep_angle_axis               = {sweep}")
    print(f"  H (pph+req)                    = {H}")

    x = ds["x"].values[::args.stride]
    y = ds["y"].values[::args.stride]
    cmi = ds["CMI"].values[::args.stride, ::args.stride]
    print(f"\n  grid Full Disk completa : {ds['y'].size} x {ds['x'].size}  (resolucion nativa)")
    print(f"  x scale/offset          : {ds['x'].attrs.get('scale_factor')} / {ds['x'].attrs.get('add_offset')}")
    print(f"  y scale/offset          : {ds['y'].attrs.get('scale_factor')} / {ds['y'].attrs.get('add_offset')}")
    print(f"  muestra usada (stride {args.stride}): {cmi.shape}")

    lon, lat = geos_to_lonlat(x, y, lon0, H, req, rpol)
    on_disk = np.isfinite(lon) & np.isfinite(lat)
    in_bbox = on_disk & (lon >= W) & (lon <= E) & (lat >= S) & (lat <= N)
    valid_cmi = in_bbox & np.isfinite(cmi)

    n_bbox = int(in_bbox.sum())
    n_valid = int(valid_cmi.sum())
    frac = (n_valid / n_bbox * 100) if n_bbox else 0.0

    print(f"\n=== Cobertura sobre bbox [{W},{S},{E},{N}] ===")
    print(f"  pixeles dentro del bbox      : {n_bbox}")
    print(f"  con dato valido (CMI finito) : {n_valid}")
    print(f"  cobertura                    : {frac:.1f} %   <- antes ~8% con CONUS")
    if frac > 90:
        print("  => Full Disk cubre la zona tropical. Adelante con el LUT Full Disk.")
    elif frac > 40:
        print("  => Cobertura parcial; revisa el bbox/zona.")
    else:
        print("  => Cobertura baja: revisa parametros antes de seguir.")


if __name__ == "__main__":
    main()
