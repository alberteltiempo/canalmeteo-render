#!/usr/bin/env python3
"""
basemaps_pipeline.py
────────────────────
Genera basemaps estáticos para superponer detrás del radar y satélite.
Se ejecuta UNA VEZ (o cuando cambien los bounds).

Genera 2 PNGs:
  - basemap_mrms.png       (bounds MRMS: 20-55°N, -130 a -60°W) 3500×1750
  - basemap_satellite.png  (bounds satellite: 24-50°N, -125 a -66°W) 3500×1750

Sube ambos a:
  s3://canalmeteo-public/data/mapas/basemap_*.png

Cron: NO necesario. Solo correr cuando se quiera regenerar.
"""

import logging
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

WORK_DIR = Path('/tmp/basemaps_work')
WORK_DIR.mkdir(exist_ok=True)

S3_BUCKET = 'canalmeteo-public'
S3_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'

# Definición de basemaps a generar
BASEMAPS = [
    {
        'name': 'basemap_mrms',
        'bounds': (-130.0, -60.0, 20.0, 55.0),  # (W, E, S, N)
        'width': 3500,
        'height': 1750,
    },
    {
        'name': 'basemap_satellite',
        'bounds': (-125.0, -66.0, 24.0, 50.0),
        'width': 3500,
        'height': 1750,
    },
]

# Estilo de Canal Meteo TV
COLOR_OCEAN = '#0e1e2e'      # azul oscuro casi negro
COLOR_LAND = '#1a2b3a'       # azul gris muy oscuro
COLOR_COASTLINE = '#5b7a99'  # azul medio para costas
COLOR_BORDER = '#5b7a99'     # bordes estados/países
COLOR_STATE = '#3b5870'      # bordes estados


def generar_basemap(cfg):
    name = cfg['name']
    w_lon, e_lon, s_lat, n_lat = cfg['bounds']
    width = cfg['width']
    height = cfg['height']

    log.info(f"Generando {name} ({width}x{height}) bounds=({w_lon},{e_lon},{s_lat},{n_lat})")

    # DPI = 100 → figsize en pulgadas
    dpi = 100
    figsize = (width / dpi, height / dpi)

    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([w_lon, e_lon, s_lat, n_lat], crs=ccrs.PlateCarree())

    # Sin márgenes
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    ax.set_axis_off()

    # Océano y tierra
    ax.add_feature(cfeature.OCEAN.with_scale('50m'),
                   facecolor=COLOR_OCEAN, zorder=0)
    ax.add_feature(cfeature.LAND.with_scale('50m'),
                   facecolor=COLOR_LAND, zorder=1)

    # Lagos (Grandes Lagos)
    ax.add_feature(cfeature.LAKES.with_scale('50m'),
                   facecolor=COLOR_OCEAN, edgecolor=COLOR_COASTLINE,
                   linewidth=0.5, zorder=2)

    # Estados USA
    states = cfeature.NaturalEarthFeature(
        category='cultural',
        name='admin_1_states_provinces_lines',
        scale='50m',
        facecolor='none'
    )
    ax.add_feature(states, edgecolor=COLOR_STATE, linewidth=1.0, zorder=3)

    # Fronteras países
    ax.add_feature(cfeature.BORDERS.with_scale('50m'),
                   edgecolor=COLOR_BORDER, linewidth=1.5, zorder=4)

    # Línea de costa
    ax.add_feature(cfeature.COASTLINE.with_scale('50m'),
                   edgecolor=COLOR_COASTLINE, linewidth=1.5, zorder=5)

    # Guardar
    output_path = WORK_DIR / f"{name}.png"
    fig.savefig(output_path, dpi=dpi, bbox_inches='tight', pad_inches=0,
                facecolor=COLOR_OCEAN)
    plt.close(fig)
    log.info(f"  ✓ Guardado: {output_path} ({output_path.stat().st_size // 1024} KB)")

    # Subir al CDN
    s3_key = f"data/mapas/{name}.png"
    upload_cmd = [
        'aws', 's3', 'cp', str(output_path),
        f's3://{S3_BUCKET}/{s3_key}',
        '--profile', AWS_PROFILE,
        '--endpoint-url', S3_ENDPOINT,
        '--acl', 'public-read',
        '--content-type', 'image/png',
        '--cache-control', 'max-age=86400',  # 1 día
    ]
    result = subprocess.run(upload_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        log.info(f"  ☁️  Subido: https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/{s3_key}")
    else:
        log.error(f"  ✗ Error subiendo: {result.stderr}")
        return False

    return True


def main():
    log.info("═══ Generando basemaps Canal Meteo ═══")
    for cfg in BASEMAPS:
        generar_basemap(cfg)
    log.info("═══ Complete ═══")


if __name__ == '__main__':
    main()
