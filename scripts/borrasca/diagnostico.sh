cd /opt/canalmeteo/scripts/borrasca
python3 << 'EOF'
import gzip, tempfile, os, requests, re
import numpy as np
import xarray as xr

# Descargar PrecipFlag
url = "https://mrms.ncep.noaa.gov/data/2D/PrecipFlag/"
r = requests.get(url, timeout=30)
files = re.findall(r'MRMS_PrecipFlag_00\.00_(\d{8}-\d{6})\.grib2\.gz', r.text)
latest = sorted(files)[-1]
print(f"PrecipFlag: {latest}")

grib_url = f"https://mrms.ncep.noaa.gov/data/2D/PrecipFlag/MRMS_PrecipFlag_00.00_{latest}.grib2.gz"
resp = requests.get(grib_url, timeout=60)
data = gzip.decompress(resp.content)

with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
    f.write(data)
    tmp = f.name

ds = xr.open_dataset(tmp, engine='cfgrib')
precip = ds[list(ds.data_vars)[0]].values
lats = ds.latitude.values
lons = ds.longitude.values
os.unlink(tmp)

# Buscar nieve en área de Minnesota/Wisconsin
lat_mask = (lats > 43) & (lats < 48)
lon_mask = (lons > 270) & (lons < 280)  # -90 a -80 en 0-360

# Área de interés
area = precip[lat_mask][:, lon_mask[0] if len(lon_mask.shape) > 0 else lon_mask]

print(f"\nÁrea Minnesota/Wisconsin:")
print(f"  Shape datos: {precip.shape}")
print(f"  Lats: {lats.min():.1f} a {lats.max():.1f}")
print(f"  Lons: {lons.min():.1f} a {lons.max():.1f}")

# Contar tipos globalmente
unique, counts = np.unique(precip[~np.isnan(precip)].astype(int), return_counts=True)
print("\nTipos de precipitación (global):")
types = {0:'Sin precip', 1:'Lluvia strat', 2:'NIEVE', 3:'Lluvia', 4:'Lluvia fría', 6:'Convectiva', 7:'Granizo', 10:'Mixta'}
for v, c in zip(unique, counts):
    if c > 5000:
        pct = c / precip.size * 100
        print(f"  {int(v):2d}: {types.get(int(v), '?'):15s} = {c:>10,} px ({pct:.2f}%)")
EOF
