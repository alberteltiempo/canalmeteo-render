"""
Canal Meteo TV - Configuración de estados y ciudades para pronóstico
Cada estado tiene 3-6 ciudades representativas con sus coordenadas.
Se usa lat/lon para obtener el gridpoint del NWS automáticamente.
"""

STATES = {
    "alabama": {
        "nombre": "Alabama",
        "abreviatura": "AL",
        "ciudades": [
            {"nombre": "Birmingham", "lat": 33.5207, "lon": -86.8025},
            {"nombre": "Mobile", "lat": 30.6954, "lon": -88.0399},
            {"nombre": "Huntsville", "lat": 34.7304, "lon": -86.5861},
            {"nombre": "Montgomery", "lat": 32.3792, "lon": -86.3077},
        ]
    },
    "alaska": {
        "nombre": "Alaska",
        "abreviatura": "AK",
        "ciudades": [
            {"nombre": "Anchorage", "lat": 61.2181, "lon": -149.9003},
            {"nombre": "Fairbanks", "lat": 64.8378, "lon": -147.7164},
            {"nombre": "Juneau", "lat": 58.3005, "lon": -134.4197},
        ]
    },
    "arizona": {
        "nombre": "Arizona",
        "abreviatura": "AZ",
        "ciudades": [
            {"nombre": "Phoenix", "lat": 33.4484, "lon": -112.0740},
            {"nombre": "Tucson", "lat": 32.2226, "lon": -110.9747},
            {"nombre": "Flagstaff", "lat": 35.1983, "lon": -111.6513},
            {"nombre": "Mesa", "lat": 33.4152, "lon": -111.8315},
        ]
    },
    "arkansas": {
        "nombre": "Arkansas",
        "abreviatura": "AR",
        "ciudades": [
            {"nombre": "Little Rock", "lat": 34.7465, "lon": -92.2896},
            {"nombre": "Fayetteville", "lat": 36.0822, "lon": -94.1719},
            {"nombre": "Fort Smith", "lat": 35.3859, "lon": -94.3985},
        ]
    },
    "california": {
        "nombre": "California",
        "abreviatura": "CA",
        "ciudades": [
            {"nombre": "Los Angeles", "lat": 34.0522, "lon": -118.2437},
            {"nombre": "San Francisco", "lat": 37.7749, "lon": -122.4194},
            {"nombre": "San Diego", "lat": 32.7157, "lon": -117.1611},
            {"nombre": "Sacramento", "lat": 38.5816, "lon": -121.4944},
            {"nombre": "Fresno", "lat": 36.7378, "lon": -119.7871},
            {"nombre": "Redding", "lat": 40.5865, "lon": -122.3917},
        ]
    },
    "colorado": {
        "nombre": "Colorado",
        "abreviatura": "CO",
        "ciudades": [
            {"nombre": "Denver", "lat": 39.7392, "lon": -104.9903},
            {"nombre": "Colorado Springs", "lat": 38.8339, "lon": -104.8214},
            {"nombre": "Grand Junction", "lat": 39.0639, "lon": -108.5506},
            {"nombre": "Fort Collins", "lat": 40.5853, "lon": -105.0844},
        ]
    },
    "connecticut": {
        "nombre": "Connecticut",
        "abreviatura": "CT",
        "ciudades": [
            {"nombre": "Hartford", "lat": 41.7658, "lon": -72.6734},
            {"nombre": "New Haven", "lat": 41.3083, "lon": -72.9279},
            {"nombre": "Bridgeport", "lat": 41.1865, "lon": -73.1952},
        ]
    },
    "delaware": {
        "nombre": "Delaware",
        "abreviatura": "DE",
        "ciudades": [
            {"nombre": "Wilmington", "lat": 39.7391, "lon": -75.5398},
            {"nombre": "Dover", "lat": 39.1582, "lon": -75.5244},
            {"nombre": "Rehoboth Beach", "lat": 38.7210, "lon": -75.0760},
        ]
    },
    "florida": {
        "nombre": "Florida",
        "abreviatura": "FL",
        "ciudades": [
            {"nombre": "Miami", "lat": 25.7617, "lon": -80.1918},
            {"nombre": "Orlando", "lat": 28.5383, "lon": -81.3792},
            {"nombre": "Tampa", "lat": 27.9506, "lon": -82.4572},
            {"nombre": "Jacksonville", "lat": 30.3322, "lon": -81.6557},
            {"nombre": "Tallahassee", "lat": 30.4383, "lon": -84.2807},
            {"nombre": "Pensacola", "lat": 30.4213, "lon": -87.2169},
        ]
    },
    "georgia": {
        "nombre": "Georgia",
        "abreviatura": "GA",
        "ciudades": [
            {"nombre": "Atlanta", "lat": 33.7490, "lon": -84.3880},
            {"nombre": "Savannah", "lat": 32.0809, "lon": -81.0912},
            {"nombre": "Augusta", "lat": 33.4735, "lon": -81.9748},
            {"nombre": "Macon", "lat": 32.8407, "lon": -83.6324},
        ]
    },
    "hawaii": {
        "nombre": "Hawái",
        "abreviatura": "HI",
        "ciudades": [
            {"nombre": "Honolulu", "lat": 21.3069, "lon": -157.8583},
            {"nombre": "Hilo", "lat": 19.7071, "lon": -155.0885},
            {"nombre": "Kahului", "lat": 20.8893, "lon": -156.4729},
        ]
    },
    "idaho": {
        "nombre": "Idaho",
        "abreviatura": "ID",
        "ciudades": [
            {"nombre": "Boise", "lat": 43.6150, "lon": -116.2023},
            {"nombre": "Idaho Falls", "lat": 43.4917, "lon": -112.0339},
            {"nombre": "Coeur d'Alene", "lat": 47.6777, "lon": -116.7805},
        ]
    },
    "illinois": {
        "nombre": "Illinois",
        "abreviatura": "IL",
        "ciudades": [
            {"nombre": "Chicago", "lat": 41.8781, "lon": -87.6298},
            {"nombre": "Springfield", "lat": 39.7817, "lon": -89.6501},
            {"nombre": "Rockford", "lat": 42.2711, "lon": -89.0940},
            {"nombre": "Peoria", "lat": 40.6936, "lon": -89.5890},
        ]
    },
    "indiana": {
        "nombre": "Indiana",
        "abreviatura": "IN",
        "ciudades": [
            {"nombre": "Indianápolis", "lat": 39.7684, "lon": -86.1581},
            {"nombre": "Fort Wayne", "lat": 41.0793, "lon": -85.1394},
            {"nombre": "Evansville", "lat": 37.9716, "lon": -87.5711},
        ]
    },
    "iowa": {
        "nombre": "Iowa",
        "abreviatura": "IA",
        "ciudades": [
            {"nombre": "Des Moines", "lat": 41.5868, "lon": -93.6250},
            {"nombre": "Cedar Rapids", "lat": 41.9779, "lon": -91.6656},
            {"nombre": "Davenport", "lat": 41.5236, "lon": -90.5776},
        ]
    },
    "kansas": {
        "nombre": "Kansas",
        "abreviatura": "KS",
        "ciudades": [
            {"nombre": "Wichita", "lat": 37.6872, "lon": -97.3301},
            {"nombre": "Topeka", "lat": 39.0489, "lon": -95.6780},
            {"nombre": "Kansas City", "lat": 39.1141, "lon": -94.6275},
            {"nombre": "Dodge City", "lat": 37.7528, "lon": -100.0171},
        ]
    },
    "kentucky": {
        "nombre": "Kentucky",
        "abreviatura": "KY",
        "ciudades": [
            {"nombre": "Louisville", "lat": 38.2527, "lon": -85.7585},
            {"nombre": "Lexington", "lat": 38.0406, "lon": -84.5037},
            {"nombre": "Bowling Green", "lat": 36.9685, "lon": -86.4808},
        ]
    },
    "louisiana": {
        "nombre": "Louisiana",
        "abreviatura": "LA",
        "ciudades": [
            {"nombre": "Nueva Orleans", "lat": 29.9511, "lon": -90.0715},
            {"nombre": "Baton Rouge", "lat": 30.4515, "lon": -91.1871},
            {"nombre": "Shreveport", "lat": 32.5252, "lon": -93.7502},
            {"nombre": "Lafayette", "lat": 30.2241, "lon": -92.0198},
        ]
    },
    "maine": {
        "nombre": "Maine",
        "abreviatura": "ME",
        "ciudades": [
            {"nombre": "Portland", "lat": 43.6591, "lon": -70.2568},
            {"nombre": "Bangor", "lat": 44.8016, "lon": -68.7712},
            {"nombre": "Augusta", "lat": 44.3106, "lon": -69.7795},
        ]
    },
    "maryland": {
        "nombre": "Maryland",
        "abreviatura": "MD",
        "ciudades": [
            {"nombre": "Baltimore", "lat": 39.2904, "lon": -76.6122},
            {"nombre": "Annapolis", "lat": 38.9784, "lon": -76.4922},
            {"nombre": "Frederick", "lat": 39.4143, "lon": -77.4105},
        ]
    },
    "massachusetts": {
        "nombre": "Massachusetts",
        "abreviatura": "MA",
        "ciudades": [
            {"nombre": "Boston", "lat": 42.3601, "lon": -71.0589},
            {"nombre": "Worcester", "lat": 42.2626, "lon": -71.8023},
            {"nombre": "Springfield", "lat": 42.1015, "lon": -72.5898},
            {"nombre": "Cape Cod", "lat": 41.6688, "lon": -70.2962},
        ]
    },
    "michigan": {
        "nombre": "Michigan",
        "abreviatura": "MI",
        "ciudades": [
            {"nombre": "Detroit", "lat": 42.3314, "lon": -83.0458},
            {"nombre": "Grand Rapids", "lat": 42.9634, "lon": -85.6681},
            {"nombre": "Traverse City", "lat": 44.7631, "lon": -85.6206},
            {"nombre": "Marquette", "lat": 46.5436, "lon": -87.3954},
        ]
    },
    "minnesota": {
        "nombre": "Minnesota",
        "abreviatura": "MN",
        "ciudades": [
            {"nombre": "Minneapolis", "lat": 44.9778, "lon": -93.2650},
            {"nombre": "Saint Paul", "lat": 44.9537, "lon": -93.0900},
            {"nombre": "Duluth", "lat": 46.7867, "lon": -92.1005},
            {"nombre": "Rochester", "lat": 44.0121, "lon": -92.4802},
        ]
    },
    "mississippi": {
        "nombre": "Misisipi",
        "abreviatura": "MS",
        "ciudades": [
            {"nombre": "Jackson", "lat": 32.2988, "lon": -90.1848},
            {"nombre": "Gulfport", "lat": 30.3674, "lon": -89.0928},
            {"nombre": "Tupelo", "lat": 34.2576, "lon": -88.7034},
        ]
    },
    "missouri": {
        "nombre": "Misuri",
        "abreviatura": "MO",
        "ciudades": [
            {"nombre": "Kansas City", "lat": 39.0997, "lon": -94.5786},
            {"nombre": "St. Louis", "lat": 38.6270, "lon": -90.1994},
            {"nombre": "Springfield", "lat": 37.2090, "lon": -93.2923},
        ]
    },
    "montana": {
        "nombre": "Montana",
        "abreviatura": "MT",
        "ciudades": [
            {"nombre": "Billings", "lat": 45.7833, "lon": -108.5007},
            {"nombre": "Missoula", "lat": 46.8721, "lon": -114.0001},
            {"nombre": "Great Falls", "lat": 47.5002, "lon": -111.3008},
        ]
    },
    "nebraska": {
        "nombre": "Nebraska",
        "abreviatura": "NE",
        "ciudades": [
            {"nombre": "Omaha", "lat": 41.2565, "lon": -95.9345},
            {"nombre": "Lincoln", "lat": 40.8136, "lon": -96.7026},
            {"nombre": "North Platte", "lat": 41.1403, "lon": -100.7601},
        ]
    },
    "nevada": {
        "nombre": "Nevada",
        "abreviatura": "NV",
        "ciudades": [
            {"nombre": "Las Vegas", "lat": 36.1699, "lon": -115.1398},
            {"nombre": "Reno", "lat": 39.5296, "lon": -119.8138},
            {"nombre": "Elko", "lat": 40.8324, "lon": -115.7631},
        ]
    },
    "new-hampshire": {
        "nombre": "Nuevo Hampshire",
        "abreviatura": "NH",
        "ciudades": [
            {"nombre": "Manchester", "lat": 42.9956, "lon": -71.4548},
            {"nombre": "Concord", "lat": 43.2081, "lon": -71.5376},
            {"nombre": "Nashua", "lat": 42.7654, "lon": -71.4676},
        ]
    },
    "new-jersey": {
        "nombre": "Nueva Jersey",
        "abreviatura": "NJ",
        "ciudades": [
            {"nombre": "Newark", "lat": 40.7357, "lon": -74.1724},
            {"nombre": "Atlantic City", "lat": 39.3643, "lon": -74.4229},
            {"nombre": "Trenton", "lat": 40.2206, "lon": -74.7699},
        ]
    },
    "new-mexico": {
        "nombre": "Nuevo México",
        "abreviatura": "NM",
        "ciudades": [
            {"nombre": "Albuquerque", "lat": 35.0844, "lon": -106.6504},
            {"nombre": "Santa Fe", "lat": 35.6870, "lon": -105.9378},
            {"nombre": "Las Cruces", "lat": 32.3199, "lon": -106.7637},
            {"nombre": "Roswell", "lat": 33.3943, "lon": -104.5230},
        ]
    },
    "new-york": {
        "nombre": "Nueva York",
        "abreviatura": "NY",
        "ciudades": [
            {"nombre": "Nueva York", "lat": 40.7128, "lon": -74.0060},
            {"nombre": "Buffalo", "lat": 42.8864, "lon": -78.8784},
            {"nombre": "Albany", "lat": 42.6526, "lon": -73.7562},
            {"nombre": "Syracuse", "lat": 43.0481, "lon": -76.1474},
            {"nombre": "Rochester", "lat": 43.1566, "lon": -77.6088},
        ]
    },
    "north-carolina": {
        "nombre": "Carolina del Norte",
        "abreviatura": "NC",
        "ciudades": [
            {"nombre": "Charlotte", "lat": 35.2271, "lon": -80.8431},
            {"nombre": "Raleigh", "lat": 35.7796, "lon": -78.6382},
            {"nombre": "Asheville", "lat": 35.5951, "lon": -82.5515},
            {"nombre": "Wilmington", "lat": 34.2257, "lon": -77.9447},
        ]
    },
    "north-dakota": {
        "nombre": "Dakota del Norte",
        "abreviatura": "ND",
        "ciudades": [
            {"nombre": "Fargo", "lat": 46.8772, "lon": -96.7898},
            {"nombre": "Bismarck", "lat": 46.8083, "lon": -100.7837},
            {"nombre": "Grand Forks", "lat": 47.9253, "lon": -97.0329},
        ]
    },
    "ohio": {
        "nombre": "Ohio",
        "abreviatura": "OH",
        "ciudades": [
            {"nombre": "Columbus", "lat": 39.9612, "lon": -82.9988},
            {"nombre": "Cleveland", "lat": 41.4993, "lon": -81.6944},
            {"nombre": "Cincinnati", "lat": 39.1031, "lon": -84.5120},
            {"nombre": "Toledo", "lat": 41.6528, "lon": -83.5379},
        ]
    },
    "oklahoma": {
        "nombre": "Oklahoma",
        "abreviatura": "OK",
        "ciudades": [
            {"nombre": "Oklahoma City", "lat": 35.4676, "lon": -97.5164},
            {"nombre": "Tulsa", "lat": 36.1540, "lon": -95.9928},
            {"nombre": "Norman", "lat": 35.2226, "lon": -97.4395},
        ]
    },
    "oregon": {
        "nombre": "Oregón",
        "abreviatura": "OR",
        "ciudades": [
            {"nombre": "Portland", "lat": 45.5152, "lon": -122.6784},
            {"nombre": "Eugene", "lat": 44.0521, "lon": -123.0868},
            {"nombre": "Bend", "lat": 44.0582, "lon": -121.3153},
            {"nombre": "Medford", "lat": 42.3265, "lon": -122.8756},
        ]
    },
    "pennsylvania": {
        "nombre": "Pensilvania",
        "abreviatura": "PA",
        "ciudades": [
            {"nombre": "Filadelfia", "lat": 39.9526, "lon": -75.1652},
            {"nombre": "Pittsburgh", "lat": 40.4406, "lon": -79.9959},
            {"nombre": "Harrisburg", "lat": 40.2732, "lon": -76.8867},
            {"nombre": "Erie", "lat": 42.1292, "lon": -80.0851},
        ]
    },
    "rhode-island": {
        "nombre": "Rhode Island",
        "abreviatura": "RI",
        "ciudades": [
            {"nombre": "Providence", "lat": 41.8240, "lon": -71.4128},
            {"nombre": "Newport", "lat": 41.4901, "lon": -71.3128},
            {"nombre": "Warwick", "lat": 41.7001, "lon": -71.4162},
        ]
    },
    "south-carolina": {
        "nombre": "Carolina del Sur",
        "abreviatura": "SC",
        "ciudades": [
            {"nombre": "Charleston", "lat": 32.7765, "lon": -79.9311},
            {"nombre": "Columbia", "lat": 34.0007, "lon": -81.0348},
            {"nombre": "Myrtle Beach", "lat": 33.6891, "lon": -78.8867},
            {"nombre": "Greenville", "lat": 34.8526, "lon": -82.3940},
        ]
    },
    "south-dakota": {
        "nombre": "Dakota del Sur",
        "abreviatura": "SD",
        "ciudades": [
            {"nombre": "Sioux Falls", "lat": 43.5446, "lon": -96.7311},
            {"nombre": "Rapid City", "lat": 44.0805, "lon": -103.2310},
            {"nombre": "Pierre", "lat": 44.3683, "lon": -100.3510},
        ]
    },
    "tennessee": {
        "nombre": "Tennessee",
        "abreviatura": "TN",
        "ciudades": [
            {"nombre": "Nashville", "lat": 36.1627, "lon": -86.7816},
            {"nombre": "Memphis", "lat": 35.1495, "lon": -90.0490},
            {"nombre": "Knoxville", "lat": 35.9606, "lon": -83.9207},
            {"nombre": "Chattanooga", "lat": 35.0456, "lon": -85.3097},
        ]
    },
    "texas": {
        "nombre": "Texas",
        "abreviatura": "TX",
        "ciudades": [
            {"nombre": "Houston", "lat": 29.7604, "lon": -95.3698},
            {"nombre": "Dallas", "lat": 32.7767, "lon": -96.7970},
            {"nombre": "San Antonio", "lat": 29.4241, "lon": -98.4936},
            {"nombre": "Austin", "lat": 30.2672, "lon": -97.7431},
            {"nombre": "El Paso", "lat": 31.7619, "lon": -106.4850},
            {"nombre": "Lubbock", "lat": 33.5779, "lon": -101.8552},
        ]
    },
    "utah": {
        "nombre": "Utah",
        "abreviatura": "UT",
        "ciudades": [
            {"nombre": "Salt Lake City", "lat": 40.7608, "lon": -111.8910},
            {"nombre": "St. George", "lat": 37.0965, "lon": -113.5684},
            {"nombre": "Provo", "lat": 40.2338, "lon": -111.6585},
        ]
    },
    "vermont": {
        "nombre": "Vermont",
        "abreviatura": "VT",
        "ciudades": [
            {"nombre": "Burlington", "lat": 44.4759, "lon": -73.2121},
            {"nombre": "Montpelier", "lat": 44.2601, "lon": -72.5754},
            {"nombre": "Rutland", "lat": 43.6106, "lon": -72.9726},
        ]
    },
    "virginia": {
        "nombre": "Virginia",
        "abreviatura": "VA",
        "ciudades": [
            {"nombre": "Richmond", "lat": 37.5407, "lon": -77.4360},
            {"nombre": "Virginia Beach", "lat": 36.8529, "lon": -75.9780},
            {"nombre": "Norfolk", "lat": 36.8508, "lon": -76.2859},
            {"nombre": "Roanoke", "lat": 37.2710, "lon": -79.9414},
        ]
    },
    "washington": {
        "nombre": "Washington",
        "abreviatura": "WA",
        "ciudades": [
            {"nombre": "Seattle", "lat": 47.6062, "lon": -122.3321},
            {"nombre": "Spokane", "lat": 47.6588, "lon": -117.4260},
            {"nombre": "Tacoma", "lat": 47.2529, "lon": -122.4443},
            {"nombre": "Yakima", "lat": 46.6021, "lon": -120.5059},
        ]
    },
    "west-virginia": {
        "nombre": "Virginia Occidental",
        "abreviatura": "WV",
        "ciudades": [
            {"nombre": "Charleston", "lat": 38.3498, "lon": -81.6326},
            {"nombre": "Morgantown", "lat": 39.6295, "lon": -79.9559},
            {"nombre": "Huntington", "lat": 38.4192, "lon": -82.4452},
        ]
    },
    "wisconsin": {
        "nombre": "Wisconsin",
        "abreviatura": "WI",
        "ciudades": [
            {"nombre": "Milwaukee", "lat": 43.0389, "lon": -87.9065},
            {"nombre": "Madison", "lat": 43.0731, "lon": -89.4012},
            {"nombre": "Green Bay", "lat": 44.5133, "lon": -88.0133},
            {"nombre": "La Crosse", "lat": 43.8014, "lon": -91.2396},
        ]
    },
    "wyoming": {
        "nombre": "Wyoming",
        "abreviatura": "WY",
        "ciudades": [
            {"nombre": "Cheyenne", "lat": 41.1400, "lon": -104.8202},
            {"nombre": "Casper", "lat": 42.8666, "lon": -106.3131},
            {"nombre": "Jackson", "lat": 43.4799, "lon": -110.7624},
        ]
    },
    # Territorios
    "puerto-rico": {
        "nombre": "Puerto Rico",
        "abreviatura": "PR",
        "ciudades": [
            {"nombre": "San Juan", "lat": 18.4655, "lon": -66.1057},
            {"nombre": "Ponce", "lat": 18.0111, "lon": -66.6141},
            {"nombre": "Mayagüez", "lat": 18.2013, "lon": -67.1397},
        ]
    },
}

