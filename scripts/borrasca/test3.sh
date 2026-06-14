cd /opt/canalmeteo/scripts/borrasca
python3 << 'EOF'
import gzip, tempfile, os, requests, re
import numpy as np
import xarray as xr

# Descargar datos
def download_grib(product, file_prefix):
    url = f"https://mrms.ncep.noaa.gov/data/2D/{product}/"
    r = requests.get(url, timeout=30)
    files = re.findall(rf'{file_prefix}_(\d{{8}}-\d{{6}})\.grib2\.gz', r.text)
    latest = sorted(files)[-1]
    
    grib_url = f"https://mrms.ncep.noaa.gov/data/2D/{product}/{file_prefix}_{latest}.grib2.gz"
    resp = requests.get(grib_url, timeout=60)
    data = gzip.decompress(resp.content)
    
    with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
        f.write(data)
        tmp = f.name
    
    ds = xr.open_dataset(tmp, engine='cfgrib')
    arr = ds[list(ds.data_vars)[0]].values
    os.unlink(tmp)
    return arr, latest

refl, ts1 = download_grib('MergedReflectivityQCComposite', 'MRMS_MergedReflectivityQCComposite_00.50')
precip, ts2 = download_grib('PrecipFlag', 'MRMS_PrecipFlag_00.00')

print(f"Reflectividad: {ts1}")
print(f"PrecipFlag: {ts2}")

# Definir tipos
PRECIP_RAIN = [1, 3, 6, 91]
PRECIP_SNOW = [2, 96, -3]
PRECIP_MIX = [10, 4]

# Crear máscaras
mask_rain = np.isin(precip, PRECIP_RAIN)
mask_snow = np.isin(precip, PRECIP_SNOW)
mask_mix = np.isin(precip, PRECIP_MIX)

# Con reflectividad >= 5
has_refl = refl >= 5

print(f"\n--- Píxeles con reflectividad >= 5 dBZ ---")
print(f"Total: {has_refl.sum():,}")
print(f"Lluvia: {(mask_rain & has_refl).sum():,}")
print(f"Nieve:  {(mask_snow & has_refl).sum():,}")
print(f"Mixta:  {(mask_mix & has_refl).sum():,}")

# Verificar si las máscaras se solapan
unknown = has_refl & ~mask_rain & ~mask_snow & ~mask_mix
print(f"Sin clasificar: {unknown.sum():,}")
EOF
