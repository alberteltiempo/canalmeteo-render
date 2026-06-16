#!/opt/canalmeteo/venv/bin/python3
# -*- coding: utf-8 -*-
"""
alerts_by_state_pipeline.py
============================
Pipeline de alertas NWS agrupadas por estado para Canal Meteo TV.

Descarga todas las alertas activas de la NWS, las agrupa por estado de EE.UU.
usando los códigos UGC (TXC453 → TX), traduce los nombres de eventos al
español, y genera un JSON que el canal Roku consume directamente.

Estructura de salida:
{
    "generated": "2026-05-21T19:30:00Z",
    "national_critical": [  # Eventos críticos en cualquier punto del país
        { "event": "Tornado Warning", "eventEs": "Aviso de Tornado", ... }
    ],
    "by_state": {
        "TX": [ {alerta1}, {alerta2}, ... ],
        "CA": [ ... ],
        ...
    },
    "_meta": { "total_alerts": N, ... }
}

Uso:
    /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/alerts_by_state_pipeline.py
    /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/alerts_by_state_pipeline.py --no-upload

Programado en cron cada 2 minutos.
"""

import json
import os
import sys
import logging
import argparse
import subprocess
from datetime import datetime, timezone
from collections import defaultdict

import requests

# ============================================================
# CONFIGURACIÓN
# ============================================================
NWS_API_URL = "https://api.weather.gov/alerts/active"
USER_AGENT = "canalmeteo/1.0 (contacto: soporte@canalmeteo.tv)"
TIMEOUT_SECONDS = 60
OUTPUT_FILE = "/tmp/canalmeteo-alerts-by-state.json"

# DO Spaces
SPACES_BUCKET = "canalmeteo-public"
SPACES_PATH = "data/alerts/by-state.json"
SPACES_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
AWS_PROFILE = "do-tor1"

# Eventos críticos nacionales: aparecen arriba del todo del Roku
# independientemente del estado del usuario
EVENTOS_CRITICOS_NACIONALES = {
    "Tornado Warning",
    "Tornado Emergency",
    "Hurricane Warning",
    "Flash Flood Emergency",
    "Tsunami Warning",
}

# Logging a fichero + stdout
LOG_FILE = "/var/log/canalmeteo/alerts_by_state.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("alerts_by_state")

# ============================================================
# TRADUCCIÓN DE EVENTOS AL ESPAÑOL
# ============================================================
# Traducción de niveles de severidad
TRADUCCIONES_SEVERIDAD = {
    "Extreme": "extrema",
    "Severe": "severa",
    "Moderate": "moderada",
    "Minor": "menor",
    "Unknown": "desconocida",
}

# Traducción de niveles de urgencia
TRADUCCIONES_URGENCIA = {
    "Immediate": "inmediata",
    "Expected": "prevista",
    "Future": "futura",
    "Past": "pasada",
    "Unknown": "desconocida",
}