# Traducciones de condiciones meteorológicas del NWS
WEATHER_TRANSLATIONS = {
    "Sunny": "Soleado",
    "Mostly Sunny": "Mayormente soleado",
    "Partly Sunny": "Parcialmente soleado",
    "Clear": "Despejado",
    "Mostly Clear": "Mayormente despejado",
    "Partly Cloudy": "Parcialmente nublado",
    "Mostly Cloudy": "Mayormente nublado",
    "Cloudy": "Nublado",
    "Overcast": "Cubierto",
    "Rain": "Lluvia",
    "Light Rain": "Lluvia ligera",
    "Heavy Rain": "Lluvia fuerte",
    "Showers": "Chubascos",
    "Scattered Showers": "Chubascos dispersos",
    "Chance Showers": "Posibilidad de chubascos",
    "Chance Rain": "Posibilidad de lluvia",
    "Slight Chance Showers": "Ligera posibilidad de chubascos",
    "Slight Chance Rain": "Ligera posibilidad de lluvia",
    "Thunderstorms": "Tormentas eléctricas",
    "Chance Thunderstorms": "Posibilidad de tormentas",
    "Scattered Thunderstorms": "Tormentas dispersas",
    "Severe Thunderstorms": "Tormentas severas",
    "Snow": "Nieve",
    "Light Snow": "Nieve ligera",
    "Heavy Snow": "Nevada fuerte",
    "Chance Snow": "Posibilidad de nieve",
    "Blizzard": "Ventisca",
    "Freezing Rain": "Lluvia helada",
    "Sleet": "Aguanieve",
    "Ice": "Hielo",
    "Fog": "Niebla",
    "Dense Fog": "Niebla densa",
    "Haze": "Neblina",
    "Smoke": "Humo",
    "Dust": "Polvo",
    "Windy": "Ventoso",
    "Breezy": "Brisa",
    "Hot": "Caluroso",
    "Cold": "Frío",
    "Frost": "Helada",
    "Tropical Storm": "Tormenta tropical",
    "Hurricane": "Huracán",
    "Tornado": "Tornado",
    "Wind Chill": "Sensación térmica fría",
    "Heat Index": "Índice de calor",
    # Combinaciones comunes
    "Showers And Thunderstorms": "Chubascos y tormentas",
    "Rain And Snow": "Lluvia y nieve",
    "Chance Showers And Thunderstorms": "Posibilidad de chubascos y tormentas",
    "Slight Chance Showers And Thunderstorms": "Ligera posibilidad de chubascos y tormentas",
    "Showers And Thunderstorms Likely": "Probable chubascos y tormentas",
    "Rain Showers": "Chubascos de lluvia",
    "Chance Rain Showers": "Posibilidad de chubascos",
    "Rain Showers Likely": "Probable chubascos de lluvia",
    "Isolated Thunderstorms": "Tormentas aisladas",
    "Areas Of Fog": "Áreas de niebla",
    "Patchy Fog": "Niebla irregular",
}

def translate_condition(condition):
    """Traduce una condición meteorológica del NWS al español."""
    if not condition:
        return "No disponible"
    # Intentar traducción exacta
    if condition in WEATHER_TRANSLATIONS:
        return WEATHER_TRANSLATIONS[condition]
    # Intentar sin distinguir mayúsculas
    for eng, esp in WEATHER_TRANSLATIONS.items():
        if eng.lower() == condition.lower():
            return esp
    # Buscar coincidencia parcial
    for eng, esp in WEATHER_TRANSLATIONS.items():
        if eng.lower() in condition.lower():
            return esp
    return condition  # Devolver original si no hay traducción
