#!/usr/bin/env python3
"""
Borrasca - GFS Data Processor
=============================
Descarga datos GRIB2 del modelo GFS de NOAA NOMADS,
los procesa y genera tiles PNG para el visualizador.

Uso:
    python fetch_gfs.py              # Procesa todas las variables
    python fetch_gfs.py temp-2m      # Solo temperatura 2m
    python fetch_gfs.py --hours 48   # Solo hasta hora 48

Cron (ejecutar después de cada run GFS, ~4h después):
    30 4,10,16,22 * * * /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/borrasca/fetch_gfs.py >> /var/log/borrasca/gfs.log 2>&1
"""

import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import tempfile

import numpy as np
import requests

# Importar configuración de Borrasca
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    setup_logger, upload_to_spaces, get_spaces_url,
    DATA_DIR, download_binary
)

# Intentar importar librerías de procesamiento
try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False
    print("Warning: xarray not installed. Install with: pip install xarray cfgrib")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: Pillow not installed. Install with: pip install Pillow")

# Logger
logger = setup_logger('gfs', 'gfs.log')

# =============================================
# CONFIGURACIÓN GFS
# =============================================

# Variables disponibles
GFS_VARIABLES = {
    'temp-2m': {
        'name': 'Temperatura 2m',
        'filter_level': 'lev_2_m_above_ground=on',
        'filter_var': 'var_TMP=on',
        'grib_key': 't2m',
        'unit': '°C',
        'kelvin_offset': -273.15,
        'range': (-40, 50),
        'colormap': 'temperature'
    },
    'temp-850': {
        'name': 'Temperatura 850 hPa',
        'filter_level': 'lev_850_mb=on',
        'filter_var': 'var_TMP=on',
        'grib_key': 't',
        'unit': '°C',
        'kelvin_offset': -273.15,
        'range': (-40, 40),
        'colormap': 'temperature'
    },
    'temp-500': {
        'name': 'Temperatura 500 hPa',
        'filter_level': 'lev_500_mb=on',
        'filter_var': 'var_TMP=on',
        'grib_key': 't',
        'unit': '°C',
        'kelvin_offset': -273.15,
        'range': (-60, 10),
        'colormap': 'temperature'
    },
    'wind-10m': {
        'name': 'Viento 10m',
        'filter_level': 'lev_10_m_above_ground=on',
        'filter_var': 'var_UGRD=on&var_VGRD=on',
        'grib_key': 'wind',
        'unit': 'kt',
        'is_wind': True,
        'range': (0, 80),
        'colormap': 'wind'
    },
    'wind-250': {
        'name': 'Jet Stream 250 hPa',
        'filter_level': 'lev_250_mb=on',
        'filter_var': 'var_UGRD=on&var_VGRD=on',
        'grib_key': 'wind',
        'unit': 'kt',
        'is_wind': True,
        'range': (0, 200),
        'colormap': 'wind'
    },
    'precip': {
        'name': 'Precipitación Acumulada',
        'filter_level': 'lev_surface=on',
        'filter_var': 'var_APCP=on',
        'grib_key': 'tp',
        'unit': 'mm',
        'range': (0, 100),
        'colormap': 'precipitation'
    },
    'mslp': {
        'name': 'Presión Nivel del Mar',
        'filter_level': 'lev_mean_sea_level=on',
        'filter_var': 'var_PRMSL=on',
        'grib_key': 'prmsl',
        'unit': 'hPa',
        'scale': 0.01,  # Pa a hPa
        'range': (960, 1050),
        'colormap': 'pressure'
    },
    'rh-2m': {
        'name': 'Humedad Relativa 2m',
        'filter_level': 'lev_2_m_above_ground=on',
        'filter_var': 'var_RH=on',
        'grib_key': 'r2',
        'unit': '%',
        'range': (0, 100),
        'colormap': 'humidity'
    },
    'clouds': {
        'name': 'Nubosidad Total',
        'filter_level': 'lev_entire_atmosphere_%5C%28considered_as_a_single_layer%5C%29=on',
        'filter_var': 'var_TCDC=on',
        'grib_key': 'tcc',
        'unit': '%',
        'range': (0, 100),
        'colormap': 'clouds'
    },
    'geopot-500': {
        'name': 'Geopotencial 500 hPa',
        'filter_level': 'lev_500_mb=on',
        'filter_var': 'var_HGT=on',
        'grib_key': 'gh',
        'unit': 'dam',
        'scale': 0.1,  # m a dam
        'range': (480, 600),
        'colormap': 'geopotential'
    },
}

