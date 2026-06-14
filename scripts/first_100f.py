#!/usr/bin/env python3
"""
===============================================================================
Canal Meteo TV - Primera vez que se alcanzan 100°F esta temporada
===============================================================================

Consulta datos OBSERVADOS de estaciones ThreadEx (RCC-ACIS) para encontrar
la primera fecha en que cada estación alcanzó o superó 100°F esta temporada.

FUENTE: RCC-ACIS StnData API (https://data.rcc-acis.org)
DATOS: Temperaturas máximas diarias observadas (maxt)

SALIDA:
  - first_100f.json         → JSON completo con todos los datos
  - first_100f.geojson      → GeoJSON para mapas interactivos
  - first_100f.kml          → KML para Google Earth / Baron
  - first_100f_records.json → Récords históricos de máxima para ese día

USO:
  python3 first_100f.py [--no-upload] [--threshold 100]

CRON (2x al día, mediodía y medianoche):
  0 0,12 * * * /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/first_100f.py

===============================================================================
"""

import requests
import json
import argparse
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.dom import minidom

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

CONFIG = {
    "acis_url": "https://data.rcc-acis.org",
    "user_agent": "CanalMeteoTV/2.0 (https://canalmeteo.tv; contact@canalmeteo.tv)",
    "threshold": 100,  # °F
    "season_start": "2026-01-01",  # Inicio de temporada (año actual)
    "max_workers": 8,
    "request_timeout": 30,
    "output_dir": "/opt/canalmeteo/data/first100f",
    "s3_bucket": "canalmeteo-public",
    "s3_base_path": "lynx/first100f",
    "s3_endpoint": "https://sfo3.digitaloceanspaces.com",
    "cdn_base": "https://canalmeteo-public.sfo3.digitaloceanspaces.com/lynx/first100f",
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# ESTACIONES THREADEX (~300 estaciones principales de EE.UU.)
# Formato: (sid, nombre, estado, lat, lon)
# =============================================================================

THREADEX_STATIONS = [
    # Alabama
    ("BHMthr", "Birmingham", "AL", 33.5656, -86.7453),
    ("HSVthr", "Huntsville", "AL", 34.6370, -86.7781),
    ("MOBthr", "Mobile", "AL", 30.6880, -88.0431),
    ("MGMthr", "Montgomery", "AL", 32.2998, -86.3918),
    # Alaska
    ("ANCPAthr", "Anchorage", "AK", 61.1743, -149.9962),
    ("FAIthr", "Fairbanks", "AK", 64.8151, -147.8547),
    # Arizona
    ("PHXthr", "Phoenix", "AZ", 33.4373, -112.0078),
    ("TUSthr", "Tucson", "AZ", 32.1313, -110.9553),
    ("FLGthr", "Flagstaff", "AZ", 35.1405, -111.6692),
    # Arkansas
    ("LITthr", "Little Rock", "AR", 34.7252, -92.2313),
    ("FSMthr", "Fort Smith", "AR", 35.3364, -94.3636),
    # California
    ("LAXthr", "Los Angeles AP", "CA", 33.9382, -118.3886),
    ("SFOthr", "San Francisco AP", "CA", 37.6197, -122.3647),
    ("SACthr", "Sacramento", "CA", 38.5125, -121.4975),
    ("SANthr", "San Diego", "CA", 32.7336, -117.1831),
    ("BFLthr", "Bakersfield", "CA", 35.4336, -119.0560),
    ("FATthr", "Fresno", "CA", 36.7800, -119.7194),
    ("RDDthr", "Redding", "CA", 40.5092, -122.2961),
    # Colorado
    ("DENthr", "Denver", "CO", 39.8561, -104.6737),
    ("COSthr", "Colorado Springs", "CO", 38.8058, -104.7009),
    ("PUBthr", "Pueblo", "CO", 38.2898, -104.5230),
    ("GJTthr", "Grand Junction", "CO", 39.1224, -108.5267),
    # Connecticut
    ("BDLthr", "Hartford", "CT", 41.9389, -72.6833),
    ("BDRthr", "Bridgeport", "CT", 41.1631, -73.1261),
    # Delaware
    ("ILGthr", "Wilmington", "DE", 39.6731, -75.6014),
    # Florida
    ("JAXthr", "Jacksonville", "FL", 30.4950, -81.6939),
    ("MIAthr", "Miami", "FL", 25.7903, -80.3164),
    ("TBWthr", "Tampa", "FL", 27.9656, -82.5375),
    ("MCOthr", "Orlando", "FL", 28.4342, -81.3253),
    ("TLHthr", "Tallahassee", "FL", 30.3965, -84.3514),
    ("PNSthr", "Pensacola", "FL", 30.4734, -87.1875),
    # Georgia
    ("ATLthr", "Atlanta", "GA", 33.6301, -84.4419),
    ("SAVthr", "Savannah", "GA", 32.1278, -81.2021),
    ("AGSthr", "Augusta", "GA", 33.3701, -81.9645),
    ("MCNthr", "Macon", "GA", 32.6922, -83.6497),
    # Hawaii
    ("HNLthr", "Honolulu", "HI", 21.3259, -157.9369),
    # Idaho
    ("BOIthr", "Boise", "ID", 43.5644, -116.2228),
    ("PIHthr", "Pocatello", "ID", 42.9186, -112.5961),
    # Illinois
    ("ORDthr", "Chicago O'Hare", "IL", 41.9903, -87.9336),
    ("SPIthr", "Springfield", "IL", 39.8442, -89.6839),
    ("PIAthr", "Peoria", "IL", 40.6675, -89.6847),
    ("MLIthr", "Moline", "IL", 41.4486, -90.5072),
    # Indiana
    ("INDthr", "Indianapolis", "IN", 39.7173, -86.2944),
    ("FWAthr", "Fort Wayne", "IN", 40.9792, -85.1950),
    ("EVVthr", "Evansville", "IN", 38.0444, -87.5314),
    ("SBNthr", "South Bend", "IN", 41.7089, -86.3172),
    # Iowa
    ("DSMthr", "Des Moines", "IA", 41.5341, -93.6531),
    ("CIDthr", "Cedar Rapids", "IA", 41.8847, -91.7108),
    ("DBQthr", "Dubuque", "IA", 42.4017, -90.7042),
    ("SUXthr", "Sioux City", "IA", 42.3997, -96.3836),
    # Kansas
    ("ICTthr", "Wichita", "KS", 37.6500, -97.4331),
    ("TOPthr", "Topeka", "KS", 39.0672, -95.6244),
    ("DDCthr", "Dodge City", "KS", 37.7683, -99.9667),
    ("GCKthr", "Garden City", "KS", 37.9278, -100.7244),
    ("CNKthr", "Concordia", "KS", 39.5491, -97.6514),
    # Kentucky
    ("CVGthr", "Cincinnati/NKY", "KY", 39.0556, -84.6611),
    ("LEXthr", "Lexington", "KY", 38.0364, -84.6058),
    ("SDFthr", "Louisville", "KY", 38.1744, -85.7361),
    ("PAHthr", "Paducah", "KY", 37.0597, -88.7731),
    # Louisiana
    ("MSYthr", "New Orleans", "LA", 29.9931, -90.2583),
    ("BTRthr", "Baton Rouge", "LA", 30.5333, -91.1500),
    ("SHVthr", "Shreveport", "LA", 32.4467, -93.8242),
    ("LCHthr", "Lake Charles", "LA", 30.1261, -93.2286),
    # Maine
    ("PWMthr", "Portland", "ME", 43.6464, -70.3086),
    ("BGRthr", "Bangor", "ME", 44.8017, -68.8281),
    ("CARthr", "Caribou", "ME", 46.8722, -68.0178),
    # Maryland
    ("BWIthr", "Baltimore", "MD", 39.1753, -76.6683),
    # Massachusetts
    ("BOSthr", "Boston", "MA", 42.3606, -71.0106),
    ("ORHthr", "Worcester", "MA", 42.2672, -71.8756),
    # Michigan
    ("DTWthr", "Detroit", "MI", 42.2142, -83.3536),
    ("GRRthr", "Grand Rapids", "MI", 42.8828, -85.5228),
    ("MBSthr", "Saginaw", "MI", 43.5328, -84.0797),
    ("TVCthr", "Traverse City", "MI", 44.7414, -85.5822),
    ("MQTthr", "Marquette", "MI", 46.5328, -87.5489),
    ("LANthr", "Lansing", "MI", 42.7786, -84.5872),
    # Minnesota
    ("MSPthr", "Minneapolis", "MN", 44.8831, -93.2289),
    ("DLHthr", "Duluth", "MN", 46.8422, -92.1836),
    ("RSTthr", "Rochester", "MN", 43.9089, -92.5000),
    ("STPthr", "St. Cloud", "MN", 45.5464, -94.0592),
    # Mississippi
    ("JANthr", "Jackson", "MS", 32.3117, -90.0758),
    # Missouri
    ("STLthr", "St. Louis", "MO", 38.7486, -90.3700),
    ("MCIthr", "Kansas City", "MO", 39.2975, -94.7139),
    ("SGFthr", "Springfield", "MO", 37.2358, -93.3881),
    # Montana
    ("BILthr", "Billings", "MT", 45.8078, -108.5428),
    ("GTFthr", "Great Falls", "MT", 47.4822, -111.3706),
    ("MSOthr", "Missoula", "MT", 46.9211, -114.0928),
    ("HLNthr", "Helena", "MT", 46.6061, -111.9528),
    # Nebraska
    ("OMAAthr", "Omaha", "NE", 41.3003, -95.8944),
    ("LNKthr", "Lincoln", "NE", 40.8506, -96.7592),
    ("LBFthr", "North Platte", "NE", 41.1306, -100.6847),
    ("GRIthr", "Grand Island", "NE", 40.9675, -98.3142),
    # Nevada
    ("LASthr", "Las Vegas", "NV", 36.0800, -115.1522),
    ("RNOthr", "Reno", "NV", 39.4994, -119.7681),
    ("EKOthr", "Elko", "NV", 40.8247, -115.7886),
    # New Hampshire
    ("CONthr", "Concord", "NH", 43.2025, -71.5031),
    # New Jersey
    ("EWRthr", "Newark", "NJ", 40.6925, -74.1686),
    ("ACYthr", "Atlantic City", "NJ", 39.4575, -74.5772),
    # New Mexico
    ("ABQthr", "Albuquerque", "NM", 35.0419, -106.6153),
    ("ROWthr", "Roswell", "NM", 33.3017, -104.5308),
    # New York
    ("NYCthr", "New York City", "NY", 40.7789, -73.9692),
    ("LGAthr", "New York LGA", "NY", 40.7794, -73.8803),
    ("JFKthr", "New York JFK", "NY", 40.6414, -73.7781),
    ("BUFthr", "Buffalo", "NY", 42.9406, -78.7367),
    ("ROCthr", "Rochester", "NY", 43.1186, -77.6769),
    ("SYRthr", "Syracuse", "NY", 43.1114, -76.1064),
    ("ALBthr", "Albany", "NY", 42.7483, -73.8031),
    # North Carolina
    ("CLTthr", "Charlotte", "NC", 35.2144, -80.9431),
    ("RDUthr", "Raleigh", "NC", 35.8916, -78.7844),
    ("GSOthr", "Greensboro", "NC", 36.0978, -79.9428),
    ("AVLthr", "Asheville", "NC", 35.4360, -82.5418),
    ("ILMthr", "Wilmington", "NC", 34.2706, -77.9028),
    # North Dakota
    ("FARthr", "Fargo", "ND", 46.9203, -96.8153),
    ("BISthr", "Bismarck", "ND", 46.7706, -100.7500),
    # Ohio
    ("CLEthr", "Cleveland", "OH", 41.4117, -81.8497),
    ("CMHthr", "Columbus", "OH", 39.9981, -82.8919),
    ("DAYthr", "Dayton", "OH", 39.9044, -84.2194),
    ("TOLthr", "Toledo", "OH", 41.5886, -83.8017),
    ("YNGthr", "Youngstown", "OH", 41.2608, -80.6792),
    # Oklahoma
    ("OKCthr", "Oklahoma City", "OK", 35.3931, -97.6006),
    ("TULthr", "Tulsa", "OK", 36.1981, -95.8864),
    # Oregon
    ("PDXthr", "Portland", "OR", 45.5958, -122.6100),
    ("MFRthr", "Medford", "OR", 42.3742, -122.8736),
    ("EUGthr", "Eugene", "OR", 44.1247, -123.2197),
    ("RDMthr", "Redmond/Bend", "OR", 44.2547, -121.1497),
    # Pennsylvania
    ("PHLthr", "Philadelphia", "PA", 39.8722, -75.2411),
    ("PITthr", "Pittsburgh", "PA", 40.4914, -80.2328),
    ("ABEthr", "Allentown", "PA", 40.6514, -75.4408),
    ("AVPthr", "Scranton", "PA", 41.3386, -75.7236),
    ("ERIthr", "Erie", "PA", 42.0831, -80.1764),
    # Rhode Island
    ("PVDthr", "Providence", "RI", 41.7239, -71.4331),
    # South Carolina
    ("CAEthr", "Columbia", "SC", 33.9388, -81.1186),
    ("CHSthr", "Charleston", "SC", 32.8986, -80.0403),
    ("GSPthr", "Greenville", "SC", 34.8958, -82.2189),
    # South Dakota
    ("FSDthr", "Sioux Falls", "SD", 43.5828, -96.7417),
    ("RAPthr", "Rapid City", "SD", 44.0453, -103.0536),
    ("ABRthr", "Aberdeen", "SD", 45.4492, -98.4217),
    # Tennessee
    ("BNAthr", "Nashville", "TN", 36.1189, -86.6892),
    ("MEMthr", "Memphis", "TN", 35.0622, -89.9867),
    ("TYSthr", "Knoxville", "TN", 35.8117, -83.9939),
    ("CHAthr", "Chattanooga", "TN", 35.0350, -85.2000),
    # Texas
    ("DFWthr", "Dallas/Fort Worth", "TX", 32.8997, -97.0403),
    ("IAHthr", "Houston Intl", "TX", 29.9844, -95.3600),
    ("SATthr", "San Antonio", "TX", 29.5336, -98.4697),
    ("AUSthr", "Austin", "TX", 30.1806, -97.6794),
    ("ELPthr", "El Paso", "TX", 31.8064, -106.3778),
    ("LBBthr", "Lubbock", "TX", 33.6656, -101.8228),
    ("AMAAthr", "Amarillo", "TX", 35.2194, -101.7058),
    ("MAFthr", "Midland", "TX", 31.9428, -102.2019),
    ("CRPthr", "Corpus Christi", "TX", 27.7742, -97.5122),
    ("BROthr", "Brownsville", "TX", 25.9069, -97.4258),
    ("ABIthr", "Abilene", "TX", 32.4117, -99.6817),
    ("SJTthr", "San Angelo", "TX", 31.3578, -100.4947),
    ("DRTthr", "Del Rio", "TX", 29.3742, -100.9278),
    ("VCTthr", "Victoria", "TX", 28.8528, -96.9175),
    # Utah
    ("SLCthr", "Salt Lake City", "UT", 40.7781, -111.9694),
    # Vermont
    ("BTVthr", "Burlington", "VT", 44.4722, -73.1533),
    # Virginia
    ("RICthr", "Richmond", "VA", 37.5053, -77.3197),
    ("ORFthr", "Norfolk", "VA", 36.8975, -76.2058),
    ("ROAthr", "Roanoke", "VA", 37.3175, -79.9744),
    ("IADthr", "Washington Dulles", "VA", 38.9350, -77.4472),
    # Washington
    ("SEAthr", "Seattle-Tacoma", "WA", 47.4444, -122.3139),
    ("GEGthr", "Spokane", "WA", 47.6208, -117.5283),
    ("YKMthr", "Yakima", "WA", 46.5683, -120.5442),
    # Washington DC
    ("DCA_thr", "Washington DC", "DC", 38.8512, -77.0402),
    # West Virginia
    ("CRWthr", "Charleston", "WV", 38.3731, -81.5900),
    ("BKWthr", "Beckley", "WV", 37.7875, -81.1242),
    # Wisconsin
    ("MKEthr", "Milwaukee", "WI", 42.9472, -87.8967),
    ("MSNthr", "Madison", "WI", 43.1399, -89.3375),
    ("GRBthr", "Green Bay", "WI", 44.4847, -88.1297),
    # Wyoming
    ("CYSthr", "Cheyenne", "WY", 41.1558, -104.8111),
    ("CASPthr", "Casper", "WY", 42.9083, -106.4736),
    # Puerto Rico
    ("SJUthr", "San Juan", "PR", 18.4373, -66.0022),
]


class First100FTracker:
    """
    Rastrea la primera vez que cada estación ThreadEx alcanza ≥100°F
    en la temporada actual, usando datos OBSERVADOS de RCC-ACIS.
    """
    
    def __init__(self, threshold: int = 100, output_dir: str = None):
        self.threshold = threshold
        self.acis_url = CONFIG["acis_url"]
        self.headers = {
            "User-Agent": CONFIG["user_agent"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.output_dir = Path(output_dir or CONFIG["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.year = datetime.now().year
        self.season_start = f"{self.year}-01-01"
        
    def fetch_station_data(self, station: tuple) -> Optional[Dict]:
        """
        Consulta RCC-ACIS StnData para obtener las máximas diarias
        de una estación desde el inicio de la temporada hasta hoy.
        Busca la primera fecha con maxt >= threshold.
        """
        sid, name, state, lat, lon = station
        
        params = {
            "sid": sid,
            "sdate": self.season_start,
            "edate": self.today,
            "meta": "name,state,ll",
            "elems": [
                {"name": "maxt"}
            ]
        }
        
        try:
            response = requests.post(
                f"{self.acis_url}/StnData",
                json=params,
                headers=self.headers,
                timeout=CONFIG["request_timeout"]
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                logger.warning(f"  Error ACIS para {sid} ({name}): {data['error']}")
                return None
            
            # Buscar primera fecha >= threshold
            first_date = None
            first_temp = None
            max_temp_season = None
            max_temp_date = None
            days_above = 0
            
            for row in data.get("data", []):
                date_str = row[0]
                maxt_str = row[1]
                
                # Skip missing data
                if maxt_str in ("M", "T", "S", ""):
                    continue
                    
                try:
                    maxt = float(maxt_str)
                except (ValueError, TypeError):
                    continue
                
                # Rastrear máxima de la temporada
                if max_temp_season is None or maxt > max_temp_season:
                    max_temp_season = maxt
                    max_temp_date = date_str
                
                # ¿Alcanzó el umbral?
                if maxt >= self.threshold:
                    days_above += 1
                    if first_date is None:
                        first_date = date_str
                        first_temp = maxt
            
            if first_date is None:
                return None  # Nunca alcanzó 100°F esta temporada
            
            return {
                "sid": sid,
                "name": name,
                "state": state,
                "lat": lat,
                "lon": lon,
                "first_date": first_date,
                "first_temp": int(first_temp),
                "max_temp_season": int(max_temp_season) if max_temp_season else None,
                "max_temp_date": max_temp_date,
                "days_above_100": days_above,
            }
            
        except requests.RequestException as e:
            logger.warning(f"  Error de red para {sid} ({name}): {e}")
            return None
        except Exception as e:
            logger.warning(f"  Error inesperado para {sid} ({name}): {e}")
            return None
    
    def fetch_record_for_date(self, station: tuple, target_date: str) -> Optional[Dict]:
        """
        Obtiene el récord histórico de temperatura máxima para el día
        del año en que la estación alcanzó 100°F por primera vez.
        """
        sid = station[0]
        
        # Obtener datos históricos para ese día del año
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        month, day = dt.month, dt.day
        
        params = {
            "sid": sid,
            "sdate": "por",
            "edate": "por",
            "elems": [
                {
                    "name": "maxt",
                    "interval": [1, 0, 0],
                    "duration": "dly",
                    "reduce": {"reduce": "max", "add": "date"},
                    "maxmissing": 0,
                    "season_start": f"{month:02d}-{day:02d}",
                }
            ]
        }
        
        try:
            response = requests.post(
                f"{self.acis_url}/StnData",
                json=params,
                headers=self.headers,
                timeout=CONFIG["request_timeout"]
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data or not data.get("data"):
                return None
            
            # El resultado es la máxima histórica para ese día del año
            for row in data.get("data", []):
                val = row[1]
                if isinstance(val, list) and len(val) == 2:
                    try:
                        record_temp = float(val[0])
                        record_date = val[1]
                        return {
                            "record_high": int(record_temp),
                            "record_date": record_date,
                        }
                    except (ValueError, TypeError):
                        pass
                elif isinstance(val, str) and val not in ("M", "T", ""):
                    try:
                        return {"record_high": int(float(val)), "record_date": None}
                    except (ValueError, TypeError):
                        pass
            
            return None
            
        except Exception as e:
            logger.debug(f"  No se pudo obtener récord para {sid}: {e}")
            return None
    
    def run(self) -> Dict:
        """Ejecuta la consulta para todas las estaciones."""
        logger.info(f"=" * 60)
        logger.info(f"Canal Meteo TV - Primera vez ≥{self.threshold}°F esta temporada")
        logger.info(f"Período: {self.season_start} → {self.today}")
        logger.info(f"Estaciones: {len(THREADEX_STATIONS)}")
        logger.info(f"=" * 60)
        
        results = []
        errors = 0
        
        # Fase 1: Consultar todas las estaciones en paralelo
        logger.info("Fase 1: Consultando temperaturas observadas...")
        with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
            future_to_station = {
                executor.submit(self.fetch_station_data, stn): stn
                for stn in THREADEX_STATIONS
            }
            
            for future in as_completed(future_to_station):
                stn = future_to_station[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                        logger.info(f"  ✓ {result['name']}, {result['state']}: "
                                   f"{result['first_temp']}°F el {result['first_date']}")
                except Exception as e:
                    errors += 1
                    logger.warning(f"  ✗ Error en {stn[1]}: {e}")
        
        logger.info(f"\nFase 1 completada: {len(results)} estaciones con ≥{self.threshold}°F, "
                    f"{errors} errores")
        
        # Fase 2: Obtener récords históricos para las fechas encontradas
        if results:
            logger.info("Fase 2: Consultando récords históricos...")
            station_map = {s[0]: s for s in THREADEX_STATIONS}
            
            with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
                future_to_result = {}
                for r in results:
                    stn = station_map.get(r["sid"])
                    if stn:
                        future = executor.submit(
                            self.fetch_record_for_date, stn, r["first_date"]
                        )
                        future_to_result[future] = r
                
                for future in as_completed(future_to_result):
                    r = future_to_result[future]
                    try:
                        record = future.result()
                        if record:
                            r["record_high_for_day"] = record.get("record_high")
                            r["record_date_for_day"] = record.get("record_date")
                    except Exception:
                        pass
        
        # Ordenar por fecha (más reciente primero)
        results.sort(key=lambda x: x["first_date"], reverse=True)
        
        # Agrupar por estado
        by_state = {}
        for r in results:
            st = r["state"]
            if st not in by_state:
                by_state[st] = []
            by_state[st].append(r)
        
        # Agrupar por fecha
        by_date = {}
        for r in results:
            d = r["first_date"]
            if d not in by_date:
                by_date[d] = []
            by_date[d].append(r)
        
        # Estadísticas
        earliest = min(results, key=lambda x: x["first_date"]) if results else None
        latest = max(results, key=lambda x: x["first_date"]) if results else None
        hottest = max(results, key=lambda x: x["first_temp"]) if results else None
        
        output = {
            "meta": {
                "title": f"Primera vez ≥{self.threshold}°F - Temporada {self.year}",
                "title_en": f"First time ≥{self.threshold}°F - {self.year} Season",
                "generated": datetime.now().isoformat(),
                "threshold": self.threshold,
                "season_start": self.season_start,
                "season_end": self.today,
                "total_stations_queried": len(THREADEX_STATIONS),
                "total_stations_reached": len(results),
                "total_states_reached": len(by_state),
                "source": "RCC-ACIS / ThreadEx",
                "source_url": "https://data.rcc-acis.org",
            },
            "summary": {
                "earliest_station": earliest,
                "latest_station": latest,
                "hottest_reading": hottest,
                "dates_count": len(by_date),
                "states_list": sorted(by_state.keys()),
            },
            "stations": results,
            "by_state": {k: v for k, v in sorted(by_state.items())},
            "by_date": {k: v for k, v in sorted(by_date.items(), reverse=True)},
        }
        
        return output
    
    def create_geojson(self, results: List[Dict]) -> Dict:
        """Genera GeoJSON con marcadores para cada estación."""
        features = []
        for r in results:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [r["lon"], r["lat"]]
                },
                "properties": {
                    "name": r["name"],
                    "state": r["state"],
                    "sid": r["sid"],
                    "first_date": r["first_date"],
                    "first_temp": r["first_temp"],
                    "max_temp_season": r.get("max_temp_season"),
                    "max_temp_date": r.get("max_temp_date"),
                    "days_above_100": r.get("days_above_100", 0),
                    "record_high_for_day": r.get("record_high_for_day"),
                    "record_date_for_day": r.get("record_date_for_day"),
                    # simplestyle-spec para compatibilidad
                    "marker-color": "#dc2626",
                    "marker-size": "medium",
                    "marker-symbol": "fire-station",
                    "title": f"{r['name']}, {r['state']}",
                    "description": (
                        f"Primera vez ≥{self.threshold}°F: {r['first_date']}\n"
                        f"Temperatura: {r['first_temp']}°F\n"
                        f"Días ≥100°F: {r.get('days_above_100', 0)}"
                    ),
                }
            }
            features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "title": f"Primera vez ≥{self.threshold}°F - Temporada {self.year}",
                "generated": datetime.now().isoformat(),
                "source": "RCC-ACIS / ThreadEx / Canal Meteo TV",
            }
        }
    
    def create_kml(self, results: List[Dict]) -> str:
        """Genera KML para Google Earth / Baron."""
        kml_header = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
<Document>
  <name>Primera vez ≥{self.threshold}°F - Temporada {self.year}</name>
  <description>Estaciones que alcanzaron {self.threshold}°F o más por primera vez esta temporada. Fuente: RCC-ACIS / Canal Meteo TV</description>
  <Style id="heat100">
    <IconStyle>
      <color>ff0000ff</color>
      <scale>1.2</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href>
      </Icon>
    </IconStyle>
    <LabelStyle>
      <color>ff0000ff</color>
      <scale>0.8</scale>
    </LabelStyle>
  </Style>
"""
        placemarks = []
        for r in results:
            record_info = ""
            if r.get("record_high_for_day"):
                record_info = f"\nRécord histórico del día: {r['record_high_for_day']}°F"
                if r.get("record_date_for_day"):
                    record_info += f" ({r['record_date_for_day']})"
            
            pm = f"""  <Placemark>
    <name>{r['name']}, {r['state']} — {r['first_temp']}°F</name>
    <description><![CDATA[
      <b>{r['name']}, {r['state']}</b><br/>
      Primera vez ≥{self.threshold}°F: <b>{r['first_date']}</b><br/>
      Temperatura: <b>{r['first_temp']}°F</b><br/>
      Máx. temporada: {r.get('max_temp_season', 'N/A')}°F ({r.get('max_temp_date', '')})<br/>
      Días ≥100°F: {r.get('days_above_100', 0)}{record_info}
    ]]></description>
    <styleUrl>#heat100</styleUrl>
    <Point>
      <coordinates>{r['lon']},{r['lat']},0</coordinates>
    </Point>
  </Placemark>
"""
            placemarks.append(pm)
        
        kml_footer = """</Document>
</kml>"""
        
        return kml_header + "\n".join(placemarks) + kml_footer
    
    def save_and_upload(self, data: Dict):
        """Guarda archivos localmente y sube a DigitalOcean Spaces."""
        output_dir = self.output_dir
        
        # 1. JSON completo
        json_path = output_dir / "first_100f.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"JSON guardado: {json_path}")
        
        stations = data.get("stations", [])
        
        # 2. GeoJSON
        geojson = self.create_geojson(stations)
        geojson_path = output_dir / "first_100f.geojson"
        with open(geojson_path, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=2, ensure_ascii=False)
        logger.info(f"GeoJSON guardado: {geojson_path} ({len(stations)} features)")
        
        # 3. KML
        kml = self.create_kml(stations)
        kml_path = output_dir / "first_100f.kml"
        with open(kml_path, 'w', encoding='utf-8') as f:
            f.write(kml)
        logger.info(f"KML guardado: {kml_path}")
        
        # 4. Subir a DigitalOcean Spaces
        if not args.no_upload:
            self._upload_all(output_dir)
        else:
            logger.info("⏭️  Upload omitido (--no-upload)")
    
    def _upload_all(self, output_dir: Path):
        """Sube todos los archivos a DigitalOcean Spaces via AWS CLI."""
        files_to_upload = {
            "first_100f.json": "application/json",
            "first_100f.geojson": "application/geo+json",
            "first_100f.kml": "application/vnd.google-earth.kml+xml",
        }
        
        for filename, content_type in files_to_upload.items():
            filepath = output_dir / filename
            if filepath.exists():
                s3_key = f"{CONFIG['s3_base_path']}/{filename}"
                cmd = (
                    f"aws s3 cp {filepath} "
                    f"s3://{CONFIG['s3_bucket']}/{s3_key} "
                    f"--endpoint-url {CONFIG['s3_endpoint']} "
                    f"--acl public-read "
                    f"--content-type '{content_type}' "
                    f"--cache-control 'max-age=900' "
                    f"--profile do-tor1 "
                    f"2>&1"
                )
                result = os.popen(cmd).read()
                if "upload" in result.lower() or result.strip() == "":
                    logger.info(f"  ☁️  Subido: {filename} → {CONFIG['cdn_base']}/{filename}")
                else:
                    logger.warning(f"  ⚠️  Error subiendo {filename}: {result}")


def main():
    global args
    parser = argparse.ArgumentParser(
        description="Canal Meteo TV - Primera vez ≥100°F esta temporada"
    )
    parser.add_argument("--threshold", type=int, default=100,
                       help="Umbral de temperatura en °F (default: 100)")
    parser.add_argument("--output", type=str, default=CONFIG["output_dir"],
                       help="Directorio de salida")
    parser.add_argument("--no-upload", action="store_true",
                       help="No subir a DigitalOcean Spaces")
    args = parser.parse_args()
    
    tracker = First100FTracker(
        threshold=args.threshold,
        output_dir=args.output,
    )
    
    data = tracker.run()
    tracker.save_and_upload(data)
    
    # Resumen final
    total = data["meta"]["total_stations_reached"]
    logger.info(f"\n{'=' * 60}")
    logger.info(f"RESUMEN FINAL")
    logger.info(f"{'=' * 60}")
    logger.info(f"Estaciones con ≥{args.threshold}°F: {total}")
    logger.info(f"Estados: {data['meta']['total_states_reached']}")
    
    if data["summary"]["earliest_station"]:
        e = data["summary"]["earliest_station"]
        logger.info(f"Primera del año: {e['name']}, {e['state']} — "
                    f"{e['first_temp']}°F el {e['first_date']}")
    if data["summary"]["hottest_reading"]:
        h = data["summary"]["hottest_reading"]
        logger.info(f"Más caliente: {h['name']}, {h['state']} — "
                    f"{h['first_temp']}°F el {h['first_date']}")
    
    logger.info(f"\nArchivos en: {args.output}")
    if not args.no_upload:
        logger.info(f"CDN: {CONFIG['cdn_base']}/")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
