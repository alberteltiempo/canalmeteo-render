"""
nps_webcams_config.py — Canal Meteo
══════════════════════════════════════════════════════════════════════
Lista curada de las 19 webcams oficiales de la red NPS Air Quality,
con metadata pre-calculada para uso en webcam_scraper.py y Remotion.

ESTRUCTURA: 4 grupos × 4 cámaras = 16 cámaras activas + 3 reserva.
Todos los grupos se renderizan cada hora.

URL pattern descubierto:
    https://www.nps.gov/featurecontent/ard/webcams/images/{CODE}.jpg

Ubicación: /opt/canalmeteo/scripts/nps_webcams_config.py
"""

NPS_WEBCAM_IMAGE_URL = "https://www.nps.gov/featurecontent/ard/webcams/images/{code}.jpg"


# ═════════════════════════════════════════════════════════════════════
# CATÁLOGO DE 19 CÁMARAS — campo 'group' actualizado
# ═════════════════════════════════════════════════════════════════════

NPS_WEBCAMS = [
    # ─── GRUPO 1: OESTE — Desiertos y Oeste ──────────────────────────
    {"code": "jotr", "park_name_es": "Parque Nacional Joshua Tree", "park_name_en": "Joshua Tree National Park",
     "state": "CALIFORNIA", "state_abbr": "CA", "view_es": "Vista del desierto Mojave hacia las Little San Bernardino",
     "lat": 34.0996, "lon": -116.1858, "elevation_ft": 4052, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "oeste",
     "metar": {"id": "KPSP", "name": "Palm Springs Intl", "lat": 33.8297, "lon": -116.5067, "distance_mi": 26.5}},

    {"code": "yose", "park_name_es": "Parque Nacional Yosemite", "park_name_en": "Yosemite National Park",
     "state": "CALIFORNIA", "state_abbr": "CA", "view_es": "Half Dome desde Turtleback Dome",
     "lat": 37.7456, "lon": -119.5936, "elevation_ft": 6001, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "oeste",
     "metar": {"id": "KFAT", "name": "Fresno (Yosemite Intl)", "lat": 36.7762, "lon": -119.7181, "distance_mi": 67.1}},

    {"code": "seki", "park_name_es": "Parque Nacional Sequoia", "park_name_en": "Sequoia National Park",
     "state": "CALIFORNIA", "state_abbr": "CA", "view_es": "Lower Kaweah desde Ash Mountain",
     "lat": 36.4864, "lon": -118.8253, "elevation_ft": 1726, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "oeste",
     "metar": {"id": "KFAT", "name": "Fresno (Yosemite Intl)", "lat": 36.7762, "lon": -119.7181, "distance_mi": 53.6}},

    {"code": "brca", "park_name_es": "Parque Nacional Bryce Canyon", "park_name_en": "Bryce Canyon National Park",
     "state": "UTAH", "state_abbr": "UT", "view_es": "Anfiteatro de hoodoos en Bryce Canyon",
     "lat": 37.6406, "lon": -112.1690, "elevation_ft": 8000, "tz": "America/Denver", "tz_abbr": "MT",
     "group": "oeste",
     "metar": {"id": "KCDC", "name": "Cedar City Municipal", "lat": 37.7011, "lon": -113.0986, "distance_mi": 51.0}},

    # ─── GRUPO 2: MONTAÑAS — Montañas y Bosques ──────────────────────
    {"code": "grte", "park_name_es": "Parque Nacional Grand Teton", "park_name_en": "Grand Teton National Park",
     "state": "WYOMING", "state_abbr": "WY", "view_es": "Cordillera Teton desde Jackson Lake",
     "lat": 43.7904, "lon": -110.6818, "elevation_ft": 6791, "tz": "America/Denver", "tz_abbr": "MT",
     "group": "montanas",
     "metar": {"id": "KJAC", "name": "Jackson Hole", "lat": 43.6073, "lon": -110.7378, "distance_mi": 13.0}},

    {"code": "mora", "park_name_es": "Parque Nacional Mount Rainier", "park_name_en": "Mount Rainier National Park",
     "state": "WASHINGTON", "state_abbr": "WA", "view_es": "Mount Rainier desde Tahoma Vista",
     "lat": 46.8500, "lon": -121.7600, "elevation_ft": 5400, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "montanas",
     "metar": {"id": "KSEA", "name": "Seattle-Tacoma Intl", "lat": 47.4490, "lon": -122.3094, "distance_mi": 48.7}},

    {"code": "olym", "park_name_es": "Parque Nacional Olympic", "park_name_en": "Olympic National Park",
     "state": "WASHINGTON", "state_abbr": "WA", "view_es": "Hurricane Ridge sobre la cordillera olímpica",
     "lat": 47.9700, "lon": -123.4990, "elevation_ft": 5242, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "montanas",
     "metar": {"id": "KSEA", "name": "Seattle-Tacoma Intl", "lat": 47.4490, "lon": -122.3094, "distance_mi": 66.0}},

    {"code": "noca", "park_name_es": "Parque Nacional North Cascades", "park_name_en": "North Cascades National Park",
     "state": "WASHINGTON", "state_abbr": "WA", "view_es": "Vista hacia el Mount Baker",
     "lat": 48.7800, "lon": -121.2000, "elevation_ft": 1657, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "montanas",
     "metar": {"id": "KBLI", "name": "Bellingham International", "lat": 48.7929, "lon": -122.5375, "distance_mi": 61.4}},

    # ─── GRUPO 3: APALACHES — Apalaches y Sureste ────────────────────
    {"code": "grsm", "park_name_es": "Great Smoky Mountains",
     "park_name_en": "Great Smoky Mountains National Park",
     "state": "TENNESSEE", "state_abbr": "TN", "view_es": "Vista panorámica de la cordillera Smoky",
     "lat": 35.6532, "lon": -83.5070, "elevation_ft": 4000, "tz": "America/New_York", "tz_abbr": "ET",
     "group": "apalaches",
     "metar": {"id": "KTYS", "name": "Knoxville (McGhee Tyson)", "lat": 35.8110, "lon": -83.9940, "distance_mi": 28.0}},

    {"code": "grcd", "park_name_es": "Great Smoky Mountains — Kuwohi",
     "park_name_en": "Great Smoky Mountains National Park (Kuwohi)",
     "state": "TENNESSEE", "state_abbr": "TN", "view_es": "Kuwohi (antes Clingmans Dome)",
     "lat": 35.5628, "lon": -83.4985, "elevation_ft": 6643, "tz": "America/New_York", "tz_abbr": "ET",
     "group": "apalaches",
     "metar": {"id": "KTYS", "name": "Knoxville (McGhee Tyson)", "lat": 35.8110, "lon": -83.9940, "distance_mi": 36.7}},

    {"code": "maca", "park_name_es": "Parque Nacional Mammoth Cave", "park_name_en": "Mammoth Cave National Park",
     "state": "KENTUCKY", "state_abbr": "KY", "view_es": "Bosques de hardwood sobre el sistema cavernario",
     "lat": 37.1862, "lon": -86.1000, "elevation_ft": 738, "tz": "America/Chicago", "tz_abbr": "CT",
     "group": "apalaches",
     "metar": {"id": "KBWG", "name": "Bowling Green (Warren County)", "lat": 36.9645, "lon": -86.4197, "distance_mi": 23.5}},

    {"code": "shen", "park_name_es": "Parque Nacional Shenandoah", "park_name_en": "Shenandoah National Park",
     "state": "VIRGINIA", "state_abbr": "VA", "view_es": "Big Meadows sobre el valle Shenandoah",
     "lat": 38.5226, "lon": -78.4347, "elevation_ft": 3514, "tz": "America/New_York", "tz_abbr": "ET",
     "group": "apalaches",
     "metar": {"id": "KCHO", "name": "Charlottesville-Albemarle", "lat": 38.1386, "lon": -78.4528, "distance_mi": 26.5}},

    # ─── GRUPO 4: ICÓNICOS — Icónicos y Singulares ───────────────────
    {"code": "acad", "park_name_es": "Parque Nacional Acadia", "park_name_en": "Acadia National Park",
     "state": "MAINE", "state_abbr": "ME", "view_es": "Cadillac Mountain sobre Bar Harbor",
     "lat": 44.3386, "lon": -68.2733, "elevation_ft": 1530, "tz": "America/New_York", "tz_abbr": "ET",
     "group": "iconicos",
     "metar": {"id": "KBGR", "name": "Bangor Intl", "lat": 44.8074, "lon": -68.8281, "distance_mi": 41.6}},

    {"code": "dena", "park_name_es": "Parque Nacional Denali", "park_name_en": "Denali National Park and Preserve",
     "state": "ALASKA", "state_abbr": "AK", "view_es": "Denali (Mount McKinley)",
     "lat": 63.7300, "lon": -148.9200, "elevation_ft": 1735, "tz": "America/Anchorage", "tz_abbr": "AKT",
     "group": "iconicos",
     "metar": {"id": "PATK", "name": "Talkeetna", "lat": 62.3205, "lon": -150.0937, "distance_mi": 60.0}},

    {"code": "havo", "park_name_es": "Parque Nacional Hawaiʻi Volcanoes", "park_name_en": "Hawaiʻi Volcanoes National Park",
     "state": "HAWAIʻI", "state_abbr": "HI", "view_es": "Cráter Halemaʻumaʻu en el Kīlauea",
     "lat": 19.4194, "lon": -155.2885, "elevation_ft": 4009, "tz": "Pacific/Honolulu", "tz_abbr": "HST",
     "group": "iconicos",
     "metar": {"id": "PHTO", "name": "Hilo Intl", "lat": 19.7214, "lon": -155.0485, "distance_mi": 30.0}},

    {"code": "wash", "park_name_es": "National Mall", "park_name_en": "National Mall and Memorial Parks",
     "state": "WASHINGTON, D.C.", "state_abbr": "DC", "view_es": "Capitolio y Washington Monument desde el Mall",
     "lat": 38.8895, "lon": -77.0353, "elevation_ft": 23, "tz": "America/New_York", "tz_abbr": "ET",
     "group": "iconicos",
     "metar": {"id": "KDCA", "name": "Reagan National", "lat": 38.8521, "lon": -77.0377, "distance_mi": 2.6}},

    # ─── RESERVA — fallback automático si una primary falla ──────────
    {"code": "pore", "park_name_es": "Costa Nacional Point Reyes", "park_name_en": "Point Reyes National Seashore",
     "state": "CALIFORNIA", "state_abbr": "CA", "view_es": "Vista costera del Pacífico",
     "lat": 38.0731, "lon": -122.8814, "elevation_ft": 423, "tz": "America/Los_Angeles", "tz_abbr": "PT",
     "group": "reserva",
     "metar": {"id": "KSFO", "name": "San Francisco Intl", "lat": 37.6189, "lon": -122.3750, "distance_mi": 42.1}},

    {"code": "bibe", "park_name_es": "Parque Nacional Big Bend", "park_name_en": "Big Bend National Park",
     "state": "TEXAS", "state_abbr": "TX", "view_es": "Cordillera Chisos en el desierto chihuahuense",
     "lat": 29.2700, "lon": -103.1800, "elevation_ft": 5400, "tz": "America/Chicago", "tz_abbr": "CT",
     "group": "reserva",
     "metar": {"id": "KMAF", "name": "Midland Intl", "lat": 31.9425, "lon": -102.2019, "distance_mi": 193.8}},

    {"code": "dino", "park_name_es": "Monumento Nacional Dinosaur", "park_name_en": "Dinosaur National Monument",
     "state": "UTAH", "state_abbr": "UT", "view_es": "Cañón del Yampa River sobre el desierto rojo",
     "lat": 40.4469, "lon": -109.3047, "elevation_ft": 4750, "tz": "America/Denver", "tz_abbr": "MT",
     "group": "reserva",
     "metar": {"id": "KRKS", "name": "Rock Springs (SW Wyoming)", "lat": 41.5942, "lon": -109.0651, "distance_mi": 80.4}},
    # --- Anadidas 12/09/2026: salen en lynx/parques (web + app) pero no estaban
    # en el catalogo. Van en "reserva" para no alterar los 4 grupos de 4 del video.
    {"code": "grca", "park_name_es": "Parque Nacional Gran Canon", "park_name_en": "Grand Canyon National Park",
     "state": "ARIZONA", "state_abbr": "AZ", "view_es": "El Gran Canon desde Yavapai Point",
     "lat": 36.0544, "lon": -112.1401, "elevation_ft": 7100, "tz": "America/Phoenix", "tz_abbr": "MST",
     "group": "reserva",
     "metar": {"id": "KGCN", "name": "Grand Canyon National Park Airport", "lat": 35.9524, "lon": -112.1470, "distance_mi": 7.6}},

    {"code": "thro", "park_name_es": "Parque Nacional Theodore Roosevelt", "park_name_en": "Theodore Roosevelt National Park",
     "state": "DAKOTA DEL NORTE", "state_abbr": "ND", "view_es": "Badlands desde Painted Canyon",
     "lat": 46.9790, "lon": -103.4397, "elevation_ft": 2600, "tz": "America/Denver", "tz_abbr": "MT",
     "group": "reserva",
     "metar": {"id": "K20U", "name": "Beach Municipal", "lat": 46.9250, "lon": -104.0200, "distance_mi": 26.0}},

]


