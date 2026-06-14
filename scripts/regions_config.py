"""
regions_config.py — Canal Meteo
═══════════════════════════════════════════════════════════════════════
Configuración maestra de las 8 regiones que componen el sistema de
productos regionales de Canal Meteo TV.

Esta es la FUENTE ÚNICA DE VERDAD de:
  - Bbox geográfico de cada región
  - Centro y zoom para Mapbox
  - Lista de ciudades por tier (1, 2, 3) para mapas de máximas/temps
  - 3 ciudades destacadas para el slide de pronóstico 3 días
  - Música de fondo de cada región
  - Información editorial (nombre largo, color de marca, etc.)

Uso:
  from regions_config import REGIONS, get_region, all_cities_flat

Ubicación: /opt/canalmeteo/scripts/regions_config.py
═══════════════════════════════════════════════════════════════════════
"""

# ═════════════════════════════════════════════════════════════════════
# REGIONES
# ═════════════════════════════════════════════════════════════════════

REGIONS = {
    # ─── 1. NORESTE ─────────────────────────────────────────────────
    "noreste": {
        "id": "noreste",
        "name_es": "Noreste",
        "name_long_es": "Noreste de Estados Unidos",
        "bbox": {"west": -85.0, "east": -67.0, "south": 36.0, "north": 47.5},
        "center": {"lon": -76.0, "lat": 41.7},
        "zoom": 5.5,
        "states": ["ME", "NH", "VT", "MA", "CT", "RI", "NY", "NJ", "PA", "DE", "MD", "DC", "WV", "OH", "VA", "NC"],
        "music_file": "pronostico_noreste.mp3",
        "accent_color": "#f4a623",
        "active": True,
        "forecast_cities": [
            {"id": "boston",     "name": "Boston",     "name_es": "Boston",     "state": "MA", "state_es": "Massachusetts",  "lat": 42.3601, "lon": -71.0589, "metar": "KBOS"},
            {"id": "new-york",   "name": "New York",   "name_es": "Nueva York", "state": "NY", "state_es": "Nueva York",     "lat": 40.7128, "lon": -74.0060, "metar": "KNYC"},
            {"id": "washington", "name": "Washington", "name_es": "Washington", "state": "DC", "state_es": "D.C.",           "lat": 38.8951, "lon": -77.0364, "metar": "KDCA"},
        ],
        "tier1_cities": [  # ciudades grandes — siempre se muestran prominentemente
            {"id": "boston",       "name": "Boston",       "lat": 42.3601, "lon": -71.0589, "metar": "KBOS", "state": "MA"},
            {"id": "new-york",     "name": "New York",     "lat": 40.7128, "lon": -74.0060, "metar": "KNYC", "state": "NY"},
            {"id": "philadelphia", "name": "Philadelphia", "lat": 39.9526, "lon": -75.1652, "metar": "KPHL", "state": "PA"},
            {"id": "washington",   "name": "Washington",   "lat": 38.8951, "lon": -77.0364, "metar": "KDCA", "state": "DC"},
            {"id": "pittsburgh",   "name": "Pittsburgh",   "lat": 40.4406, "lon": -79.9959, "metar": "KPIT", "state": "PA"},
        ],
        "tier2_cities": [
            {"id": "detroit",      "name": "Detroit",      "lat": 42.3314, "lon": -83.0458, "metar": "KDET", "state": "MI"},
            {"id": "cleveland",    "name": "Cleveland",    "lat": 41.4993, "lon": -81.6944, "metar": "KCLE", "state": "OH"},
            {"id": "buffalo",      "name": "Buffalo",      "lat": 42.8864, "lon": -78.8784, "metar": "KBUF", "state": "NY"},
            {"id": "syracuse",     "name": "Syracuse",     "lat": 43.0481, "lon": -76.1474, "metar": "KSYR", "state": "NY"},
            {"id": "albany",       "name": "Albany",       "lat": 42.6526, "lon": -73.7562, "metar": "KALB", "state": "NY"},
            {"id": "hartford",     "name": "Hartford",     "lat": 41.7658, "lon": -72.6734, "metar": "KBDL", "state": "CT"},
            {"id": "newark",       "name": "Newark",       "lat": 40.7357, "lon": -74.1724, "metar": "KEWR", "state": "NJ"},
            {"id": "baltimore",    "name": "Baltimore",    "lat": 39.2904, "lon": -76.6122, "metar": "KBWI", "state": "MD"},
            {"id": "richmond",     "name": "Richmond",     "lat": 37.5407, "lon": -77.4360, "metar": "KRIC", "state": "VA"},
            {"id": "charleston",   "name": "Charleston",   "lat": 38.3498, "lon": -81.6326, "metar": "KCRW", "state": "WV"},
            {"id": "cincinnati",   "name": "Cincinnati",   "lat": 39.1031, "lon": -84.5120, "metar": "KCVG", "state": "OH"},
            {"id": "columbus",     "name": "Columbus",     "lat": 39.9612, "lon": -82.9988, "metar": "KCMH", "state": "OH"},
            {"id": "indianapolis", "name": "Indianapolis", "lat": 39.7684, "lon": -86.1581, "metar": "KIND", "state": "IN"},
        ],
        "tier3_cities": [
            {"id": "erie",         "name": "Erie",         "lat": 42.1292, "lon": -80.0851, "metar": "KERI", "state": "PA"},
            {"id": "harrisburg",   "name": "Harrisburg",   "lat": 40.2732, "lon": -76.8867, "metar": "KMDT", "state": "PA"},
            {"id": "lexington",    "name": "Lexington",    "lat": 38.0406, "lon": -84.5037, "metar": "KLEX", "state": "KY"},
            {"id": "raleigh",      "name": "Raleigh",      "lat": 35.7796, "lon": -78.6382, "metar": "KRDU", "state": "NC"},
            {"id": "norfolk",      "name": "Norfolk",      "lat": 36.8508, "lon": -76.2859, "metar": "KORF", "state": "VA"},
            {"id": "manchester",   "name": "Manchester",   "lat": 42.9956, "lon": -71.4548, "metar": "KMHT", "state": "NH"},
            {"id": "portland-me",  "name": "Portland",     "lat": 43.6591, "lon": -70.2568, "metar": "KPWM", "state": "ME"},
            {"id": "burlington",   "name": "Burlington",   "lat": 44.4759, "lon": -73.2121, "metar": "KBTV", "state": "VT"},
            {"id": "providence",   "name": "Providence",   "lat": 41.8240, "lon": -71.4128, "metar": "KPVD", "state": "RI"},
        ],
    },

    # ─── 2. SURESTE ─────────────────────────────────────────────────
    "sureste": {
        "id": "sureste",
        "name_es": "Sureste",
        "name_long_es": "Sureste de Estados Unidos",
        "bbox": {"west": -92.0, "east": -75.0, "south": 30.0, "north": 38.0},
        "center": {"lon": -84.0, "lat": 34.0},
        "zoom": 5.5,
        "states": ["NC", "SC", "GA", "AL", "MS", "TN", "KY", "AR", "LA"],
        "music_file": "pronostico_sureste.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "atlanta",   "name": "Atlanta",   "name_es": "Atlanta",   "state": "GA", "state_es": "Georgia",        "lat": 33.7490, "lon": -84.3880, "metar": "KATL"},
            {"id": "charlotte", "name": "Charlotte", "name_es": "Charlotte", "state": "NC", "state_es": "Carolina del N.", "lat": 35.2271, "lon": -80.8431, "metar": "KCLT"},
            {"id": "nashville", "name": "Nashville", "name_es": "Nashville", "state": "TN", "state_es": "Tennessee",      "lat": 36.1627, "lon": -86.7816, "metar": "KBNA"},
        ],
        "tier1_cities": [
            {"id": "atlanta",       "name": "Atlanta",       "lat": 33.7490, "lon": -84.3880, "metar": "KATL", "state": "GA"},
            {"id": "charlotte",     "name": "Charlotte",     "lat": 35.2271, "lon": -80.8431, "metar": "KCLT", "state": "NC"},
            {"id": "nashville",     "name": "Nashville",     "lat": 36.1627, "lon": -86.7816, "metar": "KBNA", "state": "TN"},
            {"id": "memphis",       "name": "Memphis",       "lat": 35.1495, "lon": -90.0490, "metar": "KMEM", "state": "TN"},
            {"id": "birmingham",    "name": "Birmingham",    "lat": 33.5186, "lon": -86.8104, "metar": "KBHM", "state": "AL"},
        ],
        "tier2_cities": [
            {"id": "raleigh",       "name": "Raleigh",       "lat": 35.7796, "lon": -78.6382, "metar": "KRDU", "state": "NC"},
            {"id": "columbia",      "name": "Columbia",      "lat": 34.0007, "lon": -81.0348, "metar": "KCAE", "state": "SC"},
            {"id": "charleston-sc", "name": "Charleston",    "lat": 32.7765, "lon": -79.9311, "metar": "KCHS", "state": "SC"},
            {"id": "savannah",      "name": "Savannah",      "lat": 32.0809, "lon": -81.0912, "metar": "KSAV", "state": "GA"},
            {"id": "knoxville",     "name": "Knoxville",     "lat": 35.9606, "lon": -83.9207, "metar": "KTYS", "state": "TN"},
            {"id": "huntsville",    "name": "Huntsville",    "lat": 34.7304, "lon": -86.5861, "metar": "KHSV", "state": "AL"},
            {"id": "mobile",        "name": "Mobile",        "lat": 30.6954, "lon": -88.0399, "metar": "KMOB", "state": "AL"},
            {"id": "jackson-ms",    "name": "Jackson",       "lat": 32.2988, "lon": -90.1848, "metar": "KJAN", "state": "MS"},
            {"id": "little-rock",   "name": "Little Rock",   "lat": 34.7465, "lon": -92.2896, "metar": "KLIT", "state": "AR"},
            {"id": "lexington",     "name": "Lexington",     "lat": 38.0406, "lon": -84.5037, "metar": "KLEX", "state": "KY"},
            {"id": "louisville",    "name": "Louisville",    "lat": 38.2527, "lon": -85.7585, "metar": "KSDF", "state": "KY"},
            {"id": "new-orleans",   "name": "New Orleans",   "lat": 29.9511, "lon": -90.0715, "metar": "KMSY", "state": "LA"},
        ],
        "tier3_cities": [
            {"id": "asheville",     "name": "Asheville",     "lat": 35.5951, "lon": -82.5515, "metar": "KAVL", "state": "NC"},
            {"id": "augusta",       "name": "Augusta",       "lat": 33.4735, "lon": -82.0105, "metar": "KAGS", "state": "GA"},
            {"id": "macon",         "name": "Macon",         "lat": 32.8407, "lon": -83.6324, "metar": "KMCN", "state": "GA"},
            {"id": "shreveport",    "name": "Shreveport",    "lat": 32.5252, "lon": -93.7502, "metar": "KSHV", "state": "LA"},
            {"id": "fayetteville",  "name": "Fayetteville",  "lat": 35.0527, "lon": -78.8784, "metar": "KFAY", "state": "NC"},
        ],
    },

    # ─── 3. FLORIDA ─────────────────────────────────────────────────
    "florida": {
        "id": "florida",
        "name_es": "Florida",
        "name_long_es": "Florida",
        "bbox": {"west": -87.5, "east": -80.0, "south": 24.5, "north": 31.0},
        "center": {"lon": -83.5, "lat": 27.8},
        "zoom": 6.0,
        "states": ["FL"],
        "music_file": "pronostico_florida.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "miami",   "name": "Miami",   "name_es": "Miami",   "state": "FL", "state_es": "Florida", "lat": 25.7617, "lon": -80.1918, "metar": "KMIA"},
            {"id": "orlando", "name": "Orlando", "name_es": "Orlando", "state": "FL", "state_es": "Florida", "lat": 28.5383, "lon": -81.3792, "metar": "KMCO"},
            {"id": "tampa",   "name": "Tampa",   "name_es": "Tampa",   "state": "FL", "state_es": "Florida", "lat": 27.9506, "lon": -82.4572, "metar": "KTPA"},
        ],
        "tier1_cities": [
            {"id": "miami",         "name": "Miami",         "lat": 25.7617, "lon": -80.1918, "metar": "KMIA", "state": "FL"},
            {"id": "orlando",       "name": "Orlando",       "lat": 28.5383, "lon": -81.3792, "metar": "KMCO", "state": "FL"},
            {"id": "tampa",         "name": "Tampa",         "lat": 27.9506, "lon": -82.4572, "metar": "KTPA", "state": "FL"},
            {"id": "jacksonville",  "name": "Jacksonville",  "lat": 30.3322, "lon": -81.6557, "metar": "KJAX", "state": "FL"},
        ],
        "tier2_cities": [
            {"id": "fort-lauderdale", "name": "Fort Lauderdale", "lat": 26.1224, "lon": -80.1373, "metar": "KFLL", "state": "FL"},
            {"id": "west-palm",       "name": "West Palm Beach", "lat": 26.7153, "lon": -80.0534, "metar": "KPBI", "state": "FL"},
            {"id": "fort-myers",      "name": "Fort Myers",      "lat": 26.6406, "lon": -81.8723, "metar": "KFMY", "state": "FL"},
            {"id": "naples",          "name": "Naples",          "lat": 26.1420, "lon": -81.7948, "metar": "KAPF", "state": "FL"},
            {"id": "tallahassee",     "name": "Tallahassee",     "lat": 30.4383, "lon": -84.2807, "metar": "KTLH", "state": "FL"},
            {"id": "pensacola",       "name": "Pensacola",       "lat": 30.4213, "lon": -87.2169, "metar": "KPNS", "state": "FL"},
            {"id": "key-west",        "name": "Key West",        "lat": 24.5551, "lon": -81.7800, "metar": "KEYW", "state": "FL"},
            {"id": "daytona",         "name": "Daytona Beach",   "lat": 29.2108, "lon": -81.0228, "metar": "KDAB", "state": "FL"},
        ],
        "tier3_cities": [
            {"id": "gainesville",     "name": "Gainesville",     "lat": 29.6516, "lon": -82.3248, "metar": "KGNV", "state": "FL"},
            {"id": "ocala",           "name": "Ocala",           "lat": 29.1872, "lon": -82.1401, "metar": "KOCF", "state": "FL"},
            {"id": "panama-city",     "name": "Panama City",     "lat": 30.1588, "lon": -85.6602, "metar": "KPFN", "state": "FL"},
        ],
    },

    # ─── 4. GRANDES LAGOS ───────────────────────────────────────────
    "grandes-lagos": {
        "id": "grandes-lagos",
        "name_es": "Grandes Lagos",
        "name_long_es": "Región de los Grandes Lagos",
        "bbox": {"west": -93.0, "east": -75.0, "south": 41.0, "north": 49.0},
        "center": {"lon": -84.0, "lat": 45.0},
        "zoom": 5.5,
        "states": ["MN", "WI", "MI", "IL", "IN", "OH", "PA", "NY"],
        "music_file": "pronostico_grandes_lagos.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "chicago",     "name": "Chicago",     "name_es": "Chicago",     "state": "IL", "state_es": "Illinois", "lat": 41.8781, "lon": -87.6298, "metar": "KORD"},
            {"id": "detroit",     "name": "Detroit",     "name_es": "Detroit",     "state": "MI", "state_es": "Michigan", "lat": 42.3314, "lon": -83.0458, "metar": "KDET"},
            {"id": "minneapolis", "name": "Minneapolis", "name_es": "Minneapolis", "state": "MN", "state_es": "Minnesota","lat": 44.9778, "lon": -93.2650, "metar": "KMSP"},
        ],
        "tier1_cities": [
            {"id": "chicago",       "name": "Chicago",       "lat": 41.8781, "lon": -87.6298, "metar": "KORD", "state": "IL"},
            {"id": "detroit",       "name": "Detroit",       "lat": 42.3314, "lon": -83.0458, "metar": "KDET", "state": "MI"},
            {"id": "minneapolis",   "name": "Minneapolis",   "lat": 44.9778, "lon": -93.2650, "metar": "KMSP", "state": "MN"},
            {"id": "milwaukee",     "name": "Milwaukee",     "lat": 43.0389, "lon": -87.9065, "metar": "KMKE", "state": "WI"},
            {"id": "cleveland",     "name": "Cleveland",     "lat": 41.4993, "lon": -81.6944, "metar": "KCLE", "state": "OH"},
        ],
        "tier2_cities": [
            {"id": "indianapolis",  "name": "Indianapolis",  "lat": 39.7684, "lon": -86.1581, "metar": "KIND", "state": "IN"},
            {"id": "columbus",      "name": "Columbus",      "lat": 39.9612, "lon": -82.9988, "metar": "KCMH", "state": "OH"},
            {"id": "buffalo",       "name": "Buffalo",       "lat": 42.8864, "lon": -78.8784, "metar": "KBUF", "state": "NY"},
            {"id": "rochester",     "name": "Rochester",     "lat": 43.1566, "lon": -77.6088, "metar": "KROC", "state": "NY"},
            {"id": "grand-rapids",  "name": "Grand Rapids",  "lat": 42.9634, "lon": -85.6681, "metar": "KGRR", "state": "MI"},
            {"id": "madison",       "name": "Madison",       "lat": 43.0731, "lon": -89.4012, "metar": "KMSN", "state": "WI"},
            {"id": "green-bay",     "name": "Green Bay",     "lat": 44.5133, "lon": -88.0133, "metar": "KGRB", "state": "WI"},
            {"id": "duluth",        "name": "Duluth",        "lat": 46.7867, "lon": -92.1005, "metar": "KDLH", "state": "MN"},
            {"id": "fort-wayne",    "name": "Fort Wayne",    "lat": 41.0793, "lon": -85.1394, "metar": "KFWA", "state": "IN"},
            {"id": "toledo",        "name": "Toledo",        "lat": 41.6528, "lon": -83.5379, "metar": "KTOL", "state": "OH"},
        ],
        "tier3_cities": [
            {"id": "lansing",       "name": "Lansing",       "lat": 42.7325, "lon": -84.5555, "metar": "KLAN", "state": "MI"},
            {"id": "rockford",      "name": "Rockford",      "lat": 42.2711, "lon": -89.0940, "metar": "KRFD", "state": "IL"},
            {"id": "peoria",        "name": "Peoria",        "lat": 40.6936, "lon": -89.5890, "metar": "KPIA", "state": "IL"},
            {"id": "south-bend",    "name": "South Bend",    "lat": 41.6764, "lon": -86.2520, "metar": "KSBN", "state": "IN"},
        ],
    },

    # ─── 5. TEXAS / SUR ─────────────────────────────────────────────
    "texas": {
        "id": "texas",
        "name_es": "Texas y Sur",
        "name_long_es": "Texas y región del Golfo",
        "bbox": {"west": -107.0, "east": -93.5, "south": 25.8, "north": 36.5},
        "center": {"lon": -99.5, "lat": 31.0},
        "zoom": 5.5,
        "states": ["TX", "OK", "NM"],
        "music_file": "pronostico_texas.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "houston",     "name": "Houston",     "name_es": "Houston",     "state": "TX", "state_es": "Texas", "lat": 29.7604, "lon": -95.3698, "metar": "KIAH"},
            {"id": "dallas",      "name": "Dallas",      "name_es": "Dallas",      "state": "TX", "state_es": "Texas", "lat": 32.7767, "lon": -96.7970, "metar": "KDFW"},
            {"id": "san-antonio", "name": "San Antonio", "name_es": "San Antonio", "state": "TX", "state_es": "Texas", "lat": 29.4241, "lon": -98.4936, "metar": "KSAT"},
        ],
        "tier1_cities": [
            {"id": "houston",       "name": "Houston",       "lat": 29.7604, "lon": -95.3698, "metar": "KIAH", "state": "TX"},
            {"id": "dallas",        "name": "Dallas",        "lat": 32.7767, "lon": -96.7970, "metar": "KDFW", "state": "TX"},
            {"id": "san-antonio",   "name": "San Antonio",   "lat": 29.4241, "lon": -98.4936, "metar": "KSAT", "state": "TX"},
            {"id": "austin",        "name": "Austin",        "lat": 30.2672, "lon": -97.7431, "metar": "KAUS", "state": "TX"},
            {"id": "fort-worth",    "name": "Fort Worth",    "lat": 32.7555, "lon": -97.3308, "metar": "KFTW", "state": "TX"},
        ],
        "tier2_cities": [
            {"id": "el-paso",       "name": "El Paso",       "lat": 31.7619, "lon": -106.4850, "metar": "KELP", "state": "TX"},
            {"id": "corpus",        "name": "Corpus Christi","lat": 27.8006, "lon": -97.3964,  "metar": "KCRP", "state": "TX"},
            {"id": "lubbock",       "name": "Lubbock",       "lat": 33.5779, "lon": -101.8552, "metar": "KLBB", "state": "TX"},
            {"id": "amarillo",      "name": "Amarillo",      "lat": 35.2220, "lon": -101.8313, "metar": "KAMA", "state": "TX"},
            {"id": "midland",       "name": "Midland",       "lat": 31.9974, "lon": -102.0779, "metar": "KMAF", "state": "TX"},
            {"id": "waco",          "name": "Waco",          "lat": 31.5494, "lon": -97.1467,  "metar": "KACT", "state": "TX"},
            {"id": "brownsville",   "name": "Brownsville",   "lat": 25.9018, "lon": -97.4975,  "metar": "KBRO", "state": "TX"},
            {"id": "mcallen",       "name": "McAllen",       "lat": 26.2034, "lon": -98.2300,  "metar": "KMFE", "state": "TX"},
            {"id": "oklahoma-city", "name": "Oklahoma City", "lat": 35.4676, "lon": -97.5164,  "metar": "KOKC", "state": "OK"},
            {"id": "tulsa",         "name": "Tulsa",         "lat": 36.1540, "lon": -95.9928,  "metar": "KTUL", "state": "OK"},
            {"id": "albuquerque",   "name": "Albuquerque",   "lat": 35.0844, "lon": -106.6504, "metar": "KABQ", "state": "NM"},
        ],
        "tier3_cities": [
            {"id": "abilene",       "name": "Abilene",       "lat": 32.4487, "lon": -99.7331,  "metar": "KABI", "state": "TX"},
            {"id": "san-angelo",    "name": "San Angelo",    "lat": 31.4638, "lon": -100.4370, "metar": "KSJT", "state": "TX"},
            {"id": "tyler",         "name": "Tyler",         "lat": 32.3513, "lon": -95.3011,  "metar": "KTYR", "state": "TX"},
            {"id": "santa-fe",      "name": "Santa Fe",      "lat": 35.6870, "lon": -105.9378, "metar": "KSAF", "state": "NM"},
        ],
    },

    # ─── 6. MEDIO OESTE ─────────────────────────────────────────────
    "medio-oeste": {
        "id": "medio-oeste",
        "name_es": "Medio Oeste",
        "name_long_es": "Medio Oeste de Estados Unidos",
        "bbox": {"west": -104.0, "east": -87.0, "south": 36.0, "north": 49.0},
        "center": {"lon": -95.5, "lat": 42.5},
        "zoom": 5.5,
        "states": ["ND", "SD", "NE", "KS", "OK", "MO", "IA", "MN", "WI"],
        "music_file": "pronostico_medio_oeste.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "kansas-city", "name": "Kansas City", "name_es": "Kansas City", "state": "MO", "state_es": "Misuri",   "lat": 39.0997, "lon": -94.5786, "metar": "KMCI"},
            {"id": "st-louis",    "name": "St. Louis",   "name_es": "San Luis",    "state": "MO", "state_es": "Misuri",   "lat": 38.6270, "lon": -90.1994, "metar": "KSTL"},
            {"id": "minneapolis", "name": "Minneapolis", "name_es": "Minneapolis", "state": "MN", "state_es": "Minnesota","lat": 44.9778, "lon": -93.2650, "metar": "KMSP"},
        ],
        "tier1_cities": [
            {"id": "kansas-city",  "name": "Kansas City", "lat": 39.0997, "lon": -94.5786, "metar": "KMCI", "state": "MO"},
            {"id": "st-louis",     "name": "St. Louis",   "lat": 38.6270, "lon": -90.1994, "metar": "KSTL", "state": "MO"},
            {"id": "minneapolis",  "name": "Minneapolis", "lat": 44.9778, "lon": -93.2650, "metar": "KMSP", "state": "MN"},
            {"id": "omaha",        "name": "Omaha",       "lat": 41.2565, "lon": -95.9345, "metar": "KOMA", "state": "NE"},
            {"id": "des-moines",   "name": "Des Moines",  "lat": 41.5868, "lon": -93.6250, "metar": "KDSM", "state": "IA"},
        ],
        "tier2_cities": [
            {"id": "wichita",      "name": "Wichita",      "lat": 37.6872, "lon": -97.3301, "metar": "KICT", "state": "KS"},
            {"id": "topeka",       "name": "Topeka",       "lat": 39.0473, "lon": -95.6752, "metar": "KTOP", "state": "KS"},
            {"id": "fargo",        "name": "Fargo",        "lat": 46.8772, "lon": -96.7898, "metar": "KFAR", "state": "ND"},
            {"id": "bismarck",     "name": "Bismarck",     "lat": 46.8083, "lon": -100.7837,"metar": "KBIS", "state": "ND"},
            {"id": "sioux-falls",  "name": "Sioux Falls",  "lat": 43.5446, "lon": -96.7311, "metar": "KFSD", "state": "SD"},
            {"id": "rapid-city",   "name": "Rapid City",   "lat": 44.0805, "lon": -103.2310,"metar": "KRAP", "state": "SD"},
            {"id": "lincoln",      "name": "Lincoln",      "lat": 40.8136, "lon": -96.7026, "metar": "KLNK", "state": "NE"},
            {"id": "cedar-rapids", "name": "Cedar Rapids", "lat": 41.9779, "lon": -91.6656, "metar": "KCID", "state": "IA"},
            {"id": "springfield-mo","name":"Springfield",  "lat": 37.2090, "lon": -93.2923, "metar": "KSGF", "state": "MO"},
            {"id": "duluth",       "name": "Duluth",       "lat": 46.7867, "lon": -92.1005, "metar": "KDLH", "state": "MN"},
        ],
        "tier3_cities": [
            {"id": "rochester-mn", "name": "Rochester",    "lat": 44.0121, "lon": -92.4802, "metar": "KRST", "state": "MN"},
            {"id": "dubuque",      "name": "Dubuque",      "lat": 42.5006, "lon": -90.6646, "metar": "KDBQ", "state": "IA"},
        ],
    },

    # ─── 7. SUROESTE ────────────────────────────────────────────────
    "suroeste": {
        "id": "suroeste",
        "name_es": "Suroeste",
        "name_long_es": "Suroeste de Estados Unidos",
        "bbox": {"west": -115.0, "east": -103.0, "south": 31.0, "north": 42.0},
        "center": {"lon": -109.0, "lat": 36.5},
        "zoom": 5.5,
        "states": ["AZ", "NM", "UT", "NV", "CO"],
        "music_file": "pronostico_suroeste.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "phoenix",     "name": "Phoenix",     "name_es": "Phoenix",     "state": "AZ", "state_es": "Arizona",  "lat": 33.4484, "lon": -112.0740, "metar": "KPHX"},
            {"id": "denver",      "name": "Denver",      "name_es": "Denver",      "state": "CO", "state_es": "Colorado", "lat": 39.7392, "lon": -104.9903, "metar": "KDEN"},
            {"id": "las-vegas",   "name": "Las Vegas",   "name_es": "Las Vegas",   "state": "NV", "state_es": "Nevada",   "lat": 36.1699, "lon": -115.1398, "metar": "KLAS"},
        ],
        "tier1_cities": [
            {"id": "phoenix",       "name": "Phoenix",       "lat": 33.4484, "lon": -112.0740, "metar": "KPHX", "state": "AZ"},
            {"id": "denver",        "name": "Denver",        "lat": 39.7392, "lon": -104.9903, "metar": "KDEN", "state": "CO"},
            {"id": "las-vegas",     "name": "Las Vegas",     "lat": 36.1699, "lon": -115.1398, "metar": "KLAS", "state": "NV"},
            {"id": "salt-lake",     "name": "Salt Lake City","lat": 40.7608, "lon": -111.8910, "metar": "KSLC", "state": "UT"},
            {"id": "albuquerque",   "name": "Albuquerque",   "lat": 35.0844, "lon": -106.6504, "metar": "KABQ", "state": "NM"},
        ],
        "tier2_cities": [
            {"id": "tucson",        "name": "Tucson",        "lat": 32.2226, "lon": -110.9747, "metar": "KTUS", "state": "AZ"},
            {"id": "flagstaff",     "name": "Flagstaff",     "lat": 35.1983, "lon": -111.6513, "metar": "KFLG", "state": "AZ"},
            {"id": "santa-fe",      "name": "Santa Fe",      "lat": 35.6870, "lon": -105.9378, "metar": "KSAF", "state": "NM"},
            {"id": "colorado-springs","name":"Colorado Springs","lat":38.8339,"lon":-104.8214,"metar":"KCOS","state":"CO"},
            {"id": "reno",          "name": "Reno",          "lat": 39.5296, "lon": -119.8138, "metar": "KRNO", "state": "NV"},
            {"id": "provo",         "name": "Provo",         "lat": 40.2338, "lon": -111.6585, "metar": "KPVU", "state": "UT"},
            {"id": "grand-junction","name": "Grand Junction","lat": 39.0639, "lon": -108.5506, "metar": "KGJT", "state": "CO"},
        ],
        "tier3_cities": [
            {"id": "yuma",          "name": "Yuma",          "lat": 32.6927, "lon": -114.6277, "metar": "KYUM", "state": "AZ"},
            {"id": "roswell",       "name": "Roswell",       "lat": 33.3943, "lon": -104.5230, "metar": "KROW", "state": "NM"},
            {"id": "pueblo",        "name": "Pueblo",        "lat": 38.2544, "lon": -104.6091, "metar": "KPUB", "state": "CO"},
        ],
    },

    # ─── 8. NOROESTE ────────────────────────────────────────────────
    "noroeste": {
        "id": "noroeste",
        "name_es": "Noroeste",
        "name_long_es": "Noroeste del Pacífico",
        "bbox": {"west": -125.0, "east": -110.0, "south": 41.0, "north": 49.0},
        "center": {"lon": -118.0, "lat": 45.0},
        "zoom": 5.5,
        "states": ["WA", "OR", "ID", "MT", "WY"],
        "music_file": "pronostico_noroeste.mp3",
        "accent_color": "#f4a623",
        "active": False,
        "forecast_cities": [
            {"id": "seattle",  "name": "Seattle",  "name_es": "Seattle",  "state": "WA", "state_es": "Washington", "lat": 47.6062, "lon": -122.3321, "metar": "KSEA"},
            {"id": "portland", "name": "Portland", "name_es": "Portland", "state": "OR", "state_es": "Oregón",     "lat": 45.5152, "lon": -122.6784, "metar": "KPDX"},
            {"id": "boise",    "name": "Boise",    "name_es": "Boise",    "state": "ID", "state_es": "Idaho",      "lat": 43.6150, "lon": -116.2023, "metar": "KBOI"},
        ],
        "tier1_cities": [
            {"id": "seattle",       "name": "Seattle",       "lat": 47.6062, "lon": -122.3321, "metar": "KSEA", "state": "WA"},
            {"id": "portland",      "name": "Portland",      "lat": 45.5152, "lon": -122.6784, "metar": "KPDX", "state": "OR"},
            {"id": "boise",         "name": "Boise",         "lat": 43.6150, "lon": -116.2023, "metar": "KBOI", "state": "ID"},
            {"id": "spokane",       "name": "Spokane",       "lat": 47.6588, "lon": -117.4260, "metar": "KGEG", "state": "WA"},
        ],
        "tier2_cities": [
            {"id": "tacoma",        "name": "Tacoma",        "lat": 47.2529, "lon": -122.4443, "metar": "KTCM", "state": "WA"},
            {"id": "yakima",        "name": "Yakima",        "lat": 46.6021, "lon": -120.5059, "metar": "KYKM", "state": "WA"},
            {"id": "eugene",        "name": "Eugene",        "lat": 44.0521, "lon": -123.0868, "metar": "KEUG", "state": "OR"},
            {"id": "salem",         "name": "Salem",         "lat": 44.9429, "lon": -123.0351, "metar": "KSLE", "state": "OR"},
            {"id": "medford",       "name": "Medford",       "lat": 42.3265, "lon": -122.8756, "metar": "KMFR", "state": "OR"},
            {"id": "bend",          "name": "Bend",          "lat": 44.0582, "lon": -121.3153, "metar": "KBDN", "state": "OR"},
            {"id": "billings",      "name": "Billings",      "lat": 45.7833, "lon": -108.5007, "metar": "KBIL", "state": "MT"},
            {"id": "missoula",      "name": "Missoula",      "lat": 46.8721, "lon": -113.9940, "metar": "KMSO", "state": "MT"},
            {"id": "great-falls",   "name": "Great Falls",   "lat": 47.5053, "lon": -111.3008, "metar": "KGTF", "state": "MT"},
            {"id": "casper",        "name": "Casper",        "lat": 42.8666, "lon": -106.3131, "metar": "KCPR", "state": "WY"},
            {"id": "cheyenne",      "name": "Cheyenne",      "lat": 41.1400, "lon": -104.8202, "metar": "KCYS", "state": "WY"},
            {"id": "idaho-falls",   "name": "Idaho Falls",   "lat": 43.4917, "lon": -112.0339, "metar": "KIDA", "state": "ID"},
        ],
        "tier3_cities": [
            {"id": "olympia",       "name": "Olympia",       "lat": 47.0379, "lon": -122.9007, "metar": "KOLM", "state": "WA"},
            {"id": "bellingham",    "name": "Bellingham",    "lat": 48.7519, "lon": -122.4787, "metar": "KBLI", "state": "WA"},
            {"id": "bozeman",       "name": "Bozeman",       "lat": 45.6770, "lon": -111.0429, "metar": "KBZN", "state": "MT"},
        ],
    },
}


