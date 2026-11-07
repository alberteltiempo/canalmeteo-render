#!/usr/bin/env python3
"""
===============================================================================
Multi-Model Raster Pipeline — Canal Meteo TV  (v5.2 — HRRR_EXT añadido)
===============================================================================
Supports: NBM, GFS, HRRR, HRRR_EXT
Usage:
  python model_pipeline.py              # defaults to NBM
  python model_pipeline.py --model gfs
  python model_pipeline.py --model hrrr      # 0-18h cada hora
  python model_pipeline.py --model hrrr_ext  # 0-48h en ciclos 00/06/12/18z

Cron:
  20 * * * *      .../model_pipeline.py --model nbm
  35 * * * *      .../model_pipeline.py --model hrrr
  45 0,6,12,18 * * * .../model_pipeline.py --model gfs
  55 0,6,12,18 * * * .../model_pipeline.py --model hrrr_ext

NUEVOS PRODUCTOS (v5):
  GFS:
    - reflectivity (REFC composite simulado, hires)
    - jet250       (corriente en chorro a 250 mb, mph)
    - temp850C     (temperatura a 850 mb, °C)
    - wind850      (viento a 850 mb, mph)
    - pressureMb   (PRMSL — ya existía pero ahora se renderiza también como ISOBARAS)
  NBM:
    - tempAnom     (anomalía de temperatura vs NCEI 1991-2020)
  GFS:
    - tempAnom     (anomalía de temperatura vs NCEI 1991-2020)

Requiere para anomalía:
  - /opt/canalmeteo/data/climatology/tavg_normals_1991_2020.nc
  - Generado con: python download_climatology.py
===============================================================================
"""
import requests, json, subprocess, logging, sys, os, time, warnings, argparse
import centros_presion   # bajas y altas del campo de presión (26/09)
import frames_grid   # emparejamiento model-frames ↔ grid (W-2 Studio Pro)
import frames_runs   # rutas por pasada + purga (30.2 Studio)
import manifest_relleno   # 15/09: nunca publicar una línea de tiempo más corta
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
warnings.filterwarnings('ignore')

try:
    import cfgrib
    from PIL import Image
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
except ImportError as e:
    print(f"ERROR: {e}"); sys.exit(1)

# =============================================================================
# COMMON CONFIG
# =============================================================================
BASE = {
    'aws_profile': 'do-tor1',
    'cdn_bucket': 'canalmeteo-public',
    'cdn_endpoint': 'https://sfo3.digitaloceanspaces.com',
    # Escrituras (aws s3 cp) van al ORIGEN vía cdn_endpoint. Las URLs que se
    # escriben en el manifest apuntan al EDGE (Cloudflare, PoPs globales) para que
    # los espectadores lean desde el borde y no desde SFO3. El cliente además
    # tolera URLs de origen (las reescribe), así que esto es compatible hacia atrás.
    'cdn_base': 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com',
    'user_agent': 'CanalMeteoTV/1.0',
    'lat_min': 24.0, 'lat_max': 50.0,
    'lon_min': -125.0, 'lon_max': -66.0,
    'img_width': 590, 'img_height': 260,
    'img_width_hires': 3600, 'img_height_hires': 2120,
    'climatology_path': '/opt/canalmeteo/data/climatology/temp_normals_1991_2020.nc',
}

# Variables que se renderizan a alta resolución
HIRES_VARS = {'reflectivity', 'refd1km', 'ptypeRefl'}

# Variables que se renderizan como contornos (no relleno)
CONTOUR_VARS = {'pressureMb_iso'}

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================
MODELS = {
    'nbm': {
        'name': 'NBM',
        'img_width': 1800, 'img_height': 800,     # #28: nativo 2,5 km
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_blend.pl',
        'file_tmpl': 'blend.t{cc}z.core.f{fh:03d}.co.grib2',
        'dir_tmpl': '/blend.{dd}/{cc}/core',
        'cycles': list(range(24)),
        # El detector de ciclo valida la ÚLTIMA de esta lista, así que aquí se
        # queda el horizonte CORTO (78 h). Las horas largas (f084..f264, de 6 en
        # 6) las pide nbm_runner.sh solo en los ciclos que llegan a f264 — si se
        # pusieran aquí, el detector exigiría f264 y perderíamos los demás ciclos.
        'forecast_hours': list(range(1, 49)) + [51, 54, 57, 60, 66, 72, 78],
        'forecast_hours_largo': list(range(1, 49)) + [51, 54, 57, 60, 66, 72, 78]
                                + list(range(84, 265, 6)),
        'lon_360': True,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&var_APTMP=on&var_TMAX=on&var_TMIN=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_WIND=on&var_GUST=on&var_WDIR=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_GUST=on&var_CAPE=on&var_APCP=on&lev_surface=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh', 'aptmp': 'feelsF',
            'si10': 'wspdMph', 'i10fg': 'gustMph', 'wdir10': 'wdir',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            # Tmax/Tmin nativos (ventanas 12h). No se renderizan por hora: se
            # vuelcan a .npy y el merge construye la anomalía diaria. Sentinel
            # var-name (no está en CONVERTERS) por si no se hace el pop.
            'tmax': '_tmaxDaily', 'tmin': '_tminDaily',
        },
        # NBM no tiene PRMSL ni REFC en el filter — anomalía sí, calculada vs t2m
        'compute_anomaly_from': 't2m',
        # Anomalía diaria de Tmax/Tmin (hoy/mañana/pasado) vs normal 1991-2020.
        'daily_temp_anomaly': True,
        # Lluvia acumulada: integrar el APCP de 1 h hora a hora (para huracanes).
        'accumulate_precip': True,
    },
    'gfs': {
        'name': 'GFS',
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl',
        'file_tmpl': 'gfs.t{cc}z.pgrb2.0p25.f{fh:03d}',
        'dir_tmpl': '/gfs.{dd}/{cc}/atmos',
        'cycles': [0, 6, 12, 18],
        'forecast_hours': list(range(0, 49)) + list(range(51, 121, 3)),
        'lon_360': False,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_GUST=on&var_CAPE=on&var_APCP=on&var_PRMSL=on&'
                                       'var_PRATE=on&'   # 04/10: faltaba la tasa (precipRate)
                                       'var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&'
                                       'lev_surface=on&lev_mean_sea_level=on'},
            {'name': 'refl', 'params': 'var_REFD=on&all_lev=on'},
            # NUEVOS:
            {'name': 'refc',  'params': 'var_REFC=on&var_TCDC=on&lev_entire_atmosphere=on'},
            {'name': '250mb', 'params': 'var_UGRD=on&var_VGRD=on&lev_250_mb=on'},
            {'name': '850mb', 'params': 'var_TMP=on&var_UGRD=on&var_VGRD=on&lev_850_mb=on'},
            # 14/09/2026: agua precipitable (columna completa)
            {'name': 'pwat', 'params': 'var_PWAT=on&lev_entire_atmosphere_%28considered_as_a_single_layer%29=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
            'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            'prmsl': 'pressureMb', 'pwat': 'pwat', 'prate': 'precipRate',
            'refd': 'refd1km',
            'refc': 'reflectivity',     # NUEVO
            'crain': 'crain', 'csnow': 'csnow', 'cfrzr': 'cfrzr', 'cicep': 'cicep',
            # Claves de niveles isobáricos (renombradas en extract_fields según level)
            'u250': 'u250', 'v250': 'v250',
            't850': 'temp850C', 'u850': 'u850', 'v850': 'v850',
        },
        # Para 250mb/850mb los keys de cfgrib pueden colisionar con superficie;
        # se manejan en extract_fields() con detección por typeOfLevel.
        'compute_anomaly_from': 't2m',
        # 14/09/2026: nieve acumulada 10:1 = Σ APCP del tramo × CSNOW medio del tramo
        # (el GFS no publica ASNOW; ver gfs_snow_accum). Solo modo legacy (horas en orden).
        'snow_from_csnow': True,
        'render_isobars': True,
        'render_jet': True,
        'render_850': True,
    },
    'hrrr': {
        'name': 'HRRR',
        'img_width': 1800, 'img_height': 800,     # #28: nativo 3 km
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl',
        'file_tmpl': 'hrrr.t{cc}z.wrfsfcf{fh:02d}.grib2',
        'dir_tmpl': '/hrrr.{dd}/conus',
        'cycles': list(range(24)),
        'forecast_hours': list(range(0, 19)),
        'forecast_hours_extended': list(range(0, 49)),
        'lon_360': False,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_GUST=on&var_CAPE=on&var_APCP=on&'
                                       'var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&lev_surface=on'},
            {'name': 'refc', 'params': 'var_REFC=on&var_TCDC=on&lev_entire_atmosphere=on'},
            {'name': 'refd', 'params': 'var_REFD=on&lev_1000_m_above_ground=on'},
            # HRRR-Smoke: MASSDEN (humo cerca de superficie, 8 m) y COLMD (columna
            # total). cfgrib no conoce estos parámetros y los nombra 'unknown';
            # extract_fields los renombra por grupo (ver UNKNOWN_BY_GROUP).
            {'name': 'smokesfc', 'params': 'var_MASSDEN=on&lev_8_m_above_ground=on'},
            {'name': 'smokecol', 'params': 'var_COLMD=on&lev_entire_atmosphere_%28considered_as_a_single_layer%29=on'},
            # Baron parity 22.4/22.12: helicidad updraft máx 1h (2-5 km) + SRH 0-3 km (para EHI)
            {'name': 'uphl', 'params': 'var_MXUPHL=on&lev_5000-2000_m_above_ground=on'},
            {'name': 'hlcy', 'params': 'var_HLCY=on&lev_3000-0_m_above_ground=on'},
            # IR simulado (SBT124 = temp. de brillo GOES-East 10.7 µm; cfgrib
            # lo nombra 'SBT124' tal cual, typeOfLevel nominalTop)
            {'name': 'satir', 'params': 'var_SBT124=on&lev_top_of_atmosphere=on'},
            # 14/09/2026: nieve total acumulada (ASNOW, m, desde f00) + viento a 80 m
            {'name': 'snow80', 'params': 'var_ASNOW=on&var_UGRD=on&var_VGRD=on&lev_surface=on&lev_80_m_above_ground=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
            'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            'refc': 'reflectivity', 'refd': 'refd1km',
            'crain': 'crain', 'csnow': 'csnow', 'cfrzr': 'cfrzr', 'cicep': 'cicep',
            'massden': 'smokeSfc', 'colmd': 'smokeCol',
            'mxuphl': 'uphlMax', 'hlcy': 'srh3',
            'SBT124': 'satIR',
            # crudos (no están en CONVERTERS → no se pintan; los derivados sí)
            'asnow': '_asnowRaw', 'u80': '_u80', 'v80': '_v80',
        },
    },
    'hrrr_ext': {
        # HRRR Extendido — mismos productos que HRRR pero hasta 48h.
        # NOAA solo publica las horas extendidas (19-48) en los ciclos
        # principales: 00z, 06z, 12z, 18z. Los demás ciclos solo llegan a 18h.
        'name': 'HRRR_EXT',
        'img_width': 1800, 'img_height': 800,     # #28: nativo 3 km
        'filter': 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_2d.pl',
        'file_tmpl': 'hrrr.t{cc}z.wrfsfcf{fh:02d}.grib2',
        'dir_tmpl': '/hrrr.{dd}/conus',
        'cycles': [0, 6, 12, 18],            # SOLO ciclos principales
        'forecast_hours': list(range(0, 49)),  # SIEMPRE 0-48 horas
        'lon_360': False,
        'groups': [
            {'name': '2m',  'params': 'var_TMP=on&var_DPT=on&var_RH=on&lev_2_m_above_ground=on'},
            {'name': '10m', 'params': 'var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on'},
            {'name': 'sfc', 'params': 'var_VIS=on&var_GUST=on&var_CAPE=on&var_APCP=on&'
                                       'var_CRAIN=on&var_CSNOW=on&var_CFRZR=on&var_CICEP=on&lev_surface=on'},
            {'name': 'refc', 'params': 'var_REFC=on&var_TCDC=on&lev_entire_atmosphere=on'},
            {'name': 'refd', 'params': 'var_REFD=on&lev_1000_m_above_ground=on'},
            {'name': 'smokesfc', 'params': 'var_MASSDEN=on&lev_8_m_above_ground=on'},
            {'name': 'smokecol', 'params': 'var_COLMD=on&lev_entire_atmosphere_%28considered_as_a_single_layer%29=on'},
            # Baron parity 22.4/22.12: helicidad updraft máx 1h (2-5 km) + SRH 0-3 km (para EHI)
            {'name': 'uphl', 'params': 'var_MXUPHL=on&lev_5000-2000_m_above_ground=on'},
            {'name': 'hlcy', 'params': 'var_HLCY=on&lev_3000-0_m_above_ground=on'},
            {'name': 'satir', 'params': 'var_SBT124=on&lev_top_of_atmosphere=on'},
            # 14/09/2026: nieve total acumulada (ASNOW, m, desde f00) + viento a 80 m
            {'name': 'snow80', 'params': 'var_ASNOW=on&var_UGRD=on&var_VGRD=on&lev_surface=on&lev_80_m_above_ground=on'},
        ],
        'fields': {
            't2m': 'tempF', 'd2m': 'dewpF', 'r2': 'rh',
            'u10': 'u10', 'v10': 'v10', 'gust': 'gustMph',
            'vis': 'visMi', 'tcc': 'cloudPct', 'cape': 'cape', 'tp': 'precipIn',
            'refc': 'reflectivity', 'refd': 'refd1km',
            'crain': 'crain', 'csnow': 'csnow', 'cfrzr': 'cfrzr', 'cicep': 'cicep',
            'massden': 'smokeSfc', 'colmd': 'smokeCol',
            'mxuphl': 'uphlMax', 'hlcy': 'srh3',
            'SBT124': 'satIR',
            # crudos (no están en CONVERTERS → no se pintan; los derivados sí)
            'asnow': '_asnowRaw', 'u80': '_u80', 'v80': '_v80',
        },
    },
}

# =============================================================================
# CONVERTERS (grib field values → display units)
# =============================================================================
CONVERTERS = {
    'tempF':      lambda k: (k - 273.15) * 9/5 + 32,
    'dewpF':      lambda k: (k - 273.15) * 9/5 + 32,
    'feelsF':     lambda k: (k - 273.15) * 9/5 + 32,
    'rh':         lambda x: x,
    'wspdMph':    lambda ms: ms * 2.237,
    'gustMph':    lambda ms: ms * 2.237,
    'wdir':       lambda x: x,
    'visMi':      lambda m: m / 1609.34,
    'cloudPct':   lambda x: x,
    'cape':       lambda x: x,
    'precipIn':   lambda kg: np.where(kg > 0, kg / 25.4, 0),
    'reflectivity': lambda x: x,
    'refd1km':    lambda x: x,
    'pressureMb': lambda pa: pa / 100.0,
    'crain':      lambda x: x,
    'csnow':      lambda x: x,
    'cfrzr':      lambda x: x,
    'cicep':      lambda x: x,
    'u10':        lambda x: x,
    'v10':        lambda x: x,
    # NUEVOS
    'tempAnom':   lambda f_diff: f_diff,           # ya viene en °F (calculado)
    'tmaxAnom':   lambda f_diff: f_diff,           # anomalía diaria, ya en °F
    'tminAnom':   lambda f_diff: f_diff,           # anomalía diaria, ya en °F
    'temp850C':   lambda k: k - 273.15,            # K → °C
    'jet250':     lambda ms: ms * 1.94384,         # m/s → knots (más estándar para jet)
    'wind850':    lambda ms: ms * 2.237,           # m/s → mph
    'u250':       lambda x: x, 'v250': lambda x: x,
    'u850':       lambda x: x, 'v850': lambda x: x,
    # HRRR-Smoke
    'smokeSfc':   lambda kgm3: kgm3 * 1e9,         # kg/m³ → µg/m³
    'uphlMax':    lambda x: x,                     # m²/s² tal cual
    'ehi':        lambda x: x,                     # adimensional
    'smokeCol':   lambda kgm2: kgm2 * 1e6,         # kg/m² → mg/m²
    'satIR':      lambda k: k - 273.15,            # temp. de brillo K → °C
    # 14/09/2026
    'snowAccum':  lambda inch: inch,               # ya en pulgadas (derivado)
    'pwat':       lambda kgm2: kgm2,               # kg/m² == mm
    'wind80Mph':  lambda ms: ms * 2.237,           # m/s → mph
}
# 15/09/2026: las variables del HRRR nativo llegan ya en unidades de pantalla
for _v in ('precipRate', 'iceAccum', 'snowDepth', 'cloudLowPct', 'cloudMidPct', 'cloudHighPct',
           'ceilingFt', 'mlcape', 'mucape', 'cin', 'lftx', 'srh1', 'srh3', 'uphl03', 'updraftMph',
           'shear06Mph', 'maxRefl1h', 'echoTopKft', 'vil', 'lightning', 'hailIn', 'temp500C',
           'freezingLevelFt', 'solarRad', 'lightningPotential', 'rh700', 'gh500'):
    CONVERTERS.setdefault(_v, lambda x: x)

