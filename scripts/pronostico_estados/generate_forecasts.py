#!/usr/bin/env python3
"""
Canal Meteo TV - Generador de pronóstico por estado
Extrae datos del NWS API, genera narrativas con Claude y produce HTML estático.
Sube automáticamente al hosting de canalmeteo.tv via SFTP.

Flujo:
    DigitalOcean (cron) → NWS API → Claude API → HTML → SFTP → GoDaddy (canalmeteo.tv)

Archivos que se suben al FTP:
    /public_html/pronostico/index.html              ← Índice con los 51 estados
    /public_html/pronostico/texas/index.html         ← Página de Texas
    /public_html/pronostico/florida/index.html       ← Página de Florida
    ... (un directorio por estado)

Uso:
    python3 generate_forecasts.py                  # Todos los estados + subir
    python3 generate_forecasts.py texas florida     # Solo estos estados + subir
    python3 generate_forecasts.py --no-ai           # Sin narrativa IA
    python3 generate_forecasts.py --no-upload       # Solo generar, no subir
    python3 generate_forecasts.py --use-rsync       # Usar rsync en vez de SCP

Cron:
    0 */6 * * * cd /opt/canalmeteo/scripts/pronostico_estados && \\
        ANTHROPIC_API_KEY=$(cat /opt/canalmeteo/.env_anthropic_key) \\
        /opt/canalmeteo/venv/bin/python3 generate_forecasts.py \\
        >> /var/log/canalmeteo/forecast_estados.log 2>&1
"""

import os
import sys
import json
import time
import logging
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from states_config import STATES, translate_condition

