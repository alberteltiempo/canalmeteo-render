#!/usr/bin/env python3
"""
===============================================================================
RÉCORDS DE TEMPERATURA POTENCIALES
Canal Meteo TV - canalmeteo.tv
===============================================================================

Obtiene datos de récords históricos de ThreadEx (RCC-ACIS) y los compara
con pronósticos del NWS para identificar ciudades que podrían romper récords.

Estructura en servidor:
- Script: /opt/canalmeteo/scripts/records_potenciales.py
- Entorno: /opt/canalmeteo/env/
- Datos locales: /opt/canalmeteo/data/records/
- Publicación: s3://canalmeteo-public/lynx/records/ via AWS CLI

Uso:
    python3 records_potenciales.py
    
Cron (cada hora):
    0 * * * * /opt/canalmeteo/env/bin/python3 /opt/canalmeteo/scripts/records_potenciales.py

===============================================================================
"""

import requests
import json
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

CONFIG = {
    # APIs
    'acis_url': 'https://data.rcc-acis.org',
    'nws_url': 'https://api.weather.gov',
    'user_agent': 'CanalMeteoTV/1.0 (https://canalmeteo.tv; contacto@canalmeteo.tv)',
    
    # Rutas locales
    'output_dir': '/opt/canalmeteo/data/records',
    'output_json': '/opt/canalmeteo/data/records/records_potenciales.json',
    
    # AWS/Spaces config (igual que otros scripts de Canal Meteo)
    'aws_profile': 'do-tor1',
    'aws_endpoint': 'https://sfo3.digitaloceanspaces.com',
    's3_bucket': 'canalmeteo-public',
    's3_base_path': 'lynx/records',
    
    # Parámetros
    'threshold_fahrenheit': 3,  # Diferencia para considerar "cerca del récord"
    'max_workers': 5,           # Threads para consultas paralelas
    'request_timeout': 30,      # Timeout para requests
}

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# ESTACIONES THREADEX
# Formato: (sid, nombre, nombre_es, estado, lat, lon)
# =============================================================================