# 04/10/2026: conversiones que dependen del modelo. El HRRR nativo entrega
# `precipRate` ya en in/h (la identidad de arriba), pero el GFS da PRATE en
# kg·m⁻²·s⁻¹ y hay que pasarlo a in/h. Sin esto el GFS no publicaba la variable.
CONVERTERS_MODELO = {
    'gfs': {'precipRate': lambda kgms: np.where(kgms > 0, kgms * 3600.0 / 25.4, 0)},
}

# =============================================================================
# RENDER VARS (paletas de color para PNG)
# =============================================================================
import escala_lluvia as _el
RENDER_VARS = {
    'tempF':    {'label': 'Temperatura (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 110,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a',
                            '#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'dewpF':    {'label': 'Punto de rocío (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 80,
                 'colors': ['#4e342e','#6d4c41','#a1887f','#e0e0e0','#a5d6a7','#66bb6a','#2e7d32',
                            '#00e676','#0097a7','#01579b','#4a148c']},
    'feelsF':   {'label': 'Sensación (°F)', 'unit': '°F', 'vmin': -10, 'vmax': 120,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#0097a7','#00897b','#4caf50','#8bc34a',
                            '#cddc39','#ffeb3b','#ffc107','#ff9800','#ff5722','#d32f2f','#b71c1c','#880e4f']},
    'rh':       {'label': 'Humedad (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                 'colors': ['#b71c1c','#e65100','#f57f17','#cddc39','#8bc34a','#43a047','#2e7d32','#1565c0','#0d47a1']},
    'wspdMph':  {'label': 'Viento (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 60,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c']},
    'gustMph':  {'label': 'Ráfagas (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 80,
                 'colors': ['#e0e0e0','#81d4fa','#29b6f6','#ffeb3b','#ffa726','#ff7043','#e53935','#b71c1c','#4a148c']},
    'visMi':    {'label': 'Visibilidad (mi)', 'unit': 'mi', 'vmin': 0, 'vmax': 15,
                 'colors': ['#b71c1c','#e53935','#ff7043','#ffa726','#ffeb3b','#e0e0e0','#90caf9']},
    'cloudPct': {'label': 'Nubes (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                 'colors': ['#0d47a1','#1565c0','#42a5f5','#90caf9','#e0e0e0','#bdbdbd','#9e9e9e','#757575','#424242']},
    'cape':     {'label': 'CAPE (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 4000,
                 'colors': ['#263238','#37474f','#4caf50','#8bc34a','#ffeb3b','#ff9800','#f44336','#d32f2f','#880e4f']},
    'precipIn': {'label': 'Precipitación (in)', 'unit': 'in', 'vmin': 0, 'vmax': 2.0,
                 # 22/09: escala común (escala_lluvia), muestreada cada 0.01" para los
                 # renderizadores y leyendas que reparten los colores por igual
                 'colors': _el.colores_lineales(2.0, 0.01),
                 'stops': [x for x in _el.stops_json('in') if x['value'] <= 2.0]},
    # Lluvia acumulada (integrada hora a hora desde el APCP de 1 h, como el GFS):
    'precipAccum': {'label': 'Lluvia acumulada (in)', 'unit': 'in', 'vmin': 0, 'vmax': 20.0,
                 # 22/09: escala común (escala_lluvia), muestreada cada 0.05" para los
                 # renderizadores y leyendas que reparten los colores por igual
                 'colors': _el.colores_lineales(20.0, 0.05),
                 'stops': [x for x in _el.stops_json('in') if x['value'] <= 20.0]},
    'reflectivity': {'label': 'Radar simulado (dBZ)', 'unit': 'dBZ', 'vmin': 0, 'vmax': 80,
                 'colors': 'nws_refl', 'discrete': True},
    'refd1km':  {'label': 'Radar 1km base (dBZ)', 'unit': 'dBZ', 'vmin': 0, 'vmax': 80,
                 'colors': 'nws_refl', 'discrete': True},
    'ptypeRefl': {'label': 'Tipo precip + radar', 'unit': 'dBZ', 'vmin': 0, 'vmax': 75,
                 'colors': ['#00000000','#02fd02','#01c501','#008e00','#fdf802','#fd9500','#fd0000',
                            '#81d4fa','#039be5','#01579b','#f48fb1','#e91e63','#880e4f','#7c4dff','#6200ea','#fdfdfd']},
    'pressureMb': {'label': 'Presión nivel del mar (mb)', 'unit': 'mb', 'vmin': 980, 'vmax': 1050,
                 'colors': ['#4a148c','#1565c0','#42a5f5','#81c784','#ffeb3b','#ff9800','#e53935','#880e4f']},
    # === NUEVOS ===
    'tempAnom': {'label': 'Anomalía temp. (°F)', 'unit': '°F', 'vmin': -25, 'vmax': 25,
                 # Paleta divergente azul → blanco → rojo (frío vs cálido)
                 'colors': ['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7',
                            '#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']},
    # Anomalía diaria de máxima/mínima (mapas hoy/mañana/pasado) — misma escala divergente
    'tmaxAnom': {'label': 'Anomalía máxima (°F)', 'unit': '°F', 'vmin': -25, 'vmax': 25,
                 'colors': ['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7',
                            '#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']},
    'tminAnom': {'label': 'Anomalía mínima (°F)', 'unit': '°F', 'vmin': -25, 'vmax': 25,
                 'colors': ['#053061','#2166ac','#4393c3','#92c5de','#d1e5f0','#f7f7f7',
                            '#fddbc7','#f4a582','#d6604d','#b2182b','#67001f']},
    'temp850C': {'label': 'Temperatura 850 mb (°C)', 'unit': '°C', 'vmin': -40, 'vmax': 30,
                 'colors': ['#4a148c','#1a237e','#0d47a1','#01579b','#0097a7','#00897b','#43a047',
                            '#cddc39','#ffeb3b','#ffa726','#ef5350','#c62828','#880e4f']},
    'jet250':   {'label': 'Corriente en chorro 250 mb (kt)', 'unit': 'kt', 'vmin': 50, 'vmax': 200,
                 # Verde claro → amarillo → naranja → rojo → magenta para >150 kt
                 'colors': ['#00000000','#a5d6a7','#cddc39','#ffeb3b','#ffa726','#ef5350',
                            '#c62828','#880e4f','#6a1b9a','#311b92']},
    'wind850':  {'label': 'Viento 850 mb (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 70,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f']},
    # HRRR-Smoke — escala sqrt: el humo ligero (1-30 µg/m³) es lo habitual y con
    # escala lineal quedaría todo en el primer color. Los ticks de la leyenda del
    # cliente (customTicks) están cuadrados para casar con esta escala.
    # 14/09/2026 — mismas paletas que ecmwf_global (el visor ya las conoce)
    'snowAccum': {'label': 'Nieve acumulada (in)', 'unit': 'in', 'vmin': 0, 'vmax': 24,
                 'colors': ['#e1f5fe','#81d4fa','#29b6f6','#1e88e5','#3949ab','#5e35b1','#8e24aa','#d500f9','#f48fb1']},
    'pwat':     {'label': 'Agua precipitable (mm)', 'unit': 'mm', 'vmin': 0, 'vmax': 70,
                 'colors': ['#3e2723','#795548','#bcaaa4','#e0e0e0','#a5d6a7','#4caf50','#00897b',
                            '#0288d1','#1565c0','#4527a0','#880e4f']},
    'wind80Mph': {'label': 'Viento 80 m (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 80,
                 'colors': ['#e0e0e0','#b0bec5','#81d4fa','#039be5','#ffb300','#e65100','#bf360c','#880e4f','#4a148c']},
    'smokeSfc': {'label': 'Humo superficie (µg/m³)', 'unit': 'µg/m³', 'vmin': 0, 'vmax': 225,
                 'scale': 'sqrt',
                 'colors': ['#c9b6e0','#9c4dcc','#6a1b9a','#4a0072']},
    'smokeCol': {'label': 'Humo columna (mg/m²)', 'unit': 'mg/m²', 'vmin': 0, 'vmax': 900,
                 'scale': 'sqrt',
                 'colors': ['#c9b6e0','#9c4dcc','#6a1b9a','#4a0072']},
    # Helicidad updraft 2-5 km máx horaria — firma de supercélula del futurecast
    'uphlMax':  {'label': 'Helicidad updraft 2-5 km (m²/s²)', 'unit': 'm²/s²', 'vmin': 0, 'vmax': 200,
                 'colors': ['#00000000','#ce93d8','#8e24aa','#e53935','#000000']},
    # EHI 0-3 km = CAPE×SRH/160000 — coincidencia de energía y giro
    'ehi':      {'label': 'EHI 0-3 km', 'unit': '', 'vmin': 0, 'vmax': 8,
                 'colors': ['#00000000','#a5d6a7','#ffeb3b','#fb8c00','#e53935','#880e4f']},
    # IR simulado (SBT124): realce clásico — topes fríos coloreados, suelo en
    # grises (cálido = oscuro). vmin es el extremo FRÍO.
    'satIR':    {'label': 'IR simulado (°C)', 'unit': '°C', 'vmin': -80, 'vmax': 40,
                 'colors': ['#ffffff','#e040fb','#8e24aa','#e53935','#fb8c00','#fdd835',
                            '#bdbdbd','#9e9e9e','#757575','#616161','#424242','#212121']},
}

