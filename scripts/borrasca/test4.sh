cd /opt/canalmeteo/scripts/borrasca
python3 << 'EOF'
import gzip, tempfile, os, requests, re
import numpy as np
import xarray as xr
from PIL import Image

# Colores
COLORS_RAIN = [
    (-999, 5,    0,   0,   0,   0),
    (5,    10,   0,   255, 255, 150),    # Cyan
    (10,   20,   0,   200, 200, 210),
]
COLORS_SNOW = [
    (-999, 5,    0,   0,   0,   0),
    (5,    10,   180, 220, 255, 150),    # Azul claro
    (10,   20,   120, 180, 255, 210),    # Azul
]

PRECIP_RAIN = [1, 3, 6, 91]
PRECIP_SNOW = [2, 96, -3]

# Descargar pequeña área
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
    return arr

refl = download_grib('MergedReflectivityQCComposite', 'MRMS_MergedReflectivityQCComposite_00.50')
precip = download_grib('PrecipFlag', 'MRMS_PrecipFlag_00.00')

# Área pequeña para test (donde hay nieve)
# Minnesota/Ontario area: rows 500-600, cols 3000-3100
test_refl = refl[500:600, 3000:3100]
test_precip = precip[500:600, 3000:3100]

print(f"Área de test:")
print(f"  Reflectividad >= 5: {(test_refl >= 5).sum()}")
print(f"  Nieve (precip=-3 o 2): {np.isin(test_precip, [-3, 2]).sum()}")
print(f"  Lluvia: {np.isin(test_precip, [1,3]).sum()}")

# Generar RGBA
h, w = test_refl.shape
rgba = np.zeros((h, w, 4), dtype=np.uint8)

mask_snow = np.isin(test_precip, PRECIP_SNOW)
mask_rain = np.isin(test_precip, PRECIP_RAIN)

# Aplicar nieve
for dbz_min, dbz_max, r, g, b, a in COLORS_SNOW:
    mask = mask_snow & (test_refl >= dbz_min) & (test_refl < dbz_max)
    rgba[mask] = [r, g, b, a]
    if mask.sum() > 0:
        print(f"  Nieve {dbz_min}-{dbz_max} dBZ: {mask.sum()} px -> RGB({r},{g},{b})")

# Aplicar lluvia
for dbz_min, dbz_max, r, g, b, a in COLORS_RAIN:
    mask = mask_rain & (test_refl >= dbz_min) & (test_refl < dbz_max)
    rgba[mask] = [r, g, b, a]
    if mask.sum() > 0:
        print(f"  Lluvia {dbz_min}-{dbz_max} dBZ: {mask.sum()} px -> RGB({r},{g},{b})")

# Guardar imagen de test
img = Image.fromarray(rgba, 'RGBA')
img.save('/tmp/test_snow.png')
print(f"\nImagen guardada en /tmp/test_snow.png")
EOF