# ═════════════════════════════════════════════════════════════════════
# DEFINICIÓN DE LOS 4 GRUPOS
# ═════════════════════════════════════════════════════════════════════

GROUPS = {
    "oeste": {
        "name_es": "Desiertos y Oeste",
        "name_short_es": "Oeste",
        "cams": ["jotr", "yose", "seki", "brca"],
    },
    "montanas": {
        "name_es": "Montañas y Bosques",
        "name_short_es": "Montañas",
        "cams": ["grte", "mora", "olym", "noca"],
    },
    "apalaches": {
        "name_es": "Apalaches y Sureste",
        "name_short_es": "Apalaches",
        "cams": ["grsm", "grcd", "maca", "shen"],
    },
    "iconicos": {
        "name_es": "Icónicos y Singulares",
        "name_short_es": "Icónicos",
        "cams": ["acad", "dena", "havo", "wash"],
    },
}

# Códigos de cámaras de reserva — fallback si una primary falla
RESERVE_CAMS = ["pore", "bibe", "dino"]

# Lista de los 4 grupos para iterar
GROUP_NAMES = list(GROUPS.keys())


# ═════════════════════════════════════════════════════════════════════
# FUNCIONES PÚBLICAS
# ═════════════════════════════════════════════════════════════════════

def get_image_url(code: str) -> str:
    """Build the NPS image URL for a given webcam code."""
    return NPS_WEBCAM_IMAGE_URL.format(code=code)


