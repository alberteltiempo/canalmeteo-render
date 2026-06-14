#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hrrr_variables.py — Definición centralizada de variables HRRR.

Contiene:
  - Configuración de cada variable (search string para Herbie, unidades, paletas)
  - Listas de variables por producto (HRRR 18h vs HRRR 48h)
  - Paletas de colores estándar Canal Meteo

Cualquier ajuste de paletas o variables se hace AQUÍ, no en model_pipeline.py.

Uso:
    from hrrr_variables import VARIABLES, HRRR_18H_VARS, HRRR_48H_VARS
"""

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, ListedColormap


# ═══════════════════════════════════════════════════════════════════════════
# PALETAS DE COLORES (estándar Canal Meteo / NWS)
# ═══════════════════════════════════════════════════════════════════════════

# Temperatura (°C) — paleta extendida tipo "TWC"
CMAP_TEMP = LinearSegmentedColormap.from_list('cm_temp', [
    (0.00, '#5c2a8a'),  # -40
    (0.10, '#3949ab'),  # -30
    (0.20, '#1e88e5'),  # -20
    (0.30, '#26c6da'),  # -10
    (0.40, '#43a047'),  #   0
    (0.50, '#cddc39'),  #  10
    (0.60, '#fdd835'),  #  20
    (0.70, '#fb8c00'),  #  30
    (0.85, '#e53935'),  #  40
    (1.00, '#880e4f'),  #  50
], N=256)

# Punto de rocío (°C) — verdes para humedad cómoda, rojos para sofocante
CMAP_DPT = LinearSegmentedColormap.from_list('cm_dpt', [
    (0.00, '#37474f'),  # -20
    (0.20, '#90a4ae'),  #   0
    (0.40, '#aed581'),  #  10
    (0.55, '#558b2f'),  #  18
    (0.70, '#f9a825'),  #  22
    (0.85, '#e64a19'),  #  25
    (1.00, '#6a1b9a'),  #  30+
], N=256)

# Viento (mph) — Beaufort + tropical
CMAP_WIND = LinearSegmentedColormap.from_list('cm_wind', [
    (0.00, '#e3f2fd'),
    (0.15, '#64b5f6'),
    (0.30, '#26a69a'),
    (0.45, '#9ccc65'),
    (0.55, '#ffeb3b'),
    (0.65, '#ff9800'),
    (0.75, '#e53935'),
    (0.85, '#ad1457'),
    (1.00, '#4a148c'),
], N=256)

# Reflectividad (dBZ) — paleta NWS clásica
CMAP_REFC = ListedColormap([
    '#00000000',  # < 5
    '#04e9e7',    # 5-10
    '#019ff4',    # 10-15
    '#0300f4',    # 15-20
    '#02fd02',    # 20-25
    '#01c501',    # 25-30
    '#008e00',    # 30-35
    '#fdf802',    # 35-40
    '#e5bc00',    # 40-45
    '#fd9500',    # 45-50
    '#fd0000',    # 50-55
    '#d40000',    # 55-60
    '#bc0000',    # 60-65
    '#f800fd',    # 65-70
    '#9854c6',    # 70-75
])

# Precipitación acumulada (mm)
CMAP_APCP = LinearSegmentedColormap.from_list('cm_apcp', [
    (0.00, '#00000000'),
    (0.05, '#a5d6a7'),
    (0.15, '#388e3c'),
    (0.30, '#1976d2'),
    (0.50, '#7b1fa2'),
    (0.75, '#e65100'),
    (1.00, '#b71c1c'),
], N=256)

# Nieve acumulada (cm)
CMAP_SNOW = LinearSegmentedColormap.from_list('cm_snow', [
    (0.00, '#00000000'),
    (0.10, '#e3f2fd'),
    (0.30, '#90caf9'),
    (0.50, '#42a5f5'),
    (0.70, '#1565c0'),
    (1.00, '#311b92'),
], N=256)

# CAPE (J/kg)
CMAP_CAPE = LinearSegmentedColormap.from_list('cm_cape', [
    (0.00, '#00000000'),
    (0.10, '#fff9c4'),
    (0.25, '#ffeb3b'),
    (0.40, '#ff9800'),
    (0.60, '#e53935'),
    (0.80, '#880e4f'),
    (1.00, '#311b92'),
], N=256)

# Nubosidad (%)
CMAP_TCDC = LinearSegmentedColormap.from_list('cm_tcdc', [
    (0.00, '#00000000'),
    (1.00, '#cfd8dc'),
], N=256)

# PRMSL (presión nivel mar, hPa)
CMAP_PRMSL = LinearSegmentedColormap.from_list('cm_prmsl', [
    (0.00, '#311b92'),  # 970
    (0.30, '#1976d2'),  # 1000
    (0.50, '#ffffff'),  # 1013
    (0.70, '#fb8c00'),  # 1025
    (1.00, '#b71c1c'),  # 1050
], N=256)

# Visibilidad (mi) — invertida: poco viz = rojo
CMAP_VIS = LinearSegmentedColormap.from_list('cm_vis', [
    (0.00, '#b71c1c'),  # 0 mi (niebla densa)
    (0.10, '#e65100'),  # 0.5
    (0.25, '#fdd835'),  # 1
    (0.50, '#aed581'),  # 3
    (1.00, '#00000000'),  # 10+ mi (transparente)
], N=256)

# Tipo de precipitación (categórico)
# 0=ninguna, 1=lluvia, 2=lluvia helada, 3=aguanieve, 4=nieve
CMAP_PTYPE = ListedColormap([
    '#00000000',  # 0 ninguna
    '#1e88e5',    # 1 lluvia (azul)
    '#e91e63',    # 2 lluvia helada (rosa/magenta)
    '#ce93d8',    # 3 aguanieve (lila)
    '#ffffff',    # 4 nieve (blanco)
])

# Granizo (in)
CMAP_HAIL = LinearSegmentedColormap.from_list('cm_hail', [
    (0.00, '#00000000'),
    (0.20, '#fff59d'),  # 0.25"
    (0.40, '#ffb300'),  # 1"
    (0.60, '#e53935'),  # 1.5"
    (0.80, '#880e4f'),  # 2"
    (1.00, '#311b92'),  # 3"+
], N=256)

# Rayos
CMAP_LTNG = LinearSegmentedColormap.from_list('cm_ltng', [
    (0.00, '#00000000'),
    (0.20, '#fffde7'),
    (0.50, '#fdd835'),
    (0.80, '#fb8c00'),
    (1.00, '#b71c1c'),
], N=256)

# Helicidad updraft (m²/s²) — proxy tornado
CMAP_MXUPHL = LinearSegmentedColormap.from_list('cm_mxuphl', [
    (0.00, '#00000000'),
    (0.20, '#ce93d8'),
    (0.50, '#8e24aa'),
    (0.80, '#e53935'),
    (1.00, '#000000'),
], N=256)


# ═══════════════════════════════════════════════════════════════════════════
# DEFINICIÓN DE VARIABLES
# ═══════════════════════════════════════════════════════════════════════════
# Cada variable define:
#   key:        identificador interno (también nombre de carpeta en CDN)
#   label:      etiqueta para UI en español
#   herbie:     search string para Herbie (regex sobre el .idx file)
#   conv:       función de conversión desde unidades GRIB nativas
#   vmin/vmax:  rango para colormap
#   cmap:       paleta matplotlib
#   smooth:     sigma de Gaussian smoothing (None = sin suavizado)
#   derived:    si True, se calcula a partir de otras variables (no descarga directa)
#   composite:  si es lista, descarga múltiples variables y las combina
# ═══════════════════════════════════════════════════════════════════════════

VARIABLES = {
    # ─── Núcleo de pronóstico ──────────────────────────────────────────────
    'tmp_2m': {
        'label': 'Temperatura 2m',
        'herbie': 'TMP:2 m above ground',
        'grib_var': 't2m',
        'conv': lambda x: x - 273.15,  # K → °C
        'vmin': -40, 'vmax': 50,
        'cmap': CMAP_TEMP,
        'smooth': 0.8,
        'unit': '°C',
    },
    'dpt_2m': {
        'label': 'Punto de rocío 2m',
        'herbie': 'DPT:2 m above ground',
        'grib_var': 'd2m',
        'conv': lambda x: x - 273.15,
        'vmin': -20, 'vmax': 30,
        'cmap': CMAP_DPT,
        'smooth': 0.8,
        'unit': '°C',
    },
    'apt_2m': {
        'label': 'Sensación térmica',
        'derived': True,
        'depends_on': ['tmp_2m', 'dpt_2m', 'wind_10m'],
        'vmin': -50, 'vmax': 55,
        'cmap': CMAP_TEMP,
        'smooth': 0.8,
        'unit': '°C',
    },
    'wind_10m': {
        'label': 'Viento 10m',
        'composite': ['UGRD:10 m above ground', 'VGRD:10 m above ground'],
        'grib_vars': ['u10', 'v10'],
        'conv': lambda u, v: np.sqrt(u**2 + v**2) * 2.23694,  # m/s → mph
        'vmin': 0, 'vmax': 80,
        'cmap': CMAP_WIND,
        'smooth': 0.5,
        'unit': 'mph',
    },
    'gust': {
        'label': 'Ráfagas',
        'herbie': 'GUST:surface',
        'grib_var': 'gust',
        'conv': lambda x: x * 2.23694,
        'vmin': 0, 'vmax': 100,
        'cmap': CMAP_WIND,
        'smooth': 0.5,
        'unit': 'mph',
    },
    'apcp': {
        'label': 'Precipitación acumulada',
        'herbie': 'APCP:surface',
        'grib_var': 'tp',
        'conv': lambda x: x,  # ya en mm
        'vmin': 0, 'vmax': 100,
        'cmap': CMAP_APCP,
        'smooth': 0.4,
        'unit': 'mm',
    },
    'asnow': {
        'label': 'Nieve acumulada',
        'herbie': 'ASNOW:surface',
        'grib_var': 'asnow',
        'conv': lambda x: x * 100,  # m → cm
        'vmin': 0, 'vmax': 60,
        'cmap': CMAP_SNOW,
        'smooth': 0.4,
        'unit': 'cm',
    },
    'ptype': {
        'label': 'Tipo de precipitación',
        'derived': True,
        'depends_on': ['CRAIN', 'CSNOW', 'CICEP', 'CFRZR'],
        'vmin': 0, 'vmax': 4,
        'cmap': CMAP_PTYPE,
        'smooth': None,  # categórico, NO suavizar
        'unit': 'cat',
    },
    'tcdc': {
        'label': 'Nubosidad total',
        'herbie': 'TCDC:entire atmosphere',
        'grib_var': 'tcc',
        'conv': lambda x: x,
        'vmin': 0, 'vmax': 100,
        'cmap': CMAP_TCDC,
        'smooth': 1.0,
        'unit': '%',
    },
    'prmsl': {
        'label': 'Presión nivel del mar',
        'herbie': 'MSLMA:mean sea level',
        'grib_var': 'mslma',
        'conv': lambda x: x / 100.0,  # Pa → hPa
        'vmin': 970, 'vmax': 1050,
        'cmap': CMAP_PRMSL,
        'smooth': 1.5,
        'unit': 'hPa',
    },

    # ─── Convección y severo (solo HRRR 18h) ───────────────────────────────
    'refc': {
        'label': 'Reflectividad simulada',
        'herbie': 'REFC:entire atmosphere',
        'grib_var': 'refc',
        'conv': lambda x: x,
        'vmin': 5, 'vmax': 75,
        'cmap': CMAP_REFC,
        'smooth': None,  # radar = NO suavizar
        'unit': 'dBZ',
    },
    'retop': {
        'label': 'Topes de eco',
        'herbie': 'RETOP:cloud top',
        'grib_var': 'unknown',  # Herbie a veces lo nombra distinto
        'conv': lambda x: x * 3.281,  # m → ft (luego /1000 para kft)
        'vmin': 0, 'vmax': 60000,  # 0-60 kft
        'cmap': CMAP_REFC,
        'smooth': 0.3,
        'unit': 'ft',
    },
    'cape': {
        'label': 'CAPE',
        'herbie': 'CAPE:surface',
        'grib_var': 'cape',
        'conv': lambda x: x,
        'vmin': 0, 'vmax': 5000,
        'cmap': CMAP_CAPE,
        'smooth': 1.0,
        'unit': 'J/kg',
    },
    'cin': {
        'label': 'CIN',
        'herbie': 'CIN:surface',
        'grib_var': 'cin',
        'conv': lambda x: x,  # ya negativo
        'vmin': -300, 'vmax': 0,
        'cmap': 'Blues_r',
        'smooth': 1.0,
        'unit': 'J/kg',
    },
    'mxuphl': {
        'label': 'Helicidad updraft 2-5km',
        'herbie': 'MXUPHL:5000-2000 m above ground',
        'grib_var': 'unknown',
        'conv': lambda x: x,
        'vmin': 0, 'vmax': 200,
        'cmap': CMAP_MXUPHL,
        'smooth': 0.5,
        'unit': 'm²/s²',
    },
    'hail': {
        'label': 'Granizo máximo',
        'herbie': 'HAIL:surface',
        'grib_var': 'unknown',
        'conv': lambda x: x * 39.3701,  # m → in
        'vmin': 0, 'vmax': 3,
        'cmap': CMAP_HAIL,
        'smooth': 0.3,
        'unit': 'in',
    },
    'ltng': {
        'label': 'Densidad de rayos',
        'herbie': 'LTNG:entire atmosphere',
        'grib_var': 'ltng',
        'conv': lambda x: x,
        'vmin': 0, 'vmax': 5,
        'cmap': CMAP_LTNG,
        'smooth': 0.5,
        'unit': 'flashes',
    },

    # ─── Inmediatez (solo HRRR 18h) ────────────────────────────────────────
    'vis': {
        'label': 'Visibilidad',
        'herbie': 'VIS:surface',
        'grib_var': 'vis',
        'conv': lambda x: x * 0.000621371,  # m → mi
        'vmin': 0, 'vmax': 10,
        'cmap': CMAP_VIS,
        'smooth': 0.5,
        'unit': 'mi',
    },
    'prate': {
        'label': 'Tasa de precipitación',
        'herbie': 'PRATE:surface',
        'grib_var': 'prate',
        'conv': lambda x: x * 3600,  # kg/m²/s → mm/h
        'vmin': 0, 'vmax': 30,
        'cmap': CMAP_APCP,
        'smooth': 0.4,
        'unit': 'mm/h',
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# LISTAS DE VARIABLES POR PRODUCTO
# ═══════════════════════════════════════════════════════════════════════════

# HRRR 18h: 19 variables (sub-horarias en fase 2)
HRRR_18H_VARS = [
    # Núcleo de pronóstico
    'tmp_2m', 'dpt_2m', 'apt_2m',
    'wind_10m', 'gust',
    'apcp', 'asnow', 'ptype',
    'tcdc', 'prmsl',
    # Convección y severo
    'refc', 'retop', 'cape', 'cin',
    'mxuphl', 'hail', 'ltng',
    # Inmediatez
    'vis', 'prate',
]

# HRRR 48h: 12 variables (curadas para narrativa de 2 días)
HRRR_48H_VARS = [
    'tmp_2m', 'dpt_2m', 'apt_2m',
    'wind_10m', 'gust',
    'apcp', 'asnow', 'ptype',
    'refc', 'cape',
    'tcdc', 'prmsl',
]


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN POR PRODUCTO
# ═══════════════════════════════════════════════════════════════════════════

PRODUCT_CONFIGS = {
    'hrrr-18h': {
        'name': 'HRRR 18h',
        'variables': HRRR_18H_VARS,
        'forecast_hours': list(range(0, 19)),  # F00 .. F18
        'eligible_run_hours': list(range(0, 24)),  # cualquier ciclo
        'output_prefix': 'hrrr-18h',
        'lock_file': '/tmp/hrrr-18h.lock',
        'product_grib': 'sfc',  # wrfsfcf*.grib2
        'description': 'Pronóstico horario alta resolución 18h',
    },
    'hrrr-48h': {
        'name': 'HRRR 48h',
        'variables': HRRR_48H_VARS,
        'forecast_hours': list(range(0, 49)),  # F00 .. F48
        'eligible_run_hours': [0, 6, 12, 18],  # solo ciclos extendidos
        'output_prefix': 'hrrr-48h',
        'lock_file': '/tmp/hrrr-48h.lock',
        'product_grib': 'sfc',
        'description': 'Pronóstico extendido 48h (4 veces al día)',
    },
}


def get_variables_for_product(product_key):
    """Devuelve la lista de variables (con configuración) para un producto."""
    if product_key not in PRODUCT_CONFIGS:
        raise ValueError(f'Producto desconocido: {product_key}. Opciones: {list(PRODUCT_CONFIGS)}')
    var_keys = PRODUCT_CONFIGS[product_key]['variables']
    return {k: VARIABLES[k] for k in var_keys}


if __name__ == '__main__':
    # Smoke test: imprimir resumen de configuración
    print('═' * 70)
    print('  HRRR_VARIABLES — Configuración Canal Meteo')
    print('═' * 70)
    for prod_key, prod in PRODUCT_CONFIGS.items():
        print(f"\n📦 {prod['name']} ({prod_key})")
        print(f"   Variables: {len(prod['variables'])}")
        print(f"   Forecast hours: F{prod['forecast_hours'][0]:02d}..F{prod['forecast_hours'][-1]:02d}")
        print(f"   Run hours: {prod['eligible_run_hours']}")
        print(f"   CDN prefix: {prod['output_prefix']}/")
        print(f"   Variables list:")
        for v in prod['variables']:
            cfg = VARIABLES[v]
            print(f"     • {v:12s} — {cfg['label']:30s} ({cfg.get('unit', '?')})")
    print()