# ═════════════════════════════════════════════════════════════════════
# FUNCIONES DE UTILIDAD
# ═════════════════════════════════════════════════════════════════════

def get_region(region_id: str) -> dict:
    """Devuelve la config de una región dada por su ID."""
    if region_id not in REGIONS:
        raise ValueError(
            f"Región '{region_id}' no existe. "
            f"Válidas: {', '.join(REGIONS.keys())}"
        )
    return REGIONS[region_id]


def all_region_ids() -> list:
    """Devuelve la lista de IDs de todas las regiones."""
    return list(REGIONS.keys())


def active_region_ids() -> list:
    """Devuelve solo las regiones activas (active=True)."""
    return [r["id"] for r in REGIONS.values() if r.get("active")]


def all_cities_flat(region_id: str = None) -> list:
    """
    Devuelve todas las ciudades (tier1 + tier2 + tier3 + forecast_cities)
    de una región, sin duplicados (por id).

    Si region_id es None, devuelve TODAS las ciudades de TODAS las regiones.
    Cada ciudad incluye campo 'region_id' para identificar a qué región pertenece.
    """
    seen_ids = set()
    cities = []

    region_ids = [region_id] if region_id else all_region_ids()

    for rid in region_ids:
        region = REGIONS[rid]
        all_tiers = (
            region.get("tier1_cities", [])
            + region.get("tier2_cities", [])
            + region.get("tier3_cities", [])
            + region.get("forecast_cities", [])
        )
        for city in all_tiers:
            key = (rid, city["id"])
            if key in seen_ids:
                continue
            seen_ids.add(key)
            cities.append({**city, "region_id": rid})

    return cities