# Consejos de acción recomendada según tipo de evento (se añaden al final
# de la descripción si el evento contiene alguna de estas palabras clave)
CONSEJOS_POR_EVENTO = {
    "Tornado": "Busque refugio inmediatamente en un cuarto interior sin ventanas, en el piso más bajo de un edificio resistente.",
    "Hurricane": "Siga las indicaciones de las autoridades locales. Si se ha emitido orden de evacuación, evacúe inmediatamente.",
    "Tropical Storm": "Asegure los objetos sueltos en exteriores y prepare suministros de emergencia. Evite la costa.",
    "Storm Surge": "Aléjese inmediatamente de la costa y zonas bajas. Diríjase a terreno elevado.",
    "Tsunami": "Aléjese inmediatamente de la costa y diríjase a terreno elevado o tierra adentro.",
    "Flash Flood": "No conduzca ni camine sobre carreteras inundadas. Diríjase a terreno elevado.",
    "Flood": "Evite zonas inundadas. No conduzca a través de agua estancada en la vía.",
    "Severe Thunderstorm": "Permanezca dentro de un edificio resistente. Aléjese de ventanas y objetos metálicos.",
    "Winter Storm": "Evite viajar si es posible. Si debe salir, lleve provisiones de emergencia en el vehículo.",
    "Blizzard": "Evite viajar. Permanezca en interiores y proteja a personas mayores, niños y mascotas del frío extremo.",
    "Ice Storm": "Evite viajar. Las superficies estarán resbaladizas y pueden caer árboles y cables eléctricos.",
    "Freeze": "Proteja plantas sensibles, mascotas y tuberías expuestas. Compruebe el estado de personas vulnerables.",
    "Excessive Heat": "Beba abundante agua, evite la exposición prolongada al sol y compruebe el estado de personas mayores y niños.",
    "Extreme Heat": "Beba abundante agua, evite la exposición prolongada al sol y compruebe el estado de personas mayores y niños.",
    "Heat Advisory": "Manténgase hidratado y evite la actividad física intensa durante las horas de mayor calor.",
    "High Wind": "Asegure objetos sueltos en exteriores. Tenga precaución al conducir vehículos altos.",
    "Red Flag": "Evite cualquier actividad que pueda generar chispas. Riesgo elevado de incendios forestales.",
    "Fire Weather": "Condiciones favorables para incendios forestales. Evite quemas al aire libre.",
    "Dense Fog": "Conduzca con extrema precaución. Reduzca la velocidad y use las luces bajas.",
    "Rip Current": "Evite nadar. Si queda atrapado en una corriente de resaca, nade paralelo a la costa hasta salir de ella.",
    "Air Quality": "Personas con problemas respiratorios deben limitar la actividad al aire libre.",
}

def extraer_hora_local(iso_str: str) -> str:
    """
    Recibe '2026-05-21T18:25:00-05:00' y devuelve '18:25'.
    Devuelve cadena vacía si no se puede parsear.
    """
    if not iso_str or len(iso_str) < 16:
        return ""
    try:
        return iso_str[11:16]
    except Exception:
        return ""


def consejo_para_evento(evento: str) -> str:
    """Devuelve el consejo más específico que coincida con el nombre del evento."""
    for clave, consejo in CONSEJOS_POR_EVENTO.items():
        if clave.lower() in evento.lower():
            return consejo
    return ""


def generar_descripcion_es(props: dict) -> str:
    """
    Construye una descripción en español enfocada en HORA + CONSEJO.
    El área, severidad y expiración se muestran en paneles aparte en el Roku,
    así que aquí solo añadimos lo que no se ve en otro sitio.
    """
    evento = props.get("event", "") or ""
    sent = props.get("sent", "") or ""

    partes = []

    # Frase 1: hora de emisión
    hora_sent = extraer_hora_local(sent)
    if hora_sent:
        partes.append(f"Emitido a las {hora_sent} hora local.")

    # Frase 2: consejo de acción según tipo
    consejo = consejo_para_evento(evento)
    if consejo:
        partes.append(consejo)

    return " ".join(partes)

