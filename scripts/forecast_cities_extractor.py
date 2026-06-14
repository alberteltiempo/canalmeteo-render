"""
forecast_cities_extractor.py — Canal Meteo
═══════════════════════════════════════════════════════════════════════
Extrae datos puntuales del NBM para las 24 ciudades destacadas del
pronóstico (3 ciudades × 8 regiones) y genera un JSON con el pronóstico
de 3 días por ciudad.

Diseño:
    Este módulo se invoca DESDE model_pipeline.py durante el procesamiento
    de cada GRIB, JUSTO ANTES de que sea borrado. No descarga nada por
    su cuenta — solo aprovecha los GRIBs que ya están en disco.

    Al final del run, model_pipeline.py llama a finalize_and_upload()
    que agrupa los datos por días (en TZ local de cada ciudad), calcula
    máximas/mínimas/condición/icono, y sube el JSON al CDN.

Output:
    canalmeteo-public/data/regional/forecast-cities.json

Uso desde model_pipeline.py:
    from forecast_cities_extractor import ForecastCitiesAccumulator

    acc = ForecastCitiesAccumulator(cycle_dt=cycle_dt)
    # En el loop principal, antes de os.remove(grib_path):
    acc.extract(grib_path, fhour=fhour, group_name=gname)
    # Al final del pipeline:
    acc.finalize_and_upload()

Ubicación: /opt/canalmeteo/scripts/forecast_cities_extractor.py
═══════════════════════════════════════════════════════════════════════
"""
import json
import logging
import os
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python < 3.9
    from backports.zoneinfo import ZoneInfo

# cfgrib y xarray se importan de forma lazy en extract() para que el módulo
# se pueda importar/testear sin tenerlos instalados. En producción son
# obligatorios, ya que model_pipeline.py los usa.
_cfgrib = None
_xr = None

def _lazy_import_grib_libs():
    global _cfgrib, _xr
    if _cfgrib is None:
        try:
            import cfgrib as _c
            import xarray as _x
            _cfgrib = _c
            _xr = _x
        except ImportError as e:
            raise ImportError(
                f"forecast_cities_extractor requiere cfgrib y xarray: {e}"
            )

from regions_config import REGIONS

log = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# CONSTANTES Y CONFIGURACIÓN
# ═════════════════════════════════════════════════════════════════════

CDN_BUCKET = 'canalmeteo-public'
CDN_ENDPOINT = 'https://sfo3.digitaloceanspaces.com'
AWS_PROFILE = 'do-tor1'
CDN_KEY = 'data/regional/forecast-cities.json'

# Variables NBM por grupo (matches model_pipeline.py groups)
VARS_BY_GROUP = {
    '2m':  ['t2m', 'd2m', 'r2', 'aptmp'],
    '10m': ['si10', 'i10fg', 'wdir10'],
    'sfc': ['vis', 'tcc', 'cape', 'tp'],
}

# Mapeo estado → zona horaria IANA
# (cubre todos los estados que aparecen en regions_config.py)
STATE_TO_TZ = {
    # Eastern
    'ME': 'America/New_York', 'NH': 'America/New_York', 'VT': 'America/New_York',
    'MA': 'America/New_York', 'RI': 'America/New_York', 'CT': 'America/New_York',
    'NY': 'America/New_York', 'NJ': 'America/New_York', 'PA': 'America/New_York',
    'DE': 'America/New_York', 'MD': 'America/New_York', 'DC': 'America/New_York',
    'WV': 'America/New_York', 'VA': 'America/New_York', 'NC': 'America/New_York',
    'SC': 'America/New_York', 'GA': 'America/New_York', 'FL': 'America/New_York',
    'OH': 'America/New_York', 'MI': 'America/New_York', 'IN': 'America/Indiana/Indianapolis',
    'KY': 'America/New_York',
    # Central
    'AL': 'America/Chicago', 'MS': 'America/Chicago', 'TN': 'America/Chicago',
    'IL': 'America/Chicago', 'WI': 'America/Chicago', 'MN': 'America/Chicago',
    'IA': 'America/Chicago', 'MO': 'America/Chicago', 'AR': 'America/Chicago',
    'LA': 'America/Chicago', 'OK': 'America/Chicago', 'KS': 'America/Chicago',
    'ND': 'America/Chicago', 'SD': 'America/Chicago', 'NE': 'America/Chicago',
    'TX': 'America/Chicago',
    # Mountain
    'MT': 'America/Denver', 'WY': 'America/Denver', 'CO': 'America/Denver',
    'NM': 'America/Denver', 'UT': 'America/Denver', 'ID': 'America/Boise',
    'AZ': 'America/Phoenix',  # Arizona no observa DST
    # Pacific
    'WA': 'America/Los_Angeles', 'OR': 'America/Los_Angeles',
    'NV': 'America/Los_Angeles', 'CA': 'America/Los_Angeles',
}

