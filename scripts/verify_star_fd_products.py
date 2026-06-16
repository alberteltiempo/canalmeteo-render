#!/usr/bin/env python3
"""
verify_star_fd_products.py — Canal Meteo TV / Tormenta
Comprueba que productos Full Disk publica el CDN STAR para GOES-East y West,
ANTES de escribir el pipeline multi-vista. Evita adivinar URLs.

Para cada (satelite x producto) hace una peticion ligera y reporta:
  - status HTTP
  - tamano en MB (Content-Length)
  - dimensiones reales del JPG (descarga solo los que existen)

Uso en nimbus-01:
    /opt/canalmeteo/venv/bin/python3 verify_star_fd_products.py
"""

import requests
from io import BytesIO
from PIL import Image

BASE = 'https://cdn.star.nesdis.noaa.gov'
RES = '5424x5424'   # grid 2km (coincide con el scan de la geometria verificada)
SATS = ['GOES19', 'GOES18']

# Productos candidatos. Bandas individuales + RGB de interes tropical.
PRODUCTS = [
    ('GeoColor',     'GEOCOLOR'),
    ('Visible B02',  '02'),
    ('WV alto B08',  '08'),
    ('WV medio B09', '09'),
    ('IR B13',       '13'),
    ('Dust RGB',     'Dust'),       # polvo del Sahara — clave si existe para FD
    ('AirMass RGB',  'AirMass'),
]

HEADERS = {'User-Agent': 'CanalMeteoTV/1.0 (contacto@canalmeteo.tv)'}


def check(url):
    """Devuelve (status, size_mb, dims). Descarga solo si existe."""
    try:
        h = requests.head(url, headers=HEADERS, timeout=20, allow_redirects=True)
        status = h.status_code
        size = h.headers.get('Content-Length')
        if status != 200:
            return status, None, None
        # Confirmar dimensiones reales
        g = requests.get(url, headers=HEADERS, timeout=60)
        img = Image.open(BytesIO(g.content))
        size_mb = len(g.content) / 1e6
        return status, size_mb, f"{img.width}x{img.height}"
    except Exception as e:
        return f"ERR {str(e)[:40]}", None, None


def main():
    print(f"Verificacion productos Full Disk STAR @ {RES}\n")
    for sat in SATS:
        print(f"{'='*64}\n{sat}\n{'='*64}")
        for label, prod in PRODUCTS:
            url = f"{BASE}/{sat}/ABI/FD/{prod}/{RES}.jpg"
            status, size_mb, dims = check(url)
            ok = '✅' if status == 200 else '❌'
            extra = f"  {size_mb:.1f}MB  {dims}" if size_mb else ""
            print(f"  {ok} {label:14s} [{prod:9s}] -> {status}{extra}")
        print()


if __name__ == '__main__':
    main()