TRADUCCIONES_EVENTOS = {
    # Tornados
    "Tornado Warning": "Aviso de Tornado",
    "Tornado Watch": "Vigilancia de Tornado",
    "Tornado Emergency": "Emergencia de Tornado",
    # Tormentas
    "Severe Thunderstorm Warning": "Aviso de Tormenta Severa",
    "Severe Thunderstorm Watch": "Vigilancia de Tormenta Severa",
    "Special Marine Warning": "Aviso Marino Especial",
    "Special Weather Statement": "Aviso Meteorológico Especial",
    # Inundaciones
    "Flash Flood Warning": "Aviso de Inundación Repentina",
    "Flash Flood Watch": "Vigilancia de Inundación Repentina",
    "Flash Flood Emergency": "Emergencia de Inundación Repentina",
    "Flood Warning": "Aviso de Inundación",
    "Flood Watch": "Vigilancia de Inundación",
    "Flood Advisory": "Aviso de Inundación",
    "Coastal Flood Warning": "Aviso de Inundación Costera",
    "Coastal Flood Advisory": "Aviso de Inundación Costera",
    "Coastal Flood Watch": "Vigilancia de Inundación Costera",
    "River Flood Warning": "Aviso de Crecida de Río",
    "River Flood Watch": "Vigilancia de Crecida de Río",
    "Coastal Flood Statement": "Aviso de Inundación Costera",
    "Hydrologic Outlook": "Pronóstico Hidrológico",
    # Huracanes y tropicales
    "Hurricane Warning": "Aviso de Huracán",
    "Hurricane Watch": "Vigilancia de Huracán",
    "Tropical Storm Warning": "Aviso de Tormenta Tropical",
    "Tropical Storm Watch": "Vigilancia de Tormenta Tropical",
    "Storm Surge Warning": "Aviso de Marejada Ciclónica",
    "Storm Surge Watch": "Vigilancia de Marejada Ciclónica",
    # Tsunamis
    "Tsunami Warning": "Aviso de Tsunami",
    "Tsunami Watch": "Vigilancia de Tsunami",
    "Tsunami Advisory": "Aviso de Tsunami",
    # Invierno
    "Winter Storm Warning": "Aviso de Tormenta Invernal",
    "Winter Storm Watch": "Vigilancia de Tormenta Invernal",
    "Winter Weather Advisory": "Aviso de Clima Invernal",
    "Blizzard Warning": "Aviso de Ventisca",
    "Ice Storm Warning": "Aviso de Tormenta de Hielo",
    "Freeze Warning": "Aviso de Congelación",
    "Freeze Watch": "Vigilancia de Congelación",
    "Hard Freeze Warning": "Aviso de Congelación Severa",
    "Hard Freeze Watch": "Vigilancia de Congelación Severa",
    "Frost Advisory": "Aviso de Heladas",
    "Wind Chill Warning": "Aviso de Sensación Térmica Fría",
    "Wind Chill Advisory": "Aviso de Sensación Térmica Fría",
    "Wind Chill Watch": "Vigilancia de Sensación Térmica Fría",
    "Extreme Cold Warning": "Aviso de Frío Extremo",
    "Cold Weather Advisory": "Aviso de Clima Frío",
    "Snow Squall Warning": "Aviso de Chubasco de Nieve",
    "Freezing Rain Advisory": "Aviso de Lluvia Helada",
    "Lake Effect Snow Warning": "Aviso de Nieve por Efecto Lago",
    "Lake Effect Snow Advisory": "Aviso de Nieve por Efecto Lago",
    "Lake Effect Snow Watch": "Vigilancia de Nieve por Efecto Lago",
    "Winter Weather Message": "Mensaje de Clima Invernal",
    # Calor
    "Excessive Heat Warning": "Aviso de Calor Excesivo",
    "Excessive Heat Watch": "Vigilancia de Calor Excesivo",
    "Heat Advisory": "Aviso de Calor",
    "Extreme Heat Warning": "Aviso de Calor Extremo",
    "Extreme Heat Watch": "Vigilancia de Calor Extremo",
    # Viento
    "High Wind Warning": "Aviso de Vientos Fuertes",
    "High Wind Watch": "Vigilancia de Vientos Fuertes",
    "Wind Advisory": "Aviso de Viento",
    "Lake Wind Advisory": "Aviso de Viento en Lago",
    # Fuego
    "Red Flag Warning": "Aviso de Bandera Roja",
    "Fire Weather Watch": "Vigilancia de Clima de Incendios",
    # Polvo y humo
    "Dust Storm Warning": "Aviso de Tormenta de Polvo",
    "Blowing Dust Advisory": "Aviso de Polvo en Suspensión",
    "Dust Advisory": "Aviso de Polvo",
    "Dense Fog Advisory": "Aviso de Niebla Densa",
    "Dense Smoke Advisory": "Aviso de Humo Denso",
    # Calidad del aire
    "Air Quality Alert": "Alerta de Calidad del Aire",
    "Air Stagnation Advisory": "Aviso de Estancamiento del Aire",
    # Costa
    "Rip Current Statement": "Aviso de Corrientes de Resaca",
    "High Surf Advisory": "Aviso de Oleaje Alto",
    "High Surf Warning": "Aviso de Oleaje Peligroso",
    "Beach Hazards Statement": "Aviso de Peligros en la Playa",
    # Marino
    "Small Craft Advisory": "Aviso para Embarcaciones Pequeñas",
    "Gale Warning": "Aviso de Vendaval",
    "Storm Warning": "Aviso de Tormenta",
    "Hurricane Force Wind Warning": "Aviso de Vientos de Fuerza Huracanada",
    "Marine Weather Statement": "Aviso Meteorológico Marino",
    # Otros
    "Hazardous Weather Outlook": "Pronóstico de Clima Peligroso",
    "Severe Weather Statement": "Aviso de Clima Severo",
}