THREADEX_STATIONS = [
    # ALABAMA (5)
    ("BHMthr", "Birmingham", "Birmingham", "AL", 33.5656, -86.7453),
    ("HSVthr", "Huntsville", "Huntsville", "AL", 34.6370, -86.7781),
    ("MOBthr", "Mobile", "Mobile", "AL", 30.6880, -88.0431),
    ("MGMthr", "Montgomery", "Montgomery", "AL", 32.2998, -86.3918),
    ("MSLthr", "Muscle Shoals", "Muscle Shoals", "AL", 34.7454, -87.6006),
    # ALASKA (20)
    ("ANCPAthr", "Anchorage", "Anchorage", "AK", 61.1743, -149.9962),
    ("ANNthr", "Annette", "Annette", "AK", 55.0424, -131.5725),
    ("BRWthr", "Barrow", "Barrow", "AK", 71.2906, -156.7886),
    ("BETthr", "Bethel", "Bethel", "AK", 60.7797, -161.8380),
    ("BTTthr", "Bettles", "Bettles", "AK", 66.9139, -151.5169),
    ("CDBthr", "Cold Bay", "Cold Bay", "AK", 55.2061, -162.7256),
    ("BIGthr", "Delta Junction", "Delta Junction", "AK", 63.9944, -145.7217),
    ("FAIthr", "Fairbanks", "Fairbanks", "AK", 64.8151, -147.8547),
    ("GKNthr", "Gulkana", "Gulkana", "AK", 62.1553, -145.4567),
    ("HOMthr", "Homer", "Homer", "AK", 59.6456, -151.4767),
    ("JNUthr", "Juneau", "Juneau", "AK", 58.3567, -134.5639),
    ("AKNthr", "King Salmon", "King Salmon", "AK", 58.6792, -156.6492),
    ("ADQthr", "Kodiak", "Kodiak", "AK", 57.7497, -152.4936),
    ("OTZthr", "Kotzebue", "Kotzebue", "AK", 66.8844, -162.5983),
    ("MCGthr", "McGrath", "McGrath", "AK", 62.9533, -155.6058),
    ("OMEthr", "Nome", "Nome", "AK", 64.5089, -165.4450),
    ("SNPthr", "St Paul Island", "Isla San Pablo", "AK", 57.1531, -170.2197),
    ("TKAthr", "Talkeetna", "Talkeetna", "AK", 62.3208, -150.0936),
    ("YAKthr", "Yakutat", "Yakutat", "AK", 59.5033, -139.6603),
    ("SGYthr", "Skagway", "Skagway", "AK", 59.4597, -135.3142),
    # ARIZONA (8)
    ("FLGthr", "Flagstaff", "Flagstaff", "AZ", 35.1405, -111.6692),
    ("PHXthr", "Phoenix", "Phoenix", "AZ", 33.4373, -112.0078),
    ("TUSthr", "Tucson", "Tucson", "AZ", 32.1313, -110.9553),
    ("INWthr", "Winslow", "Winslow", "AZ", 35.0242, -110.7231),
    ("YUMthr", "Yuma", "Yuma", "AZ", 32.6567, -114.6092),
    ("HVSthr", "Lake Havasu City", "Lake Havasu City", "AZ", 34.4839, -114.3225),
    ("IGMthr", "Kingman", "Kingman", "AZ", 35.2594, -113.9383),
    ("ORCthr", "Oracle", "Oracle", "AZ", 32.6106, -110.7676),
    # ARKANSAS (9)
    ("FSMthr", "Fort Smith", "Fort Smith", "AR", 35.3364, -94.3636),
    ("LITthr", "Little Rock", "Little Rock", "AR", 34.7252, -92.2313),
    ("HROthr", "Harrison", "Harrison", "AR", 36.2617, -93.1546),
    ("JBRthr", "Jonesboro", "Jonesboro", "AR", 35.8423, -90.7043),
    ("PBFthr", "Pine Bluff", "Pine Bluff", "AR", 34.1731, -91.9356),
    ("RUEthr", "Russellville", "Russellville", "AR", 35.2592, -93.0933),
    ("BVOthr", "Booneville", "Booneville", "AR", 35.1400, -93.9217),
    ("DQNthr", "Dequeen", "Dequeen", "AR", 34.0459, -94.3413),
    ("MDAithr", "Mount Ida", "Mount Ida", "AR", 34.5567, -93.6352),
    # CALIFORNIA (34)
    ("BFLthr", "Bakersfield", "Bakersfield", "CA", 35.4336, -119.0560),
    ("BIHthr", "Bishop", "Bishop", "CA", 37.3711, -118.3636),
    ("ACVthr", "Eureka", "Eureka", "CA", 40.9781, -124.1086),
    ("FATthr", "Fresno", "Fresno", "CA", 36.7762, -119.7181),
    ("LGBthr", "Long Beach", "Long Beach", "CA", 33.8117, -118.1517),
    ("LAXthr", "Los Angeles Airport", "Los Ángeles Aeropuerto", "CA", 33.9382, -118.3886),
    ("CQTthr", "Los Angeles Downtown", "Los Ángeles Centro", "CA", 34.0522, -118.2437),
    ("RDDthr", "Redding", "Redding", "CA", 40.5093, -122.2933),
    ("SACthr", "Sacramento", "Sacramento", "CA", 38.5125, -121.4975),
    ("SANthr", "San Diego", "San Diego", "CA", 32.7336, -117.1831),
    ("SFOthr", "San Francisco Airport", "San Francisco Aeropuerto", "CA", 37.6197, -122.3647),
    ("SMXthr", "Santa Maria", "Santa María", "CA", 34.8989, -120.4369),
    ("SCKthr", "Stockton", "Stockton", "CA", 37.8944, -121.2264),
    ("BURthr", "Burbank", "Burbank", "CA", 34.2006, -118.3586),
    ("CMLthr", "Camarillo", "Camarillo", "CA", 34.2164, -119.0931),
    ("EDSthr", "Needles", "Needles", "CA", 34.7669, -114.6181),
    ("OXRthr", "Oxnard", "Oxnard", "CA", 34.2008, -119.2075),
    ("PSPthr", "Palm Springs", "Palm Springs", "CA", 33.8303, -116.5064),
    ("RIVthr", "Riverside", "Riverside", "CA", 33.9533, -117.4472),
    ("RNMthr", "Ramona", "Ramona", "CA", 33.0392, -116.8681),
    ("UKIthr", "Ukiah", "Ukiah", "CA", 39.1258, -123.2008),
    ("ESFthr", "Escondido", "Escondido", "CA", 33.1192, -117.0864),
    ("CREthr", "Crescent City", "Crescent City", "CA", 41.7808, -124.2028),
    ("TKCthr", "Tahoe City", "Tahoe City", "CA", 39.1677, -120.1427),
    ("AATthr", "Alturas", "Alturas", "CA", 41.4871, -120.5413),
    ("WJFthr", "Lancaster", "Lancaster", "CA", 34.7411, -118.2197),
    ("MSTthr", "Mount Shasta", "Mount Shasta", "CA", 41.3099, -122.3106),
    ("PMDthr", "Palmdale", "Palmdale", "CA", 34.6295, -118.0848),
    ("IPLthr", "El Centro", "El Centro", "CA", 32.8342, -115.5700),
    ("SEEthr", "El Cajon", "El Cajon", "CA", 32.8262, -116.9719),
    ("MCEthr", "Merced", "Merced", "CA", 37.2847, -120.5139),
    ("MAEthr", "Madera", "Madera", "CA", 36.9886, -120.1114),
    ("HJOthr", "Hanford", "Hanford", "CA", 36.3169, -119.6392),
    ("SJCthr", "San Jose", "San José", "CA", 37.3626, -121.9291),
    # COLORADO (5)
    ("ALSthr", "Alamosa", "Alamosa", "CO", 37.4350, -105.8667),
    ("COSthr", "Colorado Springs", "Colorado Springs", "CO", 38.8058, -104.7007),
    ("DENthr", "Denver", "Denver", "CO", 39.8561, -104.6737),
    ("GJTthr", "Grand Junction", "Grand Junction", "CO", 39.1224, -108.5267),
    ("PUBthr", "Pueblo", "Pueblo", "CO", 38.2831, -104.5228),
    # CONNECTICUT (2)
    ("BDRthr", "Bridgeport", "Bridgeport", "CT", 41.1632, -73.1263),
    ("BDLthr", "Hartford", "Hartford", "CT", 41.9389, -72.6832),
    # DELAWARE (2)
    ("ILGthr", "Wilmington", "Wilmington", "DE", 39.6787, -75.6056),
    ("GEDthr", "Georgetown", "Georgetown", "DE", 38.6893, -75.3838),
    # DC (1)
    ("DCAthr", "Washington", "Washington DC", "DC", 38.8512, -77.0402),
    # FLORIDA (23)
    ("DABthr", "Daytona Beach", "Daytona Beach", "FL", 29.1803, -81.0481),
    ("RSWthr", "Fort Myers", "Fort Myers", "FL", 26.5362, -81.7553),
    ("GNVthr", "Gainesville", "Gainesville", "FL", 29.6897, -82.2717),
    ("JAXthr", "Jacksonville", "Jacksonville", "FL", 30.4941, -81.6879),
    ("EYWthr", "Key West", "Key West", "FL", 24.5551, -81.7518),
    ("MLBthr", "Melbourne", "Melbourne", "FL", 28.1014, -80.6431),
    ("MIAthr", "Miami", "Miami", "FL", 25.7906, -80.3164),
    ("MCOthr", "Orlando", "Orlando", "FL", 28.4294, -81.3089),
    ("PNSthr", "Pensacola", "Pensacola", "FL", 30.4734, -87.1870),
    ("TLHthr", "Tallahassee", "Tallahassee", "FL", 30.3965, -84.3534),
    ("TBWthr", "Tampa", "Tampa", "FL", 27.9614, -82.5389),
    ("VRBthr", "Vero Beach", "Vero Beach", "FL", 27.6556, -80.4178),
    ("PBIthr", "West Palm Beach", "West Palm Beach", "FL", 26.6831, -80.0956),
    ("FLLthr", "Fort Lauderdale", "Fort Lauderdale", "FL", 26.0726, -80.1528),
    ("FPRthr", "Fort Pierce", "Fort Pierce", "FL", 27.4956, -80.3828),
    ("SFBthr", "Sanford", "Sanford", "FL", 28.7775, -81.2378),
    ("SRQthr", "Sarasota-Bradenton", "Sarasota-Bradenton", "FL", 27.3950, -82.5544),
    ("LALthr", "Lakeland", "Lakeland", "FL", 27.9889, -82.0186),
    ("LEEthr", "Leesburg", "Leesburg", "FL", 28.8233, -81.8092),
    ("PGDthr", "Punta Gorda", "Punta Gorda", "FL", 26.9206, -81.9903),
    ("MTHthr", "Marathon", "Marathon", "FL", 24.7261, -81.0514),
    ("BKVthr", "Brooksville", "Brooksville", "FL", 28.5633, -82.4542),
    ("GIFthr", "Winter Haven", "Winter Haven", "FL", 28.0644, -81.7697),
    # GEORGIA (7)
    ("AHNthr", "Athens", "Atenas", "GA", 33.9519, -83.3263),
    ("ATLthr", "Atlanta", "Atlanta", "GA", 33.6407, -84.4277),
    ("AGSthr", "Augusta", "Augusta", "GA", 33.3700, -81.9644),
    ("CSGthr", "Columbus", "Columbus", "GA", 32.5163, -84.9389),
    ("MCNthr", "Macon", "Macon", "GA", 32.6926, -83.6497),
    ("SAVthr", "Savannah", "Savannah", "GA", 32.1275, -81.2022),
    ("ABYthr", "Albany", "Albany", "GA", 31.5353, -84.1944),
    # HAWAII (4)
    ("ITOthr", "Hilo", "Hilo", "HI", 19.7214, -155.0556),
    ("HNLthr", "Honolulu", "Honolulu", "HI", 21.3187, -157.9225),
    ("OGGthr", "Kahului", "Kahului", "HI", 20.8986, -156.4306),
    ("LIHthr", "Lihue", "Lihue", "HI", 21.9756, -159.3389),
    # IDAHO (11)
    ("BOIthr", "Boise", "Boise", "ID", 43.5644, -116.2228),
    ("LWSthr", "Lewiston", "Lewiston", "ID", 46.3745, -117.0119),
    ("PIHthr", "Pocatello", "Pocatello", "ID", 42.9164, -112.5961),
    ("MYLthr", "McCall", "McCall", "ID", 44.8885, -116.1016),
    ("BYIthr", "Burley", "Burley", "ID", 42.5427, -113.7725),
    ("SMNthr", "Salmon", "Salmon", "ID", 45.1794, -113.8958),
    ("STNthr", "Stanley", "Stanley", "ID", 44.2163, -114.9308),
    ("CHLthr", "Challis", "Challis", "ID", 44.5049, -114.2319),
    ("JERthr", "Jerome", "Jerome", "ID", 42.7244, -114.5186),
    ("AIDthr", "American Falls", "American Falls", "ID", 42.7861, -112.8544),
    ("DWRthr", "Dworshak", "Dworshak", "ID", 46.5136, -116.2950),
    # ILLINOIS (7)
    ("ORDthr", "Chicago", "Chicago", "IL", 41.9742, -87.9073),
    ("MLIthr", "Moline", "Moline", "IL", 41.4486, -90.5075),
    ("PIAthr", "Peoria", "Peoria", "IL", 40.6675, -89.6836),
    ("RFDthr", "Rockford", "Rockford", "IL", 42.1944, -89.0972),
    ("SPIthr", "Springfield", "Springfield", "IL", 39.8440, -89.6779),
    ("UINthr", "Quincy", "Quincy", "IL", 39.9426, -91.1951),
    ("MDHthr", "Carbondale", "Carbondale", "IL", 37.7781, -89.2519),
    # INDIANA (4)
    ("EVVthr", "Evansville", "Evansville", "IN", 38.0369, -87.5322),
    ("FWAthr", "Fort Wayne", "Fort Wayne", "IN", 40.9786, -85.1953),
    ("INDthr", "Indianapolis", "Indianápolis", "IN", 39.7173, -86.2944),
    ("SBNthr", "South Bend", "South Bend", "IN", 41.7086, -86.3172),
    # IOWA (7)
    ("DSMthr", "Des Moines", "Des Moines", "IA", 41.5341, -93.6630),
    ("DBQthr", "Dubuque", "Dubuque", "IA", 42.3981, -90.7045),
    ("SUXthr", "Sioux City", "Sioux City", "IA", 42.3978, -96.3844),
    ("ALOthr", "Waterloo", "Waterloo", "IA", 42.5572, -92.4003),
    ("SPWthr", "Spencer", "Spencer", "IA", 43.1639, -95.2028),
    ("CIDthr", "Cedar Rapids", "Cedar Rapids", "IA", 41.8847, -91.7108),
    ("BRLthr", "Burlington", "Burlington", "IA", 40.7833, -91.1256),
    # KANSAS (6)
    ("CNKthr", "Concordia", "Concordia", "KS", 39.5492, -97.6514),
    ("DDCthr", "Dodge City", "Dodge City", "KS", 37.7625, -99.9694),
    ("GFDthr", "Goodland", "Goodland", "KS", 39.3686, -101.6989),
    ("TOPthr", "Topeka", "Topeka", "KS", 39.0688, -95.6225),
    ("ICTthr", "Wichita", "Wichita", "KS", 37.6500, -97.4331),
    ("SLNthr", "Salina", "Salina", "KS", 38.7917, -97.6522),
    # KENTUCKY (4)
    ("JKLthr", "Jackson", "Jackson", "KY", 37.5936, -83.3172),
    ("LEXthr", "Lexington", "Lexington", "KY", 38.0408, -84.6053),
    ("SDFthr", "Louisville", "Louisville", "KY", 38.1744, -85.7361),
    ("PAHthr", "Paducah", "Paducah", "KY", 37.0597, -88.7731),
    # LOUISIANA (7)
    ("BTRthr", "Baton Rouge", "Baton Rouge", "LA", 30.5337, -91.1494),
    ("LCHthr", "Lake Charles", "Lake Charles", "LA", 30.1253, -93.2283),
    ("MSYthr", "New Orleans", "Nueva Orleans", "LA", 29.9928, -90.2580),
    ("SHVthr", "Shreveport", "Shreveport", "LA", 32.4466, -93.8199),
    ("MLUthr", "Monroe", "Monroe", "LA", 32.5093, -92.0379),
    ("TVRthr", "Tallulah-Vicksburg", "Tallulah-Vicksburg", "LA", 32.4086, -91.0268),
    ("NATthr", "Natchitoches", "Natchitoches", "LA", 31.7607, -93.0863),
    # MAINE (4)
    ("BGRthr", "Bangor", "Bangor", "ME", 44.8074, -68.8281),
    ("CARthr", "Caribou", "Caribou", "ME", 46.8715, -68.0179),
    ("PWMthr", "Portland", "Portland", "ME", 43.6500, -70.3090),
    ("MLTthr", "Millinocket", "Millinocket", "ME", 45.6478, -68.7064),
    # MARYLAND (5)
    ("BWIthr", "Baltimore", "Baltimore", "MD", 39.1754, -76.6684),
    ("SBYthr", "Salisbury", "Salisbury", "MD", 38.3404, -75.5104),
    ("ANPthr", "Annapolis", "Annapolis", "MD", 38.9784, -76.4922),
    ("DMHthr", "Baltimore Downtown", "Baltimore Centro", "MD", 39.2904, -76.6122),
    ("HGRthr", "Hagerstown", "Hagerstown", "MD", 39.7076, -77.7269),
    # MASSACHUSETTS (4)
    ("BOSthr", "Boston", "Boston", "MA", 42.3606, -71.0106),
    ("MILthr", "Milton", "Milton", "MA", 42.2284, -71.0689),
    ("ORHthr", "Worcester", "Worcester", "MA", 42.2677, -71.8757),
    ("BAFthr", "Westfield", "Westfield", "MA", 42.1579, -72.7156),
    # MICHIGAN (13)
    ("APNthr", "Alpena", "Alpena", "MI", 45.0722, -83.5603),
    ("DTWthr", "Detroit", "Detroit", "MI", 42.2125, -83.3534),
    ("FNTthr", "Flint", "Flint", "MI", 42.9654, -83.7438),
    ("GRRthr", "Grand Rapids", "Grand Rapids", "MI", 42.8808, -85.5228),
    ("HTLthr", "Houghton Lake", "Houghton Lake", "MI", 44.3611, -84.6711),
    ("LANthr", "Lansing", "Lansing", "MI", 42.7789, -84.5867),
    ("MQTthr", "Marquette", "Marquette", "MI", 46.5335, -87.5486),
    ("MKGthr", "Muskegon", "Muskegon", "MI", 43.1695, -86.2382),
    ("CIUthr", "Sault Ste Marie", "Sault Ste Marie", "MI", 46.4731, -84.3514),
    ("MBSthr", "Saginaw", "Saginaw", "MI", 43.5328, -84.0796),
    ("AZOthr", "Kalamazoo", "Kalamazoo", "MI", 42.2350, -85.5522),
    ("BTLthr", "Battle Creek", "Battle Creek", "MI", 42.3078, -85.2514),
    ("HOLthr", "Holland", "Holland", "MI", 42.7425, -86.1111),
    # MINNESOTA (7)
    ("DLHthr", "Duluth", "Duluth", "MN", 46.8369, -92.1936),
    ("INLthr", "International Falls", "International Falls", "MN", 48.5614, -93.4031),
    ("MSPthr", "Minneapolis-St Paul", "Minneapolis-St Paul", "MN", 44.8831, -93.2289),
    ("RSTthr", "Rochester", "Rochester", "MN", 43.9043, -92.4940),
    ("STCthr", "Saint Cloud", "Saint Cloud", "MN", 45.5465, -94.0593),
    ("BRDthr", "Brainerd", "Brainerd", "MN", 46.3983, -94.1372),
    ("HIBthr", "Hibbing", "Hibbing", "MN", 47.3872, -92.8386),
    # MISSISSIPPI (8)
    ("JANthr", "Jackson", "Jackson", "MS", 32.3117, -90.0758),
    ("MEIthr", "Meridian", "Meridian", "MS", 32.3336, -88.7517),
    ("TUPthr", "Tupelo", "Tupelo", "MS", 34.2681, -88.7697),
    ("GLHthr", "Greenville", "Greenville", "MS", 33.4820, -90.9870),
    ("PIBthr", "Hattiesburg", "Hattiesburg", "MS", 31.2639, -89.2517),
    ("GPTthr", "Gulfport", "Gulfport", "MS", 30.4072, -89.0703),
    ("GTRthr", "Columbus", "Columbus", "MS", 33.4504, -88.3892),
    ("GWOthr", "Greenwood", "Greenwood", "MS", 33.4943, -90.0848),
    # MISSOURI (6)
    ("COUthr", "Columbia", "Columbia", "MO", 38.8181, -92.2194),
    ("MCIthr", "Kansas City", "Kansas City", "MO", 39.2975, -94.7139),
    ("SGFthr", "Springfield", "Springfield", "MO", 37.2344, -93.3886),
    ("STLthr", "St Louis", "San Luis", "MO", 38.7525, -90.3736),
    ("JEFthr", "Jefferson City", "Jefferson City", "MO", 38.5906, -92.1517),
    ("POFthr", "Poplar Bluff", "Poplar Bluff", "MO", 36.7739, -90.4648),
    # MONTANA (8)
    ("BILthr", "Billings", "Billings", "MT", 45.8077, -108.5428),
    ("GGWthr", "Glasgow", "Glasgow", "MT", 48.2125, -106.6147),
    ("GTFthr", "Great Falls", "Great Falls", "MT", 47.4825, -111.3706),
    ("HVRthr", "Havre", "Havre", "MT", 48.5428, -109.7622),
    ("HLNthr", "Helena", "Helena", "MT", 46.6067, -111.9822),
    ("FCAthr", "Kalispell", "Kalispell", "MT", 48.3050, -114.2561),
    ("MSOthr", "Missoula", "Missoula", "MT", 46.9211, -114.0906),
    ("DLNthr", "Deer Lodge", "Deer Lodge", "MT", 46.3975, -112.7322),
    # NEBRASKA (10)
    ("GRIthr", "Grand Island", "Grand Island", "NE", 40.9672, -98.3103),
    ("LNKthr", "Lincoln", "Lincoln", "NE", 40.8506, -96.7592),
    ("OFKthr", "Norfolk", "Norfolk", "NE", 41.9856, -97.4350),
    ("LBFthr", "North Platte", "North Platte", "NE", 41.1261, -100.6836),
    ("OPDthr", "Omaha", "Omaha", "NE", 41.3031, -95.8942),
    ("BFFthr", "Scottsbluff", "Scottsbluff", "NE", 41.8742, -103.5961),
    ("VTNthr", "Valentine", "Valentine", "NE", 42.8697, -100.5469),
    ("HSTthr", "Hastings", "Hastings", "NE", 40.6064, -98.4267),
    ("MCKthr", "McCook", "McCook", "NE", 40.2064, -100.5922),
    ("ODXthr", "Ord", "Ord", "NE", 41.6022, -98.9306),
    # NEVADA (6)
    ("EKOthr", "Elko", "Elko", "NV", 40.8249, -115.7917),
    ("ELYthr", "Ely", "Ely", "NV", 39.2997, -114.8428),
    ("LASthr", "Las Vegas", "Las Vegas", "NV", 36.0719, -115.1633),
    ("RNOthr", "Reno", "Reno", "NV", 39.4994, -119.7681),
    ("WMCthr", "Winnemucca", "Winnemucca", "NV", 40.8968, -117.8058),
    ("EUAthr", "Eureka", "Eureka", "NV", 39.5127, -115.9608),
    # NEW HAMPSHIRE (2)
    ("CNHthr", "Concord", "Concord", "NH", 43.2025, -71.5006),
    ("MHTthr", "Manchester", "Manchester", "NH", 42.9326, -71.4356),
    # NEW JERSEY (6)
    ("ACYthr", "Atlantic City", "Atlantic City", "NJ", 39.4576, -74.5772),
    ("AIYthr", "Atlantic City Marina", "Atlantic City Marina", "NJ", 39.3643, -74.4229),
    ("EWRthr", "Newark", "Newark", "NJ", 40.6925, -74.1686),
    ("TTNthr", "Trenton", "Trenton", "NJ", 40.2170, -74.7563),
    ("NRKthr", "New Brunswick", "New Brunswick", "NJ", 40.4862, -74.4518),
    ("BELthr", "Belvidere", "Belvidere", "NJ", 40.8298, -75.0771),
    # NEW MEXICO (3)
    ("ABQthr", "Albuquerque", "Albuquerque", "NM", 35.0400, -106.6092),
    ("CAOthr", "Clayton", "Clayton", "NM", 36.4528, -103.1547),
    ("ROWthr", "Roswell", "Roswell", "NM", 33.3011, -104.5308),
    # NEW YORK (17)
    ("ALBthr", "Albany", "Albany", "NY", 42.7483, -73.8019),
    ("BGMthr", "Binghamton", "Binghamton", "NY", 42.2086, -75.9797),
    ("BUFthr", "Buffalo", "Buffalo", "NY", 42.9408, -78.7358),
    ("ISPthr", "Islip", "Islip", "NY", 40.7952, -73.1002),
    ("NYCthr", "New York-Central Park", "Nueva York-Central Park", "NY", 40.7789, -73.9692),
    ("JFKthr", "New York-Kennedy Airport", "Nueva York-JFK", "NY", 40.6413, -73.7781),
    ("LGAthr", "New York-LaGuardia Airport", "Nueva York-LaGuardia", "NY", 40.7769, -73.8740),
    ("ROCthr", "Rochester", "Rochester", "NY", 43.1189, -77.6769),
    ("SYRthr", "Syracuse", "Syracuse", "NY", 43.1117, -76.1042),
    ("POUthr", "Poughkeepsie", "Poughkeepsie", "NY", 41.6269, -73.8840),
    ("GFLthr", "Glens Falls", "Glens Falls", "NY", 43.3410, -73.6787),
    ("PLBthr", "Plattsburgh", "Plattsburgh", "NY", 44.6508, -73.4681),
    ("SLKthr", "Saranac Lake", "Saranac Lake", "NY", 44.3856, -74.2062),
    ("FRGthr", "Fredonia", "Fredonia", "NY", 42.4400, -79.3317),
    ("JHWthr", "Jamestown", "Jamestown", "NY", 42.1534, -79.2581),
    ("OSWthr", "Oswego", "Oswego", "NY", 43.4647, -76.5117),
    ("NCBthr", "Newcomb", "Newcomb", "NY", 43.9703, -74.1617),
    # NORTH CAROLINA (12)
    ("AVLthr", "Asheville", "Asheville", "NC", 35.4360, -82.5418),
    ("HSEthr", "Cape Hatteras", "Cape Hatteras", "NC", 35.2321, -75.6217),
    ("CLTthr", "Charlotte", "Charlotte", "NC", 35.2133, -80.9431),
    ("GSOthr", "Greensboro", "Greensboro", "NC", 36.0978, -79.9375),
    ("RDUthr", "Raleigh", "Raleigh", "NC", 35.8776, -78.7875),
    ("ILMthr", "Wilmington", "Wilmington", "NC", 34.2706, -77.9028),
    ("ECGthr", "Elizabeth City", "Elizabeth City", "NC", 36.2607, -76.1746),
    ("LBTthr", "Lumberton", "Lumberton", "NC", 34.6101, -79.0592),
    ("FAYthr", "Fayetteville", "Fayetteville", "NC", 34.9913, -78.8803),
    ("MITthr", "Mount Mitchell", "Mount Mitchell", "NC", 35.7650, -82.2651),
    ("BRYthr", "Bryson City", "Bryson City", "NC", 35.4312, -83.4496),
    ("EWNthr", "New Bern", "New Bern", "NC", 35.0730, -77.0429),
    # NORTH DAKOTA (4)
    ("BISthr", "Bismarck", "Bismarck", "ND", 46.7727, -100.7543),
    ("FARthr", "Fargo", "Fargo", "ND", 46.9206, -96.8153),
    ("GFKthr", "Grand Forks", "Grand Forks", "ND", 47.9492, -97.1761),
    ("XWAthr", "Williston", "Williston", "ND", 48.1778, -103.6364),
    # OHIO (12)
    ("CAKthr", "Akron", "Akron", "OH", 40.9161, -81.4422),
    ("CVGthr", "Cincinnati", "Cincinnati", "OH", 39.0508, -84.6669),
    ("CLEthr", "Cleveland", "Cleveland", "OH", 41.4094, -81.8547),
    ("CMHthr", "Columbus", "Columbus", "OH", 39.9981, -82.8917),
    ("DAYthr", "Dayton", "Dayton", "OH", 39.9024, -84.2194),
    ("MFDthr", "Mansfield", "Mansfield", "OH", 40.8214, -82.5166),
    ("TOLthr", "Toledo", "Toledo", "OH", 41.5878, -83.8017),
    ("YNGthr", "Youngstown", "Youngstown", "OH", 41.2611, -80.6789),
    ("PHDthr", "New Philadelphia", "New Philadelphia", "OH", 40.5170, -81.4198),
    ("ZZVthr", "Zanesville", "Zanesville", "OH", 39.9447, -81.8917),
    ("ATSthr", "Athens", "Athens", "OH", 39.2111, -82.2314),
    ("ILNthr", "Wilmington", "Wilmington", "OH", 39.4270, -83.7922),
    # OKLAHOMA (4)
    ("OKCthr", "Oklahoma City", "Oklahoma City", "OK", 35.3928, -97.6006),
    ("TULthr", "Tulsa", "Tulsa", "OK", 36.1981, -95.8881),
    ("LAWthr", "Lawton", "Lawton", "OK", 34.5678, -98.4167),
    ("STWthr", "Stillwater", "Stillwater", "OK", 36.1606, -97.0856),
    # OREGON (14)
    ("ASTthr", "Astoria", "Astoria", "OR", 46.1561, -123.8831),
    ("BNOthr", "Burns", "Burns", "OR", 43.5874, -118.9544),
    ("EUGthr", "Eugene", "Eugene", "OR", 44.1246, -123.2190),
    ("MFRthr", "Medford", "Medford", "OR", 42.3744, -122.8728),
    ("PDTthr", "Pendleton", "Pendleton", "OR", 45.6950, -118.8414),
    ("PDXthr", "Portland", "Portland", "OR", 45.5886, -122.5975),
    ("SLEthr", "Salem", "Salem", "OR", 44.9093, -123.0016),
    ("BKEthr", "Baker City", "Baker City", "OR", 44.8374, -117.8089),
    ("ONOthr", "Ontario", "Ontario", "OR", 44.0266, -116.9629),
    ("PDWthr", "Portland Downtown", "Portland Centro", "OR", 45.5231, -122.6765),
    ("LMTthr", "Klamath Falls", "Klamath Falls", "OR", 42.1561, -121.7331),
    ("BOKthr", "Brookings", "Brookings", "OR", 42.0526, -124.2839),
    ("HIOthr", "Hillsboro", "Hillsboro", "OR", 45.5401, -122.9499),
    ("MMVthr", "McMinnville", "McMinnville", "OR", 45.1945, -123.1356),
    # PENNSYLVANIA (10)
    ("ABEthr", "Allentown", "Allentown", "PA", 40.6511, -75.4408),
    ("AVPthr", "Avoca", "Avoca", "PA", 41.3383, -75.7239),
    ("ERIthr", "Erie", "Erie", "PA", 42.0825, -80.1764),
    ("MDTthr", "Middletown-Harrisburg", "Harrisburg", "PA", 40.1944, -76.7633),
    ("PHLthr", "Philadelphia", "Filadelfia", "PA", 39.8729, -75.2311),
    ("PITthr", "Pittsburgh", "Pittsburgh", "PA", 40.4846, -80.2144),
    ("IPTthr", "Williamsport", "Williamsport", "PA", 41.2417, -76.9211),
    ("RDGthr", "Reading", "Reading", "PA", 40.3787, -75.9650),
    ("MPOthr", "Mount Pocono", "Mount Pocono", "PA", 41.1370, -75.3785),
    ("PNEthr", "Philadelphia Center City", "Filadelfia Centro", "PA", 39.9526, -75.1652),
    # PUERTO RICO (1)
    ("SJUthr", "San Juan", "San Juan", "PR", 18.4374, -66.0045),
    # RHODE ISLAND (1)
    ("PVDthr", "Providence", "Providence", "RI", 41.7236, -71.4275),
    # SOUTH CAROLINA (10)
    ("CHSthr", "Charleston", "Charleston", "SC", 32.8985, -80.0405),
    ("CXMthr", "Charleston Downtown", "Charleston Centro", "SC", 32.7765, -79.9311),
    ("CAEthr", "Columbia", "Columbia", "SC", 33.9388, -81.1189),
    ("GSPthr", "Greenville-Spartanburg", "Greenville-Spartanburg", "SC", 34.8957, -82.2189),
    ("LQKthr", "Pickens", "Pickens", "SC", 34.8832, -82.7076),
    ("AIKthr", "Aiken", "Aiken", "SC", 33.6493, -81.6845),
    ("MYRthr", "Myrtle Beach", "Myrtle Beach", "SC", 33.6795, -78.9283),
    ("CRSthr", "Caesars Head", "Caesars Head", "SC", 35.1098, -82.6221),
    ("WREthr", "Ware Shoals", "Ware Shoals", "SC", 34.3987, -82.2468),
    ("WODthr", "Woodruff", "Woodruff", "SC", 34.7393, -82.0371),
    # SOUTH DAKOTA (8)
    ("ABRthr", "Aberdeen", "Aberdeen", "SD", 45.4492, -98.4218),
    ("HONthr", "Huron", "Huron", "SD", 44.3858, -98.2286),
    ("RAPthr", "Rapid City", "Rapid City", "SD", 44.0453, -103.0544),
    ("FSDthr", "Sioux Falls", "Sioux Falls", "SD", 43.5822, -96.7419),
    ("MHEthr", "Mitchell", "Mitchell", "SD", 43.7747, -98.0386),
    ("RCAFthr", "Rapid City Downtown", "Rapid City Centro", "SD", 44.0805, -103.2310),
    ("MBGthr", "Mobridge", "Mobridge", "SD", 45.5364, -100.4089),
    ("SISSthr", "Sisseton", "Sisseton", "SD", 45.6647, -97.0497),
    # TENNESSEE (6)
    ("TRIthr", "Bristol-Johnson City", "Bristol-Johnson City", "TN", 36.4753, -82.4072),
    ("CHAthr", "Chattanooga", "Chattanooga", "TN", 35.0353, -85.2019),
    ("TYSthr", "Knoxville", "Knoxville", "TN", 35.8114, -83.9940),
    ("MEMthr", "Memphis", "Memphis", "TN", 35.0492, -89.9872),
    ("BNAthr", "Nashville", "Nashville", "TN", 36.1189, -86.6892),
    ("OQTthr", "Oak Ridge", "Oak Ridge", "TN", 36.0103, -84.2697),
    # TEXAS (27)
    ("ABIthr", "Abilene", "Abilene", "TX", 32.4111, -99.6817),
    ("AMAthr", "Amarillo", "Amarillo", "TX", 35.2194, -101.7069),
    ("AUSthr", "Austin", "Austin", "TX", 30.1945, -97.6700),
    ("AUSCthr", "Austin-Bergstrom", "Austin-Bergstrom", "TX", 30.1975, -97.6664),
    ("BPTthr", "Beaumont-Port Arthur", "Beaumont-Port Arthur", "TX", 29.9508, -94.0208),
    ("BROthr", "Brownsville", "Brownsville", "TX", 25.9061, -97.4258),
    ("CDSthr", "Childress", "Childress", "TX", 34.4261, -100.2803),
    ("CRPthr", "Corpus Christi", "Corpus Christi", "TX", 27.7742, -97.5122),
    ("DALthr", "Dallas", "Dallas", "TX", 32.8472, -96.8517),
    ("DFWthr", "Dallas-Fort Worth", "Dallas-Fort Worth", "TX", 32.8969, -97.0381),
    ("DRTthr", "Del Rio", "Del Rio", "TX", 29.3740, -100.9274),
    ("ELPthr", "El Paso", "El Paso", "TX", 31.8072, -106.3775),
    ("GLSthr", "Galveston", "Galveston", "TX", 29.2545, -94.8613),
    ("IAHthr", "Houston", "Houston", "TX", 29.9844, -95.3414),
    ("LBBthr", "Lubbock", "Lubbock", "TX", 33.6636, -101.8231),
    ("MIDthr", "Midland-Odessa", "Midland-Odessa", "TX", 31.9425, -102.2019),
    ("SJTthr", "San Angelo", "San Angelo", "TX", 31.3578, -100.4925),
    ("SATthr", "San Antonio", "San Antonio", "TX", 29.5336, -98.4697),
    ("VCTthr", "Victoria", "Victoria", "TX", 28.8528, -96.9183),
    ("ACTthr", "Waco", "Waco", "TX", 31.6114, -97.2306),
    ("SPSthr", "Wichita Falls", "Wichita Falls", "TX", 33.9886, -98.4919),
    ("CLLthr", "College Station", "College Station", "TX", 30.5883, -96.3633),
    ("TYRthr", "Tyler", "Tyler", "TX", 32.3541, -95.4025),
    ("LRDthr", "Laredo", "Laredo", "TX", 27.5439, -99.4614),
    ("MFEthr", "McAllen", "McAllen", "TX", 26.1758, -98.2392),
    ("BGDthr", "Borger", "Borger", "TX", 35.7009, -101.3921),
    ("GGGthr", "Longview", "Longview", "TX", 32.3840, -94.7119),
    # UTAH (1)
    ("SLCthr", "Salt Lake City", "Salt Lake City", "UT", 40.7781, -111.9694),
    # VERMONT (1)
    ("BTVthr", "Burlington", "Burlington", "VT", 44.4719, -73.1533),
    # VIRGINIA (9)
    ("LYHthr", "Lynchburg", "Lynchburg", "VA", 37.3267, -79.2006),
    ("ORFthr", "Norfolk", "Norfolk", "VA", 36.8969, -76.1892),
    ("RICthr", "Richmond", "Richmond", "VA", 37.5052, -77.3197),
    ("ROAthr", "Roanoke", "Roanoke", "VA", 37.3175, -79.9744),
    ("IADthr", "Sterling-Dulles Airport", "Dulles", "VA", 38.9350, -77.4472),
    ("WALthr", "Wallops Island", "Wallops Island", "VA", 37.9368, -75.4663),
    ("DANthr", "Danville", "Danville", "VA", 36.5729, -79.3350),
    ("CHOthr", "Charlottesville", "Charlottesville", "VA", 38.1386, -78.4528),
    ("BCBthr", "Blacksburg", "Blacksburg", "VA", 37.2079, -80.4086),
    # WASHINGTON (10)
    ("OLMthr", "Olympia", "Olympia", "WA", 46.9693, -122.8948),
    ("UILthr", "Quillayute", "Quillayute", "WA", 47.9364, -124.5625),
    ("SEAthr", "Seattle Tacoma", "Seattle Tacoma", "WA", 47.4444, -122.3139),
    ("WATthr", "Seattle City", "Seattle Ciudad", "WA", 47.6062, -122.3321),
    ("GEGthr", "Spokane", "Spokane", "WA", 47.6208, -117.5283),
    ("YKMthr", "Yakima", "Yakima", "WA", 46.5683, -120.5442),
    ("RLDthr", "Tri-Cities", "Tri-Cities", "WA", 46.2643, -119.1193),
    ("PUWthr", "Pullman", "Pullman", "WA", 46.7434, -117.1817),
    ("OMKthr", "Omak", "Omak", "WA", 48.4647, -119.5331),
    ("VUOthr", "Vancouver", "Vancouver", "WA", 45.6206, -122.6567),
    # WEST VIRGINIA (10)
    ("BKWthr", "Beckley", "Beckley", "WV", 37.7875, -81.1242),
    ("CRWthr", "Charleston", "Charleston", "WV", 38.3731, -81.5900),
    ("EKNthr", "Elkins", "Elkins", "WV", 38.8895, -79.8512),
    ("HTSthr", "Huntington", "Huntington", "WV", 38.3667, -82.5580),
    ("HLGthr", "Wheeling", "Wheeling", "WV", 40.1750, -80.6514),
    ("MGWthr", "Morgantown", "Morgantown", "WV", 39.6433, -79.9167),
    ("PKBthr", "Parkersburg", "Parkersburg", "WV", 39.3450, -81.4392),
    ("BLFthr", "Bluefield", "Bluefield", "WV", 37.2957, -81.2076),
    ("CKBthr", "Clarksburg", "Clarksburg", "WV", 39.2972, -80.2281),
    ("MRBthr", "Martinsburg", "Martinsburg", "WV", 39.4015, -77.9842),
    # WISCONSIN (9)
    ("GRBthr", "Green Bay", "Green Bay", "WI", 44.4847, -88.1297),
    ("LSEthr", "La Crosse", "La Crosse", "WI", 43.8791, -91.2569),
    ("MSNthr", "Madison", "Madison", "WI", 43.1399, -89.3375),
    ("MKEthr", "Milwaukee", "Milwaukee", "WI", 42.9472, -87.8967),
    ("ASHthr", "Ashland", "Ashland", "WI", 46.5547, -90.8994),
    ("EAUthr", "Eau Claire", "Eau Claire", "WI", 44.8654, -91.4843),
    ("HYRthr", "Hayward", "Hayward", "WI", 46.0247, -91.4846),
    ("AUWthr", "Wausau", "Wausau", "WI", 44.9272, -89.6270),
    ("RHIthr", "Rhinelander", "Rhinelander", "WI", 45.6311, -89.4676),
    # WYOMING (4)
    ("CASPthr", "Casper", "Casper", "WY", 42.9083, -106.4736),
    ("CYSthr", "Cheyenne", "Cheyenne", "WY", 41.1558, -104.8111),
    ("LNDthr", "Lander", "Lander", "WY", 42.8147, -108.7307),
    ("SHRthr", "Sheridan", "Sheridan", "WY", 44.7697, -106.9803),
    # PACIFIC ISLANDS (10)
    ("PPGthr", "Pago Pago", "Pago Pago", "AS", -14.3318, -170.7132),
    ("YAPthr", "Yap", "Yap", "FM", 9.5144, 138.1292),
    ("PNIthr", "Pohnpei", "Pohnpei", "FM", 6.9633, 158.2089),
    ("TKKthr", "Chuuk", "Chuuk", "FM", 7.4617, 151.8428),
    ("GUMthr", "Guam", "Guam", "GU", 13.4836, 144.7967),
    ("MAJthr", "Majuro", "Majuro", "MH", 7.0897, 171.3803),
    ("KWAthr", "Kwajalein", "Kwajalein", "MH", 8.7200, 167.7314),
    ("GSNthr", "Saipan", "Saipan", "MP", 15.1189, 145.7294),
    ("RORthr", "Koror", "Koror", "PW", 7.3419, 134.4658),
    ("AWKthr", "Wake Island", "Isla Wake", "UM", 19.2823, 166.6470),
]