def all_metars_unique() -> list:
    """
    Devuelve lista única de estaciones METAR usadas por todas las regiones.
    Útil para ampliar metar_pipeline.py con todas las que necesitamos.
    """
    seen = set()
    result = []
    for city in all_cities_flat():
        metar_id = city.get("metar")
        if metar_id and metar_id not in seen:
            seen.add(metar_id)
            result.append(metar_id)
    return sorted(result)


def get_bbox_for_region(region_id: str) -> dict:
    """Atajo para obtener el bbox de una región."""
    return get_region(region_id)["bbox"]


def point_in_bbox(lat: float, lon: float, bbox: dict) -> bool:
    """¿Un punto (lat, lon) está dentro del bbox?"""
    return (
        bbox["south"] <= lat <= bbox["north"]
        and bbox["west"] <= lon <= bbox["east"]
    )


def regions_containing_point(lat: float, lon: float) -> list:
    """Devuelve lista de region_ids que contienen el punto dado."""
    return [
        rid for rid, region in REGIONS.items()
        if point_in_bbox(lat, lon, region["bbox"])
    ]


# ═════════════════════════════════════════════════════════════════════
# CLI / debug
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"Total regiones: {len(REGIONS)}")
    print(f"Activas:        {len(active_region_ids())} → {', '.join(active_region_ids())}")
    print()
    for rid, region in REGIONS.items():
        active_mark = "✓" if region.get("active") else " "
        n_cities = (
            len(region.get("tier1_cities", []))
            + len(region.get("tier2_cities", []))
            + len(region.get("tier3_cities", []))
        )
        print(
            f"  [{active_mark}] {rid:15s} {region['name_es']:20s} "
            f"bbox=[{region['bbox']['west']:.0f},{region['bbox']['east']:.0f},"
            f"{region['bbox']['south']:.0f},{region['bbox']['north']:.0f}]  "
            f"{n_cities} ciudades"
        )
    print()
    print(f"Total METARs únicos: {len(all_metars_unique())}")
    print(f"Total ciudades:      {len(all_cities_flat())}")