# ============================================================
# CONFIGURACIÓN
# ============================================================
CONFIG = {
    # Directorios locales en DigitalOcean
    "output_dir": "/opt/canalmeteo/output/pronostico",
    "cache_dir": "/opt/canalmeteo/cache/pronostico_estados",

    # Anthropic
    "anthropic_api_key_env": "ANTHROPIC_API_KEY",
    "anthropic_model": "claude-sonnet-4-20250514",
    "anthropic_max_tokens": 1500,

    # NWS
    "nws_user_agent": "(CanalMeteoTV, contacto@canalmeteo.tv)",
    "nws_base_url": "https://api.weather.gov",
    "nws_timeout": 15,
    "nws_retry_count": 3,
    "nws_retry_delay": 2,

    # SFTP al hosting (se lee de .env)
    "sftp_enabled": True,
    "sftp_host": "",
    "sftp_user": "",
    "sftp_port": 22,
    "sftp_pass": "",
    "sftp_key": "",  # Clave OpenSSH (convertida de .ppk)
    "sftp_remote_base": "/home/zz7622j72pvq/public_html/canalmeteo.tv/pronostico",

    # General
    "site_url": "https://www.canalmeteo.tv",
    "env_file": "/opt/canalmeteo/scripts/.env",
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("forecast_gen")


# ============================================================
# CARGAR .env
# ============================================================
def load_env():
    env_path = Path(CONFIG["env_file"])
    if not env_path.exists():
        logger.warning(f".env no encontrado: {env_path}")
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            val = val.strip().strip('"').strip("'")
            mapping = {
                "SFTP_HOST": "sftp_host", "SFTP_USER": "sftp_user",
                "SFTP_PASS": "sftp_pass", "SFTP_KEY": "sftp_key",
                "SFTP_PORT": "sftp_port",
            }
            if key in mapping:
                CONFIG[mapping[key]] = int(val) if key == "SFTP_PORT" else val

    if CONFIG["sftp_host"] and CONFIG["sftp_user"]:
        auth = "clave" if CONFIG["sftp_key"] else "contraseña"
        logger.info(f"SFTP configurado: {CONFIG['sftp_user']}@{CONFIG['sftp_host']} ({auth})")
    else:
        logger.warning("SFTP no configurado, se desactiva subida")
        CONFIG["sftp_enabled"] = False


# ============================================================
# SFTP UPLOADER
# ============================================================
class SFTPUploader:
    """Sube archivos al hosting de canalmeteo.tv via SCP/rsync."""

    def __init__(self):
        self.host = CONFIG["sftp_host"]
        self.user = CONFIG["sftp_user"]
        self.port = CONFIG["sftp_port"]

    def _ssh_auth_args(self):
        """Devuelve argumentos de autenticación para SSH/SCP."""
        key = CONFIG["sftp_key"]
        passwd = CONFIG["sftp_pass"]
        if key and os.path.exists(key):
            return f"-i {key}", ""
        elif passwd:
            return "", f"sshpass -p '{passwd}'"
        return "", ""

    def _run_cmd(self, cmd, timeout=60):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stderr
        except Exception as e:
            return False, str(e)

    def ensure_remote_dir(self, remote_dir):
        ssh_auth, prefix = self._ssh_auth_args()
        cmd = f"{prefix} ssh {ssh_auth} -o StrictHostKeyChecking=no -p {self.port} {self.user}@{self.host} 'mkdir -p {remote_dir}'"
        self._run_cmd(cmd, timeout=30)

    def upload_file(self, local_path, remote_path):
        ssh_auth, prefix = self._ssh_auth_args()
        cmd = f"{prefix} scp {ssh_auth} -o StrictHostKeyChecking=no -P {self.port} {local_path} {self.user}@{self.host}:{remote_path}"
        ok, err = self._run_cmd(cmd)
        if not ok:
            logger.error(f"Error SCP {Path(local_path).name}: {err}")
        return ok

    def sync_all(self, local_dir):
        """Sube todos los HTML generados al hosting."""
        local = Path(local_dir)
        remote_base = CONFIG["sftp_remote_base"]
        uploaded, failed = 0, 0

        # Index principal
        idx = local / "index.html"
        if idx.exists():
            self.ensure_remote_dir(remote_base)
            if self.upload_file(str(idx), f"{remote_base}/index.html"):
                uploaded += 1
                logger.info(f"  ↑ index.html")
            else:
                failed += 1

        # Cada estado
        for state_dir in sorted(local.iterdir()):
            if state_dir.is_dir() and (state_dir / "index.html").exists():
                slug = state_dir.name
                remote_dir = f"{remote_base}/{slug}"
                self.ensure_remote_dir(remote_dir)
                if self.upload_file(str(state_dir / "index.html"), f"{remote_dir}/index.html"):
                    uploaded += 1
                    logger.info(f"  ↑ {slug}/index.html")
                else:
                    failed += 1

        logger.info(f"SFTP completado: {uploaded} subidos, {failed} fallidos")
        return failed == 0

    def sync_rsync(self, local_dir):
        """Alternativa más eficiente con rsync."""
        ssh_auth, prefix = self._ssh_auth_args()
        remote_base = CONFIG["sftp_remote_base"]
        ssh_cmd = f"{prefix} ssh {ssh_auth} -p {self.port} -o StrictHostKeyChecking=no".strip()
        cmd = f"rsync -avz --delete -e '{ssh_cmd}' {local_dir}/ {self.user}@{self.host}:{remote_base}/"
        ok, err = self._run_cmd(cmd, timeout=600)
        if ok:
            logger.info("✓ rsync completado")
        else:
            logger.error(f"✗ rsync falló: {err}")
        return ok


# ============================================================
# NWS FETCHER
# ============================================================
class NWSFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": CONFIG["nws_user_agent"],
            "Accept": "application/geo+json",
        })
        self.cache_dir = Path(CONFIG["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, url):
        for attempt in range(CONFIG["nws_retry_count"]):
            try:
                r = self.session.get(url, timeout=CONFIG["nws_timeout"])
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 503:
                    time.sleep(CONFIG["nws_retry_delay"] * (attempt + 1))
                    continue
                logger.error(f"NWS {r.status_code}: {url}")
                return None
            except requests.RequestException as e:
                logger.warning(f"NWS error ({attempt+1}): {e}")
                time.sleep(CONFIG["nws_retry_delay"] * (attempt + 1))
        return None

    def get_gridpoint(self, lat, lon):
        cache_file = self.cache_dir / f"grid_{lat:.4f}_{lon:.4f}.json"
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 30*86400:
            with open(cache_file) as f:
                return json.load(f)
        data = self._get(f"{CONFIG['nws_base_url']}/points/{lat},{lon}")
        if not data:
            return None
        props = data.get("properties", {})
        info = {"forecast_url": props.get("forecast")}
        with open(cache_file, "w") as f:
            json.dump(info, f)
        return info

    def get_forecast(self, lat, lon):
        grid = self.get_gridpoint(lat, lon)
        if not grid or not grid.get("forecast_url"):
            return None
        data = self._get(grid["forecast_url"])
        if not data:
            return None
        return self._parse(data.get("properties", {}).get("periods", []))

    def _parse(self, periods):
        parsed = []
        for p in periods[:14]:
            precip = p.get("probabilityOfPrecipitation", {})
            humidity = p.get("relativeHumidity", {})
            dewpoint = p.get("dewpoint", {})
            dp_val = dewpoint.get("value") if isinstance(dewpoint, dict) else None
            parsed.append({
                "nombre": p.get("name", ""),
                "es_dia": p.get("isDaytime", True),
                "temperatura": p.get("temperature"),
                "probabilidad_precip": precip.get("value") if isinstance(precip, dict) else None,
                "humedad_relativa": humidity.get("value") if isinstance(humidity, dict) else None,
                "velocidad_viento": p.get("windSpeed", ""),
                "direccion_viento": p.get("windDirection", ""),
                "resumen_corto": p.get("shortForecast", ""),
                "resumen_corto_es": translate_condition(p.get("shortForecast", "")),
                "punto_rocio": round(dp_val * 9/5 + 32, 1) if dp_val is not None else None,
            })
        return parsed


# ============================================================
# UTILIDADES
# ============================================================
def f_to_c(f):
    return round((f - 32) * 5/9, 1) if f is not None else None

def heat_index(t, h):
    if t is None or h is None or t < 80: return None
    return round(-42.379+2.049*t+10.143*h-0.225*t*h-0.007*t*t-0.055*h*h+0.001*t*t*h+0.001*t*h*h-0.000002*t*t*h*h, 1)

def wind_chill(t, w):
    if t is None or t > 50: return None
    try: ws = float(str(w).split()[0])
    except: return None
    if ws < 3: return None
    return round(35.74+0.6215*t-35.75*(ws**0.16)+0.4275*t*(ws**0.16), 1)

def uv_est(cond, is_day, lat):
    if not is_day: return 0
    b = 8 if abs(lat)<30 else (4 if abs(lat)>45 else 6)
    c = (cond or "").lower()
    if "cloudy" in c or "overcast" in c: b*=0.5
    elif "partly" in c: b*=0.75
    elif any(w in c for w in ["rain","storm","snow"]): b*=0.3
    return min(round(b), 11)

def uv_label(uv):
    if uv<=2: return "Bajo"
    if uv<=5: return "Moderado"
    if uv<=7: return "Alto"
    if uv<=10: return "Muy alto"
    return "Extremo"


# ============================================================
# NARRATIVA CON CLAUDE
# ============================================================
class NarrativeGenerator:
    def __init__(self):
        self.api_key = os.environ.get(CONFIG["anthropic_api_key_env"])
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY no configurada")

    def generate(self, state_name, cities_data):
        if not self.api_key:
            return self._fallback(state_name, cities_data)

        summary_lines = [f"Estado: {state_name}", f"Fecha: {datetime.now().strftime('%d de %B de %Y')}", ""]
        for city, forecast in cities_data.items():
            if not forecast: continue
            summary_lines.append(f"--- {city} ---")
            for p in forecast[:6]:
                line = f"  {p['nombre']}: {p.get('temperatura','?')}°F, {p['resumen_corto']}"
                if p.get('probabilidad_precip'): line += f", precip {p['probabilidad_precip']}%"
                if p.get('velocidad_viento'): line += f", viento {p['velocidad_viento']}"
                summary_lines.append(line)

        prompt = f"""Eres un meteorólogo de Canal Meteo TV (canal del tiempo en español para hispanos en EE.UU.).
Genera un resumen del pronóstico para {state_name}: 2-3 párrafos, máx 200 palabras.
Usa "tiempo" (no "clima"), español profesional pero accesible. Sin markdown ni encabezados.
Destaca eventos severos, cambios bruscos, y da recomendaciones prácticas.

DATOS:
{chr(10).join(summary_lines)}"""

        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"Content-Type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={"model": CONFIG["anthropic_model"], "max_tokens": CONFIG["anthropic_max_tokens"],
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30)
            if r.status_code == 200:
                text = r.json().get("content", [{}])[0].get("text", "")
                if text:
                    logger.info(f"  Narrativa IA generada para {state_name}")
                    return text
            else:
                logger.error(f"API error {r.status_code}")
        except Exception as e:
            logger.error(f"Error narrativa: {e}")
        return self._fallback(state_name, cities_data)

    def _fallback(self, state_name, cities_data):
        parts = []
        for city, fc in cities_data.items():
            if fc: parts.append(f"{city}: {fc[0].get('temperatura','?')}°F, {fc[0].get('resumen_corto_es','')}")
        return f"Condiciones en {state_name}: {'. '.join(parts[:4])}."


# ============================================================
# HTML GENERATOR
# ============================================================
class HTMLGenerator:
    def __init__(self):
        self.output_dir = Path(CONFIG["output_dir"])

    def _css(self):
        """CSS compartido entre todas las páginas."""
        return """
        :root {
            --cm-blue: #0A1628; --cm-blue-light: #1a2d4a;
            --cm-accent: #00B4D8; --cm-accent-warm: #FF6B35;
            --cm-text: #E8EDF3; --cm-text-muted: #8899AA;
            --cm-card-bg: rgba(255,255,255,0.06);
            --cm-card-border: rgba(255,255,255,0.08);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'Inter',sans-serif; background:var(--cm-blue); color:var(--cm-text); min-height:100vh; line-height:1.6; }
        .header { background:linear-gradient(180deg,rgba(0,180,216,0.15),transparent); border-bottom:1px solid var(--cm-card-border); padding:1rem 2rem; }
        .header-inner { max-width:1400px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; }
        .logo { font-family:'Outfit',sans-serif; font-size:1.5rem; font-weight:800; color:var(--cm-accent); text-decoration:none; }
        .logo span { color:var(--cm-text); }
        .breadcrumb { font-size:.85rem; color:var(--cm-text-muted); }
        .breadcrumb a { color:var(--cm-accent); text-decoration:none; }
        .state-hero { max-width:1400px; margin:0 auto; padding:2.5rem 2rem 1.5rem; }
        .state-hero h1 { font-family:'Outfit',sans-serif; font-size:2.5rem; font-weight:800; }
        .state-hero h1 .abbr { color:var(--cm-accent); font-weight:600; font-size:1.5rem; vertical-align:super; margin-left:.5rem; }
        .update-time { color:var(--cm-text-muted); font-size:.85rem; margin-bottom:1.5rem; }
        .narrative { max-width:1400px; margin:0 auto; padding:0 2rem 2rem; }
        .narrative-box { background:var(--cm-card-bg); border:1px solid var(--cm-card-border); border-left:4px solid var(--cm-accent); border-radius:12px; padding:1.5rem 2rem; line-height:1.8; }
        .narrative-box p { margin-bottom:.8rem; }
        .narrative-label { font-size:.75rem; text-transform:uppercase; letter-spacing:.1em; color:var(--cm-accent); font-weight:600; margin-bottom:.8rem; }
        .cities-section { max-width:1400px; margin:0 auto; padding:0 2rem 3rem; }
        .section-title { font-family:'Outfit',sans-serif; font-size:1.5rem; font-weight:700; margin-bottom:1.5rem; border-bottom:2px solid var(--cm-card-border); padding-bottom:.5rem; }
        .cities-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(380px,1fr)); gap:1.5rem; }
        .city-card { background:var(--cm-card-bg); border:1px solid var(--cm-card-border); border-radius:16px; overflow:hidden; transition:transform .2s,border-color .2s; }
        .city-card:hover { transform:translateY(-2px); border-color:rgba(0,180,216,0.3); }
        .city-header { padding:1.2rem 1.5rem .8rem; display:flex; justify-content:space-between; align-items:flex-start; }
        .city-name { font-family:'Outfit',sans-serif; font-size:1.3rem; font-weight:700; }
        .city-temp { font-family:'Outfit',sans-serif; font-size:2.2rem; font-weight:800; line-height:1; }
        .city-temp.warm { color:var(--cm-accent-warm); }
        .city-temp.cool { color:var(--cm-accent); }
        .city-temp.cold { color:#90E0EF; }
        .city-cond { padding:0 1.5rem .8rem; color:var(--cm-text-muted); font-size:.9rem; }
        .details { display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid var(--cm-card-border); border-bottom:1px solid var(--cm-card-border); }
        .det { padding:.7rem .8rem; text-align:center; border-right:1px solid var(--cm-card-border); }
        .det:last-child { border-right:none; }
        .det-l { font-size:.65rem; text-transform:uppercase; letter-spacing:.05em; color:var(--cm-text-muted); margin-bottom:.2rem; }
        .det-v { font-size:.95rem; font-weight:600; }
        .fc-days { padding:1rem 1.5rem; }
        .fc-day { display:grid; grid-template-columns:120px 1fr auto auto; align-items:center; gap:.8rem; padding:.6rem 0; border-bottom:1px solid rgba(255,255,255,0.04); }
        .fc-day:last-child { border-bottom:none; }
        .fc-name { font-weight:600; font-size:.85rem; }
        .fc-cond { font-size:.8rem; color:var(--cm-text-muted); }
        .fc-precip { font-size:.8rem; color:var(--cm-accent); }
        .fc-temps { font-weight:600; font-size:.9rem; white-space:nowrap; }
        .t-hi { color:var(--cm-accent-warm); }
        .t-lo { color:var(--cm-accent); }
        .footer { max-width:1400px; margin:0 auto; padding:2rem; text-align:center; color:var(--cm-text-muted); font-size:.8rem; border-top:1px solid var(--cm-card-border); }
        .footer a { color:var(--cm-accent); text-decoration:none; }
        /* Index styles */
        .hero { max-width:1400px; margin:0 auto; padding:2.5rem 2rem 1rem; text-align:center; }
        .hero h1 { font-family:'Outfit',sans-serif; font-size:2.5rem; font-weight:800; }
        .hero p { color:var(--cm-text-muted); font-size:1.05rem; max-width:600px; margin:.5rem auto 1rem; }
        .search-box { max-width:500px; margin:1.5rem auto 2rem; position:relative; }
        .search-box input { width:100%; padding:.9rem 1.2rem .9rem 3rem; border-radius:12px; border:1px solid var(--cm-card-border); background:var(--cm-card-bg); color:var(--cm-text); font-size:1rem; outline:none; }
        .search-box input:focus { border-color:var(--cm-accent); }
        .search-box input::placeholder { color:var(--cm-text-muted); }
        .search-icon { position:absolute; left:1rem; top:50%; transform:translateY(-50%); color:var(--cm-text-muted); }
        .states-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:.6rem; max-width:1400px; margin:0 auto; padding:0 2rem 3rem; }
        .state-item { display:flex; align-items:center; gap:.8rem; padding:.9rem 1.2rem; background:var(--cm-card-bg); border:1px solid var(--cm-card-border); border-radius:10px; text-decoration:none; color:var(--cm-text); transition:all .2s; }
        .state-item:hover { border-color:var(--cm-accent); background:rgba(0,180,216,0.08); transform:translateY(-1px); }
        .st-abbr { background:var(--cm-accent); color:var(--cm-blue); font-weight:700; font-size:.75rem; padding:.3rem .5rem; border-radius:6px; min-width:2.2rem; text-align:center; }
        .st-name { flex:1; font-weight:500; }
        .st-temp { color:var(--cm-text-muted); font-size:.85rem; }
        @media(max-width:768px) {
            .state-hero h1,.hero h1 { font-size:1.8rem; }
            .cities-grid { grid-template-columns:1fr; }
            .states-grid { grid-template-columns:1fr; }
            .fc-day { grid-template-columns:90px 1fr auto auto; gap:.4rem; }
            .details { grid-template-columns:repeat(2,1fr); }
            .det:nth-child(2) { border-right:none; }
            .header-inner { flex-direction:column; gap:.5rem; }
        }"""

    def _head(self, title, description, canonical):
        return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<link rel="canonical" href="{canonical}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@600;700;800&display=swap" rel="stylesheet">
<style>{self._css()}</style>
</head>"""

    def _header(self, breadcrumb_html):
        return f"""<header class="header"><div class="header-inner">
<a href="{CONFIG['site_url']}/" class="logo">CANAL<span>METEO</span></a>
<nav class="breadcrumb">{breadcrumb_html}</nav>
</div></header>"""

    def _footer(self, year):
        return f"""<footer class="footer">
<p>Datos: <a href="https://www.weather.gov" target="_blank">National Weather Service</a>. Narrativa generada por IA.</p>
<p style="margin-top:.5rem">&copy; {year} <a href="{CONFIG['site_url']}/">Canal Meteo TV</a></p>
</footer>"""

    def _city_card(self, name, info, forecast):
        if not forecast: return ""
        cur = forecast[0]
        t = cur.get("temperatura", 0) or 0
        tc = "warm" if t>=80 else ("cold" if t<=32 else "cool")
        cond = cur.get("resumen_corto_es", cur.get("resumen_corto",""))
        hum = cur.get("humedad_relativa")
        wind = cur.get("velocidad_viento","")
        wdir = cur.get("direccion_viento","")
        precip = cur.get("probabilidad_precip")
        dp = cur.get("punto_rocio")
        lat = info.get("lat", 35)

        fl = heat_index(t, hum) if t>=80 and hum else wind_chill(t, wind)
        uv = uv_est(cur.get("resumen_corto",""), cur.get("es_dia",True), lat)

        WDIR = {"N":"N","S":"S","E":"E","W":"O","NE":"NE","NW":"NO","SE":"SE","SW":"SO"}
        wd = WDIR.get(wdir, wdir)

        fl_s = f"{fl}°F" if fl else f"{t}°F"
        hum_s = f"{hum}%" if hum else "N/D"
        pr_s = f"{precip}%" if precip else "0%"
        dp_s = f"{dp}°F" if dp else "N/D"

        # Pair days
        pairs = self._pair_days(forecast)
        fc_html = ""
        for p in pairs[:5]:
            pr = f'<span class="fc-precip">{p["precip"]}%</span>' if p.get("precip") else ""
            fc_html += f'<div class="fc-day"><span class="fc-name">{p["name_es"]}</span><span class="fc-cond">{p["cond"]}</span>{pr}<span class="fc-temps"><span class="t-hi">{p["hi"]}°</span> / <span class="t-lo">{p["lo"]}°</span></span></div>'

        return f"""<div class="city-card">
<div class="city-header"><span class="city-name">{name}</span><span class="city-temp {tc}">{t}°F</span></div>
<div class="city-cond">{cond}</div>
<div class="details">
<div class="det"><div class="det-l">Sensación</div><div class="det-v">{fl_s}</div></div>
<div class="det"><div class="det-l">Humedad</div><div class="det-v">{hum_s}</div></div>
<div class="det"><div class="det-l">Viento</div><div class="det-v">{wd} {wind}</div></div>
<div class="det"><div class="det-l">UV</div><div class="det-v">{uv} {uv_label(uv)}</div></div>
</div>
<div class="details" style="border-top:none">
<div class="det"><div class="det-l">Precip.</div><div class="det-v">{pr_s}</div></div>
<div class="det"><div class="det-l">Pto. rocío</div><div class="det-v">{dp_s}</div></div>
<div class="det" style="grid-column:span 2"><div class="det-l">Temp. (°C)</div><div class="det-v">{f_to_c(t)}°C</div></div>
</div>
<div class="fc-days">{fc_html}</div>
</div>"""

    def _pair_days(self, periods):
        D = {"Monday":"Lunes","Tuesday":"Martes","Wednesday":"Miércoles","Thursday":"Jueves",
             "Friday":"Viernes","Saturday":"Sábado","Sunday":"Domingo","Today":"Hoy",
             "Tonight":"Esta noche","This Afternoon":"Esta tarde","Overnight":"Madrugada"}
        pairs, i = [], 0
        while i < len(periods) and len(pairs) < 5:
            p = periods[i]
            nm = p["nombre"]
            ne = nm
            for k,v in D.items():
                if k in nm: ne=v; break
            if p.get("es_dia"):
                hi = p.get("temperatura","")
                lo = periods[i+1].get("temperatura","") if i+1<len(periods) and not periods[i+1].get("es_dia") else ""
                if lo: i+=1
                pairs.append({"name_es":ne,"hi":hi,"lo":lo,"cond":p.get("resumen_corto_es",""),"precip":p.get("probabilidad_precip")})
            else:
                pairs.append({"name_es":ne,"hi":"--","lo":p.get("temperatura",""),"cond":p.get("resumen_corto_es",""),"precip":p.get("probabilidad_precip")})
            i+=1
        return pairs

    def generate_state_page(self, slug, state, narrative, forecasts):
        d = self.output_dir / slug
        d.mkdir(parents=True, exist_ok=True)
        nm, ab = state["nombre"], state["abreviatura"]
        now = datetime.now(timezone.utc)
        ut = now.strftime("%d/%m/%Y %H:%M UTC")

        cities = ""
        for ci in state["ciudades"]:
            fc = forecasts.get(ci["nombre"], [])
            if fc: cities += self._city_card(ci["nombre"], ci, fc)

        narr = "\n".join(f"<p>{p}</p>" for p in narrative.split("\n") if p.strip()) if narrative else "<p>No disponible.</p>"

        bc = f'<a href="{CONFIG["site_url"]}/">Inicio</a> › <a href="{CONFIG["site_url"]}/pronostico/">Pronóstico</a> › {nm}'
        html = f"""{self._head(f"Pronóstico {nm} - Canal Meteo TV", f"Pronóstico del tiempo para {nm} ({ab}). Canal Meteo TV.", f"{CONFIG['site_url']}/pronostico/{slug}/")}
<body>
{self._header(bc)}
<section class="state-hero"><h1>{nm} <span class="abbr">{ab}</span></h1><div class="update-time">Actualizado: {ut}</div></section>
<section class="narrative"><div class="narrative-box"><div class="narrative-label">Resumen del tiempo</div>{narr}</div></section>
<section class="cities-section"><h2 class="section-title">Pronóstico por ciudad</h2><div class="cities-grid">{cities}</div></section>
{self._footer(now.year)}
</body></html>"""

        with open(d/"index.html","w",encoding="utf-8") as f: f.write(html)
        logger.info(f"  HTML: {slug}/index.html")

    def generate_index(self, summary):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        ut = now.strftime("%d/%m/%Y %H:%M UTC")

        items = ""
        for slug, info in sorted(summary.items(), key=lambda x: x[1]["nombre"]):
            items += f'<a href="{CONFIG["site_url"]}/pronostico/{slug}/" class="state-item"><span class="st-abbr">{info["abreviatura"]}</span><span class="st-name">{info["nombre"]}</span><span class="st-temp">{info.get("temp_summary","")}</span></a>'

        bc = f'<a href="{CONFIG["site_url"]}/">Inicio</a> › Pronóstico por estado'
        html = f"""{self._head("Pronóstico por estado - Canal Meteo TV", "Pronóstico del tiempo para los 50 estados de EE.UU. en español.", f"{CONFIG['site_url']}/pronostico/")}
<body>
{self._header(bc)}
<section class="hero"><h1>Pronóstico por estado</h1><p>Selecciona un estado para ver el pronóstico detallado del tiempo.</p><div class="update-time">Última actualización: {ut}</div></section>
<div class="search-box"><svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg><input type="text" id="s" placeholder="Buscar estado..." autocomplete="off"></div>
<div class="states-grid" id="g">{items}</div>
{self._footer(now.year)}
<script>document.getElementById('s').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('.state-item').forEach(i=>{{const n=i.querySelector('.st-name').textContent.toLowerCase();const a=i.querySelector('.st-abbr').textContent.toLowerCase();i.style.display=(n.includes(q)||a.includes(q))?'flex':'none'}})}});</script>
</body></html>"""

        with open(self.output_dir/"index.html","w",encoding="utf-8") as f: f.write(html)
        logger.info("HTML: index.html")


# ============================================================
# MAIN
# ============================================================
def process_state(slug, data, fetcher, narrator, html_gen, use_ai=True):
    nm = data["nombre"]
    logger.info(f"Procesando {nm}...")
    forecasts = {}
    for city in data["ciudades"]:
        cn = city["nombre"]
        fc = fetcher.get_forecast(city["lat"], city["lon"])
        if fc:
            forecasts[cn] = fc
            logger.info(f"  ✓ {cn}: {len(fc)} períodos")
        else:
            logger.warning(f"  ✗ {cn}: sin datos")
        time.sleep(0.3)

    if not forecasts:
        logger.error(f"Sin datos para {nm}")
        return None

    narr = narrator.generate(nm, forecasts) if use_ai else narrator._fallback(nm, forecasts)
    html_gen.generate_state_page(slug, data, narr, forecasts)

    t = list(forecasts.values())[0][0].get("temperatura","")
    return {"nombre": nm, "abreviatura": data["abreviatura"], "temp_summary": f"{t}°F" if t else ""}


def main():
    parser = argparse.ArgumentParser(description="Canal Meteo - Pronóstico por estado")
    parser.add_argument("states", nargs="*", help="Estados específicos (slugs)")
    parser.add_argument("--no-ai", action="store_true", help="Sin narrativa IA")
    parser.add_argument("--index-only", action="store_true", help="Solo índice")
    parser.add_argument("--no-upload", action="store_true", help="No subir al hosting")
    parser.add_argument("--use-rsync", action="store_true", help="Usar rsync")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Canal Meteo TV - Pronóstico por estado")
    logger.info("=" * 60)

    load_env()
    fetcher = NWSFetcher()
    narrator = NarrativeGenerator()
    html_gen = HTMLGenerator()

    targets = {s: STATES[s] for s in args.states if s in STATES} if args.states else STATES
    if args.states and not targets:
        logger.error(f"Estados no encontrados: {args.states}")
        sys.exit(1)

    summary = {}
    if not args.index_only:
        t0 = time.time()
        for slug, data in targets.items():
            try:
                r = process_state(slug, data, fetcher, narrator, html_gen, not args.no_ai)
                if r: summary[slug] = r
            except Exception as e:
                logger.error(f"Error {slug}: {e}")
        logger.info(f"Procesados {len(summary)}/{len(targets)} en {time.time()-t0:.0f}s")

    if not summary:
        for slug, data in STATES.items():
            summary[slug] = {"nombre": data["nombre"], "abreviatura": data["abreviatura"], "temp_summary": ""}

    html_gen.generate_index(summary)

    # ---- SUBIDA AL HOSTING ----
    if not args.no_upload and CONFIG["sftp_enabled"]:
        logger.info("")
        logger.info("Subiendo al hosting de canalmeteo.tv...")
        up = SFTPUploader()
        ok = up.sync_rsync(CONFIG["output_dir"]) if args.use_rsync else up.sync_all(CONFIG["output_dir"])
        if ok:
            logger.info("✓ Archivos publicados en canalmeteo.tv/pronostico/")
        else:
            logger.error("✗ Errores en la subida")
    elif not args.no_upload:
        logger.warning("SFTP no configurado, archivos solo en local")

    logger.info("¡Completado!")


if __name__ == "__main__":
    main()