# Nombres de estados en español
ESTADOS_ES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "Washington D.C.", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "PR": "Puerto Rico",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", 
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", 
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", 
    "WI": "Wisconsin", "WY": "Wyoming",
    "AS": "Samoa Americana", "FM": "Micronesia", "GU": "Guam", 
    "MH": "Islas Marshall", "MP": "Islas Marianas", "PW": "Palaos", 
    "UM": "Islas Menores"
}


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class RecordsPotenciales:
    """Sistema para detectar récords de temperatura potenciales"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": CONFIG['user_agent'],
            "Accept": "application/json"
        }
        # Crear directorio de salida
        Path(CONFIG['output_dir']).mkdir(parents=True, exist_ok=True)
        
    def get_records_for_date(self, sid: str, month: int, day: int) -> Optional[Dict]:
        """
        Obtiene los récords históricos de ThreadEx para un día específico del año
        """
        params = {
            "sid": sid,
            "sdate": "1890-01-01",
            "edate": datetime.now().strftime("%Y-%m-%d"),
            "elems": ["maxt", "mint"]
        }
        
        try:
            response = requests.post(
                f"{CONFIG['acis_url']}/StnData",
                json=params,
                headers=self.headers,
                timeout=CONFIG['request_timeout']
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                return None
            
            # Filtrar para el día específico del año
            target_mmdd = f"{month:02d}-{day:02d}"
            max_temps = []
            min_temps = []
            
            for row in data.get("data", []):
                date_str = row[0]
                if date_str[5:10] == target_mmdd:
                    maxt, mint = row[1], row[2]
                    year = date_str[:4]
                    
                    if maxt not in ["M", "T", None, ""]:
                        try:
                            max_temps.append((float(maxt), year))
                        except (ValueError, TypeError):
                            pass
                    if mint not in ["M", "T", None, ""]:
                        try:
                            min_temps.append((float(mint), year))
                        except (ValueError, TypeError):
                            pass
            
            if not max_temps or not min_temps:
                return None
            
            return {
                "high_max": {"value": max(max_temps, key=lambda x: x[0])[0], 
                            "year": max(max_temps, key=lambda x: x[0])[1]},
                "low_max": {"value": min(max_temps, key=lambda x: x[0])[0], 
                           "year": min(max_temps, key=lambda x: x[0])[1]},
                "high_min": {"value": max(min_temps, key=lambda x: x[0])[0], 
                            "year": max(min_temps, key=lambda x: x[0])[1]},
                "low_min": {"value": min(min_temps, key=lambda x: x[0])[0], 
                           "year": min(min_temps, key=lambda x: x[0])[1]},
                "years_of_record": len(set([t[1] for t in max_temps]))
            }
            
        except Exception as e:
            logger.debug(f"Error ACIS para {sid}: {e}")
            return None
    
    def get_nws_forecast(self, lat: float, lon: float) -> Optional[List[Dict]]:
        """Obtiene pronóstico de 7 días del NWS"""
        try:
            # Obtener metadata del punto
            point_resp = requests.get(
                f"{CONFIG['nws_url']}/points/{lat:.4f},{lon:.4f}",
                headers=self.headers,
                timeout=CONFIG['request_timeout']
            )
            point_resp.raise_for_status()
            point_data = point_resp.json()
            
            # Obtener pronóstico
            forecast_url = point_data["properties"]["forecast"]
            forecast_resp = requests.get(
                forecast_url,
                headers=self.headers,
                timeout=CONFIG['request_timeout']
            )
            forecast_resp.raise_for_status()
            forecast_data = forecast_resp.json()
            
            periods = []
            for p in forecast_data["properties"]["periods"][:14]:
                periods.append({
                    "name": p["name"],
                    "temperature": p["temperature"],
                    "unit": p["temperatureUnit"],
                    "is_day": p["isDaytime"],
                    "start": p["startTime"],
                    "short_forecast": p["shortForecast"]
                })
            
            return periods
            
        except Exception as e:
            logger.debug(f"Error NWS ({lat}, {lon}): {e}")
            return None
    
    def process_station(self, station: Tuple) -> List[Dict]:
        """Procesa una estación y retorna lista de récords potenciales"""
        sid, name_en, name_es, state, lat, lon = station
        potential_records = []
        
        # Obtener pronóstico
        forecast = self.get_nws_forecast(lat, lon)
        if not forecast:
            return []
        
        processed_dates = set()
        
        for period in forecast:
            try:
                start_dt = datetime.fromisoformat(period["start"].replace("Z", "+00:00"))
            except:
                continue
                
            date_key = start_dt.strftime("%Y-%m-%d")
            if date_key in processed_dates:
                continue
            
            # Obtener récords históricos para ese día
            records = self.get_records_for_date(sid, start_dt.month, start_dt.day)
            if not records:
                continue
            
            forecast_temp = period["temperature"]
            is_day = period["is_day"]
            threshold = CONFIG['threshold_fahrenheit']
            
            # Verificar proximidad a récords
            if is_day:
                # Temperatura máxima
                if forecast_temp >= records["high_max"]["value"] - threshold:
                    diff = forecast_temp - records["high_max"]["value"]
                    potential_records.append(self._create_record(
                        name_en, name_es, state, lat, lon, date_key, start_dt,
                        "HIGH_MAX", "Récord de Calor (Máxima)",
                        forecast_temp, records["high_max"], diff, records["years_of_record"]
                    ))
                
                if forecast_temp <= records["low_max"]["value"] + threshold:
                    diff = forecast_temp - records["low_max"]["value"]
                    potential_records.append(self._create_record(
                        name_en, name_es, state, lat, lon, date_key, start_dt,
                        "LOW_MAX", "Récord de Frío (Máxima más baja)",
                        forecast_temp, records["low_max"], diff, records["years_of_record"],
                        is_cold=True
                    ))
            else:
                # Temperatura mínima
                if forecast_temp >= records["high_min"]["value"] - threshold:
                    diff = forecast_temp - records["high_min"]["value"]
                    potential_records.append(self._create_record(
                        name_en, name_es, state, lat, lon, date_key, start_dt,
                        "HIGH_MIN", "Récord de Calor (Mínima más alta)",
                        forecast_temp, records["high_min"], diff, records["years_of_record"]
                    ))
                
                if forecast_temp <= records["low_min"]["value"] + threshold:
                    diff = forecast_temp - records["low_min"]["value"]
                    potential_records.append(self._create_record(
                        name_en, name_es, state, lat, lon, date_key, start_dt,
                        "LOW_MIN", "Récord de Frío (Mínima)",
                        forecast_temp, records["low_min"], diff, records["years_of_record"],
                        is_cold=True
                    ))
            
            processed_dates.add(date_key)
            time.sleep(0.1)
        
        return potential_records
    
    def _create_record(self, name_en, name_es, state, lat, lon, date_key, date_dt,
                       record_type, type_es, forecast_temp, record_data, diff, years, is_cold=False):
        """Crea un objeto de récord"""
        if is_cold:
            status = "BREAK" if diff <= 0 else "TIE" if diff < 1 else "NEAR"
            status_es = "ROMPE" if diff <= 0 else "IGUALA" if diff < 1 else "CERCA"
        else:
            status = "BREAK" if diff >= 0 else "TIE" if diff > -1 else "NEAR"
            status_es = "ROMPE" if diff >= 0 else "IGUALA" if diff > -1 else "CERCA"
        
        return {
            "city": name_en,
            "city_es": name_es,
            "state": state,
            "state_es": ESTADOS_ES.get(state, state),
            "date": date_key,
            "date_formatted": date_dt.strftime("%A, %B %d"),
            "type": record_type,
            "type_es": type_es,
            "forecast_temp": forecast_temp,
            "forecast_temp_c": round((forecast_temp - 32) * 5/9, 1),
            "record_temp": record_data["value"],
            "record_temp_c": round((record_data["value"] - 32) * 5/9, 1),
            "record_year": record_data["year"],
            "diff": round(diff, 1),
            "status": status,
            "status_es": status_es,
            "lat": lat,
            "lon": lon,
            "years_of_record": years,
            "is_heat": record_type in ["HIGH_MAX", "HIGH_MIN"],
            "is_cold": record_type in ["LOW_MAX", "LOW_MIN"]
        }
    
    def run(self, max_stations: int = None) -> Dict:
        """Ejecuta el escaneo completo"""
        logger.info("Iniciando escaneo de récords potenciales...")
        start_time = time.time()
        
        stations = THREADEX_STATIONS[:max_stations] if max_stations else THREADEX_STATIONS
        all_records = []
        
        logger.info(f"Procesando {len(stations)} estaciones...")
        
        with ThreadPoolExecutor(max_workers=CONFIG['max_workers']) as executor:
            futures = {executor.submit(self.process_station, s): s for s in stations}
            completed = 0
            for future in as_completed(futures):
                station = futures[future]
                try:
                    records = future.result()
                    all_records.extend(records)
                except Exception as e:
                    logger.debug(f"Error en {station[1]}: {e}")
                completed += 1
                if completed % 20 == 0:
                    logger.info(f"Progreso: {completed}/{len(stations)} estaciones")
        
        # Organizar resultados
        result = self._organize_results(all_records)
        result["metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "generated_at_unix": int(time.time()),
            "stations_processed": len(stations),
            "processing_time_seconds": round(time.time() - start_time, 2),
            "threshold_fahrenheit": CONFIG['threshold_fahrenheit'],
            "total_records": len(all_records)
        }
        
        logger.info(f"Escaneo completado en {result['metadata']['processing_time_seconds']}s")
        logger.info(f"Total récords potenciales: {len(all_records)}")
        
        return result
    
    def _organize_results(self, records: List[Dict]) -> Dict:
        """Organiza los récords en diferentes vistas"""
        result = {
            "by_date": {},
            "by_state": {},
            "by_type": {
                "HIGH_MAX": [], "LOW_MAX": [], "HIGH_MIN": [], "LOW_MIN": []
            },
            "by_status": {"BREAK": [], "TIE": [], "NEAR": []},
            "heat_records": [],
            "cold_records": [],
            "all_records": records
        }
        
        for record in records:
            # Por fecha
            date = record["date"]
            if date not in result["by_date"]:
                result["by_date"][date] = []
            result["by_date"][date].append(record)
            
            # Por estado
            state = record["state"]
            if state not in result["by_state"]:
                result["by_state"][state] = []
            result["by_state"][state].append(record)
            
            # Por tipo
            result["by_type"][record["type"]].append(record)
            
            # Por estado
            result["by_status"][record["status"]].append(record)
            
            # Calor vs Frío
            if record["is_heat"]:
                result["heat_records"].append(record)
            else:
                result["cold_records"].append(record)
        
        # Ordenar
        result["by_date"] = dict(sorted(result["by_date"].items()))
        result["by_state"] = dict(sorted(result["by_state"].items()))
        
        # Ordenar por diferencia (más cerca del récord primero)
        result["ranked_by_diff"] = sorted(records, key=lambda x: abs(x["diff"]))
        
        # Generar resumen por día
        result["daily_summary"] = {}
        for date, recs in result["by_date"].items():
            result["daily_summary"][date] = {
                "total": len(recs),
                "heat": len([r for r in recs if r["is_heat"]]),
                "cold": len([r for r in recs if r["is_cold"]]),
                "breaking": len([r for r in recs if r["status"] == "BREAK"]),
                "tying": len([r for r in recs if r["status"] == "TIE"]),
                "near": len([r for r in recs if r["status"] == "NEAR"])
            }
        
        # Resumen por estado
        result["state_summary"] = {}
        for state, recs in result["by_state"].items():
            result["state_summary"][state] = {
                "state_es": ESTADOS_ES.get(state, state),
                "total": len(recs),
                "heat": len([r for r in recs if r["is_heat"]]),
                "cold": len([r for r in recs if r["is_cold"]])
            }
        
        return result
    
    def save_and_upload(self, results: Dict):
        """Guarda localmente y sube a S3"""
        output_path = Path(CONFIG['output_json'])
        output_dir = Path(CONFIG['output_dir'])
        
        # Guardar JSON principal
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"Guardado localmente: {output_path}")
        
        # Subir a S3
        self._upload_to_s3(output_path, f"{CONFIG['s3_base_path']}/records_potenciales.json")
        
        # =====================================================================
        # GENERAR GEOJSON SEPARADOS
        # =====================================================================
        
        # Separar récords:
        # - records_max = HIGH_MAX (calor: máxima supera récord de máxima alta)
        # - records_min = LOW_MAX + LOW_MIN (frío: temperatura por debajo de récords fríos)
        records_max = [r for r in results["all_records"] if r["type"] == "HIGH_MAX"]
        records_min = [r for r in results["all_records"] if r["type"] in ["LOW_MAX", "LOW_MIN"]]
        
        logger.info(f"Récords HIGH_MAX (calor): {len(records_max)}")
        logger.info(f"Récords LOW_MAX + LOW_MIN (frío): {len(records_min)}")
        
        # 1. GeoJSON TOTAL de máximas (HIGH_MAX = calor)
        geojson_max_total = self._create_geojson(records_max, "Récords de Temperatura Máxima (Calor)")
        max_total_path = output_dir / "record_temp_max_total.geojson"
        with open(max_total_path, 'w', encoding='utf-8') as f:
            json.dump(geojson_max_total, f, ensure_ascii=False, indent=2)
        self._upload_to_s3(max_total_path, f"{CONFIG['s3_base_path']}/record_temp_max_total.geojson")
        logger.info(f"GeoJSON máximas total: {len(records_max)} features")
        
        # 2. GeoJSON TOTAL de mínimas (LOW_MIN = frío)
        geojson_min_total = self._create_geojson(records_min, "Récords de Temperatura Mínima (Frío)")
        min_total_path = output_dir / "record_temp_min_total.geojson"
        with open(min_total_path, 'w', encoding='utf-8') as f:
            json.dump(geojson_min_total, f, ensure_ascii=False, indent=2)
        self._upload_to_s3(min_total_path, f"{CONFIG['s3_base_path']}/record_temp_min_total.geojson")
        logger.info(f"GeoJSON mínimas total: {len(records_min)} features")
        
        # 3. GeoJSON por día - Máximas HIGH_MAX (day0, day1, day2...)
        geojson_files = []  # Para el índice
        sorted_dates = sorted(results["by_date"].keys())
        
        for day_num, date in enumerate(sorted_dates):
            day_records_max = [r for r in results["by_date"][date] if r["type"] == "HIGH_MAX"]
            if day_records_max:
                geojson = self._create_geojson(day_records_max, f"Récords Máxima Día {day_num}")
                filename = f"record_temp_max_day{day_num}.geojson"
                filepath = output_dir / filename
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(geojson, f, ensure_ascii=False, indent=2)
                self._upload_to_s3(filepath, f"{CONFIG['s3_base_path']}/{filename}")
                geojson_files.append({
                    "day": day_num,
                    "date": date,
                    "type": "max",
                    "filename": filename,
                    "count": len(day_records_max)
                })
        
        # 4. GeoJSON por día - Mínimas LOW_MAX + LOW_MIN (day0, day1, day2...)
        for day_num, date in enumerate(sorted_dates):
            day_records_min = [r for r in results["by_date"][date] if r["type"] in ["LOW_MAX", "LOW_MIN"]]
            if day_records_min:
                geojson = self._create_geojson(day_records_min, f"Récords Mínima Día {day_num}")
                filename = f"record_temp_min_day{day_num}.geojson"
                filepath = output_dir / filename
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(geojson, f, ensure_ascii=False, indent=2)
                self._upload_to_s3(filepath, f"{CONFIG['s3_base_path']}/{filename}")
                geojson_files.append({
                    "day": day_num,
                    "date": date,
                    "type": "min", 
                    "filename": filename,
                    "count": len(day_records_min)
                })
        
        logger.info(f"GeoJSON por día generados: {len(geojson_files)} archivos")
        
        # =====================================================================
        # GENERAR KML SEPARADOS (mismo esquema que GeoJSON)
        # =====================================================================
        
        # 1. KML TOTAL de máximas
        kml_max_total = self._create_kml(records_max, "Records de Temperatura Maxima - Total")
        kml_max_total_path = output_dir / "record_temp_max_total.kml"
        with open(kml_max_total_path, 'w', encoding='utf-8') as f:
            f.write(kml_max_total)
        self._upload_to_s3(kml_max_total_path, f"{CONFIG['s3_base_path']}/record_temp_max_total.kml", content_type='application/vnd.google-earth.kml+xml')
        logger.info(f"KML máximas total: {len(records_max)} placemarks")
        
        # 2. KML TOTAL de mínimas
        kml_min_total = self._create_kml(records_min, "Records de Temperatura Minima - Total")
        kml_min_total_path = output_dir / "record_temp_min_total.kml"
        with open(kml_min_total_path, 'w', encoding='utf-8') as f:
            f.write(kml_min_total)
        self._upload_to_s3(kml_min_total_path, f"{CONFIG['s3_base_path']}/record_temp_min_total.kml", content_type='application/vnd.google-earth.kml+xml')
        logger.info(f"KML mínimas total: {len(records_min)} placemarks")
        
        # 3. KML por día - Máximas HIGH_MAX (day0, day1, day2...)
        kml_files = []
        for day_num, date in enumerate(sorted_dates):
            day_records_max = [r for r in results["by_date"][date] if r["type"] == "HIGH_MAX"]
            if day_records_max:
                kml = self._create_kml(day_records_max, f"Records Maxima Dia {day_num} ({date})")
                filename = f"record_temp_max_day{day_num}.kml"
                filepath = output_dir / filename
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(kml)
                self._upload_to_s3(filepath, f"{CONFIG['s3_base_path']}/{filename}", content_type='application/vnd.google-earth.kml+xml')
                kml_files.append({"day": day_num, "date": date, "type": "max", "filename": filename})
        
        # 4. KML por día - Mínimas LOW_MAX + LOW_MIN (day0, day1, day2...)
        for day_num, date in enumerate(sorted_dates):
            day_records_min = [r for r in results["by_date"][date] if r["type"] in ["LOW_MAX", "LOW_MIN"]]
            if day_records_min:
                kml = self._create_kml(day_records_min, f"Records Minima Dia {day_num} ({date})")
                filename = f"record_temp_min_day{day_num}.kml"
                filepath = output_dir / filename
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(kml)
                self._upload_to_s3(filepath, f"{CONFIG['s3_base_path']}/{filename}", content_type='application/vnd.google-earth.kml+xml')
                kml_files.append({"day": day_num, "date": date, "type": "min", "filename": filename})
        
        logger.info(f"KML por día generados: {len(kml_files)} archivos")
        
        # =====================================================================
        # OTROS ARCHIVOS JSON
        # =====================================================================
        
        # Solo frío (para tormentas de invierno)
        cold_path = output_dir / "cold_records.json"
        with open(cold_path, 'w', encoding='utf-8') as f:
            json.dump({
                "updated": results["metadata"]["generated_at"],
                "total": len(results["cold_records"]),
                "records": results["cold_records"]
            }, f, ensure_ascii=False, indent=2)
        self._upload_to_s3(cold_path, f"{CONFIG['s3_base_path']}/cold_records.json")
        
        # Solo calor
        heat_path = output_dir / "heat_records.json"
        with open(heat_path, 'w', encoding='utf-8') as f:
            json.dump({
                "updated": results["metadata"]["generated_at"],
                "total": len(results["heat_records"]),
                "records": results["heat_records"]
            }, f, ensure_ascii=False, indent=2)
        self._upload_to_s3(heat_path, f"{CONFIG['s3_base_path']}/heat_records.json")
        
        # Resumen ligero con índice de archivos GeoJSON
        summary_path = output_dir / "summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump({
                "updated": results["metadata"]["generated_at"],
                "total": results["metadata"]["total_records"],
                "heat": len(results["heat_records"]),
                "cold": len(results["cold_records"]),
                "breaking": len(results["by_status"]["BREAK"]),
                "daily_summary": results["daily_summary"],
                "state_summary": results["state_summary"],
                "geojson_files": geojson_files,
                "geojson_totals": {
                    "max": "record_temp_max_total.geojson",
                    "min": "record_temp_min_total.geojson"
                }
            }, f, ensure_ascii=False, indent=2)
        self._upload_to_s3(summary_path, f"{CONFIG['s3_base_path']}/summary.json")
    
    def _create_geojson(self, records: List[Dict], title: str) -> Dict:
        """
        Crea un GeoJSON compatible con sistemas Baron/LUDA.
        
        Estructura con objeto 'style' separado (no en properties) para
        compatibilidad con sistemas de visualización meteorológica.
        """
        features = []
        
        for idx, record in enumerate(records):
            # Determinar color basado en tipo
            is_heat = record.get("is_heat", False)
            is_breaking = record.get("status") == "BREAK"
            
            if is_heat:
                fill_color = "#b02a37" if is_breaking else "#dc3545"  # Rojo
            else:
                fill_color = "#0a58ca" if is_breaking else "#0dcaf0"  # Azul
            
            feature = {
                "type": "Feature",
                "id": f"{record['city']}_{record['state']}_{record['type']}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [record["lon"], record["lat"]]
                },
                "properties": {
                    "city": record["city"],
                    "city_es": record["city_es"],
                    "state": record["state"],
                    "state_es": record["state_es"],
                    "date": record["date"],
                    "type": record["type"],
                    "type_es": record["type_es"],
                    "forecast_temp_f": record["forecast_temp"],
                    "forecast_temp_c": record["forecast_temp_c"],
                    "record_temp_f": record["record_temp"],
                    "record_temp_c": record["record_temp_c"],
                    "record_year": record["record_year"],
                    "diff_f": record["diff"],
                    "status": record["status"],
                    "status_es": record["status_es"],
                    "is_heat": is_heat,
                    "years_of_record": record.get("years_of_record", 0),
                    "title": f"{record['city_es']}, {record['state']}",
                    "description": f"{record['type_es']}: {record['forecast_temp']}°F (Récord: {record['record_temp']}°F de {record['record_year']})"
                },
                "style": {
                    "fill": fill_color,
                    "stroke": fill_color,
                    "stroke-width": 2,
                    "stroke-opacity": 1,
                    "fill-opacity": 0.8,
                    "marker-color": fill_color,
                    "marker-size": "medium" if is_breaking else "small"
                }
            }
            features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": features
        }
    
    def _create_kml(self, records: List[Dict], title: str) -> str:
        """
        Crea un archivo KML con los récords de temperatura.
        
        Usa iconos de colores:
        - Rojo para calor (red-circle)
        - Azul para frío (blue-circle)
        - Tamaño mayor si rompe el récord
        """
        # Header KML
        kml = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{title}</name>
  <description>Records de temperatura potenciales - Canal Meteo TV</description>
  
  <!-- Estilos para calor -->
  <Style id="heat-breaking">
    <IconStyle>
      <scale>1.4</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon>
    </IconStyle>
    <LabelStyle><scale>0.8</scale></LabelStyle>
  </Style>
  <Style id="heat-near">
    <IconStyle>
      <scale>1.0</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon>
    </IconStyle>
    <LabelStyle><scale>0.7</scale></LabelStyle>
  </Style>
  
  <!-- Estilos para frio -->
  <Style id="cold-breaking">
    <IconStyle>
      <scale>1.4</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/blu-circle.png</href></Icon>
    </IconStyle>
    <LabelStyle><scale>0.8</scale></LabelStyle>
  </Style>
  <Style id="cold-near">
    <IconStyle>
      <scale>1.0</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/blu-circle.png</href></Icon>
    </IconStyle>
    <LabelStyle><scale>0.7</scale></LabelStyle>
  </Style>
  
'''.format(title=self._escape_xml(title))
        
        # Placemarks
        for record in records:
            is_heat = record.get("is_heat", False)
            is_breaking = record.get("status") == "BREAK"
            
            # Seleccionar estilo
            if is_heat:
                style_id = "heat-breaking" if is_breaking else "heat-near"
            else:
                style_id = "cold-breaking" if is_breaking else "cold-near"
            
            # Descripcion HTML para el popup
            description = '''<![CDATA[
<b>{type_es}</b><br/>
<b>Pronostico:</b> {forecast}F ({forecast_c}C)<br/>
<b>Record:</b> {record}F ({record_c}C) en {year}<br/>
<b>Diferencia:</b> {diff}F<br/>
<b>Estado:</b> {status_es}<br/>
<b>Fecha:</b> {date}
]]>'''.format(
                type_es=self._escape_xml(record['type_es']),
                forecast=record['forecast_temp'],
                forecast_c=record['forecast_temp_c'],
                record=record['record_temp'],
                record_c=record['record_temp_c'],
                year=record['record_year'],
                diff=record['diff'],
                status_es=record['status_es'],
                date=record['date']
            )
            
            placemark = '''  <Placemark>
    <name>{name}</name>
    <description>{description}</description>
    <styleUrl>#{style_id}</styleUrl>
    <Point>
      <coordinates>{lon},{lat},0</coordinates>
    </Point>
  </Placemark>
'''.format(
                name=self._escape_xml(f"{record['city_es']}, {record['state']}"),
                description=description,
                style_id=style_id,
                lon=record['lon'],
                lat=record['lat']
            )
            kml += placemark
        
        # Footer KML
        kml += '''</Document>
</kml>'''
        
        return kml
    
    def _escape_xml(self, text: str) -> str:
        """Escapa caracteres especiales para XML"""
        if not isinstance(text, str):
            text = str(text)
        return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))
        
    def _upload_to_s3(self, local_path: Path, s3_path: str, content_type: str = None):
        """Sube archivo a DigitalOcean Spaces via AWS CLI"""
        s3_uri = f"s3://{CONFIG['s3_bucket']}/{s3_path}"
        
        # Determinar content-type
        if content_type is None:
            if str(local_path).endswith('.geojson'):
                content_type = 'application/geo+json'
            elif str(local_path).endswith('.kml'):
                content_type = 'application/vnd.google-earth.kml+xml'
            else:
                content_type = 'application/json'
        
        cmd = [
            'aws', '--profile', CONFIG['aws_profile'],
            's3', 'cp', str(local_path), s3_uri,
            '--endpoint-url', CONFIG['aws_endpoint'],
            '--acl', 'public-read',
            '--content-type', content_type,
            '--cache-control', 'max-age=300'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.info(f"Subido a S3: {s3_path}")
            else:
                logger.error(f"Error subiendo a S3: {result.stderr}")
        except Exception as e:
            logger.error(f"Error en upload: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    logger.info("=" * 60)
    logger.info("RÉCORDS DE TEMPERATURA POTENCIALES - Canal Meteo TV")
    logger.info("=" * 60)
    
    tracker = RecordsPotenciales()
    results = tracker.run()
    tracker.save_and_upload(results)
    
    # Mostrar resumen
    logger.info("-" * 60)
    logger.info("RESUMEN:")
    logger.info(f"  Total récords: {results['metadata']['total_records']}")
    logger.info(f"  Calor: {len(results['heat_records'])}")
    logger.info(f"  Frío: {len(results['cold_records'])}")
    logger.info(f"  Rompiendo: {len(results['by_status']['BREAK'])}")
    logger.info("-" * 60)


if __name__ == "__main__":
    main()
