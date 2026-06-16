#!/usr/bin/env python3
"""
=============================================================================
monitor_status.py v2 — Canal Meteo TV
=============================================================================
Recopila el estado de todos los pipelines en sfo3-a y publica un JSON al CDN
para que dev.canalmeteo.tv/monitor.php lo lea.

v2: inventario completo basado en el crontab real (52 jobs activos).

Tipos de pipeline:
  - "runner": tipo NBM/HRRR, hora por hora con barra de progreso
  - "single": un solo proceso

Salida:
  /opt/canalmeteo/data/monitor/status.json  (local)
  s3://canalmeteo-public/monitor/status.json  (CDN, público)

Cron sugerido:
  * * * * * /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/monitor_status.py
=============================================================================
"""

import os
import re
import json
import subprocess
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────
SPACES_BUCKET = "canalmeteo-public"
SPACES_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
AWS_PROFILE = "do-tor1"
OUTPUT_LOCAL = "/opt/canalmeteo/data/monitor/status.json"
OUTPUT_CDN_KEY = "monitor/status.json"

# ─────────────────────────────────────────────────────────────────────────
# DEFINICIÓN DE PIPELINES — basado en crontab real
# ─────────────────────────────────────────────────────────────────────────
PIPELINES = {
    # ═══════ MODELOS NUMÉRICOS ═══════
    "nbm": {
        "category": "Modelos numéricos",
        "display_name": "NBM Surface",
        "type": "runner",
        "log": "/var/log/canalmeteo/nbm.log",
        "lock": "/tmp/nbm.lock",
        "watch_files": ["/opt/canalmeteo/data/nbm/nbm_manifest.json"],
        "schedule": ":20 cada hora",
        "expected_hours": 55,
        "warn_minutes": 120, "alert_minutes": 300,
    },
    "hrrr": {
        "category": "Modelos numéricos",
        "display_name": "HRRR 0-18h",
        "type": "runner",
        "log": "/var/log/canalmeteo/hrrr.log",
        "lock": "/tmp/hrrr.lock",
        "watch_files": ["/opt/canalmeteo/data/hrrr/hrrr_manifest.json"],
        "schedule": ":50 cada hora",
        "expected_hours": 19,
        "warn_minutes": 90, "alert_minutes": 240,
    },
    "hrrr_ext": {
        "category": "Modelos numéricos",
        "display_name": "HRRR Extended 48h",
        "type": "runner",
        "log": "/var/log/canalmeteo/hrrr_ext.log",
        "lock": "/tmp/hrrr_ext.lock",
        "watch_files": ["/opt/canalmeteo/data/hrrr_ext/hrrr_ext_manifest.json"],
        "schedule": "cada 6h (00/06/12/18 UTC)",
        "paused": True,
        "warn_minutes": 480, "alert_minutes": 1440,
    },
    "gfs": {
        "category": "Modelos numéricos",
        "display_name": "GFS",
        "type": "runner",
        "log": "/var/log/canalmeteo/gfs.log",
        "lock": "/tmp/gfs.lock",
        "watch_files": ["/opt/canalmeteo/data/gfs/gfs_manifest.json"],
        "schedule": "cada 6h",
        "paused": True,
        "warn_minutes": 480, "alert_minutes": 1440,
    },

    # ═══════ RADAR Y SATÉLITE ═══════
    "mrms": {
        "category": "Radar y satélite",
        "display_name": "MRMS Reflectividad",
        "type": "single",
        "log": "/var/log/canalmeteo/mrms.log",
        "lock": "/tmp/mrms.lock",
        "schedule": "cada 2 min",
        "warn_minutes": 6, "alert_minutes": 15,
    },
    "radar_compose": {
        "category": "Radar y satélite",
        "display_name": "Radar Compose",
        "type": "single",
        "log": "/var/log/canalmeteo/radar_compose.log",
        "lock": "/tmp/radar_compose.lock",
        "schedule": "cada 5 min",
        "warn_minutes": 15, "alert_minutes": 30,
    },
    "radar_tile": {
        "category": "Radar y satélite",
        "display_name": "Radar Tile",
        "type": "single",
        "log": "/var/log/canalmeteo/radar_proxy.log",
        "lock": "/tmp/radar_tile.lock",
        "schedule": "cada 10 min",
        "warn_minutes": 30, "alert_minutes": 60,
    },
    "satellite": {
        "category": "Radar y satélite",
        "display_name": "GOES-East",
        "type": "single",
        "log": "/var/log/canalmeteo/satellite.log",
        "lock": "/tmp/sat.lock",
        "schedule": "cada 5 min",
        "warn_minutes": 15, "alert_minutes": 45,
    },
    "satellite_regional": {
        "category": "Radar y satélite",
        "display_name": "Satélite Regional (8 zonas)",
        "type": "single",
        "log": "/var/log/canalmeteo/satellite_regional.log",
        "lock": "/tmp/sat_regional.lock",
        "schedule": "cada 5 min",
        "warn_minutes": 15, "alert_minutes": 45,
    },

    # ═══════ ALERTAS Y SEVEROS ═══════
    "tor_warn": {
        "category": "Alertas y severos",
        "display_name": "Tornado Warnings",
        "type": "single",
        "log": "/var/log/canalmeteo/tor_warn.log",
        "lock": "/tmp/tor_warn.lock",
        "schedule": "cada 1 min",
        "warn_minutes": 5, "alert_minutes": 15,
    },
    "tor_voices": {
        "category": "Alertas y severos",
        "display_name": "Tornado Voices",
        "type": "single",
        "log": "/var/log/canalmeteo/tor_voices.log",
        "lock": "/tmp/tor_voices.lock",
        "schedule": "cada 1 min (+30s)",
        "warn_minutes": 5, "alert_minutes": 15,
    },
    "severe_warnings": {
        "category": "Alertas y severos",
        "display_name": "Severe Warnings",
        "type": "single",
        "log": "/var/log/canalmeteo/severe_warnings.log",
        "lock": "/tmp/severe_warnings.lock",
        "schedule": "cada 1 min",
        "warn_minutes": 5, "alert_minutes": 15,
    },
    "tornado_broadcast": {
        "category": "Alertas y severos",
        "display_name": "Tornado Broadcast",
        "type": "single",
        "log": "/var/log/canalmeteo/tornado_broadcast.log",
        "lock": "/tmp/tornado_broadcast.lock",
        "schedule": "cada 1 min",
        "warn_minutes": 5, "alert_minutes": 15,
    },
    "alertas_nws": {
        "category": "Alertas y severos",
        "display_name": "NWS Alerts",
        "type": "single",
        "log": "/opt/canalmeteo/logs/alertas_nws.log",
        "lock": "/tmp/alertas.lock",
        "schedule": "cada 2 min",
        "warn_minutes": 8, "alert_minutes": 20,
    },
    "alerts_by_state": {
        "category": "Alertas y severos",
        "display_name": "Alerts by State",
        "type": "single",
        "log": "/var/log/canalmeteo/alerts_by_state.log",
        "lock": "/tmp/alerts_by_state.lock",
        "schedule": "cada 2 min",
        "warn_minutes": 8, "alert_minutes": 20,
    },
    "voice_warnings": {
        "category": "Alertas y severos",
        "display_name": "Voice Warnings",
        "type": "single",
        "log": "/opt/canalmeteo/logs/voice_warnings.log",
        "lock": "/tmp/voice_warnings.lock",
        "schedule": "cada 2 min",
        "warn_minutes": 8, "alert_minutes": 20,
    },
    "storm_reports": {
        "category": "Alertas y severos",
        "display_name": "Local Storm Reports",
        "type": "single",
        "log": "/var/log/canalmeteo/storm_reports.log",
        "lock": "/tmp/lsr.lock",
        "schedule": "cada 5 min",
        "warn_minutes": 15, "alert_minutes": 45,
    },
    "spc_download": {
        "category": "Alertas y severos",
        "display_name": "SPC Download",
        "type": "single",
        "log": "/opt/canalmeteo/scripts/radar/logs/download_spc.log",
        "lock": "/tmp/spc.lock",
        "schedule": "cada 15 min",
        "warn_minutes": 45, "alert_minutes": 120,
    },
    "spc_to_cdn": {
        "category": "Alertas y severos",
        "display_name": "SPC → CDN",
        "type": "single",
        "log": "/var/log/canalmeteo/spc_to_cdn.log",
        "schedule": "cada 15 min",
        "warn_minutes": 45, "alert_minutes": 120,
    },

    # ═══════ DATOS METEOROLÓGICOS EN TIEMPO REAL ═══════
    "space_weather": {
        "category": "Datos meteorológicos",
        "display_name": "Space Weather",
        "type": "single",
        "log": "/var/log/canalmeteo/space-weather.log",
        "lock": "/tmp/space.lock",
        "schedule": "cada 2 min",
        "warn_minutes": 8, "alert_minutes": 20,
    },
    "metar": {
        "category": "Datos meteorológicos",
        "display_name": "METAR",
        "type": "single",
        "log": "/var/log/canalmeteo/metar.log",
        "lock": "/tmp/metar.lock",
        "schedule": "cada 10 min",
        "warn_minutes": 30, "alert_minutes": 60,
    },
    "aeropuertos": {
        "category": "Datos meteorológicos",
        "display_name": "Aeropuertos FAA",
        "type": "single",
        "log": "/var/log/canalmeteo/aero.log",
        "schedule": "cada 30 min",
        "warn_minutes": 90, "alert_minutes": 180,
    },
    "cities_weather": {
        "category": "Datos meteorológicos",
        "display_name": "Cities Weather (60)",
        "type": "single",
        "log": "/var/log/canalmeteo/cities_weather.log",
        "lock": "/tmp/cities_weather.lock",
        "watch_files": ["/opt/canalmeteo/data/cities_weather.json"],
        "schedule": "cada hora :00",
        "warn_minutes": 90, "alert_minutes": 180,
    },
    "forecast_cities": {
        "category": "Datos meteorológicos",
        "display_name": "Forecast Cities",
        "type": "single",
        "log": "/var/log/canalmeteo/forecast_cities_aggregator.log",
        "schedule": "cada hora :30",
        "warn_minutes": 90, "alert_minutes": 180,
    },
    "forecast_estados": {
        "category": "Datos meteorológicos",
        "display_name": "Forecast Estados (IA)",
        "type": "single",
        "log": "/var/log/canalmeteo/forecast_estados.log",
        "schedule": "cada 6h :30",
        "warn_minutes": 480, "alert_minutes": 900,
    },
    "airquality": {
        "category": "Datos meteorológicos",
        "display_name": "Air Quality",
        "type": "single",
        "log": "/var/log/canalmeteo/airquality.log",
        "schedule": "cada 3h",
        "warn_minutes": 240, "alert_minutes": 480,
    },

    # ═══════ TROPICAL Y FUEGOS ═══════
    # Fuente de verdad tropical desde 2026-06-13: nhc_gis_pipeline.py (esquema GIS de la web).
    # tropical_pipeline.py quedó desactivado en cron (esquema incompatible que lo pisaba).
    "nhc_gis_pipeline": {
        "category": "Tropical y fuegos",
        "display_name": "Tropical (NHC)",
        "type": "single",
        "log": "/var/log/canalmeteo/nhc_gis.log",
        "lock": "/tmp/nhc_gis.lock",
        "schedule": "cada 15 min",
        "warn_minutes": 45, "alert_minutes": 120,
    },
    "fires": {
        "category": "Tropical y fuegos",
        "display_name": "Wildfires (NIFC)",
        "type": "single",
        "log": "/opt/canalmeteo/logs/fires_cron.log",
        "lock": "/tmp/fires.lock",
        "schedule": "cada hora :25",
        "warn_minutes": 120, "alert_minutes": 240,
    },

    # ═══════ TERREMOTOS ═══════
    "terremotos_usgs": {
        "category": "Terremotos",
        "display_name": "Terremotos USGS",
        "type": "single",
        "log": "/var/log/canalmeteo/terremotos.log",
        "schedule": "cada 10 min",
        "warn_minutes": 30, "alert_minutes": 60,
    },
    "terremoto_mag7": {
        "category": "Terremotos",
        "display_name": "Terremoto Mag7",
        "type": "single",
        "log": "/var/log/canalmeteo/terremoto_mag7.log",
        "lock": "/tmp/terremoto_mag7.lock",
        "schedule": "cada hora :01",
        "warn_minutes": 90, "alert_minutes": 180,
    },

    # ═══════ ASTRONOMÍA ═══════
    "astro_lunar": {
        "category": "Astronomía",
        "display_name": "Astro Lunar",
        "type": "single",
        "log": "/var/log/canalmeteo/astro.log",
        "schedule": "cada 6h :50",
        "warn_minutes": 480, "alert_minutes": 900,
    },
    "astro_ephemeris": {
        "category": "Astronomía",
        "display_name": "Astro Ephemeris",
        "type": "single",
        "log": "/var/log/canalmeteo/astro_ephemeris.log",
        "lock": "/tmp/astro_ephemeris.lock",
        "schedule": "diario 00:15",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "astro_planets": {
        "category": "Astronomía",
        "display_name": "Astro Planets",
        "type": "single",
        "log": "/var/log/canalmeteo/astro_planets.log",
        "lock": "/tmp/astro_planets.lock",
        "schedule": "diario 00:25",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "iss_pipeline": {
        "category": "Astronomía",
        "display_name": "ISS",
        "type": "single",
        "log": "/var/log/canalmeteo/iss_pipeline.log",
        "lock": "/tmp/iss-pipeline.lock",
        "schedule": "cada 6h :15",
        "warn_minutes": 480, "alert_minutes": 900,
    },
    "cielo_pipeline": {
        "category": "Astronomía",
        "display_name": "Cielo",
        "type": "single",
        "log": "/var/log/canalmeteo/cielo_pipeline.log",
        "lock": "/tmp/cielo_pipeline.lock",
        "schedule": "cada hora :30",
        "warn_minutes": 90, "alert_minutes": 180,
    },

    # ═══════ RECORDS Y CLIMATOLOGÍA ═══════
    "records": {
        "category": "Records y climatología",
        "display_name": "Records SPC",
        "type": "single",
        "log": "/var/log/canalmeteo/records.log",
        "lock": "/tmp/records.lock",
        "schedule": "cada 30 min (:12, :42)",
        "warn_minutes": 90, "alert_minutes": 180,
    },
    "records_daily": {
        "category": "Records y climatología",
        "display_name": "Records Diarios",
        "type": "single",
        "log": "/var/log/canalmeteo/records_daily.log",
        "lock": "/tmp/records_daily.lock",
        "schedule": "cada hora :15",
        "warn_minutes": 90, "alert_minutes": 180,
    },
    "records_potenciales": {
        "category": "Records y climatología",
        "display_name": "Records Potenciales",
        "type": "single",
        "log": "/var/log/canalmeteo/records.log",  # comparte log
        "schedule": "diario 04:00",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "first_100f": {
        "category": "Records y climatología",
        "display_name": "Primeros 100°F",
        "type": "single",
        "log": "/opt/canalmeteo/data/first100f/cron.log",
        "schedule": "07:00 y 19:00",
        "warn_minutes": 800, "alert_minutes": 1500,
    },

    # ═══════ DIARIOS LYNX (sin log redirigido) ═══════
    # Estos NO redireccionan a log file, así que solo podemos saber por watch_files
    "spc_outlook_daily": {
        "category": "Diarios (lynx)",
        "display_name": "SPC Outlook (lynx)",
        "type": "single",
        "schedule": "diario 05:05",
        "warn_minutes": 1500, "alert_minutes": 2880,
        "note": "sin log redirigido — solo se detecta por archivos de salida",
    },
    "nfd_tmax": {
        "category": "Diarios (lynx)",
        "display_name": "NFD T° Máxima",
        "type": "single",
        "schedule": "diario 05:10",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "nfd_tmin": {
        "category": "Diarios (lynx)",
        "display_name": "NFD T° Mínima",
        "type": "single",
        "schedule": "diario 05:20",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "nfd_aparente": {
        "category": "Diarios (lynx)",
        "display_name": "NFD T° Aparente",
        "type": "single",
        "schedule": "diario 05:30",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "heladas": {
        "category": "Diarios (lynx)",
        "display_name": "Heladas",
        "type": "single",
        "schedule": "diario 07:20",
        "warn_minutes": 1500, "alert_minutes": 2880,
    },
    "poblacion_alertas": {
        "category": "Diarios (lynx)",
        "display_name": "Población Alertas",
        "type": "single",
        "schedule": "cada hora :10",
        "warn_minutes": 90, "alert_minutes": 180,
        "note": "sin log redirigido",
    },

    # ═══════ OTROS ═══════
    "sync_beach": {
        "category": "Otros",
        "display_name": "Sync Beach",
        "type": "single",
        "log": "/var/log/canalmeteo/sync-beach.log",
        "lock": "/tmp/sync-beach.lock",
        "schedule": "cada 4h",
        "warn_minutes": 300, "alert_minutes": 600,
    },
    "drought": {
        "category": "Otros",
        "display_name": "Drought",
        "type": "single",
        "log": "/var/log/canalmeteo/drought.log",
        "schedule": "semanal (jueves)",
        "warn_minutes": 10800, "alert_minutes": 14400,  # 7.5d / 10d
    },
}

# ─────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────
def now_utc():
    return datetime.now(timezone.utc)

def file_mtime(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    except Exception:
        return None

def is_lock_active(lock_path):
    """¿El lock existe Y hay proceso vivo tenedor?"""
    if not lock_path or not os.path.exists(lock_path):
        return False
    try:
        result = subprocess.run(
            ["fuser", lock_path],
            capture_output=True, text=True, timeout=2
        )
        return bool(result.stdout.strip())
    except Exception:
        return False

def tail_log(log_path, n=300):
    if not log_path or not os.path.exists(log_path):
        return ""
    try:
        result = subprocess.run(
            ["tail", "-n", str(n), log_path],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout
    except Exception:
        return ""

def parse_runner_progress(log_content):
    info = {}
    m = re.findall(r"Ciclo detectado: (\d+)/(\d+)z", log_content)
    if m:
        info["cycle"] = f"{m[-1][0]}/{m[-1][1]}z"
    m = re.findall(r"── f(\d+) \((\d+)/(\d+)\) ──", log_content)
    if m:
        last = m[-1]
        info["progress_current"] = int(last[1])
        info["progress_total"] = int(last[2])
        info["current_hour"] = int(last[0])
    m = re.findall(r"Horas procesadas: (\d+) OK · (\d+) fallos · (\d+) total", log_content)
    if m:
        last = m[-1]
        info["last_run_ok"] = int(last[0])
        info["last_run_fail"] = int(last[1])
        info["last_run_total"] = int(last[2])
    starts = re.findall(r"\[([\d-]+ [\d:]+)\][^\n]*Runner — subprocess", log_content)
    if starts:
        info["last_start"] = starts[-1]
    return info

def freshness_status(mtime, warn_min, alert_min):
    if not mtime:
        return "none"
    age_min = (now_utc() - mtime).total_seconds() / 60
    if age_min < warn_min:
        return "fresh"
    elif age_min < alert_min:
        return "warn"
    else:
        return "alert"

def detect_errors_in_log(log_content):
    """Detecta errores específicos comunes en los logs."""
    errors = []
    if re.search(r"source: not found", log_content):
        errors.append("source not found (cron usa /bin/sh, necesita bash -c)")
    if re.search(r"ModuleNotFoundError|ImportError", log_content):
        errors.append("módulo Python no encontrado")
    if re.search(r"Permission denied", log_content):
        errors.append("permisos")
    # Solo retorna el último error encontrado
    return errors[-1] if errors else None

def check_pipeline(name, config):
    out = {
        "name": name,
        "display_name": config["display_name"],
        "category": config["category"],
        "type": config["type"],
        "schedule": config.get("schedule", ""),
        "paused": config.get("paused", False),
    }
    if "note" in config:
        out["note"] = config["note"]

    out["running"] = is_lock_active(config.get("lock"))

    # Última actualización
    last_mtime = None
    for wf in config.get("watch_files", []):
        mt = file_mtime(wf)
        if mt:
            last_mtime = mt
            break
    if not last_mtime and config.get("log"):
        last_mtime = file_mtime(config["log"])
    out["last_update"] = last_mtime.isoformat() if last_mtime else None

    warn = config.get("warn_minutes", 30)
    alert = config.get("alert_minutes", 120)
    out["freshness"] = freshness_status(last_mtime, warn, alert)

    # Parsing extra
    log_content = tail_log(config.get("log"), n=400)
    if config["type"] == "runner":
        out.update(parse_runner_progress(log_content))

    # Detección de errores comunes
    err = detect_errors_in_log(log_content)
    if err:
        out["detected_error"] = err

    return out

def main():
    pipelines = {}
    for name, config in PIPELINES.items():
        try:
            pipelines[name] = check_pipeline(name, config)
        except Exception as e:
            pipelines[name] = {
                "name": name,
                "display_name": config.get("display_name", name),
                "category": config.get("category", "Otros"),
                "error": str(e),
            }

    output = {
        "generated_at": now_utc().isoformat(),
        "hostname": os.uname().nodename,
        "pipelines": pipelines,
    }

    os.makedirs(os.path.dirname(OUTPUT_LOCAL), exist_ok=True)
    with open(OUTPUT_LOCAL, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    try:
        subprocess.run([
            "aws", "s3", "cp", OUTPUT_LOCAL,
            f"s3://{SPACES_BUCKET}/{OUTPUT_CDN_KEY}",
            "--profile", AWS_PROFILE,
            "--endpoint-url", SPACES_ENDPOINT,
            "--acl", "public-read",
            "--content-type", "application/json",
            "--cache-control", "max-age=20, public"
        ], check=True, capture_output=True, timeout=30)
    except Exception as e:
        print(f"Error subiendo al CDN: {e}")

if __name__ == "__main__":
    main()
