cd /opt/canalmeteo/scripts/borrasca
python3 << 'EOF'
import gzip, tempfile, os, requests, re
import numpy as np
import xarray as xr

url = "https://mrms.ncep.noaa.gov/data/2D/PrecipFlag/"
r = requests.get(url, timeout=30)
files = re.findall(r'MRMS_PrecipFlag_00\.00_(\d{8}-\d{6})\.grib2\.gz', r.text)
latest = sorted(files)[-1]

grib_url = f"https://mrms.ncep.noaa.gov/data/2D/PrecipFlag/MRMS_PrecipFlag_00.00_{latest}.grib2.gz"
resp = requests.get(grib_url, timeout=60)
data = gzip.decompress(resp.content)

with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
    f.write(data)
    tmp = f.name

ds = xr.open_dataset(tmp, engine='cfgrib')
precip = ds[list(ds.data_vars)[0]].values
os.unlink(tmp)

print(f"Dtype: {precip.dtype}")
print(f"Valores únicos negativos: {np.unique(precip[precip < 0])}")
print(f"Min: {np.nanmin(precip)}, Max: {np.nanmax(precip)}")

# Test de máscara
PRECIP_SNOW = [2, 96, -3]
mask = np.isin(precip, PRECIP_SNOW)
print(f"\nPixeles detectados como nieve: {mask.sum():,}")

# Probar con float
PRECIP_SNOW_FLOAT = [2.0, 96.0, -3.0]
mask_float = np.isin(precip, PRECIP_SNOW_FLOAT)
print(f"Pixeles con float: {mask_float.sum():,}")
EOF