# 15/09/2026 — variables nuevas del HRRR nativo (hrrr_png_nativo.py). `visible_min` /
# `visible_max` + `alpha`: transparente fuera de ese rango (ver render_png).
_P_SEVERO = ['#c9e7c0', '#e6e600', '#f0a546', '#fd0000', '#f800fd']
RENDER_VARS.update({
    'precipRate': {'label': 'Intensidad de precipitación (in/h)', 'unit': 'in/h', 'vmin': 0, 'vmax': 2,
                   'visible_min': 0.01, 'alpha': 0.75, 'colors': ['#263238','#1b5e20','#4caf50','#a5d6a7','#ffeb3b','#ff9800','#f44336','#e040fb']},   # 22/09: la de siempre; es INTENSIDAD (in/h), no hereda la escala de acumulado
    'iceAccum':   {'label': 'Lluvia engelante acumulada (in)', 'unit': 'in', 'vmin': 0, 'vmax': 1,
                   'visible_min': 0.01, 'alpha': 0.80,
                   'colors': ['#f8bbd0', '#f06292', '#d81b60', '#880e4f', '#4a148c']},
    'snowDepth':  {'label': 'Nieve en el suelo (in)', 'unit': 'in', 'vmin': 0, 'vmax': 24,
                   'visible_min': 0.1, 'alpha': 0.80, 'colors': RENDER_VARS['snowAccum']['colors']},
    'cloudLowPct':  {'label': 'Nubes bajas (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                     'colors': RENDER_VARS['cloudPct']['colors']},
    'cloudMidPct':  {'label': 'Nubes medias (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                     'colors': RENDER_VARS['cloudPct']['colors']},
    'cloudHighPct': {'label': 'Nubes altas (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                     'colors': RENDER_VARS['cloudPct']['colors']},
    'ceilingFt':  {'label': 'Techo de nubes (ft)', 'unit': 'ft', 'vmin': 0, 'vmax': 12000,
                   'visible_max': 12000, 'alpha': 0.75,
                   'colors': ['#b71c1c', '#e53935', '#ff7043', '#ffa726', '#ffeb3b', '#a5d6a7', '#90caf9']},
    'mlcape':     {'label': 'CAPE capa de mezcla (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 4000,
                   'colors': RENDER_VARS['cape']['colors']},
    'mucape':     {'label': 'CAPE más inestable (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 4000,
                   'colors': RENDER_VARS['cape']['colors']},
    'cin':        {'label': 'CIN superficie (J/kg)', 'unit': 'J/kg', 'vmin': -300, 'vmax': 0,
                   'visible_max': -10, 'alpha': 0.75,
                   'colors': ['#4a148c', '#7b1fa2', '#ab47bc', '#ce93d8', '#f3e5f5']},
    'lftx':       {'label': 'Índice de elevación (°C)', 'unit': '°C', 'vmin': -10, 'vmax': 10,
                   'colors': ['#880e4f', '#d32f2f', '#ff9800', '#ffeb3b', '#e0e0e0', '#90caf9', '#1565c0']},
    'srh1':       {'label': 'Helicidad 0-1 km (m²/s²)', 'unit': 'm²/s²', 'vmin': 0, 'vmax': 500,
                   'visible_min': 50, 'alpha': 0.80, 'colors': _P_SEVERO},
    'srh3':       {'label': 'Helicidad 0-3 km (m²/s²)', 'unit': 'm²/s²', 'vmin': 0, 'vmax': 600,
                   'visible_min': 50, 'alpha': 0.80, 'colors': _P_SEVERO},
    'uphl03':     {'label': 'Helicidad updraft 0-3 km (m²/s²)', 'unit': 'm²/s²', 'vmin': 0, 'vmax': 100,
                   'visible_min': 10, 'alpha': 0.85, 'colors': RENDER_VARS['uphlMax']['colors']},
    'updraftMph': {'label': 'Corriente ascendente máxima (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 60,
                   'visible_min': 5, 'alpha': 0.80, 'colors': _P_SEVERO},
    'shear06Mph': {'label': 'Cizalladura 0-6 km (mph)', 'unit': 'mph', 'vmin': 0, 'vmax': 90,
                   'colors': RENDER_VARS['wspdMph']['colors']},
    'maxRefl1h':  {'label': 'Reflectividad máxima 1 h (dBZ)', 'unit': 'dBZ', 'vmin': 0, 'vmax': 80,
                   'colors': 'nws_refl', 'discrete': True},
    'echoTopKft': {'label': 'Topes de eco (kft)', 'unit': 'kft', 'vmin': 0, 'vmax': 60,
                   'visible_min': 5, 'alpha': 0.85,
                   'colors': ['#4b96e1', '#8fd08a', '#e6e600', '#f0a546', '#fd0000', '#f800fd']},
    'vil':        {'label': 'VIL (kg/m²)', 'unit': 'kg/m²', 'vmin': 0, 'vmax': 70,
                   'visible_min': 1, 'alpha': 0.85,
                   'colors': ['#c9e7c0', '#8fd08a', '#e6e600', '#f0a546', '#fd0000', '#f800fd']},
    'lightning':  {'label': 'Amenaza de rayos (fl/km²/5 min)', 'unit': 'fl/km²/5min', 'vmin': 0, 'vmax': 3,
                   'visible_min': 0.05, 'alpha': 0.85,
                   'colors': ['#c9c9c9', '#e6e600', '#f0a546', '#fd0000', '#f800fd']},
    'hailIn':     {'label': 'Granizo máximo (in)', 'unit': 'in', 'vmin': 0, 'vmax': 3,
                   'visible_min': 0.25, 'alpha': 0.90, 'colors': _P_SEVERO},
    'temp500C':   {'label': 'Temperatura 500 mb (°C)', 'unit': '°C', 'vmin': -40, 'vmax': 0,
                   'colors': RENDER_VARS['temp850C']['colors']},
    'freezingLevelFt': {'label': 'Altura de la isoterma 0 °C (ft)', 'unit': 'ft', 'vmin': 0, 'vmax': 16000,
                   'colors': ['#4a148c', '#1565c0', '#42a5f5', '#81c784', '#ffeb3b', '#ff9800', '#e53935']},
    'solarRad':   {'label': 'Radiación solar (W/m²)', 'unit': 'W/m²', 'vmin': 0, 'vmax': 1000,
                   'colors': ['#1a237e', '#5c6bc0', '#ffb300', '#ffee58', '#fffde7']},
    # ICON-EU nativo (icon_eu_nativo_pipeline.py)
    'lightningPotential': {'label': 'Potencial de rayos (J/kg)', 'unit': 'J/kg', 'vmin': 0, 'vmax': 150,
                   'visible_min': 5, 'alpha': 0.85, 'colors': _P_SEVERO},
    'rh700':      {'label': 'Humedad 700 mb (%)', 'unit': '%', 'vmin': 0, 'vmax': 100,
                   'colors': RENDER_VARS['rh']['colors']},
    'gh500':      {'label': 'Geopotencial 500 mb (dam)', 'unit': 'dam', 'vmin': 510, 'vmax': 600,
                   'colors': RENDER_VARS['pressureMb']['colors']},
})

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


# =============================================================================
# CYCLE DETECTION
# =============================================================================
def find_latest_cycle(model_cfg):
    """Find latest available cycle for this model."""
    now = datetime.now(timezone.utc)
    # HRRR_EXT solo tiene 4 ciclos/día (cada 6h), igual que GFS
    if model_cfg['name'] in ('GFS', 'HRRR_EXT'):
        max_lookback = 24
    else:
        max_lookback = 12
    seen_cycles = set()

    for hb in range(0, max_lookback):
        t = now - timedelta(hours=hb)
        cc_int = t.hour
        valid_cycles = sorted(model_cfg['cycles'])
        cc_int = max([c for c in valid_cycles if c <= cc_int], default=valid_cycles[-1])
        cc = f"{cc_int:02d}"
        dd = t.strftime('%Y%m%d')

        cycle_key = f"{dd}/{cc}"
        if cycle_key in seen_cycles:
            continue
        seen_cycles.add(cycle_key)

        dir_path = model_cfg['dir_tmpl'].format(dd=dd, cc=cc)
        # Validar la ULTIMA hora: si existe, el ciclo esta completo.
        # (f000 nace casi al instante; usarla aceptaba ciclos parciales)
        fh = model_cfg['forecast_hours'][-1]
        fname = model_cfg['file_tmpl'].format(cc=cc, fh=fh)
        lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
        test_group = model_cfg['groups'][0]
        url = (f"{model_cfg['filter']}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
               f"{test_group['params']}&subregion=&toplat=26&leftlon={lw}&rightlon={lw+2}&bottomlat=24")
        try:
            r = requests.get(url, timeout=20, headers={'User-Agent': BASE['user_agent']})
            if r.status_code == 200 and len(r.content) > 100:
                log.info(f"Cycle: {dd}/{cc}z")
                return dd, cc
        except Exception:
            pass
    return None, None


# =============================================================================
# DOWNLOAD GROUP
# =============================================================================
def download_group(model_cfg, date, cycle, fhour, group):
    """Download one filtered GRIB2."""
    data_dir = f"/opt/canalmeteo/data/{model_cfg['name'].lower()}"
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    outpath = os.path.join(data_dir,
        f"{model_cfg['name'].lower()}_{group['name']}_{date}_{cycle}z_f{fhour:03d}.grib2")

    lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
    le = BASE['lon_max'] + (360 if model_cfg['lon_360'] else 0)
    dir_path = model_cfg['dir_tmpl'].format(dd=date, cc=cycle)
    fname = model_cfg['file_tmpl'].format(cc=cycle, fh=fhour)

    url = (f"{model_cfg['filter']}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
           f"{group['params']}&subregion=&toplat={BASE['lat_max']}&leftlon={lw}&"
           f"rightlon={le}&bottomlat={BASE['lat_min']}")
    try:
        r = requests.get(url, timeout=90, headers={'User-Agent': BASE['user_agent']})
        if r.status_code == 200 and len(r.content) > 500:
            with open(outpath, 'wb') as f:
                f.write(r.content)
            return outpath, len(r.content), group['name']
    except Exception as e:
        log.warning(f"    {group['name']}: {e}")
    return None, 0, group['name']


# =============================================================================
# APCP de 1 hora — para la lluvia acumulada
# =============================================================================
def extract_apcp_window(grib_path, length_h):
    """Devuelve (valores_mm, lats, lons) del registro APCP con intervalo de
    acumulación `length_h` horas (lengthOfTimeRange). Usamos 1 h, que el NBM
    publica en TODAS las horas y ciclos (las ventanas de 6 h/12 h solo están en
    los ciclos sinópticos 00/06/12/18). None si no existe."""
    try:
        import xarray as xr
        ds = xr.open_dataset(
            grib_path, engine='cfgrib',
            backend_kwargs={'indexpath': '',
                            'filter_by_keys': {'shortName': 'tp',
                                               'lengthOfTimeRange': length_h,
                                               # PDT 8 = acumulación determinista.
                                               # (PDT 9 = probabilidad 0-100%; sin
                                               # este filtro cfgrib cogía esa y la
                                               # sumaba como mm -> ~100 in absurdos.)
                                               'productDefinitionTemplateNumber': 8}})
        if 'tp' in ds:
            return ds['tp'].values, ds.latitude.values, ds.longitude.values
    except Exception as e:
        log.warning(f"    apcp{length_h}h: {e}")
    return None, None, None


# =============================================================================
# NIEVE ACUMULADA GFS (14/09/2026)
# =============================================================================
# El GFS 0.25 no publica ASNOW. En cada hora trae el APCP del TRAMO de 6 h en curso
# («6-7 hour acc», «18-24 hour acc», «48-51 hour acc») y la media del tipo
# categórico nieve en ese mismo tramo («18-24 hour ave»). Nieve del tramo (in, 10:1)
# = APCP_mm × CSNOW_medio × 10 / 25,4. El total desde f000 es la suma de los tramos
# cerrados + el tramo en curso. Estado en memoria: solo vale en el modo legacy, que
# recorre las horas en orden en un mismo proceso (así corre el cron del GFS).
_GFS_SNOW = {'run': None, 'done': None, 'bucket': None, 'partial': None}


def extract_gfs_snow_bucket(grib_path, fhour):
    """Nieve (in, 10:1) del tramo de 6 h en curso, o None si faltan registros."""
    bs = ((fhour - 1) // 6) * 6
    apcp = csnow = None
    try:
        import eccodes
        with open(grib_path, 'rb') as fh_:
            while True:
                g = eccodes.codes_grib_new_from_file(fh_)
                if g is None:
                    break
                try:
                    sn = eccodes.codes_get(g, 'shortName')
                    if sn not in ('tp', 'csnow'):
                        continue
                    st = eccodes.codes_get(g, 'stepType')
                    s0 = int(eccodes.codes_get(g, 'startStep'))
                    s1 = int(eccodes.codes_get(g, 'endStep'))
                    unit = eccodes.codes_get(g, 'stepUnits')
                    if unit not in (1, 'h') or s0 != bs or s1 != fhour or s0 == s1:
                        continue
                    ny, nx = eccodes.codes_get(g, 'Nj'), eccodes.codes_get(g, 'Ni')
                    vals = eccodes.codes_get_values(g).reshape(ny, nx)
                    if sn == 'tp' and st == 'accum' and apcp is None:
                        apcp = vals
                    elif sn == 'csnow' and st in ('avg', 'ave') and csnow is None:
                        csnow = vals
                finally:
                    eccodes.codes_release(g)
    except Exception as e:
        log.warning(f"    nieve GFS f{fhour:03d}: {e}")
        return None
    if apcp is None or csnow is None:
        log.warning(f"    nieve GFS f{fhour:03d}: sin APCP/CSNOW del tramo {bs}-{fhour}")
        return None
    return (np.clip(apcp, 0, None) * np.clip(csnow, 0, 1) * 10.0 / 25.4).astype('float32')


_GFS_LLUVIA = {'run': None, 'done': None, 'bucket': None, 'partial': None}


def gfs_rain_accum(date, cycle, fhour, bucket_in):
    """Lluvia acumulada desde f000 (in) del GFS, tramo a tramo.

    El GFS 0.25 no publica un acumulado total: cada hora trae el APCP del TRAMO
    de 6 h en curso («6-7 hour acc», «18-24 hour acc»…). El total es la suma de
    los tramos CERRADOS más el tramo en curso — la misma cuenta que ya hacíamos
    para la nieve. Sumar los APCP hora a hora sin más los contaría varias veces.

    Estado en memoria: vale en el modo legacy, que recorre las horas en orden en
    un mismo proceso (así corre el cron del GFS). En --single-hour no se publica.
    """
    st = _GFS_LLUVIA
    run = f'{date}{cycle}'
    bs = ((fhour - 1) // 6) * 6
    if st['run'] != run or st['done'] is None or st['done'].shape != bucket_in.shape:
        st.update(run=run, done=np.zeros_like(bucket_in), bucket=None, partial=None)
    if st['bucket'] is not None and bs != st['bucket'] and st['partial'] is not None:
        st['done'] = st['done'] + st['partial']
    st['bucket'], st['partial'] = bs, bucket_in
    return st['done'] + bucket_in


def gfs_snow_accum(date, cycle, fhour, bucket_in):
    """Suma tramos cerrados + tramo en curso. Si falta la hora final de un tramo,
    se cierra con su último parcial visto (no se pierde el tramo entero)."""
    st = _GFS_SNOW
    run = f'{date}{cycle}'
    bs = ((fhour - 1) // 6) * 6
    if st['run'] != run or st['done'] is None or st['done'].shape != bucket_in.shape:
        st.update(run=run, done=np.zeros_like(bucket_in), bucket=None, partial=None)
    if st['bucket'] is not None and bs != st['bucket'] and st['partial'] is not None:
        st['done'] = st['done'] + st['partial']
    st['bucket'], st['partial'] = bs, bucket_in
    return st['done'] + bucket_in


# =============================================================================
# EXTRACT FIELDS — versión consciente del nivel
# =============================================================================
def extract_fields(grib_path, field_map, group_name=None):
    """Extract known fields from GRIB2.
    Para grupos de niveles isobáricos (250mb, 850mb), renombra los campos
    para evitar colisión con campos de superficie del mismo nombre (UGRD/VGRD/TMP).
    """
    # Los campos de humo del HRRR (MASSDEN/COLMD) no están en las tablas de
    # cfgrib → salen como 'unknown'. Van cada uno en su propio grupo/fichero,
    # así que el nombre del grupo basta para identificarlos.
    UNKNOWN_BY_GROUP = {'smokesfc': 'massden', 'smokecol': 'colmd', 'uphl': 'mxuphl', 'hlcy': 'hlcy',
                        'snow80': 'asnow'}   # ASNOW: único 'unknown' del grupo snow80 (u/v 80 m sí tienen nombre)
    found = {}
    try:
        for ds in cfgrib.open_datasets(grib_path):
            # Detectar el nivel del dataset
            type_of_level = None
            level_value = None
            try:
                if 'isobaricInhPa' in ds.coords:
                    type_of_level = 'isobaricInhPa'
                    level_value = float(ds['isobaricInhPa'].values) \
                        if ds['isobaricInhPa'].ndim == 0 \
                        else float(ds['isobaricInhPa'].values[0])
            except Exception:
                pass
            # 14/09/2026: viento a 80 m (cfgrib lo llama u/v con heightAboveGround=80)
            hag80 = False
            try:
                if 'heightAboveGround' in ds.coords:
                    hv = np.atleast_1d(ds['heightAboveGround'].values)
                    hag80 = hv.size == 1 and abs(float(hv[0]) - 80) < 0.5
            except Exception:
                pass

            for fname in ds.data_vars:
                data = ds[fname].values
                if data.ndim == 3:
                    data = data[0]

                # Campos isobáricos: renombrar según nivel (250mb / 850mb)
                key = fname
                if fname == 'unknown' and group_name in UNKNOWN_BY_GROUP:
                    key = UNKNOWN_BY_GROUP[group_name]
                if type_of_level == 'isobaricInhPa' and level_value is not None:
                    if abs(level_value - 250) < 1:
                        if fname == 'u': key = 'u250'
                        elif fname == 'v': key = 'v250'
                    elif abs(level_value - 850) < 1:
                        if fname == 't': key = 't850'
                        elif fname == 'u': key = 'u850'
                        elif fname == 'v': key = 'v850'

                if hag80 and fname in ('u', 'v'):
                    key = fname + '80'
                if key in field_map and key not in found:
                    found[key] = (data, ds.latitude.values, ds.longitude.values)
    except Exception as e:
        log.warning(f"    cfgrib ({group_name}): {e}")
    return found


# =============================================================================
# NWS RADAR REFLECTIVITY COLOR TABLE
# =============================================================================
NWS_REFL_TABLE = [
    (15, (  1, 159, 244)), (20, (  3,   0, 244)), (25, (  2, 253,   2)),
    (30, (  1, 197,   1)), (35, (  0, 142,   0)), (40, (253, 248,   2)),
    (45, (229, 188,   0)), (50, (253, 149,   0)), (55, (253,   0,   0)),
    (60, (212,   0,   0)), (65, (188,   0,   0)), (70, (248,   0, 253)),
    (75, (152,  84, 198)), (80, (253, 253, 253)),
]

def render_nws_refl(field):
    """Render radar field using exact NWS discrete color bins."""
    h, w = field.shape
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    for i, (threshold, (r, g, b)) in enumerate(NWS_REFL_TABLE):
        if i < len(NWS_REFL_TABLE) - 1:
            next_threshold = NWS_REFL_TABLE[i + 1][0]
            mask = (field >= threshold) & (field < next_threshold)
        else:
            mask = field >= threshold
        rgba[mask, 0] = r / 255.0
        rgba[mask, 1] = g / 255.0
        rgba[mask, 2] = b / 255.0
        rgba[mask, 3] = 0.92
    return rgba


# =============================================================================
# REPROJECTION (cached KDTree)
# =============================================================================
_kdtree_cache = {}
# ═══════════════════════════════════════════════════════════════════
# KDTree disk cache — persiste indices entre runs (Apr 30 2026)
# ═══════════════════════════════════════════════════════════════════
_KDTREE_CACHE_DIR = "/opt/canalmeteo/data/cache/kdtree"

def _kdtree_cache_path(model_name, src_shape, target_h, target_w, sample_hash):
    """Ruta del archivo cache para esta configuración."""
    import os
    os.makedirs(_KDTREE_CACHE_DIR, exist_ok=True)
    fname = f"{model_name}_{src_shape[0]}x{src_shape[1]}_to_{target_h}x{target_w}_{sample_hash}.pkl"
    return os.path.join(_KDTREE_CACHE_DIR, fname)

def _kdtree_grid_hash(lats_2d, lons_2d):
    """Hash corto de las coords para detectar cambios de grid (raros)."""
    import hashlib
    sample = lats_2d.ravel()[:8].tobytes() + lons_2d.ravel()[:8].tobytes()
    return hashlib.md5(sample).hexdigest()[:8]

def load_kdtree_indices(model_name, src_shape, target_h, target_w, sample_hash):
    """Carga indices desde disco. Devuelve None si no existe."""
    import os, pickle
    path = _kdtree_cache_path(model_name, src_shape, target_h, target_w, sample_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            indices = pickle.load(f)
        log.info(f"    Loaded KDTree indices from cache: {os.path.basename(path)}")
        return indices
    except Exception as e:
        log.warning(f"    Failed to load KDTree cache: {e} — rebuilding")
        return None

def save_kdtree_indices(model_name, src_shape, target_h, target_w, sample_hash, indices):
    """Guarda indices a disco."""
    import os, pickle
    path = _kdtree_cache_path(model_name, src_shape, target_h, target_w, sample_hash)
    try:
        with open(path, "wb") as f:
            pickle.dump(indices, f, protocol=4)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        log.info(f"    Saved KDTree indices to cache: {os.path.basename(path)} ({size_mb:.1f} MB)")
    except Exception as e:
        log.warning(f"    Failed to save KDTree cache: {e}")



def reproject_cached(data, lats_2d, lons_2d, target_h, target_w):
    """Cached version — reuses KDTree across variables for same grid shape."""
    global _kdtree_cache
    from scipy.spatial import cKDTree

    cache_key = (lats_2d.shape, target_h, target_w)
    if cache_key not in _kdtree_cache:
        # Try loading from disk first (Apr 30 2026 disk cache)
        model_for_cache = globals().get('_current_model_name', 'unknown')
        sample_hash = _kdtree_grid_hash(lats_2d, lons_2d)
        indices = load_kdtree_indices(
            model_for_cache, lats_2d.shape, target_h, target_w, sample_hash,
        )

        if indices is None:
            # Build from scratch
            lons_fixed = np.where(lons_2d > 180, lons_2d - 360, lons_2d)
            lat_reg = np.linspace(BASE['lat_max'], BASE['lat_min'], target_h)
            lon_reg = np.linspace(BASE['lon_min'], BASE['lon_max'], target_w)
            lon_grid, lat_grid = np.meshgrid(lon_reg, lat_reg)

            src_points = np.column_stack([lats_2d.ravel(), lons_fixed.ravel()])
            tree = cKDTree(src_points)
            tgt_points = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
            _, indices = tree.query(tgt_points)
            log.info(f"    Built KDTree for {lats_2d.shape} -> {target_h}x{target_w}")

            # Persist to disk for future runs
            save_kdtree_indices(
                model_for_cache, lats_2d.shape, target_h, target_w, sample_hash, indices,
            )

        _kdtree_cache[cache_key] = indices

    indices = _kdtree_cache[cache_key]
    return data.ravel()[indices].reshape(target_h, target_w)


# =============================================================================
# CLIMATOLOGY (NCEI 1991-2020) — para anomalía
# =============================================================================
_clim_cache = {}

def load_climatology_var(varname):
    """Carga el cubo (365, H, W) de una variable climatológica en °F (cache por var).

    Lee con netCDF4 DIRECTO: el backend netCDF4 de xarray falla con 'HDF error'
    en este entorno (probado con varios ficheros), mientras netCDF4.Dataset abre
    bien. Devuelve el array o False si no está disponible.
    """
    if varname in _clim_cache:
        return _clim_cache[varname]
    path = BASE['climatology_path']
    if not os.path.exists(path):
        log.warning(f"    Climatología no encontrada: {path} — anomalía deshabilitada")
        _clim_cache[varname] = False
        return False
    try:
        import netCDF4
        nc = netCDF4.Dataset(path, 'r')
        try:
            use = varname
            if use not in nc.variables:
                # Compat con el fichero antiguo (única var de Tavg).
                cands = [v for v in nc.variables if v.endswith('_F')]
                if varname == 'tavg_F' and cands:
                    use = cands[0]
                else:
                    log.warning(f"    Var climatológica '{varname}' ausente "
                                f"(disponibles: {cands})")
                    _clim_cache[varname] = False
                    return False
            arr = np.asarray(nc.variables[use][:], dtype=np.float32)
        finally:
            nc.close()
        _clim_cache[varname] = arr
        log.info(f"    Climatología '{varname}' cargada: {arr.shape}")
        return arr
    except Exception as e:
        log.warning(f"    No se pudo cargar climatología '{varname}': {e}")
        _clim_cache[varname] = False
        return False


def load_climatology():
    """Compat: cubo de Tavg en °F (usado por el producto tempAnom)."""
    return load_climatology_var('tavg_F')


def compute_temp_anomaly(t_field_F, lats, lons, valid_dt):
    """Calcula T_modelo (°F) - T_climatología(día_del_año).
    t_field_F: array 2D ya convertido a °F
    valid_dt: datetime UTC del valid time
    Retorna array 2D de anomalía en °F, o None si la climatología no está disponible."""
    clim = load_climatology()
    if clim is False or clim is None:
        return None
    doy = valid_dt.timetuple().tm_yday - 1  # 0-indexed
    if doy >= clim.shape[0]:
        doy = clim.shape[0] - 1
    clim_field = clim[doy]  # (H_clim, W_clim) — ya regrillado a img_height x img_width

    # El campo t puede venir a tamaño nativo o reproyectado.
    # Lo reescalamos a img_height × img_width (resolución de la climatología).
    target_h, target_w = clim_field.shape
    if t_field_F.shape != clim_field.shape:
        if lats.ndim == 2:
            t_resized = reproject_cached(t_field_F, lats, lons, target_h, target_w)
        else:
            # Grid regular → resize bilineal vía PIL
            from PIL import Image as PILImage
            img = PILImage.fromarray(t_field_F.astype(np.float32), mode='F')
            t_resized = np.array(img.resize((target_w, target_h), PILImage.BILINEAR))
    else:
        t_resized = t_field_F

    return t_resized - clim_field


# =============================================================================
# RENDER PNG (relleno por celda)
# =============================================================================
def render_png(data, lats, lons, var_name, convert_fn, output_path, needs_reproject=False):
    """Render field as PNG using fast PIL resize."""
    if var_name not in RENDER_VARS:
        return False
    rcfg = RENDER_VARS[var_name]

    field = convert_fn(data.copy())
    field = np.where(np.isnan(field), rcfg['vmin'], field)

    # ── REPROJECT Lambert Conformal (2D coords) to regular lat/lon grid ──
    if needs_reproject and lats.ndim == 2:
        if var_name in HIRES_VARS:
            field = reproject_cached(field, lats, lons,
                                     BASE['img_height_hires'], BASE['img_width_hires'])
        else:
            field = reproject_cached(field, lats, lons,
                                     BASE['img_height'], BASE['img_width'])

    # ── ANTI-PIXELADO PARA RADAR ──
    # Para reflectividad en grid regular (ej. GFS 0.25° → 25km de píxel nativo),
    # el render directo a 3600x2120 muestra cuadrados visibles. Suavizamos solo
    # los píxeles con eco real para evitar halos donde no debería haberlos.
    if var_name in {'reflectivity', 'refd1km'}:
        try:
            from scipy.ndimage import gaussian_filter, zoom
            # Si el campo NO fue reproyectado (grid regular nativo), ampliarlo
            # con interpolación bilineal antes de pasar al colormap discreto NWS.
            if not (needs_reproject and lats.ndim == 2):
                # Ampliar al tamaño hires con factor de zoom
                target_h, target_w = BASE['img_height_hires'], BASE['img_width_hires']
                zh = target_h / field.shape[0]
                zw = target_w / field.shape[1]
                # Máscara de ecos válidos (>5 dBZ) — interpolada también
                mask = (field > 5).astype(np.float32)
                # Suavizar el campo antes de ampliar (sigma pequeño en grid nativo)
                field_smooth = gaussian_filter(field, sigma=0.7)
                # Ampliar por interpolación bilineal (orden 1)
                field = zoom(field_smooth, (zh, zw), order=1)
                # Ampliar máscara con orden 0 (nearest) para preservar bordes
                mask = zoom(mask, (zh, zw), order=1)
                # Aplicar máscara: donde no había eco, forzar a 0
                field = np.where(mask > 0.3, field, 0)
            else:
                # Ya reproyectado a hires: solo suavizado leve
                field = gaussian_filter(field, sigma=1.0)
        except Exception as e:
            log.warning(f"    Suavizado radar falló: {e}")

    # ── Discrete NWS colormap para radar ──
    if rcfg.get('discrete') and rcfg['colors'] == 'nws_refl':
        rgba = render_nws_refl(field)
        out_w, out_h = BASE['img_width_hires'], BASE['img_height_hires']
    else:
        norm = np.clip((field - rcfg['vmin']) / (rcfg['vmax'] - rcfg['vmin']), 0, 1)
        if rcfg.get('scale') == 'sqrt':
            norm = np.sqrt(norm)
        cmap = mcolors.LinearSegmentedColormap.from_list('c', rcfg['colors'], N=1024)
        rgba = cmap(norm)

        if var_name in HIRES_VARS:
            rgba[:, :, 3] = np.where(field > 15, 0.92, 0.0)
            out_w, out_h = BASE['img_width_hires'], BASE['img_height_hires']
        elif var_name == 'jet250':
            # Jet: solo visible donde supera 50 kt
            rgba[:, :, 3] = np.where(field > 50, 0.85, 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name == 'uphlMax':
            # Helicidad: solo visible con rotación significativa
            rgba[:, :, 3] = np.where(field > 10, 0.85, 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name == 'ehi':
            rgba[:, :, 3] = np.where(field > 0.25, 0.85, 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name in ('tempAnom', 'tmaxAnom', 'tminAnom'):
            # Anomalía: 80% opaco, escala divergente
            rgba[:, :, 3] = 0.80
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name in ('smokeSfc', 'smokeCol'):
            # Humo: transparente sin humo, ganando opacidad con la densidad
            # (norm ya va en escala sqrt → el humo ligero aparece tenue)
            rgba[:, :, 3] = np.clip(norm * 3, 0, 1) * 0.90
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name == 'snowAccum':
            # Nieve: transparente bajo 0,1 in (como ecmwf_global)
            rgba[:, :, 3] = np.where(field > 0.1, 0.80, 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif var_name in ('precipIn', 'precipAccum'):
            # Precipitación: transparente bajo 0.01 in — antes se pintaba el color
            # base #263238 a 70% en todo el dominio y se veía la malla del modelo
            # con valores ~0 (mismo umbral que gfs_global.render_png)
            rgba[:, :, 3] = np.where(field > 0.01, 0.70, 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        elif 'visible_min' in rcfg or 'visible_max' in rcfg:
            # 15/09/2026 (HRRR nativo): transparente fuera del rango con señal
            vis = np.ones(field.shape, dtype=bool)
            if 'visible_min' in rcfg:
                vis &= field >= rcfg['visible_min']
            if 'visible_max' in rcfg:
                vis &= field <= rcfg['visible_max']
            rgba[:, :, 3] = np.where(vis, rcfg.get('alpha', 0.75), 0.0)
            out_w, out_h = BASE['img_width'], BASE['img_height']
        else:
            rgba[:, :, 3] = 0.70
            out_w, out_h = BASE['img_width'], BASE['img_height']

    img_full = Image.fromarray((rgba * 255).astype(np.uint8), 'RGBA')
    # Si el campo ya fue ampliado a hires (grid regular suavizado), no resize
    if (needs_reproject and lats.ndim == 2) or \
       (var_name in {'reflectivity', 'refd1km'} and field.shape[0] == BASE['img_height_hires']):
        img_out = img_full
    else:
        img_out = img_full.resize((out_w, out_h), Image.BILINEAR)
    img_out.save(output_path, 'PNG', optimize=True)
    return True


def render_ptype_refl(refl_data, refl_lats, refl_lons, cr, cs, cf, ci, ptype_path):
    """Compuesto tipo de precipitación + radar (PNG hires). Extraído de process_hour
    (15/09/2026) para que hrrr_png_nativo pinte exactamente lo mismo."""
    if refl_lats.ndim == 2:
        th, tw = BASE['img_height_hires'], BASE['img_width_hires']
        refl_data = reproject_cached(refl_data, refl_lats, refl_lons, th, tw)
        cr = reproject_cached(cr, refl_lats, refl_lons, th, tw)
        cs = reproject_cached(cs, refl_lats, refl_lons, th, tw)
        cf = reproject_cached(cf, refl_lats, refl_lons, th, tw)
        ci = reproject_cached(ci, refl_lats, refl_lons, th, tw)

    refl_norm = np.clip(refl_data / 75.0, 0, 1)
    h, w = refl_data.shape[:2]
    mask_valid = refl_data > 5

    cmap = mcolors.LinearSegmentedColormap.from_list('radar',
        ['#00000000','#04e9e7','#019ff4','#0300f4','#02fd02','#01c501','#008e00',
         '#fdf802','#e5bc00','#fd9500','#fd0000','#d40000','#bc0000','#f800fd','#9854c6','#fdfdfd'], N=256)
    cmap_snow = mcolors.LinearSegmentedColormap.from_list('snow',
        ['#00000000','#b3e5fc','#81d4fa','#4fc3f7','#29b6f6','#039be5','#0277bd',
         '#01579b','#e1bee7','#ce93d8','#ab47bc','#8e24aa','#6a1b9a','#4a148c','#e0e0e0','#ffffff'], N=256)
    cmap_frzr = mcolors.LinearSegmentedColormap.from_list('frzr',
        ['#00000000','#fce4ec','#f8bbd0','#f48fb1','#f06292','#ec407a','#e91e63',
         '#d81b60','#c2185b','#ad1457','#880e4f','#ff6f00','#ff8f00','#ffa000','#ffb300','#ffffff'], N=256)
    cmap_ice = mcolors.LinearSegmentedColormap.from_list('ice',
        ['#00000000','#e8eaf6','#c5cae9','#9fa8da','#7986cb','#5c6bc0','#3f51b5',
         '#3949ab','#303f9f','#283593','#1a237e','#b388ff','#7c4dff','#651fff','#6200ea','#ffffff'], N=256)

    rgba_rain = cmap(refl_norm)
    rgba_snow = cmap_snow(refl_norm)
    rgba_frzr = cmap_frzr(refl_norm)
    rgba_ice  = cmap_ice(refl_norm)

    final = np.copy(rgba_rain)
    snow_mask = (cs > 0.5) & mask_valid
    frzr_mask = (cf > 0.5) & mask_valid
    ice_mask  = (ci > 0.5) & mask_valid
    final[snow_mask] = rgba_snow[snow_mask]
    final[frzr_mask] = rgba_frzr[frzr_mask]
    final[ice_mask]  = rgba_ice[ice_mask]
    final[:, :, 3] = np.where(mask_valid, 0.92, 0)

    img_full = Image.fromarray((final * 255).astype(np.uint8), 'RGBA')
    if refl_lats.ndim == 2:
        img_out = img_full
    else:
        img_out = img_full.resize((BASE['img_width_hires'],
                                   BASE['img_height_hires']), Image.BILINEAR)
    img_out.save(ptype_path, 'PNG', optimize=True)
    return True


# =============================================================================
# CENTROS DE PRESIÓN (bajas y altas con su valor, para rotularlos en el visor)
# =============================================================================
def detectar_centros(prmsl_pa, lats, lons, max_por_tipo=25):
    """Bajas y altas del campo PRMSL (en pascales). La detección vive en
    centros_presion.py para que GFS, ECMWF y HRRR pinten lo mismo."""
    return centros_presion.detectar(np.asarray(prmsl_pa, dtype='float32') / 100.0,
                                    lats, lons, max_por_tipo)


# =============================================================================
# RENDER ISOBARS (contornos de presión MSLP)
# =============================================================================
def render_isobars(prmsl_pa, lats, lons, output_path, needs_reproject=False):
    """Renderiza isobaras como líneas de contorno PNG transparente.
    Líneas cada 4 mb, etiquetadas, color rojo para >1016 mb (alta) y azul <1012 mb (baja).
    """
    field = prmsl_pa / 100.0  # Pa → mb
    field = np.where(np.isnan(field), 1013.25, field)

    if needs_reproject and lats.ndim == 2:
        field = reproject_cached(field, lats, lons, BASE['img_height'], BASE['img_width'])

    # Suavizado leve para mejor estética de contornos
    try:
        from scipy.ndimage import gaussian_filter
        field = gaussian_filter(field, sigma=1.5)
    except Exception:
        pass

    out_w, out_h = BASE['img_width'], BASE['img_height']
    fig = plt.figure(figsize=(out_w / 100, out_h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, field.shape[1])
    ax.set_ylim(field.shape[0], 0)
    ax.axis('off')
    fig.patch.set_alpha(0)

    levels_low  = np.arange(960, 1013, 4)
    levels_high = np.arange(1016, 1056, 4)
    levels_mid  = [1012, 1013, 1014, 1015]

    # Rojo: alta (≥1016)
    cs_high = ax.contour(field, levels=levels_high, colors='#c62828', linewidths=1.0)
    ax.clabel(cs_high, inline=True, fontsize=7, fmt='%d', colors='#c62828')
    # Azul: baja (≤1012)
    cs_low = ax.contour(field, levels=levels_low, colors='#1565c0', linewidths=1.0)
    ax.clabel(cs_low, inline=True, fontsize=7, fmt='%d', colors='#1565c0')
    # Gris: rango medio
    cs_mid = ax.contour(field, levels=levels_mid, colors='#616161', linewidths=0.7,
                        linestyles='dashed')

    fig.savefig(output_path, dpi=100, transparent=True, bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    return True


# =============================================================================
# UPLOAD
# =============================================================================
def upload(filepath, cdn_key, content_type='image/png'):
    # Los frames (image/*) son inmutables dentro de un ciclo y el cliente los pide
    # con ?v=<ciclo>, así que pueden cachearse más tiempo (no se re-descargan en
    # una sesión de antena larga). El manifest (json) es el ancla de frescura y el
    # cliente lo pide con ?ts → TTL corto para que el ciclo nuevo se vea enseguida.
    cache = 'max-age=3600' if content_type.startswith('image/') else 'max-age=600'
    if content_type.startswith('application/json') and 'charset' not in content_type:
        content_type += '; charset=utf-8'   # W-1 Studio Pro (Windows decodifica ANSI sin charset)
    # boto3 en proceso: el CLI de aws costaba ~1-2 s de CPU por spawn y este
    # pipeline sube cientos de PNGs por run (limpieza de carga del 26/07)
    try:
        if not hasattr(upload, '_c'):
            import boto3
            upload._c = boto3.Session(profile_name=BASE['aws_profile']).client(
                's3', endpoint_url=BASE['cdn_endpoint'])
        upload._c.upload_file(str(filepath), BASE['cdn_bucket'], cdn_key,
                              ExtraArgs={'ACL': 'public-read',
                                         'ContentType': content_type,
                                         'CacheControl': cache})
        return True
    except Exception as e:
        # Antes callaba: en una máquina sin credenciales salían «0 PNGs» sin
        # decir por qué (23/09). El primer fallo de cada tipo se avisa una vez.
        clave = type(e).__name__
        vistos = upload.__dict__.setdefault('_avisados', set())
        if clave not in vistos:
            vistos.add(clave)
            log.warning(f'    subida al CDN fallando ({clave}): {str(e)[:120]}')
        return False


# =============================================================================
# PROCESS HOUR
# =============================================================================
def process_hour(model_cfg, date, cycle, fhour, cycle_dt, accum_dir=None):
    """Process one forecast hour."""
    t0 = time.time()
    model_id = model_cfg['name'].lower()
    valid_dt = cycle_dt + timedelta(hours=fhour)
    hour_imgs = {}
    hour_points = {}
    img_dir = f"/opt/canalmeteo/data/{model_id}/images"
    Path(img_dir).mkdir(parents=True, exist_ok=True)

    # ── DOWNLOAD all groups ──
    all_fields = {}
    total_bytes = 0
    apcp1h_src = None  # (valores_mm, lats, lons) del APCP de 1 h (para precipIn)
    apcp_acum = None   # ventana que TESELA con el paso de esta hora (1 h o 6 h)
    apcp_acum_win = 0
    snow_bucket = None  # (nieve_in del tramo en curso) — GFS, ver gfs_snow_accum
    for group in model_cfg['groups']:
        grib_path, nbytes, gname = download_group(model_cfg, date, cycle, fhour, group)
        total_bytes += nbytes
        if grib_path:
            fields = extract_fields(grib_path, model_cfg['fields'], group_name=gname)
            all_fields.update(fields)
            # Acumulado: APCP de 1 h (presente en TODAS las horas y ciclos del NBM;
            # las ventanas de 6 h/12 h solo existen en ciclos sinópticos 00/06/12/18).
            if (model_cfg.get('accumulate_precip') and group['name'] == 'sfc'
                    and apcp1h_src is None):
                apcp1h_src = extract_apcp_window(grib_path, 1)
                if apcp1h_src[0] is not None and fhour <= 48:
                    apcp_acum, apcp_acum_win = apcp1h_src, 1
                # Pasada la hora 48 el NBM salta a pasos de 3 y 6 h: hora a hora ya
                # no se puede sumar y el acumulado se quedaba en 48 h. Con la
                # ventana de 6 h los tramos siguen TESELANDO exacto (48→54→…→264),
                # así que la lluvia acumulada llega al final de la corrida.
                if fhour > 48 and fhour % 6 == 0:
                    w6 = extract_apcp_window(grib_path, 6)
                    if w6[0] is not None:
                        apcp_acum, apcp_acum_win = w6, 6
            if model_cfg.get('snow_from_csnow') and group['name'] == 'sfc' and fhour > 0:
                snow_bucket = extract_gfs_snow_bucket(grib_path, fhour)
            try: os.remove(grib_path)
            except Exception: pass

    if not all_fields:
        return None

    log.info(f"    Downloaded: {total_bytes//1024} KB · Fields: {list(all_fields.keys())}")

    # ── FIX precipIn (NBM): el GRIB del NBM trae 'tp' como PROBABILIDAD (pdt=9,
    #    0-100 %) y como acumulación determinista (pdt=8, mm). cfgrib.open_datasets
    #    fusiona mal ambos y extract_fields se queda con la PROBABILIDAD → precipIn
    #    salía como "muro de lluvia" (0-100 mm → ~0-4 in uniformes). Sustituimos el
    #    'tp' por el APCP de 1 h que ya extrajimos con filtro correcto (pdt=8). ──
    if model_cfg.get('accumulate_precip'):
        if apcp1h_src and apcp1h_src[0] is not None:
            all_fields['tp'] = apcp1h_src
        else:
            all_fields.pop('tp', None)  # sin determinista fiable: no pintar probabilidad

    # ── Lluvia del tramo → .npy en accum_dir (el merge SUMA los tramos → precipAccum).
    #    La ventana va en el nombre para que el merge sepa si tesela sin huecos. ──
    if model_cfg.get('accumulate_precip') and accum_dir and apcp_acum and apcp_acum[0] is not None:
        try:
            vals, alats, alons = apcp_acum
            field_in = CONVERTERS['precipIn'](np.asarray(vals, dtype=float))  # mm → in (clip neg)
            if hasattr(alats, 'ndim') and alats.ndim == 2:
                field_in = reproject_cached(field_in, alats, alons,
                                            BASE['img_height'], BASE['img_width'])
            np.save(os.path.join(accum_dir,
                                 f"{model_id}_apcpw{apcp_acum_win:02d}_f{fhour:03d}.npy"),
                    np.asarray(field_in, dtype=np.float32))
        except Exception as e:
            log.warning(f"    apcp acumulado save: {e}")

    # ── Tmax/Tmin diario (NBM nativo, ventanas 12 h) → .npy para el merge ──
    # Cada GRIB con ventana max/min trae solo uno (TMAX en las ventanas diurnas
    # que acaban en 00Z, TMIN en las nocturnas que acaban en 12Z). Los sacamos de
    # all_fields para que NO entren al loop de render/GeoJSON; el merge los agrupa
    # por día, resta la normal y construye los mapas de anomalía hoy/mañana/pasado.
    for short in ('tmax', 'tmin'):
        if short not in all_fields:
            continue
        d, la, lo = all_fields.pop(short)
        if accum_dir:
            try:
                t_F = (d - 273.15) * 9 / 5 + 32
                if hasattr(la, 'ndim') and la.ndim == 2:
                    t_F = reproject_cached(t_F, la, lo,
                                           BASE['img_height'], BASE['img_width'])
                np.save(os.path.join(accum_dir, f"{model_id}_{short}_f{fhour:03d}.npy"),
                        np.asarray(t_F, dtype=np.float32))
                log.info(f"    {short} f{fhour:03d} → npy (ventana 12 h)")
            except Exception as e:
                log.warning(f"    {short} f{fhour:03d} npy: {e}")

    # ── DERIVED: viento de superficie (10m) desde UGRD/VGRD ──
    if 'u10' in all_fields and 'v10' in all_fields:
        u_data, u_lats, u_lons = all_fields['u10']
        v_data, _, _ = all_fields['v10']
        wspd = np.sqrt(u_data**2 + v_data**2)
        wdir = (270 - np.degrees(np.arctan2(v_data, u_data))) % 360
        all_fields['_wspd'] = (wspd, u_lats, u_lons)
        all_fields['_wdir'] = (wdir, u_lats, u_lons)
        model_cfg['fields']['_wspd'] = 'wspdMph'
        model_cfg['fields']['_wdir'] = 'wdir'

    # ── DERIVED 14/09/2026: nieve acumulada HRRR (ASNOW m → in) y viento 80 m ──
    if 'asnow' in all_fields:
        a, la, lo = all_fields.pop('asnow')
        all_fields['_snowAccum'] = (np.clip(np.nan_to_num(a), 0, None) * 39.3701, la, lo)
        model_cfg['fields']['_snowAccum'] = 'snowAccum'
    if 'u80' in all_fields and 'v80' in all_fields:
        u, la, lo = all_fields.pop('u80')
        v, _, _ = all_fields.pop('v80')
        all_fields['_wind80'] = (np.sqrt(u**2 + v**2), la, lo)
        model_cfg['fields']['_wind80'] = 'wind80Mph'
    # ── DERIVED 26/09/2026: lluvia acumulada GFS (suma de tramos de 6 h) ──
    if model_id == 'gfs' and fhour > 0 and 'tp' in all_fields:
        try:
            tp_mm, la, lo = all_fields['tp']
            tramo_in = CONVERTERS['precipIn'](np.nan_to_num(np.asarray(tp_mm, dtype='float32')))
            total_in = gfs_rain_accum(date, cycle, fhour, tramo_in)
            all_fields['_precipAccum'] = (total_in, la, lo)
            model_cfg['fields']['_precipAccum'] = 'precipAccum'
        except Exception as e:
            log.warning(f"    lluvia acumulada GFS: {e}")

    # ── DERIVED 14/09/2026: nieve acumulada GFS (10:1) ──
    if snow_bucket is not None and 'tp' in all_fields:
        _, la, lo = all_fields['tp']
        if snow_bucket.shape == all_fields['tp'][0].shape:
            total = gfs_snow_accum(date, cycle, fhour, snow_bucket)
            all_fields['_snowAccum'] = (total, la, lo)
            model_cfg['fields']['_snowAccum'] = 'snowAccum'

    # ── DERIVED: jet 250 mb (magnitud del viento) ──
    if 'u250' in all_fields and 'v250' in all_fields:
        u, lt, ln = all_fields['u250']
        v, _, _ = all_fields['v250']
        jet = np.sqrt(u**2 + v**2)
        all_fields['_jet250'] = (jet, lt, ln)
        model_cfg['fields']['_jet250'] = 'jet250'

    # ── DERIVED: viento 850 mb (magnitud) ──
    if 'u850' in all_fields and 'v850' in all_fields:
        u, lt, ln = all_fields['u850']
        v, _, _ = all_fields['v850']
        w850 = np.sqrt(u**2 + v**2)
        all_fields['_wind850'] = (w850, lt, ln)
        model_cfg['fields']['_wind850'] = 'wind850'

    # ── DERIVED: temperatura 850 mb (renombre directo) ──
    if 't850' in all_fields:
        model_cfg['fields']['t850'] = 'temp850C'

    # ── DERIVED: EHI 0-3 km = CAPE×SRH/160000 (Baron parity 22.12) ──
    if 'cape' in all_fields and 'hlcy' in all_fields:
        c_data, c_lats, c_lons = all_fields['cape']
        s_data, _, _ = all_fields['hlcy']
        if c_data.shape == s_data.shape:
            ehi = np.clip(c_data, 0, None) * s_data / 160000.0
            all_fields['_ehi'] = (ehi, c_lats, c_lons)
            model_cfg['fields']['_ehi'] = 'ehi'

    # ── DERIVED: anomalía de temperatura ──
    anom_src = model_cfg.get('compute_anomaly_from')
    if anom_src and anom_src in all_fields:
        t_data, t_lats, t_lons = all_fields[anom_src]
        # Convertir a °F primero
        t_F = (t_data - 273.15) * 9/5 + 32
        # Reproyectar si Lambert
        # El campo NATIVO va directo: compute_temp_anomaly ya reproyecta al grid
        # de la climatologia (KDTree cacheado). Pasar el campo regrillado con las
        # lats/lons nativas descuadraba los indices (IndexError, caida 2026-08-14).
        anom = compute_temp_anomaly(t_F, t_lats, t_lons, valid_dt)
        if anom is not None:
            # Las coords ya son grid regular del tamaño de la climatología
            lat_reg = np.linspace(BASE['lat_max'], BASE['lat_min'], anom.shape[0])
            lon_reg = np.linspace(BASE['lon_min'], BASE['lon_max'], anom.shape[1])
            all_fields['_tempAnom'] = (anom, lat_reg, lon_reg)
            model_cfg['fields']['_tempAnom'] = 'tempAnom'

    # ── PROCESS each field (PNG + GeoJSON points) ──
    for grib_field, (data, lats, lons) in all_fields.items():
        if grib_field not in model_cfg['fields']:
            continue
        var_name = model_cfg['fields'][grib_field]
        if var_name not in CONVERTERS:
            continue
        convert_fn = (CONVERTERS_MODELO.get(model_id) or {}).get(
            var_name, CONVERTERS[var_name])

        # GeoJSON points (no derivadas globales)
        gjstep = 20
        if var_name not in {'tempAnom', 'jet250', 'wind850', 'temp850C', 'uphlMax', 'ehi'}:
            if lats.ndim == 2:
                for iy in range(0, lats.shape[0], gjstep):
                    for ix in range(0, lats.shape[1], gjstep):
                        la, lo = float(lats[iy, ix]), float(lons[iy, ix])
                        if lo > 180: lo -= 360
                        if la < BASE['lat_min'] or la > BASE['lat_max']: continue
                        if lo < BASE['lon_min'] or lo > BASE['lon_max']: continue
                        val = float(data[iy, ix])
                        if np.isnan(val): continue
                        cv = convert_fn(val)
                        if hasattr(cv, '__len__'): cv = float(cv)
                        key = (round(la, 2), round(lo, 2))
                        if key not in hour_points: hour_points[key] = {}
                        hour_points[key][var_name] = round(float(cv), 1)
            elif lats.ndim == 1 and lats.size > 1 and lons.size > 1:
                # Malla regular (GFS): paso ~0.5° y solo índices dentro de bounds
                res = abs(float(lats[1]) - float(lats[0]))
                step = max(1, int(round(0.5 / max(res, 1e-6))))
                lon_vals = np.where(lons > 180, lons - 360, lons)
                lat_idx = [i for i in range(0, lats.size, step)
                           if BASE['lat_min'] <= float(lats[i]) <= BASE['lat_max']]
                lon_idx = [j for j in range(0, lons.size, step)
                           if BASE['lon_min'] <= float(lon_vals[j]) <= BASE['lon_max']]
                for iy in lat_idx:
                    la = round(float(lats[iy]), 2)
                    for ix in lon_idx:
                        val = float(data[iy, ix])
                        if np.isnan(val): continue
                        cv = convert_fn(val)
                        if hasattr(cv, '__len__'): cv = float(cv)
                        key = (la, round(float(lon_vals[ix]), 2))
                        if key not in hour_points: hour_points[key] = {}
                        hour_points[key][var_name] = round(float(cv), 1)

        # Render PNG
        needs_reproj = (lats.ndim == 2) or (model_cfg['name'] in ('HRRR', 'HRRR_EXT'))
        png_path = os.path.join(img_dir, f"{model_id}_{var_name}_f{fhour:03d}.png")
        if render_png(data, lats, lons, var_name, convert_fn, png_path,
                      needs_reproject=needs_reproj):
            cdn_key = frames_runs.clave(model_id, frames_runs.run_id(date, cycle), f"{model_id}_{var_name}_f{fhour:03d}.png")
            if upload(png_path, cdn_key):
                hour_imgs[var_name] = f"{BASE['cdn_base']}/{cdn_key}"

    # ── GeoJSON de puntos por hora (valores "123" del visor) ──
    # hour_points se muestreaba pero dejó de subirse en el refactor
    # subprocess-per-hour (los _fNNN.json del CDN quedaron congelados en abril).
    if hour_points:
        feats = [{'type': 'Feature',
                  'geometry': {'type': 'Point', 'coordinates': [lo, la]},
                  'properties': props}
                 for (la, lo), props in hour_points.items()]
        gj = {'type': 'FeatureCollection',
              'properties': {'fhour': fhour, 'validTime': valid_dt.isoformat(),
                             'validTimeUnix': int(valid_dt.timestamp())},
              'features': feats}
        gj_path = os.path.join(img_dir, f"{model_id}_f{fhour:03d}.json")
        with open(gj_path, 'w') as f:
            json.dump(gj, f, separators=(',', ':'))
        upload(gj_path, frames_runs.clave(model_id, frames_runs.run_id(date, cycle), f"{model_id}_f{fhour:03d}.json"), 'application/json')

    # ── ISOBARAS (contornos de PRMSL) ──
    if model_cfg.get('render_isobars') and 'prmsl' in all_fields:
        try:
            p_data, p_lats, p_lons = all_fields['prmsl']
            iso_path = os.path.join(img_dir, f"{model_id}_isobaras_f{fhour:03d}.png")
            if render_isobars(p_data, p_lats, p_lons, iso_path,
                              needs_reproject=(p_lats.ndim == 2)):
                cdn_key = frames_runs.clave(model_id, frames_runs.run_id(date, cycle), f"{model_id}_isobaras_f{fhour:03d}.png")
                if upload(iso_path, cdn_key):
                    hour_imgs['isobaras'] = f"{BASE['cdn_base']}/{cdn_key}"
                    log.info(f"    ✅ isobaras")
        except Exception as e:
            log.warning(f"    isobaras error: {e}")

    # ── CENTROS DE PRESIÓN (bajas/altas con su valor) ──
    if 'prmsl' in all_fields:
        try:
            p_data, p_lats, p_lons = all_fields['prmsl']
            centros = detectar_centros(p_data, p_lats, p_lons)
            if centros:
                c_path = os.path.join(img_dir, f"{model_id}_centros_f{fhour:03d}.json")
                with open(c_path, 'w') as fh:
                    json.dump({'model': model_id, 'fhour': fhour, 'centros': centros},
                              fh, separators=(',', ':'))
                cdn_key = frames_runs.clave(model_id, frames_runs.run_id(date, cycle),
                                            f"{model_id}_centros_f{fhour:03d}.json")
                if upload(c_path, cdn_key, 'application/json'):
                    hour_imgs['centros'] = f"{BASE['cdn_base']}/{cdn_key}"
                    n_b = sum(1 for c in centros if c['tipo'] == 'baja')
                    log.info(f"    ✅ centros: {n_b} baja(s), {len(centros) - n_b} alta(s)")
        except Exception as e:
            log.warning(f"    centros error: {e}")

    # ── PRECIP TYPE composite (existente) ──
    refl_data = None; refl_lats = refl_lons = None
    for rkey in ['refd1km', 'reflectivity']:
        gf = [k for k, v in model_cfg['fields'].items() if v == rkey]
        for gk in gf:
            if gk in all_fields:
                refl_data, refl_lats, refl_lons = all_fields[gk]
                break
        if refl_data is not None: break

    has_ptype = all(k in all_fields for k in ['crain', 'csnow', 'cfrzr', 'cicep']
                    if k in model_cfg['fields'].keys())

    if refl_data is not None and has_ptype:
        try:
            cr = all_fields.get('crain', (np.zeros_like(refl_data),))[0]
            cs = all_fields.get('csnow', (np.zeros_like(refl_data),))[0]
            cf = all_fields.get('cfrzr', (np.zeros_like(refl_data),))[0]
            ci = all_fields.get('cicep', (np.zeros_like(refl_data),))[0]

            ptype_path = os.path.join(img_dir, f"{model_id}_ptypeRefl_f{fhour:03d}.png")
            render_ptype_refl(refl_data, refl_lats, refl_lons, cr, cs, cf, ci, ptype_path)
            cdn_key = frames_runs.clave(model_id, frames_runs.run_id(date, cycle), f"{model_id}_ptypeRefl_f{fhour:03d}.png")
            if upload(ptype_path, cdn_key):
                hour_imgs['ptypeRefl'] = f"{BASE['cdn_base']}/{cdn_key}"
                log.info(f"    ✅ ptypeRefl")
        except Exception as e:
            log.warning(f"    ptypeRefl error: {e}")

    elapsed = time.time() - t0
    log.info(f"    f{fhour:03d}: {len(hour_imgs)} PNGs · {elapsed:.0f}s")

    if hour_imgs:
        # W-20.4 (03/10): `valid_utc`, `lead_min` y `cycle` por fotograma, con
        # los mismos nombres que en las rejillas. La interpolación del Studio
        # necesita confirmar que los dos fotogramas son de la MISMA pasada, y
        # hasta ahora había que deducirlo de la etiqueta.
        return {'fhour': fhour, 'validTime': valid_dt.isoformat(),
                'validTimeUnix': int(valid_dt.timestamp()),
                'valid_utc': valid_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'lead_min': int(fhour * 60), 'cycle': f'{date}{cycle}',
                'images': hour_imgs}
    return None


# =============================================================================
# MAIN
# =============================================================================
def acquire_internal_lock(model_id):
    """Lock interno (independiente del de flock) para detectar ejecuciones simultáneas
    aunque el lock externo no esté activo."""
    import fcntl
    lock_path = f"/tmp/canalmeteo_model_{model_id}.lock"
    try:
        lock_file = open(lock_path, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(f"{os.getpid()}\n")
        lock_file.flush()
        return lock_file
    except (IOError, OSError):
        log.error(f"⛔ Otro proceso ya está ejecutando model_pipeline para {model_id}")
        log.error(f"   Lock: {lock_path}")
        log.error(f"   Si estás seguro de que no hay otro proceso, borra el archivo.")
        sys.exit(1)


def _horizonte(model_cfg):
    """Hasta dónde puede llegar ESTE modelo, no hasta dónde llega el ciclo de hoy.
    26/09/2026: el NBM lo declara en dos listas (78 h en los ciclos cortos, 264 en
    los largos) y el merge pasaba la CORTA a `manifest_relleno`, así que un ciclo
    de 120 h se daba por completo y sustituía al de 264: la línea de tiempo se
    caía de once días a cinco cada vez que entraba un ciclo no sinóptico."""
    return max(model_cfg.get('forecast_hours_largo') or model_cfg['forecast_hours'])


def _build_manifest(model_cfg, date, cycle, manifest_hours, full=True):
    """Construye el dict del manifest final."""
    base = {
        'model': model_cfg['name'], 'version': 'raster-v5',
        'cycle': f"{date}/{cycle}z",
        'generated': datetime.now(timezone.utc).isoformat(),
        # OJO (#27 app): estos PNG van en retícula lat/lon LINEAL entre bounds,
        # NO en Mercator — el consumidor debe reproyectar (la app lo hace).
        'projection': 'EPSG:4326',
        'bounds': {'north': BASE['lat_max'], 'south': BASE['lat_min'],
                   'east': BASE['lon_max'], 'west': BASE['lon_min']},
    }
    # 23/09: `variables` era el catálogo ENTERO de RENDER_VARS para todos los
    # modelos, así que el NBM declaraba 56 y publicaba 9, y el GFS 57 y 20. El
    # Studio ofrecía en el menú variables que ese modelo no da nunca. Ahora solo
    # salen las que de verdad tienen imagen en alguna hora del ciclo.
    publicadas = {v for h in (manifest_hours or []) for v in (h.get('images') or {})}
    vars_modelo = {k: v for k, v in RENDER_VARS.items() if k in publicadas} \
        if publicadas else RENDER_VARS
    if full:
        base['variables'] = {k: {'label': v['label'], 'unit': v['unit'],
                                 'vmin': v['vmin'], 'vmax': v['vmax'],
                                 'colors': v['colors']}
                             for k, v in vars_modelo.items()}
    else:
        base['variables'] = {k: {'label': v['label'], 'unit': v['unit'],
                                 'vmin': v['vmin'], 'vmax': v['vmax']}
                             for k, v in vars_modelo.items()}
    # Rejillas numéricas que acompañan a algún PNG (hoy solo la lluvia acumulada):
    # el visor las lee para dar el valor exacto en un punto. Misma malla y mismos
    # `bounds` que las imágenes, filas de norte a sur.
    if any((h.get('values') or {}) for h in (manifest_hours or [])):
        base['values_grid'] = {'nx': BASE['img_width'], 'ny': BASE['img_height'],
                               'dtype': 'uint16-le', 'encoding': 'gzip',
                               'scale': ACUM_ESCALA, 'offset': ACUM_OFFSET,
                               'missing': ACUM_MISSING,
                               'order': 'row-major norte→sur, oeste→este',
                               'bounds': dict(base['bounds'])}
    base['hours'] = manifest_hours
    return base


# =============================================================================
# SUB-HORARIO (15 min) — wrfsubhf vía filtro NOMADS _sub
# =============================================================================
# El fichero wrfsubhfNN contiene 4 pasos apilados (NN-1:15, :30, :45, :60).
# cfgrib los expone como UN dataset con eje 'step' de tamaño 4 (timedelta64[ns]).
# Indexamos [0]=+15, [1]=+30, [2]=+45 y descartamos [3]=+60 (ya es el frame horario).
SUBH_FILTER = 'https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_sub.pl'

# Solo estos grupos tienen sentido a 15 min (lo que de verdad luce en animación).
# REFC + viento 10m + TMP 2m + PRATE (precip rate, surface).
SUBH_GROUPS = [
    {'name': 'refc', 'params': 'var_REFC=on&lev_entire_atmosphere=on'},
    {'name': '10m',  'params': 'var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on'},
    {'name': '2m',   'params': 'var_TMP=on&lev_2_m_above_ground=on'},
]
# Minutos intermedios a renderizar (no el :60, que es el horario)
SUBH_MINUTES = [15, 30, 45]


def download_group_subh(model_cfg, date, cycle, fhour, group):
    """Descarga un wrfsubhf filtrado (igual que download_group pero filtro _sub)."""
    data_dir = f"/opt/canalmeteo/data/{model_cfg['name'].lower()}"
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    outpath = os.path.join(data_dir,
        f"{model_cfg['name'].lower()}_subh_{group['name']}_{date}_{cycle}z_f{fhour:03d}.grib2")

    lw = BASE['lon_min'] + (360 if model_cfg['lon_360'] else 0)
    le = BASE['lon_max'] + (360 if model_cfg['lon_360'] else 0)
    dir_path = model_cfg['dir_tmpl'].format(dd=date, cc=cycle)
    fname = f"hrrr.t{cycle}z.wrfsubhf{fhour:02d}.grib2"

    url = (f"{SUBH_FILTER}?dir=%2F{dir_path.lstrip('/')}&file={fname}&"
           f"{group['params']}&subregion=&toplat={BASE['lat_max']}&leftlon={lw}&"
           f"rightlon={le}&bottomlat={BASE['lat_min']}")
    try:
        r = requests.get(url, timeout=120, headers={'User-Agent': BASE['user_agent']})
        if r.status_code == 200 and len(r.content) > 500:
            with open(outpath, 'wb') as f:
                f.write(r.content)
            return outpath, len(r.content), group['name']
    except Exception as e:
        log.warning(f"    subh {group['name']}: {e}")
    return None, 0, group['name']


def _extract_subh_step(grib_path, field_map, step_idx):
    """Como extract_fields pero indexando el eje 'step' (sub-horario)."""
    found = {}
    try:
        for ds in cfgrib.open_datasets(grib_path):
            for fname in ds.data_vars:
                vals = ds[fname].values
                # vals tiene forma (4, ny, nx) en sub-horario; tomamos el paso pedido
                if vals.ndim == 3:
                    if step_idx >= vals.shape[0]:
                        continue
                    data = vals[step_idx]
                elif vals.ndim == 2:
                    data = vals
                else:
                    continue
                if fname in field_map and fname not in found:
                    found[fname] = (data, ds.latitude.values, ds.longitude.values)
    except Exception as e:
        log.warning(f"    cfgrib subh: {e}")
    return found


def process_subh_block(model_cfg, date, cycle, fhour, cycle_dt):
    """Procesa los 3 sub-pasos (:15/:30/:45) del bloque de la hora fhour.

    Devuelve lista de dicts result, uno por minuto, con:
      - fhour float (ej. 1.25, 1.5, 1.75)
      - min  (15/30/45)
      - images {var: url}
    Reusa render_png + colormaps + upload del pipeline horario.
    """
    import gc
    model_id = model_cfg['name'].lower()
    img_dir = f"/opt/canalmeteo/data/{model_id}/images"
    Path(img_dir).mkdir(parents=True, exist_ok=True)

    # Descargar cada grupo sub-horario UNA vez (trae los 4 steps dentro)
    grib_by_group = {}
    total_bytes = 0
    for group in SUBH_GROUPS:
        gp, nbytes, gname = download_group_subh(model_cfg, date, cycle, fhour, group)
        total_bytes += nbytes
        if gp:
            grib_by_group[gname] = gp
    if not grib_by_group:
        log.warning(f"[subh] f{fhour:03d}: sin descargas")
        return []

    results = []
    for step_idx, mins in enumerate(SUBH_MINUTES):
        # fhour fraccionario: hora del bloque - 1 + minuto/60
        # wrfsubhf02 → bloque hora 2 → +1:15,1:30,1:45 → fhour 1.25/1.5/1.75
        frac = (fhour - 1) + mins / 60.0
        valid_dt = cycle_dt + timedelta(hours=frac)

        all_fields = {}
        for gname, gp in grib_by_group.items():
            all_fields.update(_extract_subh_step(gp, model_cfg['fields'], step_idx))

        if not all_fields:
            continue

        # Derivar viento de superficie igual que el horario
        if 'u10' in all_fields and 'v10' in all_fields:
            u_data, u_lats, u_lons = all_fields['u10']
            v_data, _, _ = all_fields['v10']
            wspd = np.sqrt(u_data**2 + v_data**2)
            wdir = (270 - np.degrees(np.arctan2(v_data, u_data))) % 360
            all_fields['_wspd'] = (wspd, u_lats, u_lons)
            all_fields['_wdir'] = (wdir, u_lats, u_lons)
            model_cfg['fields']['_wspd'] = 'wspdMph'
            model_cfg['fields']['_wdir'] = 'wdir'

        hour_imgs = {}
        suffix = f"{fhour-1:03d}_{mins:02d}"  # ej "001_15"
        for grib_field, (data, lats, lons) in all_fields.items():
            if grib_field not in model_cfg['fields']:
                continue
            var_name = model_cfg['fields'][grib_field]
            if var_name not in CONVERTERS:
                continue
            convert_fn = CONVERTERS[var_name]
            needs_reproj = (lats.ndim == 2) or (model_cfg['name'] in ('HRRR', 'HRRR_EXT'))
            png_path = os.path.join(img_dir, f"{model_id}_{var_name}_f{suffix}.png")
            if render_png(data, lats, lons, var_name, convert_fn, png_path,
                          needs_reproject=needs_reproj):
                cdn_key = frames_runs.clave(model_id, frames_runs.run_id(date, cycle), f"{model_id}_{var_name}_f{suffix}.png")
                if upload(png_path, cdn_key):
                    hour_imgs[var_name] = f"{BASE['cdn_base']}/{cdn_key}"

        if hour_imgs:
            results.append({
                'fhour': round(frac, 2),
                'min': mins,
                'subh': True,
                'valid': valid_dt.isoformat(),
                'validTime': valid_dt.isoformat(),
                'validTimeUnix': int(valid_dt.timestamp()),
                'images': hour_imgs,
            })

    # Limpieza de GRIBs sub-horarios
    for gp in grib_by_group.values():
        try: os.remove(gp)
        except Exception: pass
    log.info(f"[subh] bloque f{fhour:03d}: {total_bytes//1024} KB → {len(results)} sub-frames")
    gc.collect()
    return results


def _run_subh_hour(model_cfg, date, cycle, fhour, output_dir):
    """Genera los sub-frames de un bloque y escribe un hour_*.json por minuto."""
    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    load_climatology()
    t0 = time.time()
    results = process_subh_block(model_cfg, date, cycle, fhour, cycle_dt)
    if not results:
        log.warning(f"[subh-hour] f{fhour:03d}: sin resultados")
        return 1
    model_id = model_cfg['name'].lower()
    for res in results:
        # nombre: hour_<hora-1>_<min>.json → ordena bien en el glob del merge
        tag = f"{int(fhour-1):03d}_{res['min']:02d}"
        out_path = os.path.join(output_dir, f"{model_id}_hour_{tag}.json")
        with open(out_path, 'w') as f:
            json.dump(res, f)
    log.info(f"[subh-hour] f{fhour:03d}: ✓ {time.time()-t0:.1f}s → {len(results)} sub-frames")
    return 0


def _run_merge_subh(model_cfg, output_dir, subh_dir):
    """Merge fusionado: frames horarios (output_dir) + sub-horarios (subh_dir).

    Lee el ciclo del manifest horario YA subido para garantizar que horario y
    sub-horario son del mismo ciclo. Si no hay manifest horario, aborta sin tocar nada.
    """
    import glob as _glob
    model_id = model_cfg['name'].lower()

    manifest_path = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
    try:
        with open(manifest_path) as f:
            cur = json.load(f)
        cycle_str = cur.get('cycle', '')  # "YYYYMMDD/HHz"
    except Exception as e:
        log.error(f"[merge-subh] No hay manifest horario para fusionar: {e}")
        return 2

    hourly = []
    for fp in sorted(_glob.glob(os.path.join(output_dir, f"{model_id}_hour_*.json"))):
        try:
            with open(fp) as f:
                hourly.append(json.load(f))
        except Exception as e:
            log.warning(f"[merge-subh] horario {fp}: {e}")

    subh = []
    for fp in sorted(_glob.glob(os.path.join(subh_dir, f"{model_id}_hour_*.json"))):
        try:
            with open(fp) as f:
                subh.append(json.load(f))
        except Exception as e:
            log.warning(f"[merge-subh] subh {fp}: {e}")

    if not hourly:
        log.error("[merge-subh] Sin frames horarios; no se fusiona")
        return 3

    combined = hourly + subh
    # Deduplicar por fhour (última gana) para evitar frames repetidos
    _by_fh = {}
    for _h in combined:
        _by_fh[_h.get('fhour')] = _h
    combined = list(_by_fh.values())
    combined.sort(key=lambda h: h.get('fhour', 0))

    date, cycle = cycle_str.split('/') if '/' in cycle_str else (None, None)
    cycle = (cycle or '').rstrip('z')
    manifest = _build_manifest(model_cfg, date, cycle, combined, full=True)
    frames_grid.anotar(manifest, model_id)   # W-2 Studio Pro: variables.<var>.grid
    manifest['run'] = frames_runs.run_id(date, cycle)   # 30.2 Studio: frames en runs/<run>/
    frames_runs.purgar(model_id)                           # conserva 2 pasadas
    tmp = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
    with open(tmp, 'w') as f:
        json.dump(manifest, f, separators=(',', ':'))
    if upload(tmp, f"data/{model_id}/{model_id}_manifest.json", 'application/json'):
        log.info(f"✅ [merge-subh] Manifest fusionado: {len(hourly)} horarios + {len(subh)} sub-frames")
        return 0
    log.error("[merge-subh] Fallo al subir manifest fusionado")
    return 4


def _run_single_hour(model_cfg, date, cycle, fhour, output_dir):
    """Procesa una sola hora y guarda el dict result en output_dir/{model}_hour_NNN.json"""
    import gc
    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    load_climatology()
    log.info(f"[single-hour] Procesando f{fhour:03d} para ciclo {date}/{cycle}z")
    t0 = time.time()
    result = process_hour(model_cfg, date, cycle, fhour, cycle_dt, accum_dir=output_dir)
    if result is None:
        log.warning(f"[single-hour] f{fhour:03d}: sin resultado")
        return 1
    model_id = model_cfg['name'].lower()
    out_path = os.path.join(output_dir, f"{model_id}_hour_{fhour:03d}.json")
    with open(out_path, 'w') as f:
        json.dump(result, f)
    log.info(f"[single-hour] f{fhour:03d}: ✓ {time.time()-t0:.1f}s → {out_path}")
    gc.collect()
    return 0


def _inject_precip_accum(model_cfg, manifest_hours, output_dir, run=None):
    """Suma los tramos de APCP (SIN multiplicar) en una lluvia acumulada monótona
    desde f000 y la publica como 'precipAccum' en cada múltiplo de 6 h.

    Los .npy que deja `process_hour` llevan su ventana en el nombre
    (`<modelo>_apcpw01_f012.npy` = tramo de 1 h que acaba en f012), y aquí solo se
    encadenan los que TESELAN sin huecos ni solapes: `fh - ventana == anterior`.
    Así el NBM suma de 1 h hasta f048 y de 6 h de f048 en adelante, y la lluvia
    acumulada llega al final de la corrida en vez de pararse a las 48 h.
    (Nunca extrapolar 1 h × dt en los tramos espaciados: sobrestimaba ~3×.)

    26/09/2026 — la URL se escribe TAMBIÉN en el `<modelo>_hour_NNN.json`. Los
    .npy se borran al usarlos, así que los merges siguientes (el NBM rehace el
    manifest cada hora) acumulaban 0 y publicaban un manifest SIN precipAccum: la
    variable aparecía y desaparecía sola. Guardada en la hora, ya no se pierde."""
    import glob as _glob
    import re as _re
    model_id = model_cfg['name'].lower()
    img_dir = f"/opt/canalmeteo/data/{model_id}/images"
    Path(img_dir).mkdir(parents=True, exist_ok=True)
    lats1d = np.linspace(BASE['lat_max'], BASE['lat_min'], BASE['img_height'])
    lons1d = np.linspace(BASE['lon_min'], BASE['lon_max'], BASE['img_width'])

    ventanas = {}
    for fp in _glob.glob(os.path.join(output_dir, f"{model_id}_apcpw*_f*.npy")):
        m = _re.search(rf"{model_id}_apcpw(\d+)_f(\d+)\.npy$", fp)
        if m:
            ventanas[int(m.group(2))] = (int(m.group(1)), fp)

    accum = None
    prev_fh = 0
    n = 0
    for h in manifest_hours:
        fh = h.get('fhour')
        if fh is None or fh not in ventanas:
            continue
        win, npy = ventanas[fh]
        if fh - win != prev_fh:
            continue                    # no tesela con lo acumulado: este tramo no vale
        try:
            tramo_in = np.clip(np.nan_to_num(np.load(npy)), 0, None)   # lluvia del tramo (in)
        except Exception:
            continue
        accum = tramo_in if accum is None else accum + tramo_in
        prev_fh = fh
        try:
            os.remove(npy)
        except OSError:
            pass
        if fh % 6 != 0:
            continue  # acumulamos cada tramo, pero solo publicamos los múltiplos de 6
        png = os.path.join(img_dir, f"{model_id}_precipAccum_f{fh:03d}.png")
        if render_png(accum.copy(), lats1d, lons1d, 'precipAccum',
                      lambda x: x, png, needs_reproject=False):
            key = (frames_runs.clave(model_id, run, f"{model_id}_precipAccum_f{fh:03d}.png") if run
                   else f"data/{model_id}/{model_id}_precipAccum_f{fh:03d}.png")
            if upload(png, key):
                url = f"{BASE['cdn_base']}/{key}"
                h.setdefault('images', {})['precipAccum'] = url
                _guarda_imagen_en_hora(output_dir, model_id, fh, 'precipAccum', url)
                n += 1
                rej = _sube_rejilla_accum(model_id, run, fh, accum)
                if rej:
                    h.setdefault('values', {})['precipAccum'] = rej
                    _guarda_imagen_en_hora(output_dir, model_id, fh, 'precipAccum', rej,
                                           seccion='values')
    log.info(f"[merge] precipAccum: {n} hora(s) acumuladas"
             f"{f' (hasta f{prev_fh:03d})' if n else ''}")
    propias = [{'t': int(h['validTimeUnix']), 'img': h['images']['precipAccum'],
                'val': (h.get('values') or {}).get('precipAccum')}
               for h in manifest_hours
               if h.get('validTimeUnix') and (h.get('images') or {}).get('precipAccum')
               and not h.get('precipAccumRun')]
    if propias:
        _guarda_accum_largo(model_id, run, propias)
    _rellena_accum_previo(model_id, run, manifest_hours)


# Rejilla numérica que acompaña a cada PNG de lluvia acumulada (26/09/2026).
# El visor la lee para dar el valor exacto en un punto («consultar valores»). Antes
# tiraba de `data/models/<m>/apcp`, que va por su cuenta, con su propio ciclo y su
# propio horizonte: en cuanto los dos no coincidían el número era de otra pasada o
# no había. Esta sale del MISMO array que se acaba de pintar.
ACUM_ESCALA, ACUM_OFFSET, ACUM_MISSING = 0.01, 0.0, 65535


def _sube_rejilla_accum(model_id, run, fh, accum):
    """Sube el acumulado como uint16-le gzip y devuelve su URL (None si falla)."""
    import gzip
    raw = np.clip(np.nan_to_num(accum, nan=-1) / ACUM_ESCALA, -1, 65534)
    raw = np.where(raw < 0, ACUM_MISSING, np.round(raw)).astype('<u2')
    nombre = f'{model_id}_precipAccum_f{fh:03d}.bin.gz'
    ruta = f"/opt/canalmeteo/data/{model_id}/images/{nombre}"
    try:
        with gzip.open(ruta, 'wb', compresslevel=6) as f:
            f.write(raw.tobytes())
        key = (frames_runs.clave(model_id, run, nombre) if run
               else f'data/{model_id}/{nombre}')
        if upload(ruta, key, 'application/gzip'):
            return f"{BASE['cdn_base']}/{key}"
    except Exception as e:
        log.warning(f"[merge] rejilla acumulada f{fh:03d}: {e}")
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
    return None


def _ficha_accum(model_id):
    return f"/opt/canalmeteo/data/{model_id}/precipAccum_ultimo.json"


def _lee_accum_guardado(model_id):
    try:
        with open(_ficha_accum(model_id)) as f:
            d = json.load(f)
        return d if d.get('frames') else None
    except (OSError, ValueError):
        return None


def _guarda_accum_largo(model_id, run, frames):
    """Guarda la cadena de acumulado más LARGA (en hora de validez) que tengamos.
    Solo los ciclos sinópticos del NBM traen la ventana de APCP de 6 h, así que la
    de 00/06/12/18z llega a f264 y la de 03z se queda en f048: si el corto pisara
    el registro, el relleno desaparecería hasta el siguiente sinóptico."""
    if not frames:
        return
    ant = _lee_accum_guardado(model_id)
    if ant and ant.get('run') != run and max(f['t'] for f in ant['frames']) > max(f['t'] for f in frames):
        return
    try:
        p = _ficha_accum(model_id)
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'run': run, 'frames': frames}, f)
        os.replace(tmp, p)
    except Exception as e:
        log.warning(f"[merge] no se pudo guardar el acumulado largo: {e}")


def _rellena_accum_previo(model_id, run, manifest_hours, _hasta_fh=None):
    """Horas a las que este ciclo no llega: se les pone el fotograma de la última
    pasada que sí llegó, buscado por HORA DE VALIDEZ y tomando siempre el ANTERIOR
    o igual (nunca enseñar más lluvia de la que ha caído a esa hora). Es el mismo
    criterio de relleno entre ciclos que ya usa `manifest_relleno` con el resto de
    variables. Devuelve cuántas rellenó.

    Solo se rellena DESPUÉS de la última hora propia y en la misma cadencia de 6 h:
    intercalar fotogramas de otra pasada entre los propios rompería la progresión
    (los de la pasada anterior llevan unas horas más de lluvia acumulada)."""
    rec = _lee_accum_guardado(model_id)
    if not rec or rec.get('run') == run or str(rec.get('run', '')) > str(run):
        return 0
    propias = [h.get('fhour') for h in manifest_hours
               if (h.get('images') or {}).get('precipAccum') and not h.get('precipAccumRun')
               and h.get('fhour') is not None]
    ultima = max(propias) if propias else 0
    frames = sorted(rec['frames'], key=lambda f: f['t'])
    n = 0
    for h in manifest_hours:
        fh = h.get('fhour')
        t = int(h.get('validTimeUnix') or 0)
        if fh is None or not t or fh <= ultima or fh % 6:
            continue
        if (h.get('images') or {}).get('precipAccum'):
            continue
        cand = None
        for f in frames:
            if f['t'] <= t:
                cand = f
            else:
                break
        if not cand or t - cand['t'] > 3 * 3600:
            continue
        h.setdefault('images', {})['precipAccum'] = cand['img']
        if cand.get('val'):
            h.setdefault('values', {})['precipAccum'] = cand['val']
        h['precipAccumRun'] = rec['run']      # el visor puede avisar de que es de otra pasada
        # Hora de validez REAL del fotograma prestado: va hasta 3 h por detrás de
        # la de esta hora, y sin ella la consulta por punto buscaría el número en
        # la hora equivocada (o no lo encontraría).
        h['precipAccumValid'] = cand['t']
        n += 1
    if n:
        log.info(f"[merge] precipAccum: {n} hora(s) rellenadas con la pasada {rec['run']}")
    return n


def _guarda_imagen_en_hora(output_dir, model_id, fh, var, url, seccion='images'):
    """Fija una imagen en el <modelo>_hour_NNN.json para que sobreviva a los
    merges posteriores, que se construyen SOLO con esos ficheros."""
    fp = os.path.join(output_dir, f"{model_id}_hour_{fh:03d}.json")
    try:
        with open(fp) as f:
            hora = json.load(f)
        if hora.setdefault(seccion, {}).get(var) == url:
            return
        hora[seccion][var] = url
        tmp = fp + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(hora, f)
        os.replace(tmp, fp)
    except Exception as e:
        log.warning(f"[merge] no se pudo fijar {var} en f{fh:03d}: {e}")


_DAY_LABELS_REL = {0: 'Hoy', 1: 'Mañana', 2: 'Pasado mañana'}
_WEEKDAYS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


def _rel_day_label(target_date, today):
    """Etiqueta corta relativa: Hoy / Mañana / Pasado mañana / día de la semana."""
    delta = (target_date - today).days
    if delta in _DAY_LABELS_REL:
        return _DAY_LABELS_REL[delta]
    return _WEEKDAYS_ES[target_date.weekday()]


def _inject_daily_temp_anomaly(model_cfg, date, cycle, output_dir):
    """Construye los mapas CONUS de anomalía de Tmax/Tmin diaria (NBM nativo).

    El NBM publica TMAX/TMIN en ventanas de 12 h alineadas a 00Z (diurnas) y 12Z
    (nocturnas), que coinciden con día/noche en CONUS. Cada hora con esos campos
    dejó un .npy en output_dir. Aquí:
      1) Agrupamos por DÍA (no por orden): cada TMAX → su fecha diurna; cada TMIN
         → la fecha del día cuya noche representa (madrugada - 1 día). Así el
         máximo del día N se empareja con la mínima de esa misma noche, sea cual
         sea el ciclo (00/06/12/18z u horario).
      2) Restamos la normal 1991-2020 (día-del-año del centro de la ventana).
      3) Renderizamos hoy/mañana/pasado (d0/d1/d2) con la paleta divergente.

    Devuelve la lista 'daily' para el manifest (o [] si no hay datos/climatología).
    """
    import glob as _glob
    from zoneinfo import ZoneInfo

    model_id = model_cfg['name'].lower()
    img_dir = f"/opt/canalmeteo/data/{model_id}/images"
    Path(img_dir).mkdir(parents=True, exist_ok=True)
    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)

    clim = {'tmaxAnom': load_climatology_var('tmax_F'),
            'tminAnom': load_climatology_var('tmin_F')}
    if clim['tmaxAnom'] is False and clim['tminAnom'] is False:
        log.warning("[merge] Sin climatología tmax/tmin — se omite anomalía diaria")
        return []

    central = ZoneInfo('America/Chicago')   # referencia CONUS para etiquetar días
    today_ref = cycle_dt.astimezone(central).date()

    # collected: date(local) → {render_var: anom_array}
    collected = {}
    for kind, render_var in (('tmax', 'tmaxAnom'), ('tmin', 'tminAnom')):
        cl = clim[render_var]
        if cl is False:
            continue
        npys = sorted(_glob.glob(os.path.join(output_dir, f"{model_id}_{kind}_f*.npy")),
                      key=lambda p: int(p.rsplit('_f', 1)[1][:3]))
        for npy in npys:
            try:
                fh = int(npy.rsplit('_f', 1)[1][:3])
            except (ValueError, IndexError):
                continue
            valid_dt = cycle_dt + timedelta(hours=fh)        # fin de la ventana 12 h
            mid_dt = valid_dt - timedelta(hours=6)           # centro de la ventana
            mid_local = mid_dt.astimezone(central)
            if kind == 'tmax':
                panel_date = mid_local.date()
            else:
                # La ventana nocturna (madrugada del día D) pertenece al panel D-1.
                panel_date = (mid_local - timedelta(days=1)).date()
            doy = min(mid_dt.timetuple().tm_yday - 1, cl.shape[0] - 1)
            try:
                fcst = np.load(npy)
            except Exception as e:
                log.warning(f"[merge] no se pudo leer {npy}: {e}")
                continue
            finally:
                try: os.remove(npy)
                except OSError: pass
            if fcst.shape != cl.shape[1:]:
                # #28.1: el npy sale a img_height×img_width (800×1800) pero la
                # climatología sigue en 260×590 — reescalar antes de restar.
                from PIL import Image as PILImage
                img = PILImage.fromarray(fcst.astype(np.float32), mode='F')
                fcst = np.array(img.resize((cl.shape[2], cl.shape[1]),
                                           PILImage.BILINEAR))
            collected.setdefault(panel_date, {})[render_var] = fcst - cl[doy]

    if not collected:
        log.info("[merge] anomalía diaria: sin .npy de tmax/tmin")
        return []

    # Días a publicar: desde hoy (TZ central), los 3 primeros con CUALQUIER dato.
    # No exigimos máxima: en ciclos de tarde/noche la ventana de máxima de HOY ya
    # pasó y el NBM no la emite, pero SÍ hay mínima de esta noche → el panel "Hoy"
    # debe salir igual (con tminAnom y sin tmaxAnom). El frontend tolera que falte
    # cualquiera de las dos capas.
    sel_dates = sorted(d for d in collected if d >= today_ref)[:3]

    lats1d = np.linspace(BASE['lat_max'], BASE['lat_min'], BASE['img_height'])
    lons1d = np.linspace(BASE['lon_min'], BASE['lon_max'], BASE['img_width'])

    daily = []
    for di, pdate in enumerate(sel_dates):
        entry = {'index': di, 'date': pdate.isoformat(),
                 'label_es': _rel_day_label(pdate, today_ref)}
        for render_var, anom in sorted(collected[pdate].items()):
            png = os.path.join(img_dir, f"{model_id}_{render_var}_d{di}.png")
            if render_png(anom.copy(), lats1d, lons1d, render_var, lambda x: x, png,
                          needs_reproject=False):
                key = frames_runs.clave(model_id, frames_runs.run_id(date, cycle), f"{model_id}_{render_var}_d{di}.png")
                if upload(png, key):
                    entry[render_var] = f"{BASE['cdn_base']}/{key}"
        daily.append(entry)

    log.info(f"[merge] anomalía diaria: {len(daily)} día(s) "
             f"[{', '.join(d['label_es'] for d in daily)}]")
    return daily


def _run_merge_manifest(model_cfg, date, cycle, output_dir):
    """Lee todos los hour_NNN.json del output_dir, construye y sube manifest."""
    import glob as _glob
    model_id = model_cfg['name'].lower()
    pattern = os.path.join(output_dir, f"{model_id}_hour_*.json")
    files = sorted(_glob.glob(pattern))
    log.info(f"[merge] Encontrados {len(files)} archivos de horas en {output_dir}")
    manifest_hours = []
    for fp in files:
        try:
            with open(fp) as f:
                manifest_hours.append(json.load(f))
        except Exception as e:
            log.warning(f"[merge] No se pudo leer {fp}: {e}")
    if not manifest_hours:
        log.error("[merge] Sin horas válidas, no se sube manifest")
        return 2
    # Ordenar por fhour por si acaso
    manifest_hours.sort(key=lambda h: h.get('fhour', 0))
    # Lluvia acumulada (si el modelo lo activa). Aislado: si falla, el manifest
    # sale igual que antes, solo sin precipAccum.
    if model_cfg.get('accumulate_precip'):
        try:
            _inject_precip_accum(model_cfg, manifest_hours, output_dir,
                                 run=frames_runs.run_id(date, cycle))
        except Exception as e:
            log.warning(f"[merge] acumulado de precipitación falló (se omite): {e}")
    # Anomalía diaria de Tmax/Tmin (hoy/mañana/pasado). Aislado: si falla, el
    # manifest sale igual, solo sin la sección 'daily'.
    daily = []
    if model_cfg.get('daily_temp_anomaly'):
        try:
            daily = _inject_daily_temp_anomaly(model_cfg, date, cycle, output_dir)
        except Exception as e:
            log.warning(f"[merge] anomalía diaria falló (se omite): {e}")
    manifest = _build_manifest(model_cfg, date, cycle, manifest_hours, full=True)
    if daily:
        manifest['daily'] = daily
    frames_grid.anotar(manifest, model_id)   # W-2 Studio Pro: variables.<var>.grid
    manifest['run'] = frames_runs.run_id(date, cycle)   # 30.2 Studio: frames en runs/<run>/
    frames_runs.purgar(model_id)                           # conserva 2 pasadas
    tmp = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    manifest = manifest_relleno.componer(manifest, tmp, _horizonte(model_cfg))
    if manifest is None:
        log.info("⏸️ [merge] el ciclo nuevo cubre menos que el publicado — se mantiene el manifest")
        return 0
    with open(tmp, 'w') as f:
        json.dump(manifest, f, separators=(',', ':'))
    if upload(tmp, f"data/{model_id}/{model_id}_manifest.json", 'application/json'):
        total = sum(len(h.get('images', {})) for h in manifest_hours)
        log.info(f"✅ [merge] Manifest subido: {len(manifest_hours)} horas, {total} imágenes")
        return 0
    else:
        log.error("[merge] Fallo al subir manifest")
        return 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='nbm', choices=['nbm', 'gfs', 'hrrr', 'hrrr_ext'])
    parser.add_argument('--detect-cycle', action='store_true',
                        help='Imprime "DATE CYCLE" del último ciclo y sale')
    parser.add_argument('--single-hour', type=int, default=None,
                        help='Procesa solo esta hora de pronóstico')
    parser.add_argument('--merge-subh', action='store_true',
                        help='Fusiona frames horarios + sub-horarios en un manifest')
    parser.add_argument('--subh-dir', default='/tmp/hrrr_subh',
                        help='Directorio de los sub-frames (para --merge-subh)')
    parser.add_argument('--subh-hour', type=int, default=None,
                        help='Genera los sub-frames de 15 min del bloque de esta hora (1-18)')
    parser.add_argument('--merge-manifest', action='store_true',
                        help='Lee output-dir, construye y sube manifest final')
    parser.add_argument('--date', default=None, help='YYYYMMDD (usar con single-hour/merge)')
    parser.add_argument('--cycle', default=None, help='HH (usar con single-hour/merge)')
    parser.add_argument('--output-dir', default='/tmp/nbm_hours',
                        help='Directorio para los json por hora')
    args = parser.parse_args()

    model_cfg = MODELS[args.model]
    global _current_model_name
    _current_model_name = model_cfg['name']
    model_id = model_cfg['name'].lower()

    # #28 Studio: resolución de PNG POR MODELO. NBM (2,5 km) y HRRR (3 km)
    # iban capados al 590×260 global (~11 km/px, borroso a encuadre estatal);
    # GFS 0,25° se queda como está (ya sobra). Mutar BASE aquí vale porque
    # cada run es un proceso por modelo.
    if 'img_width' in model_cfg:
        BASE['img_width'] = model_cfg['img_width']
        BASE['img_height'] = model_cfg['img_height']

    # --- Modo: detect-cycle ---
    if args.detect_cycle:
        date, cycle = find_latest_cycle(model_cfg)
        if not date:
            sys.exit(1)
        print(f"{date} {cycle}")
        return

    # --- Modo: single-hour ---
    if args.single_hour is not None:
        if not args.date or not args.cycle:
            log.error("--single-hour requiere --date y --cycle")
            sys.exit(2)
        os.makedirs(args.output_dir, exist_ok=True)
        sys.exit(_run_single_hour(model_cfg, args.date, args.cycle,
                                  args.single_hour, args.output_dir))

    # --- Modo: merge-subh (fusion horario + subhorario) ---
    if args.merge_subh:
        sys.exit(_run_merge_subh(model_cfg, args.output_dir, args.subh_dir))

    # --- Modo: subh-hour ---
    if args.subh_hour is not None:
        if not args.date or not args.cycle:
            log.error("--subh-hour requiere --date y --cycle")
            sys.exit(2)
        sys.exit(_run_subh_hour(model_cfg, args.date, args.cycle,
                                args.subh_hour, args.output_dir))

    # --- Modo: merge-manifest ---
    if args.merge_manifest:
        if not args.date or not args.cycle:
            log.error("--merge-manifest requiere --date y --cycle")
            sys.exit(2)
        sys.exit(_run_merge_manifest(model_cfg, args.date, args.cycle, args.output_dir))

    # --- Modo legacy: todas las horas en un solo proceso (NO RECOMENDADO para NBM) ---
    _lock_handle = acquire_internal_lock(model_id)
    t_start = time.time()
    log.info("=" * 50)
    log.info(f"Model Pipeline v5 — {model_cfg['name']} — Canal Meteo TV [LEGACY ALL-IN-ONE]")
    log.info("=" * 50)
    date, cycle = find_latest_cycle(model_cfg)
    if not date:
        log.error("No cycle available"); return
    # 15/09/2026: el cron reintenta en cuanto NOAA publica (GFS); no rehacer un ciclo
    # ya publicado (tolera 2 horas fallidas para no entrar en bucle)
    try:
        with open(f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json") as _f:
            _prev = json.load(_f)
        import re as _re
        _pub = _re.sub(r'\D', '', str(_prev.get('run') or _prev.get('cycle') or ''))[:10]
        if _pub and _pub > f"{date}{cycle}":
            log.info(f"{model_cfg['name']} {date}/{cycle}z es anterior al publicado ({_pub}) — nada que hacer")
            return
        if (_prev.get('cycle') == f"{date}/{cycle}z"
                and len(manifest_relleno.horas_propias(_prev)) >= len(model_cfg['forecast_hours']) - 2):
            log.info(f"{model_cfg['name']} {date}/{cycle}z ya publicado — nada que hacer")
            return
    except Exception:
        pass
    cycle_dt = datetime.strptime(f"{date}{cycle}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    manifest_hours = []
    forecast_hours = model_cfg['forecast_hours']
    load_climatology()

    for i, fh in enumerate(forecast_hours):
        log.info(f"--- f{fh:03d} ({i+1}/{len(forecast_hours)}) ---")
        try:
            result = process_hour(model_cfg, date, cycle, fh, cycle_dt)
            if result:
                manifest_hours.append(result)
        except Exception as e:
            log.error(f"  ❌ f{fh:03d} falló: {e} — continuando con la siguiente hora")
            import traceback
            log.debug(traceback.format_exc())

        # Free memory
        import gc, glob
        for g in glob.glob(f"/opt/canalmeteo/data/{model_id}/*.grib2"):
            try: os.remove(g)
            except Exception: pass
        for g in glob.glob(f"/opt/canalmeteo/data/{model_id}/*.idx"):
            try: os.remove(g)
            except Exception: pass

        # Liberar KDTree cache si crece demasiado (evita OOM en runs largos)
        global _kdtree_cache
        if len(_kdtree_cache) > 2:
            _kdtree_cache.clear()
        try:
            import matplotlib.pyplot as plt
            plt.close('all')
        except Exception: pass
        gc.collect()
        gc.collect()
        if i > 0 and i % 10 == 0:
            try:
                import resource
                mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                log.info(f"    [mem] RSS peak: {mb:.0f} MB despues de {i+1} horas")
            except Exception: pass

        # Partial manifest cada 12 horas
        if manifest_hours and (i + 1) % 12 == 0:
            partial = _build_manifest(model_cfg, date, cycle, [dict(h) for h in manifest_hours], full=True)
            frames_grid.anotar(partial, model_id)
            partial['run'] = frames_runs.run_id(date, cycle)
            mpath = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
            partial = manifest_relleno.componer(partial, mpath, _horizonte(model_cfg))
            if partial is None:
                log.info(f"  ⏸️ Parcial de {len(manifest_hours)} horas más corto que el publicado: se mantiene")
            else:
                with open(mpath, 'w') as f:
                    json.dump(partial, f, separators=(',', ':'))
                upload(mpath, f"data/{model_id}/{model_id}_manifest.json", 'application/json')
                log.info(f"  📤 Manifest parcial: {len(manifest_hours)} horas + relleno del ciclo anterior")
        time.sleep(1)

    if manifest_hours:
        manifest = _build_manifest(model_cfg, date, cycle, manifest_hours, full=True)
        frames_grid.anotar(manifest, model_id)   # W-2 Studio Pro: variables.<var>.grid
        manifest['run'] = frames_runs.run_id(date, cycle)   # 30.2 Studio: frames en runs/<run>/
        frames_runs.purgar(model_id)                           # conserva 2 pasadas
        tmp = f"/opt/canalmeteo/data/{model_id}/{model_id}_manifest.json"
        manifest = manifest_relleno.componer(manifest, tmp, _horizonte(model_cfg))
        if manifest is None:
            log.info(f"⏸️ {model_cfg['name']}: el ciclo nuevo cubre menos que el publicado — se mantiene")
            return
        with open(tmp, 'w') as f:
            json.dump(manifest, f, separators=(',', ':'))
        if upload(tmp, f"data/{model_id}/{model_id}_manifest.json", 'application/json'):
            total = sum(len(h['images']) for h in manifest_hours)
            log.info(f"✅ {model_cfg['name']}: {total} images, {len(manifest_hours)} hours "
                     f"in {time.time()-t_start:.0f}s")


if __name__ == '__main__':
    main()