def traducir_evento(evento: str) -> str:
    """Traduce el nombre del evento al español. Si no hay traducción, lo deja igual."""
    return TRADUCCIONES_EVENTOS.get(evento, evento)


# ============================================================
# DESCARGA DE NWS API
# ============================================================
def descargar_alertas() -> list:
    """Descarga el listado de alertas activas desde NWS API."""
    log.info("Descargando alertas activas de NWS API...")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json",
    }
    params = {
        
    }

    response = requests.get(
        NWS_API_URL,
        headers=headers,
        params=params,
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    data = response.json()
    features = data.get("features", [])
    log.info(f"  ✓ {len(features)} alertas recibidas")
    return features


# ============================================================
# PROCESADO DE ALERTAS
# ============================================================
def extraer_estados_de_ugc(props: dict) -> set:
    """
    Extrae los códigos de estado a partir de los UGC.
    Ejemplos: TXC453, TXZ192, TXF001 → TX.
    Una alerta puede afectar a múltiples estados.
    """
    estados = set()
    geocode = props.get("geocode", {}) or {}
    ugc_list = geocode.get("UGC", []) or []

    for ugc in ugc_list:
        if not ugc or len(ugc) < 2:
            continue
        estado = ugc[:2].upper()
        # Filtrar zonas marítimas (AM, GM, PZ, PK, AN, PM, LM, LO, LE, LH, LS, LC, LP, SL)
        # Aceptamos cualquier 2 letras: el cliente Roku filtrará lo que no le interese.
        if estado.isalpha():
            estados.add(estado)

    return estados


def es_evento_critico(evento: str) -> bool:
    """¿Es un evento del banner crítico nacional?"""
    return evento in EVENTOS_CRITICOS_NACIONALES


def procesar_alerta(feature: dict):
    """Convierte una feature GeoJSON de NWS en un dict ligero para el Roku."""
    props = feature.get("properties", {}) or {}
    estados = extraer_estados_de_ugc(props)

    alerta = {
        "id": props.get("id", "") or "",
        "event": props.get("event", "") or "",
        "eventEs": traducir_evento(props.get("event", "") or ""),
        "headline": props.get("headline", "") or "",
        "descriptionEs": generar_descripcion_es(props),
        "areaDesc": props.get("areaDesc", "") or "",
        "severity": props.get("severity", "Unknown") or "Unknown",
        "certainty": props.get("certainty", "Unknown") or "Unknown",
        "urgency": props.get("urgency", "Unknown") or "Unknown",
        "sent": props.get("sent", "") or "",
        "expires": props.get("expires", "") or "",
        "states": sorted(estados),
    }
    return alerta, estados


def ordenar_alertas(alertas: list) -> list:
    """Ordena de mayor a menor severidad."""
    orden_severidad = {
        "Extreme": 0,
        "Severe": 1,
        "Moderate": 2,
        "Minor": 3,
        "Unknown": 4,
    }
    return sorted(
        alertas,
        key=lambda a: orden_severidad.get(a.get("severity", "Unknown"), 5)
    )


def construir_json_salida(features: list) -> dict:
    """Construye el dict final con la estructura esperada por el Roku."""
    national_critical = []
    by_state = defaultdict(list)

    # Evitar duplicar la misma alerta en national_critical si afecta a varios estados
    # (cada alerta sale una sola vez en national_critical, pero puede salir en
    # varias entradas de by_state)
    ids_criticos_vistos = set()

    for feature in features:
        try:
            alerta, estados = procesar_alerta(feature)

            # ¿Es crítica nacional?
            if es_evento_critico(alerta["event"]):
                if alerta["id"] not in ids_criticos_vistos:
                    national_critical.append(alerta)
                    ids_criticos_vistos.add(alerta["id"])

            # Añadir a cada estado afectado
            for estado in estados:
                by_state[estado].append(alerta)

        except Exception as e:
            log.warning(f"Error procesando alerta: {e}")
            continue

    # Ordenar por severidad
    national_critical = ordenar_alertas(national_critical)
    for estado in list(by_state.keys()):
        by_state[estado] = ordenar_alertas(by_state[estado])

    salida = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national_critical": national_critical,
        "by_state": dict(by_state),
        "_meta": {
            "total_alerts": len(features),
            "national_critical_count": len(national_critical),
            "states_with_alerts": len(by_state),
            "pipeline": "alerts_by_state_pipeline.py",
        },
    }
    return salida