def get_cam_by_code(code: str):
    """Devuelve el dict completo de una cámara por su código."""
    for cam in NPS_WEBCAMS:
        if cam["code"] == code:
            return cam
    return None


def all_codes():
    """Devuelve TODOS los códigos del catálogo (incluye reserva)."""
    return [c["code"] for c in NPS_WEBCAMS]


def active_codes():
    """Devuelve solo los códigos de las 16 cámaras activas (sin reserva)."""
    codes = []
    for group in GROUPS.values():
        codes.extend(group["cams"])
    return codes


def get_cams_for_group(group_name: str):
    """
    Devuelve las 4 cámaras (dicts) del grupo especificado.

    Args:
        group_name: 'oeste' | 'montanas' | 'apalaches' | 'iconicos'

    Returns:
        Lista de 4 dicts de cámaras.
    """
    if group_name not in GROUPS:
        raise ValueError(f"Grupo desconocido: {group_name}. Válidos: {GROUP_NAMES}")
    cam_codes = GROUPS[group_name]["cams"]
    return [get_cam_by_code(c) for c in cam_codes]


def get_cams_for_group_smart(group_name: str, manifest_url: str = None):
    """
    Como get_cams_for_group pero descarta cámaras failed leyendo el
    manifest del CDN. Si una primary falla, recurre a RESERVE_CAMS.

    Args:
        group_name: 'oeste' | 'montanas' | 'apalaches' | 'iconicos'
        manifest_url: URL del manifest (default canalmeteo CDN)

    Returns:
        Lista de 4 dicts de cámaras operativas.
    """
    import json
    import urllib.request

    if manifest_url is None:
        manifest_url = "https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/webcams/manifest.json"

    if group_name not in GROUPS:
        raise ValueError(f"Grupo desconocido: {group_name}. Válidos: {GROUP_NAMES}")

    primary_codes = GROUPS[group_name]["cams"]

    # Descargar manifest
    operational_codes = set()
    try:
        with urllib.request.urlopen(manifest_url, timeout=10) as r:
            manifest = json.loads(r.read())
        for cam_status in manifest.get("cams", []):
            if cam_status.get("status") == "ok":
                operational_codes.add(cam_status["code"])
    except Exception as e:
        print(f"WARN: no se pudo leer el manifest, devolviendo lista primaria: {e}")
        return [get_cam_by_code(c) for c in primary_codes]

    # Filtrar primarias que están operativas
    valid_codes = [c for c in primary_codes if c in operational_codes]

    # Si faltan, completar con reserva
    if len(valid_codes) < 4:
        for fallback_code in RESERVE_CAMS:
            if len(valid_codes) >= 4:
                break
            if fallback_code in operational_codes and fallback_code not in valid_codes:
                valid_codes.append(fallback_code)

    # Si seguimos faltos (situación rara), completar con cualquier cámara OK de otros grupos
    if len(valid_codes) < 4:
        for code in active_codes():
            if len(valid_codes) >= 4:
                break
            if code in operational_codes and code not in valid_codes:
                valid_codes.append(code)

    # Garantizar que siempre devolvemos 4 (en último recurso, repetir)
    if len(valid_codes) == 0:
        # Caso catastrófico: ninguna cámara OK. Devolver lista primaria.
        valid_codes = primary_codes

    while len(valid_codes) < 4:
        valid_codes.append(valid_codes[len(valid_codes) % len(valid_codes)])

    return [get_cam_by_code(c) for c in valid_codes[:4]]


