#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
astro_cities.py — Canal Meteo TV
Lista compartida de las 100 ciudades procesadas por todos los pipelines
astronómicos (ephemeris, planets, etc.).

Cobertura: 50 capitales estatales + DC + 49 ciudades hispanas/grandes + 3 PR.
52 estados/territorios cubiertos.

Para añadir/quitar una ciudad, editar SOLO este archivo — los pipelines
la importan dinámicamente. La regeneración del JSON tardará un poco más
con más ciudades (escala lineal: ~1.5 segundos por ciudad con Skyfield).
"""

CITIES = [
    # ===== 50 CAPITALES ESTATALES =====
    {"id": "montgomery",      "name": "Montgomery, AL",      "state": "Alabama",        "lat": 32.3792, "lon":  -86.3077, "tz": "America/Chicago"},
    {"id": "juneau",          "name": "Juneau, AK",          "state": "Alaska",         "lat": 58.3019, "lon": -134.4197, "tz": "America/Juneau"},
    {"id": "phoenix",         "name": "Phoenix, AZ",         "state": "Arizona",        "lat": 33.4484, "lon": -112.0740, "tz": "America/Phoenix"},
    {"id": "little_rock",     "name": "Little Rock, AR",     "state": "Arkansas",       "lat": 34.7465, "lon":  -92.2896, "tz": "America/Chicago"},
    {"id": "sacramento",      "name": "Sacramento, CA",      "state": "California",     "lat": 38.5816, "lon": -121.4944, "tz": "America/Los_Angeles"},
    {"id": "denver",          "name": "Denver, CO",          "state": "Colorado",       "lat": 39.7392, "lon": -104.9903, "tz": "America/Denver"},
    {"id": "hartford",        "name": "Hartford, CT",        "state": "Connecticut",    "lat": 41.7637, "lon":  -72.6851, "tz": "America/New_York"},
    {"id": "dover",           "name": "Dover, DE",           "state": "Delaware",       "lat": 39.1582, "lon":  -75.5244, "tz": "America/New_York"},
    {"id": "tallahassee",     "name": "Tallahassee, FL",     "state": "Florida",        "lat": 30.4383, "lon":  -84.2807, "tz": "America/New_York"},
    {"id": "atlanta",         "name": "Atlanta, GA",         "state": "Georgia",        "lat": 33.7490, "lon":  -84.3880, "tz": "America/New_York"},
    {"id": "honolulu",        "name": "Honolulu, HI",        "state": "Hawaii",         "lat": 21.3099, "lon": -157.8581, "tz": "Pacific/Honolulu"},
    {"id": "boise",           "name": "Boise, ID",           "state": "Idaho",          "lat": 43.6150, "lon": -116.2023, "tz": "America/Boise"},
    {"id": "springfield_il",  "name": "Springfield, IL",     "state": "Illinois",       "lat": 39.7817, "lon":  -89.6501, "tz": "America/Chicago"},
    {"id": "indianapolis",    "name": "Indianapolis, IN",    "state": "Indiana",        "lat": 39.7684, "lon":  -86.1581, "tz": "America/Indiana/Indianapolis"},
    {"id": "des_moines",      "name": "Des Moines, IA",      "state": "Iowa",           "lat": 41.5868, "lon":  -93.6250, "tz": "America/Chicago"},
    {"id": "topeka",          "name": "Topeka, KS",          "state": "Kansas",         "lat": 39.0473, "lon":  -95.6752, "tz": "America/Chicago"},
    {"id": "frankfort",       "name": "Frankfort, KY",       "state": "Kentucky",       "lat": 38.2009, "lon":  -84.8733, "tz": "America/Kentucky/Louisville"},
    {"id": "baton_rouge",     "name": "Baton Rouge, LA",     "state": "Louisiana",      "lat": 30.4515, "lon":  -91.1871, "tz": "America/Chicago"},
    {"id": "augusta",         "name": "Augusta, ME",         "state": "Maine",          "lat": 44.3107, "lon":  -69.7795, "tz": "America/New_York"},
    {"id": "annapolis",       "name": "Annapolis, MD",       "state": "Maryland",       "lat": 38.9784, "lon":  -76.4922, "tz": "America/New_York"},
    {"id": "boston",          "name": "Boston, MA",          "state": "Massachusetts",  "lat": 42.3601, "lon":  -71.0589, "tz": "America/New_York"},
    {"id": "lansing",         "name": "Lansing, MI",         "state": "Michigan",       "lat": 42.7325, "lon":  -84.5555, "tz": "America/Detroit"},
    {"id": "saint_paul",      "name": "Saint Paul, MN",      "state": "Minnesota",      "lat": 44.9537, "lon":  -93.0900, "tz": "America/Chicago"},
    {"id": "jackson",         "name": "Jackson, MS",         "state": "Mississippi",    "lat": 32.2988, "lon":  -90.1848, "tz": "America/Chicago"},
    {"id": "jefferson_city",  "name": "Jefferson City, MO",  "state": "Missouri",       "lat": 38.5767, "lon":  -92.1735, "tz": "America/Chicago"},
    {"id": "helena",          "name": "Helena, MT",          "state": "Montana",        "lat": 46.5891, "lon": -112.0391, "tz": "America/Denver"},
    {"id": "lincoln",         "name": "Lincoln, NE",         "state": "Nebraska",       "lat": 40.8136, "lon":  -96.7026, "tz": "America/Chicago"},
    {"id": "carson_city",     "name": "Carson City, NV",     "state": "Nevada",         "lat": 39.1638, "lon": -119.7674, "tz": "America/Los_Angeles"},
    {"id": "concord",         "name": "Concord, NH",         "state": "New Hampshire",  "lat": 43.2081, "lon":  -71.5376, "tz": "America/New_York"},
    {"id": "trenton",         "name": "Trenton, NJ",         "state": "New Jersey",     "lat": 40.2206, "lon":  -74.7597, "tz": "America/New_York"},
    {"id": "santa_fe",        "name": "Santa Fe, NM",        "state": "New Mexico",     "lat": 35.6870, "lon": -105.9378, "tz": "America/Denver"},
    {"id": "albany",          "name": "Albany, NY",          "state": "New York",       "lat": 42.6526, "lon":  -73.7562, "tz": "America/New_York"},
    {"id": "raleigh",         "name": "Raleigh, NC",         "state": "North Carolina", "lat": 35.7796, "lon":  -78.6382, "tz": "America/New_York"},
    {"id": "bismarck",        "name": "Bismarck, ND",        "state": "North Dakota",   "lat": 46.8083, "lon": -100.7837, "tz": "America/Chicago"},
    {"id": "columbus_oh",     "name": "Columbus, OH",        "state": "Ohio",           "lat": 39.9612, "lon":  -82.9988, "tz": "America/New_York"},
    {"id": "oklahoma_city",   "name": "Oklahoma City, OK",   "state": "Oklahoma",       "lat": 35.4676, "lon":  -97.5164, "tz": "America/Chicago"},
    {"id": "salem_or",        "name": "Salem, OR",           "state": "Oregon",         "lat": 44.9429, "lon": -123.0351, "tz": "America/Los_Angeles"},
    {"id": "harrisburg",      "name": "Harrisburg, PA",      "state": "Pennsylvania",   "lat": 40.2732, "lon":  -76.8867, "tz": "America/New_York"},
    {"id": "providence",      "name": "Providence, RI",      "state": "Rhode Island",   "lat": 41.8240, "lon":  -71.4128, "tz": "America/New_York"},
    {"id": "columbia",        "name": "Columbia, SC",        "state": "South Carolina", "lat": 34.0007, "lon":  -81.0348, "tz": "America/New_York"},
    {"id": "pierre",          "name": "Pierre, SD",          "state": "South Dakota",   "lat": 44.3683, "lon": -100.3510, "tz": "America/Chicago"},
    {"id": "nashville",       "name": "Nashville, TN",       "state": "Tennessee",      "lat": 36.1627, "lon":  -86.7816, "tz": "America/Chicago"},
    {"id": "austin",          "name": "Austin, TX",          "state": "Texas",          "lat": 30.2672, "lon":  -97.7431, "tz": "America/Chicago"},
    {"id": "salt_lake_city",  "name": "Salt Lake City, UT",  "state": "Utah",           "lat": 40.7608, "lon": -111.8910, "tz": "America/Denver"},
    {"id": "montpelier",      "name": "Montpelier, VT",      "state": "Vermont",        "lat": 44.2601, "lon":  -72.5754, "tz": "America/New_York"},
    {"id": "richmond",        "name": "Richmond, VA",        "state": "Virginia",       "lat": 37.5407, "lon":  -77.4360, "tz": "America/New_York"},
    {"id": "olympia",         "name": "Olympia, WA",         "state": "Washington",     "lat": 47.0379, "lon": -122.9007, "tz": "America/Los_Angeles"},
    {"id": "charleston_wv",   "name": "Charleston, WV",      "state": "West Virginia",  "lat": 38.3498, "lon":  -81.6326, "tz": "America/New_York"},
    {"id": "madison",         "name": "Madison, WI",         "state": "Wisconsin",      "lat": 43.0731, "lon":  -89.4012, "tz": "America/Chicago"},
    {"id": "cheyenne",        "name": "Cheyenne, WY",        "state": "Wyoming",        "lat": 41.1400, "lon": -104.8202, "tz": "America/Denver"},

    # ===== WASHINGTON DC =====
    {"id": "washington_dc",   "name": "Washington, DC",      "state": "District of Columbia", "lat": 38.9072, "lon": -77.0369, "tz": "America/New_York"},

    # ===== TEXAS — núcleo hispano (11) =====
    {"id": "houston",         "name": "Houston, TX",         "state": "Texas",          "lat": 29.7604, "lon":  -95.3698, "tz": "America/Chicago"},
    {"id": "dallas",          "name": "Dallas, TX",          "state": "Texas",          "lat": 32.7767, "lon":  -96.7970, "tz": "America/Chicago"},
    {"id": "san_antonio",     "name": "San Antonio, TX",     "state": "Texas",          "lat": 29.4241, "lon":  -98.4936, "tz": "America/Chicago"},
    {"id": "fort_worth",      "name": "Fort Worth, TX",      "state": "Texas",          "lat": 32.7555, "lon":  -97.3308, "tz": "America/Chicago"},
    {"id": "el_paso",         "name": "El Paso, TX",         "state": "Texas",          "lat": 31.7619, "lon": -106.4850, "tz": "America/Denver"},
    {"id": "corpus_christi",  "name": "Corpus Christi, TX",  "state": "Texas",          "lat": 27.8006, "lon":  -97.3964, "tz": "America/Chicago"},
    {"id": "mcallen",         "name": "McAllen, TX",         "state": "Texas",          "lat": 26.2034, "lon":  -98.2300, "tz": "America/Chicago"},
    {"id": "brownsville",     "name": "Brownsville, TX",     "state": "Texas",          "lat": 25.9018, "lon":  -97.4975, "tz": "America/Chicago"},
    {"id": "laredo",          "name": "Laredo, TX",          "state": "Texas",          "lat": 27.5036, "lon":  -99.5076, "tz": "America/Chicago"},
    {"id": "lubbock",         "name": "Lubbock, TX",         "state": "Texas",          "lat": 33.5779, "lon": -101.8552, "tz": "America/Chicago"},
    {"id": "amarillo",        "name": "Amarillo, TX",        "state": "Texas",          "lat": 35.2220, "lon": -101.8313, "tz": "America/Chicago"},

    # ===== FLORIDA — núcleo hispano (6) =====
    {"id": "miami",           "name": "Miami, FL",           "state": "Florida",        "lat": 25.7617, "lon":  -80.1918, "tz": "America/New_York"},
    {"id": "orlando",         "name": "Orlando, FL",         "state": "Florida",        "lat": 28.5384, "lon":  -81.3789, "tz": "America/New_York"},
    {"id": "tampa",           "name": "Tampa, FL",           "state": "Florida",        "lat": 27.9506, "lon":  -82.4572, "tz": "America/New_York"},
    {"id": "jacksonville",    "name": "Jacksonville, FL",    "state": "Florida",        "lat": 30.3322, "lon":  -81.6557, "tz": "America/New_York"},
    {"id": "hialeah",         "name": "Hialeah, FL",         "state": "Florida",        "lat": 25.8576, "lon":  -80.2781, "tz": "America/New_York"},
    {"id": "fort_lauderdale", "name": "Fort Lauderdale, FL", "state": "Florida",        "lat": 26.1224, "lon":  -80.1373, "tz": "America/New_York"},

    # ===== CALIFORNIA — núcleo hispano (10) =====
    {"id": "los_angeles",     "name": "Los Angeles, CA",     "state": "California",     "lat": 34.0522, "lon": -118.2437, "tz": "America/Los_Angeles"},
    {"id": "san_diego",       "name": "San Diego, CA",       "state": "California",     "lat": 32.7157, "lon": -117.1611, "tz": "America/Los_Angeles"},
    {"id": "san_jose",        "name": "San Jose, CA",        "state": "California",     "lat": 37.3382, "lon": -121.8863, "tz": "America/Los_Angeles"},
    {"id": "san_francisco",   "name": "San Francisco, CA",   "state": "California",     "lat": 37.7749, "lon": -122.4194, "tz": "America/Los_Angeles"},
    {"id": "fresno",          "name": "Fresno, CA",          "state": "California",     "lat": 36.7378, "lon": -119.7871, "tz": "America/Los_Angeles"},
    {"id": "long_beach",      "name": "Long Beach, CA",      "state": "California",     "lat": 33.7701, "lon": -118.1937, "tz": "America/Los_Angeles"},
    {"id": "bakersfield",     "name": "Bakersfield, CA",     "state": "California",     "lat": 35.3733, "lon": -119.0187, "tz": "America/Los_Angeles"},
    {"id": "anaheim",         "name": "Anaheim, CA",         "state": "California",     "lat": 33.8366, "lon": -117.9143, "tz": "America/Los_Angeles"},
    {"id": "santa_ana",       "name": "Santa Ana, CA",       "state": "California",     "lat": 33.7455, "lon": -117.8678, "tz": "America/Los_Angeles"},
    {"id": "riverside",       "name": "Riverside, CA",       "state": "California",     "lat": 33.9806, "lon": -117.3755, "tz": "America/Los_Angeles"},

    # ===== NORESTE — alta densidad hispana (5) =====
    {"id": "new_york",        "name": "New York, NY",        "state": "New York",       "lat": 40.7128, "lon":  -74.0060, "tz": "America/New_York"},
    {"id": "newark",          "name": "Newark, NJ",          "state": "New Jersey",     "lat": 40.7357, "lon":  -74.1724, "tz": "America/New_York"},
    {"id": "jersey_city",     "name": "Jersey City, NJ",     "state": "New Jersey",     "lat": 40.7178, "lon":  -74.0431, "tz": "America/New_York"},
    {"id": "paterson",        "name": "Paterson, NJ",        "state": "New Jersey",     "lat": 40.9168, "lon":  -74.1718, "tz": "America/New_York"},
    {"id": "philadelphia",    "name": "Philadelphia, PA",    "state": "Pennsylvania",   "lat": 39.9526, "lon":  -75.1652, "tz": "America/New_York"},

    # ===== GRANDES CIUDADES (otras) (12) =====
    {"id": "chicago",         "name": "Chicago, IL",         "state": "Illinois",       "lat": 41.8781, "lon":  -87.6298, "tz": "America/Chicago"},
    {"id": "detroit",         "name": "Detroit, MI",         "state": "Michigan",       "lat": 42.3314, "lon":  -83.0458, "tz": "America/Detroit"},
    {"id": "milwaukee",       "name": "Milwaukee, WI",       "state": "Wisconsin",      "lat": 43.0389, "lon":  -87.9065, "tz": "America/Chicago"},
    {"id": "memphis",         "name": "Memphis, TN",         "state": "Tennessee",      "lat": 35.1495, "lon":  -90.0490, "tz": "America/Chicago"},
    {"id": "new_orleans",     "name": "New Orleans, LA",     "state": "Louisiana",      "lat": 29.9511, "lon":  -90.0715, "tz": "America/Chicago"},
    {"id": "birmingham",      "name": "Birmingham, AL",      "state": "Alabama",        "lat": 33.5186, "lon":  -86.8104, "tz": "America/Chicago"},
    {"id": "charlotte",       "name": "Charlotte, NC",       "state": "North Carolina", "lat": 35.2271, "lon":  -80.8431, "tz": "America/New_York"},
    {"id": "baltimore",       "name": "Baltimore, MD",       "state": "Maryland",       "lat": 39.2904, "lon":  -76.6122, "tz": "America/New_York"},
    {"id": "las_vegas",       "name": "Las Vegas, NV",       "state": "Nevada",         "lat": 36.1699, "lon": -115.1398, "tz": "America/Los_Angeles"},
    {"id": "albuquerque",     "name": "Albuquerque, NM",     "state": "New Mexico",     "lat": 35.0844, "lon": -106.6504, "tz": "America/Denver"},
    {"id": "tucson",          "name": "Tucson, AZ",          "state": "Arizona",        "lat": 32.2226, "lon": -110.9747, "tz": "America/Phoenix"},
    {"id": "anchorage",       "name": "Anchorage, AK",       "state": "Alaska",         "lat": 61.2181, "lon": -149.9003, "tz": "America/Anchorage"},

    # ===== NOROESTE PACÍFICO (2) =====
    {"id": "seattle",         "name": "Seattle, WA",         "state": "Washington",     "lat": 47.6062, "lon": -122.3321, "tz": "America/Los_Angeles"},
    {"id": "portland_or",     "name": "Portland, OR",        "state": "Oregon",         "lat": 45.5152, "lon": -122.6784, "tz": "America/Los_Angeles"},

    # ===== PUERTO RICO (3) =====
    {"id": "san_juan",        "name": "San Juan, PR",        "state": "Puerto Rico",    "lat": 18.4655, "lon":  -66.1057, "tz": "America/Puerto_Rico"},
    {"id": "ponce",           "name": "Ponce, PR",           "state": "Puerto Rico",    "lat": 18.0111, "lon":  -66.6140, "tz": "America/Puerto_Rico"},
    {"id": "mayaguez",        "name": "Mayagüez, PR",        "state": "Puerto Rico",    "lat": 18.2013, "lon":  -67.1397, "tz": "America/Puerto_Rico"},
]

if __name__ == '__main__':
    # Validación rápida ejecutando: python3 astro_cities.py
    import pytz
    print(f"Total: {len(CITIES)} ciudades")
    ids = [c['id'] for c in CITIES]
    assert len(ids) == len(set(ids)), "IDs duplicados"
    for c in CITIES:
        pytz.timezone(c['tz'])  # raises if invalid
    states = set(c['state'] for c in CITIES)
    print(f"Estados/territorios: {len(states)}")
    print(f"Validacion OK")