# ============================================================
# GUARDADO Y SUBIDA
# ============================================================
def guardar_local(data: dict, filepath: str):
    """Guarda el JSON localmente (formato compacto para reducir tamaño)."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(filepath)
    log.info(f"  ✓ JSON guardado en {filepath} ({size:,} bytes)")


def subir_a_cdn(filepath: str):
    """Sube el JSON al CDN usando AWS CLI con el perfil do-tor1."""
    cdn_url = f"s3://{SPACES_BUCKET}/{SPACES_PATH}"
    log.info(f"Subiendo a {cdn_url}...")

    cmd = [
        "aws", "s3", "cp", filepath, cdn_url,
        "--profile", AWS_PROFILE,
        "--acl", "public-read",
        "--content-type", "application/json",
        "--endpoint-url", SPACES_ENDPOINT,
        "--cache-control", "max-age=60",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        log.info("  ✓ Subido al CDN correctamente")
    except subprocess.CalledProcessError as e:
        log.error(f"Error subiendo al CDN: {e.stderr}")
        raise


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Pipeline de alertas NWS por estado")
    parser.add_argument(
        "--once", action="store_true",
        help="Ejecuta una sola vez (comportamiento por defecto)"
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="No subir al CDN, solo generar local (útil para pruebas)"
    )
    args = parser.parse_args()

    inicio = datetime.now()
    log.info("=" * 60)
    log.info("Pipeline alerts_by_state INICIADO")

    try:
        # 1. Descargar alertas
        features = descargar_alertas()

        # 2. Procesar
        log.info("Procesando alertas...")
        salida = construir_json_salida(features)
        log.info(
            f"  ✓ {salida['_meta']['national_critical_count']} críticas nacionales, "
            f"{salida['_meta']['states_with_alerts']} estados con alertas"
        )

        # 3. Guardar local
        guardar_local(salida, OUTPUT_FILE)

        # 4. Subir al CDN
        if not args.no_upload:
            subir_a_cdn(OUTPUT_FILE)
        else:
            log.info("Modo --no-upload: omito subida al CDN")

        duracion = (datetime.now() - inicio).total_seconds()
        log.info(f"Pipeline COMPLETADO en {duracion:.1f}s")
        return 0

    except Exception as e:
        log.error(f"ERROR FATAL: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