def get_group_metadata(group_name: str):
    """Devuelve metadata del grupo (nombre legible)."""
    if group_name not in GROUPS:
        raise ValueError(f"Grupo desconocido: {group_name}. Válidos: {GROUP_NAMES}")
    return GROUPS[group_name]


# ═════════════════════════════════════════════════════════════════════
# FUNCIONES LEGACY — para compatibilidad con código viejo
# ═════════════════════════════════════════════════════════════════════
# DEPRECATED: ya no hay rotación por hora UTC. Mantener solo
# para no romper scripts antiguos. Usar get_cams_for_group() en su lugar.

def get_cams_for_hour(hour_utc: int):
    """[DEPRECATED] Devuelve siempre las 4 cámaras del grupo 'oeste'.
    Usar get_cams_for_group() en su lugar."""
    print("WARN: get_cams_for_hour() es DEPRECATED. Usa get_cams_for_group()")
    return get_cams_for_group("oeste")


def get_cams_for_hour_smart(hour_utc: int, manifest_url: str = None):
    """[DEPRECATED] Devuelve siempre las 4 cámaras smart del grupo 'oeste'.
    Usar get_cams_for_group_smart() en su lugar."""
    print("WARN: get_cams_for_hour_smart() es DEPRECATED. Usa get_cams_for_group_smart()")
    return get_cams_for_group_smart("oeste", manifest_url)


# ═════════════════════════════════════════════════════════════════════
# CLI / debug
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"Total cámaras catálogo: {len(NPS_WEBCAMS)}")
    print(f"Cámaras activas: {len(active_codes())} (4 grupos × 4)")
    print(f"Cámaras reserva: {len(RESERVE_CAMS)}")
    print()
    print("GRUPOS:")
    for gname, gdata in GROUPS.items():
        print(f"  [{gname:10s}] {gdata['name_es']}")
        for code in gdata["cams"]:
            cam = get_cam_by_code(code)
            print(f"     - {code}  {cam['park_name_es']}  ({cam['state_abbr']})")
    print()
    print(f"RESERVA: {', '.join(RESERVE_CAMS)}")
    print()
    print("Ejemplos de URLs:")
    for code in ["acad", "yose", "grte", "havo"]:
        print(f"  {code} → {get_image_url(code)}")