# Horas de pronóstico
DEFAULT_FORECAST_HOURS = list(range(0, 121, 3))  # 0 a 120 cada 3h

# Bounds CONUS
CONUS_BOUNDS = {
    'west': -130,
    'east': -60,
    'south': 20,
    'north': 55
}


# =============================================
# COLORMAPS
# =============================================

def create_colormap(name: str, n: int = 256) -> np.ndarray:
    """Genera un colormap como array numpy."""
    
    colormaps = {
        'temperature': [
            (49, 54, 149),    # -40°C azul oscuro
            (69, 117, 180),   # azul
            (116, 173, 209),  # azul claro
            (171, 217, 233),  # celeste
            (224, 243, 248),  # casi blanco
            (254, 224, 144),  # amarillo claro
            (253, 174, 97),   # naranja claro
            (244, 109, 67),   # naranja
            (215, 48, 39),    # rojo
            (165, 0, 38)      # rojo oscuro
        ],
        'wind': [
            (200, 230, 200),  # verde muy claro
            (144, 238, 144),  # verde claro
            (255, 255, 0),    # amarillo
            (255, 165, 0),    # naranja
            (255, 69, 0),     # rojo-naranja
            (255, 0, 0),      # rojo
            (139, 0, 139)     # morado
        ],
        'precipitation': [
            (255, 255, 255),  # blanco (sin precip)
            (166, 242, 143),  # verde claro
            (60, 179, 113),   # verde
            (30, 144, 255),   # azul
            (0, 0, 205),      # azul oscuro
            (148, 0, 211),    # violeta
            (255, 20, 147)    # rosa
        ],
        'humidity': [
            (139, 90, 43),    # marrón (seco)
            (210, 180, 140),  # beige
            (255, 255, 255),  # blanco
            (173, 216, 230),  # azul claro
            (0, 100, 200)     # azul
        ],
        'clouds': [
            (255, 255, 255),  # blanco
            (220, 220, 220),  # gris muy claro
            (180, 180, 180),  # gris claro
            (140, 140, 140),  # gris
            (100, 100, 100)   # gris oscuro
        ],
        'pressure': [
            (75, 0, 130),     # índigo (baja)
            (0, 0, 255),      # azul
            (0, 128, 0),      # verde
            (255, 255, 0),    # amarillo
            (255, 140, 0)     # naranja (alta)
        ],
        'geopotential': [
            (49, 54, 149),
            (116, 173, 209),
            (224, 243, 248),
            (253, 174, 97),
            (215, 48, 39)
        ]
    }
    
    colors = np.array(colormaps.get(name, colormaps['temperature']), dtype=np.float32)
    
    # Interpolar a n valores
    result = np.zeros((n, 3), dtype=np.uint8)
    for i in range(n):
        pos = i * (len(colors) - 1) / (n - 1)
        idx = int(pos)
        frac = pos - idx
        
        if idx >= len(colors) - 1:
            result[i] = colors[-1]
        else:
            result[i] = (colors[idx] * (1 - frac) + colors[idx + 1] * frac).astype(np.uint8)
    
    return result


# =============================================
# FUNCIONES GFS
# =============================================