# Días de la semana en español
WEEKDAYS_ES = [
    'Lunes', 'Martes', 'Miércoles', 'Jueves',
    'Viernes', 'Sábado', 'Domingo'
]

# Diccionario de traducción de condiciones meteorológicas
CONDITION_ES = {
    'sunny':         'Soleado',
    'partly-cloudy': 'Parcialmente nublado',
    'mostly-cloudy': 'Mayormente nublado',
    'cloudy':        'Nublado',
    'showers':       'Probabilidad de lluvia',
    'rain':          'Lluvia',
    'heavy-rain':    'Lluvia intensa',
    'thunderstorms': 'Tormentas',
    'wintry-mix':    'Mezcla invernal',
    'snow':          'Nieve',
    'fog':           'Niebla',
}

# Schema version del JSON output (incrementar al cambiar estructura)
SCHEMA_VERSION = '1.0'


# ═════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ═════════════════════════════════════════════════════════════════════

class ForecastCitiesAccumulator:
    """
    Acumula datos puntuales de las 24 ciudades del pronóstico durante
    el run de model_pipeline.py.

    Uso:
        acc = ForecastCitiesAccumulator(cycle_dt=cycle_dt)
        acc.extract(grib_path, fhour=12, group_name='2m')
        ...
        acc.finalize_and_upload()
    """

    def __init__(self, cycle_dt):
        """
        Args:
            cycle_dt (datetime): Hora del cycle del NBM (UTC, tzaware).
        """
        if cycle_dt.tzinfo is None:
            cycle_dt = cycle_dt.replace(tzinfo=timezone.utc)
        self.cycle_dt = cycle_dt

        # Lista plana de las 24 ciudades del pronóstico
        self.cities = self._collect_forecast_cities()

        # data: { city_id: { fhour: {var_name: value, ...} } }
        self.data = defaultdict(lambda: defaultdict(dict))

        # Estadísticas
        self.stats = {
            'extracts_called': 0,
            'extracts_succeeded': 0,
            'gribs_processed': 0,
            'errors': [],
        }

        log.info(
            f"[forecast_cities] Inicializado: cycle={cycle_dt.isoformat()} "
            f"cities={len(self.cities)}"
        )

    def _collect_forecast_cities(self):
        """Recoge las 3 ciudades del pronóstico de cada región."""
        result = []
        for region_id, region in REGIONS.items():
            for city in region.get('forecast_cities', []):
                result.append({**city, 'region_id': region_id})
        return result

    # ─── EXTRACCIÓN ───────────────────────────────────────────────

    def extract(self, grib_path, fhour, group_name):
        """
        Extrae las variables del GRIB para todas las ciudades.

        Llamar JUSTO ANTES de os.remove(grib_path).

        Args:
            grib_path (str): Path al GRIB descargado.
            fhour (int): Forecast hour (1, 2, ..., 78).
            group_name (str): Grupo NBM ('2m', '10m', 'sfc').
        """
        self.stats['extracts_called'] += 1

        if not os.path.exists(grib_path):
            log.warning(f"[forecast_cities] GRIB no existe: {grib_path}")
            return

        target_vars = VARS_BY_GROUP.get(group_name)
        if not target_vars:
            # Otros grupos (refl, refc, 250mb, etc) — no nos interesan para forecast cities
            return

        # Lazy import de cfgrib (solo cuando realmente lo necesitamos)
        _lazy_import_grib_libs()

        try:
            datasets = _cfgrib.open_datasets(grib_path)
        except Exception as e:
            log.warning(f"[forecast_cities] No se pudo abrir GRIB f{fhour:03d}/{group_name}: {e}")
            self.stats['errors'].append(f"open f{fhour:03d}/{group_name}: {e}")
            return

        try:
            self.stats['gribs_processed'] += 1
            extracted_vars = set()

            for ds in datasets:
                # Detectar si el grid es 1D regular (GFS, lat/lon arrays simples)
                # o 2D Lambert Conformal (NBM, HRRR, RAP — coords son matrices 2D)
                if 'longitude' not in ds.coords or 'latitude' not in ds.coords:
                    continue
                lats_arr = ds['latitude'].values
                lons_arr = ds['longitude'].values
                ds_uses_360 = bool(np.any(lons_arr > 180))
                is_2d_grid = (lats_arr.ndim == 2 and lons_arr.ndim == 2)

                # Para grids 2D necesitamos pre-construir un cache de indices
                # (lo guardamos en el ds para reutilizar entre extract() calls)
                if is_2d_grid:
                    # Normalizar lons a -180..180 para matching con ciudades
                    lons_norm = np.where(lons_arr > 180, lons_arr - 360, lons_arr)

                for city in self.cities:
                    lat = city['lat']
                    lon = city['lon']

                    if is_2d_grid:
                        # Busqueda manual por distancia minima
                        iy, ix = self._nearest_2d_index(
                            lats_arr, lons_norm, lat, lon
                        )
                        if iy is None:
                            continue
                        for var_name in target_vars:
                            if var_name not in ds.data_vars:
                                continue
                            try:
                                arr = ds[var_name].values
                                if arr.ndim == 3:
                                    arr = arr[0]
                                raw_value = float(arr[iy, ix])
                            except Exception:
                                continue
                            if np.isnan(raw_value):
                                continue
                            converted = self._convert(var_name, raw_value)
                            self.data[city['id']][fhour][var_name] = converted
                            extracted_vars.add(var_name)
                    else:
                        # Grid 1D regular: usar .sel() normalmente
                        sel_lon = lon + 360 if (ds_uses_360 and lon < 0) else lon
                        try:
                            point = ds.sel(latitude=lat, longitude=sel_lon, method='nearest')
                        except Exception:
                            continue
                        for var_name in target_vars:
                            if var_name not in point.data_vars:
                                continue
                            try:
                                raw_value = float(point[var_name].values)
                            except Exception:
                                continue
                            if np.isnan(raw_value):
                                continue
                            converted = self._convert(var_name, raw_value)
                            self.data[city['id']][fhour][var_name] = converted
                            extracted_vars.add(var_name)

            if extracted_vars:
                self.stats['extracts_succeeded'] += 1

        finally:
            # Importante: cerrar los datasets para liberar el archivo
            for ds in datasets:
                try:
                    ds.close()
                except Exception:
                    pass

    def _nearest_2d_index(self, lats_2d, lons_2d, target_lat, target_lon):
        """Encuentra el indice (iy, ix) del punto mas cercano en un grid 2D.

        Usa cache para evitar recalcular distancias entre calls (los grids
        del NBM no cambian entre fhours del mismo cycle).
        """
        # Pre-filtro: descartar puntos lejanos para acelerar el calculo
        # Solo consideramos puntos en una bounding box +/- 1.5 grados
        lat_diff = lats_2d - target_lat
        lon_diff = lons_2d - target_lon
        # Normalizar lon_diff por meridiano (no esencial para CONUS)
        dist_sq = lat_diff * lat_diff + lon_diff * lon_diff
        try:
            flat_idx = int(np.argmin(dist_sq))
            iy, ix = np.unravel_index(flat_idx, dist_sq.shape)
            # Validar que la distancia es razonable (< 0.5 grado ~ 50km)
            min_dist = float(np.sqrt(dist_sq.flat[flat_idx]))
            if min_dist > 0.5:
                # El punto mas cercano queda muy lejos — fuera del dominio
                return None, None
            return int(iy), int(ix)
        except Exception:
            return None, None

    def _convert(self, var_name, value):
        """Convierte valores de unidades SI a unidades imperiales."""
        if var_name in ('t2m', 'd2m', 'aptmp'):
            # Kelvin → Fahrenheit
            return (value - 273.15) * 9.0 / 5.0 + 32.0
        elif var_name in ('si10', 'i10fg'):
            # m/s → mph
            return value * 2.23694
        elif var_name == 'tp':
            # kg/m² (mm) → inches
            return value / 25.4
        elif var_name == 'vis':
            # m → miles
            return value * 0.000621371
        else:
            # cape, tcc, r2, wdir10 → sin conversión
            return value

    # ─── AGREGACIÓN POR DÍAS ──────────────────────────────────────

    def _group_by_local_day(self, city, city_data):
        """
        Agrupa las muestras horarias en días (en TZ local de la ciudad).

        Returns:
            dict { date_str: [list of hourly samples] }
            donde date_str es 'YYYY-MM-DD' en TZ local
        """
        tz_name = STATE_TO_TZ.get(city['state'], 'America/New_York')
        try:
            local_tz = ZoneInfo(tz_name)
        except Exception:
            log.warning(f"[forecast_cities] TZ desconocida: {tz_name}, usando New_York")
            local_tz = ZoneInfo('America/New_York')

        days = defaultdict(list)
        for fhour, sample in city_data.items():
            if not sample:
                continue
            valid_utc = self.cycle_dt + timedelta(hours=fhour)
            valid_local = valid_utc.astimezone(local_tz)
            date_str = valid_local.strftime('%Y-%m-%d')
            days[date_str].append({
                'fhour': fhour,
                'valid_utc': valid_utc,
                'valid_local': valid_local,
                'hour_local': valid_local.hour,
                **sample,
            })

        return days, local_tz

    def _compute_daily_summary(self, samples):
        """
        Dado una lista de muestras horarias de UN día, calcula
        el resumen (max/min temp, lluvia total, viento máx, etc.)
        """
        if not samples:
            return None

        def col(var):
            return [s[var] for s in samples if var in s]

        temps = col('t2m')
        feels = col('aptmp')
        precip = col('tp')
        winds = col('si10')
        gusts = col('i10fg')
        clouds = col('tcc')
        rh = col('r2')
        cape = col('cape')

        # Probabilidad de precipitación: % de horas con tp > 0.005 in (0.13mm)
        # NBM no incluye POP directamente en el filter request — derivamos
        n = len(samples) if samples else 1
        wet_hours = sum(1 for p in precip if p > 0.005)
        pop_pct = round(100.0 * wet_hours / n) if n else 0

        summary = {
            'max_f':         round(max(temps)) if temps else None,
            'min_f':         round(min(temps)) if temps else None,
            'feels_max_f':   round(max(feels)) if feels else None,
            'feels_min_f':   round(min(feels)) if feels else None,
            'precip_in':     round(sum(precip), 2) if precip else 0.0,
            'pop_pct':       pop_pct,
            'wind_max_mph':  round(max(winds)) if winds else None,
            'gust_max_mph':  round(max(gusts)) if gusts else None,
            'cloud_avg_pct': round(sum(clouds) / len(clouds)) if clouds else None,
            'rh_avg_pct':    round(sum(rh) / len(rh)) if rh else None,
            'cape_max':      round(max(cape)) if cape else None,
            'samples_count': len(samples),
        }

        # Derivar condición + ícono
        cond = self._derive_condition(summary, samples)
        summary['condition_id'] = cond
        summary['condition_es'] = CONDITION_ES.get(cond, cond)
        summary['icon'] = cond  # mismo ID — Remotion mapeará a SVG

        return summary

    def _derive_condition(self, summary, samples):
        """Determina la condición predominante del día."""
        precip = summary['precip_in'] or 0
        pop = summary['pop_pct'] or 0
        cloud = summary['cloud_avg_pct'] or 0
        max_temp = summary['max_f'] or 50
        min_temp = summary['min_f'] or 30
        cape = summary['cape_max'] or 0

        # Tormentas: CAPE alto + precipitación
        if cape > 1000 and precip > 0.10:
            return 'thunderstorms'

        # Nieve / mezcla: precipitación + temp baja
        if precip > 0.05 and pop > 30:
            if max_temp < 32:
                return 'snow'
            elif min_temp < 32 and max_temp < 40:
                return 'wintry-mix'

        # Lluvia
        if precip > 0.25:
            return 'heavy-rain'
        if precip > 0.05 and pop > 50:
            return 'rain'

        # Probabilidad de lluvia
        if pop > 30:
            return 'showers'

        # Cielo según nubosidad
        if cloud < 25:
            return 'sunny'
        elif cloud < 60:
            return 'partly-cloudy'
        elif cloud < 85:
            return 'mostly-cloudy'
        else:
            return 'cloudy'

    def _day_label(self, date_str, local_now):
        """Devuelve etiqueta corta como 'Hoy', 'Mañana', 'Pasado mañana', o el día largo."""
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return date_str

        today = local_now.date()
        delta = (d - today).days

        if delta == 0:
            return 'Hoy'
        elif delta == 1:
            return 'Mañana'
        elif delta == 2:
            return 'Pasado mañana'
        else:
            return WEEKDAYS_ES[d.weekday()]

    def _day_long(self, date_str):
        """Devuelve el día de la semana largo: 'Miércoles', 'Jueves', etc."""
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            return WEEKDAYS_ES[d.weekday()]
        except ValueError:
            return ''

    # ─── FINALIZACIÓN Y UPLOAD ────────────────────────────────────

    def finalize_and_upload(self):
        """
        Construye el JSON con el pronóstico de 3 días por ciudad
        y lo sube al CDN.
        """
        log.info(
            f"[forecast_cities] Finalizando: extracts_called={self.stats['extracts_called']} "
            f"extracts_succeeded={self.stats['extracts_succeeded']} "
            f"gribs_processed={self.stats['gribs_processed']} "
            f"errors={len(self.stats['errors'])}"
        )

        if self.stats['extracts_succeeded'] == 0:
            log.error("[forecast_cities] Cero extractos exitosos — abortando upload")
            return

        # Construir JSON estructurado por región
        regions_output = {}

        for region_id, region in REGIONS.items():
            cities_out = []
            for city_template in region.get('forecast_cities', []):
                city_id = city_template['id']
                city_data = self.data.get(city_id, {})

                if not city_data:
                    log.warning(
                        f"[forecast_cities] Sin datos para {city_id} ({region_id})"
                    )
                    continue

                # Agrupar por día local
                days_grouped, local_tz = self._group_by_local_day(city_template, city_data)

                # Calcular "ahora local" para etiquetas
                local_now = self.cycle_dt.astimezone(local_tz)

                # Convertir a lista ordenada de días, tomar los primeros 3 días con datos suficientes
                days_out = []
                sorted_dates = sorted(days_grouped.keys())
                for date_str in sorted_dates:
                    samples = days_grouped[date_str]
                    # Solo días con al menos 4 muestras (cobertura razonable)
                    if len(samples) < 4:
                        continue
                    summary = self._compute_daily_summary(samples)
                    if not summary:
                        continue
                    summary['date'] = date_str
                    summary['day_label_es'] = self._day_label(date_str, local_now)
                    summary['day_long_es'] = self._day_long(date_str)
                    days_out.append(summary)
                    if len(days_out) >= 3:
                        break

                if not days_out:
                    log.warning(
                        f"[forecast_cities] {city_id}: sin días con cobertura suficiente"
                    )
                    continue

                cities_out.append({
                    'id': city_id,
                    'name': city_template['name'],
                    'name_es': city_template.get('name_es', city_template['name']),
                    'state': city_template['state'],
                    'state_es': city_template.get('state_es', ''),
                    'lat': city_template['lat'],
                    'lon': city_template['lon'],
                    'tz': STATE_TO_TZ.get(city_template['state'], 'America/New_York'),
                    'days': days_out,
                })

            regions_output[region_id] = {
                'name_es': region['name_es'],
                'cities': cities_out,
            }

        # Construir output completo
        output = {
            'version': SCHEMA_VERSION,
            'generated': datetime.now(timezone.utc).isoformat(),
            'model': 'NBM',
            'cycle': self.cycle_dt.strftime('%Y%m%d/%Hz'),
            'regions': regions_output,
        }

        # Estadísticas para el log
        total_cities = sum(len(r['cities']) for r in regions_output.values())
        log.info(
            f"[forecast_cities] Output: {total_cities} ciudades en "
            f"{len(regions_output)} regiones"
        )

        # Subir al CDN
        self._upload_json(output)

    def _upload_json(self, output):
        """Escribe el JSON a un tmpfile y lo sube al CDN via aws cli."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        ) as tmp:
            json.dump(output, tmp, ensure_ascii=False, separators=(',', ':'))
            tmp_path = tmp.name

        try:
            cmd = [
                'aws', 's3', 'cp',
                tmp_path,
                f's3://{CDN_BUCKET}/{CDN_KEY}',
                '--profile', AWS_PROFILE,
                '--endpoint-url', CDN_ENDPOINT,
                '--acl', 'public-read',
                '--content-type', 'application/json',
                '--cache-control', 'public, max-age=300',
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                size_kb = os.path.getsize(tmp_path) / 1024
                log.info(
                    f"[forecast_cities] ✅ Uploaded: {CDN_KEY} ({size_kb:.1f} KB)"
                )
            else:
                log.error(
                    f"[forecast_cities] Upload falló: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired:
            log.error("[forecast_cities] Upload timeout")
        except Exception as e:
            log.error(f"[forecast_cities] Upload exception: {e}")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════
# CLI / debug
# ═════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Test simple: crear acumulador con cycle dummy y mostrar config
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    cycle_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    acc = ForecastCitiesAccumulator(cycle_dt=cycle_dt)
    print(f"\nCiudades del pronóstico ({len(acc.cities)}):")
    for c in acc.cities:
        tz = STATE_TO_TZ.get(c['state'], '?')
        print(f"  [{c['region_id']:14s}] {c['name_es']:20s} {c['state']}  TZ={tz}")
    print(f"\nCondiciones soportadas: {len(CONDITION_ES)}")
    for k, v in CONDITION_ES.items():
        print(f"  {k:18s} → {v}")