def get_latest_gfs_run() -> Tuple[datetime, str]:
    """
    Determina el último run disponible del GFS.
    Runs: 00, 06, 12, 18 UTC. Disponible ~4h después.
    """
    from config import utcnow
    now = utcnow()
    available_time = now - timedelta(hours=4)
    
    hour = (available_time.hour // 6) * 6
    run_time = available_time.replace(hour=hour, minute=0, second=0, microsecond=0)
    run_str = f"{hour:02d}"
    
    return run_time, run_str


def build_gfs_filter_url(run_date: datetime, run_hour: str, fhr: int, 
                         var_config: dict) -> str:
    """Construye URL del filtro NOMADS."""
    date_str = run_date.strftime('%Y%m%d')
    file_name = f"gfs.t{run_hour}z.pgrb2.0p25.f{fhr:03d}"
    
    base_url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
    
    params = [
        f"file={file_name}",
        var_config['filter_level'],
        var_config['filter_var'],
        "subregion=",
        f"leftlon={CONUS_BOUNDS['west']}",
        f"rightlon={CONUS_BOUNDS['east']}",
        f"toplat={CONUS_BOUNDS['north']}",
        f"bottomlat={CONUS_BOUNDS['south']}",
        f"dir=/gfs.{date_str}/{run_hour}/atmos"
    ]
    
    return f"{base_url}?{'&'.join(params)}"


def download_gfs_grib(url: str, output_path: Path) -> bool:
    """Descarga archivo GRIB2."""
    logger.info(f"Descargando: {url[:80]}...")
    
    try:
        data = download_binary(url, timeout=180)
        if data and len(data) > 100:  # Verificar que no esté vacío
            with open(output_path, 'wb') as f:
                f.write(data)
            logger.info(f"Descargado: {output_path.name} ({len(data)/1024:.1f} KB)")
            return True
        else:
            logger.error(f"Archivo vacío o error en descarga")
            return False
    except Exception as e:
        logger.error(f"Error descargando: {e}")
        return False


def process_grib_to_png(grib_path: Path, var_config: dict) -> Optional[bytes]:
    """Procesa GRIB2 a PNG coloreado."""
    if not HAS_XARRAY or not HAS_PIL:
        logger.error("Requiere xarray y Pillow instalados")
        return None
    
    try:
        # Abrir GRIB
        ds = xr.open_dataset(grib_path, engine='cfgrib')
        
        # Obtener datos
        var_names = list(ds.data_vars)
        
        # Manejar viento (combinar U y V)
        if var_config.get('is_wind'):
            u_var = [v for v in var_names if 'u' in v.lower()][0]
            v_var = [v for v in var_names if 'v' in v.lower()][0]
            u = ds[u_var].values
            v = ds[v_var].values
            data = np.sqrt(u**2 + v**2) * 1.94384  # m/s a nudos
        else:
            data = ds[var_names[0]].values
            
            # Conversiones
            if 'kelvin_offset' in var_config:
                data = data + var_config['kelvin_offset']
            if 'scale' in var_config:
                data = data * var_config['scale']
        
        ds.close()
        
        # Manejar dimensiones extra
        while data.ndim > 2:
            data = data[0]
        
        # Normalizar a 0-255
        vmin, vmax = var_config['range']
        data_norm = np.clip((data - vmin) / (vmax - vmin), 0, 1)
        data_uint8 = (data_norm * 255).astype(np.uint8)
        
        # Aplicar colormap
        colormap = create_colormap(var_config['colormap'])
        rgb = colormap[data_uint8]
        
        # Crear imagen (flip vertical para orientación correcta)
        img = Image.fromarray(rgb, mode='RGB')
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        
        # Escalar a mayor resolución con interpolación suave
        # GFS 0.25° es ~720x360, escalamos a 2880x1440 (4x)
        original_size = img.size
        target_size = (original_size[0] * 4, original_size[1] * 4)
        img = img.resize(target_size, Image.Resampling.LANCZOS)
        
        # Guardar a bytes
        from io import BytesIO
        buffer = BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Error procesando GRIB: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_variable(var_key: str, run_date: datetime, run_hour: str,
                    forecast_hours: List[int]) -> int:
    """
    Procesa una variable para todas las horas de pronóstico.
    Returns: número de frames procesados exitosamente
    """
    var_config = GFS_VARIABLES[var_key]
    logger.info(f"\n{'='*50}")
    logger.info(f"Procesando: {var_config['name']}")
    logger.info(f"{'='*50}")
    
    success_count = 0
    date_str = run_date.strftime('%Y%m%d')
    
    for fhr in forecast_hours:
        try:
            # Construir URL
            url = build_gfs_filter_url(run_date, run_hour, fhr, var_config)
            
            # Descargar a archivo temporal
            with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as tmp:
                tmp_path = Path(tmp.name)
            
            if not download_gfs_grib(url, tmp_path):
                continue
            
            # Procesar a PNG
            png_data = process_grib_to_png(tmp_path, var_config)
            
            # Limpiar temporal
            tmp_path.unlink(missing_ok=True)
            
            if png_data is None:
                continue
            
            # Subir a Spaces
            remote_path = f"gfs/{date_str}/{run_hour}/{var_key}/f{fhr:03d}.png"
            
            if upload_to_spaces(png_data, remote_path, 'image/png', 'max-age=3600'):
                logger.info(f"✅ Subido: {var_key} f{fhr:03d}")
                success_count += 1
            else:
                logger.error(f"❌ Error subiendo: {var_key} f{fhr:03d}")
                
        except Exception as e:
            logger.error(f"Error en {var_key} f{fhr:03d}: {e}")
            continue
    
    return success_count


def upload_metadata(run_date: datetime, run_hour: str, 
                   variables: List[str], forecast_hours: List[int]):
    """Sube archivo de metadatos."""
    from config import utcnow
    metadata = {
        'model': 'GFS',
        'resolution': '0.25deg',
        'run_date': run_date.strftime('%Y-%m-%d'),
        'run_hour': run_hour,
        'run_timestamp': run_date.strftime('%Y%m%d') + run_hour,
        'updated_at': utcnow().isoformat() + 'Z',
        'forecast_hours': forecast_hours,
        'variables': {
            key: {
                'name': GFS_VARIABLES[key]['name'],
                'unit': GFS_VARIABLES[key]['unit'],
                'range': GFS_VARIABLES[key]['range']
            }
            for key in variables if key in GFS_VARIABLES
        },
        'bounds': CONUS_BOUNDS,
        'base_url': get_spaces_url('gfs')
    }
    
    # Subir
    date_str = run_date.strftime('%Y%m%d')
    upload_to_spaces(metadata, f"gfs/{date_str}/{run_hour}/metadata.json")
    upload_to_spaces(metadata, "gfs/latest.json")  # Acceso rápido al último run
    
    logger.info(f"✅ Metadatos subidos")


# =============================================
# MAIN
# =============================================

def main():
    parser = argparse.ArgumentParser(description='Borrasca GFS Processor')
    parser.add_argument('variables', nargs='*', default=list(GFS_VARIABLES.keys()),
                        help='Variables a procesar (default: todas)')
    parser.add_argument('--hours', type=int, default=120,
                        help='Máximo forecast hour (default: 120)')
    parser.add_argument('--run', type=str, default=None,
                        help='Run específico YYYYMMDDHH (default: último disponible)')
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("BORRASCA - GFS Processor")
    logger.info("=" * 60)
    
    # Determinar run
    if args.run:
        run_date = datetime.strptime(args.run[:8], '%Y%m%d')
        run_hour = args.run[8:10]
    else:
        run_date, run_hour = get_latest_gfs_run()
    
    logger.info(f"Run: {run_date.strftime('%Y-%m-%d')} {run_hour}Z")
    
    # Horas de pronóstico
    forecast_hours = [h for h in DEFAULT_FORECAST_HOURS if h <= args.hours]
    logger.info(f"Forecast hours: 0-{max(forecast_hours)} (cada 3h)")
    
    # Variables a procesar
    variables = [v for v in args.variables if v in GFS_VARIABLES]
    logger.info(f"Variables: {', '.join(variables)}")
    
    # Verificar dependencias
    if not HAS_XARRAY or not HAS_PIL:
        logger.error("Faltan dependencias. Instalar con:")
        logger.error("  pip install xarray cfgrib pillow")
        logger.error("  apt install libeccodes-dev")
        sys.exit(1)
    
    # Procesar cada variable
    total_success = 0
    for var_key in variables:
        count = process_variable(var_key, run_date, run_hour, forecast_hours)
        total_success += count
    
    # Subir metadatos
    upload_metadata(run_date, run_hour, variables, forecast_hours)
    
    logger.info("\n" + "=" * 60)
    logger.info(f"COMPLETADO: {total_success} frames procesados")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
