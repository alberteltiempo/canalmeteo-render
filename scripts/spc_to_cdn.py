#!/usr/bin/env python3
"""
spc_to_cdn.py — Puente entre spc_outlook.py y el CDN público
=============================================================
Convierte el CSV generado por spc_outlook.py (en lynx) a un JSON estructurado
y lo sube a Spaces CDN público para que radar-tornado.html lo pueda consumir.

Ubicación:  /opt/canalmeteo/scripts/spc_to_cdn.py
Entrada:    spc_outlook_latest.csv (auto-detecta ubicación)
Salida:     canalmeteo-public.sfo3.digitaloceanspaces.com/data/spc/spc_outlook.json
Cron:       */15 * * * * /opt/canalmeteo/venv/bin/python /opt/canalmeteo/scripts/spc_to_cdn.py

Uso AWS CLI igual que alertas_nws.py: profile do-tor1, endpoint sfo3.
"""

import csv
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ──────────────────────────────────────────────────

# Auto-detecta el CSV en ubicaciones típicas de lynx
CSV_CANDIDATES = [
    Path("/home/canalmeteo/lynx/data/csv/spc_outlook_latest.csv"),
    Path("/home/canalmeteo/lynx/csv/spc_outlook_latest.csv"),
    Path("/home/canalmeteo/lynx/web/csv/spc_outlook_latest.csv"),
    Path("/home/canalmeteo/lynx/output/spc_outlook_latest.csv"),
    Path("/home/canalmeteo/lynx/data/spc/spc_outlook_latest.csv"),
    Path("/home/canalmeteo/lynx/spc_outlook_latest.csv"),
    Path("/var/www/html/lynx/csv/spc_outlook_latest.csv"),
]

LOCAL_TMP = Path("/tmp/spc_outlook.json")

# AWS / Spaces (mismo patrón que alertas_nws.py)
AWS_PROFILE  = "do-tor1"
AWS_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
S3_BUCKET    = "canalmeteo-public"
S3_KEY       = "data/spc/spc_outlook.json"
S3_URL       = f"https://{S3_BUCKET}.sfo3.digitaloceanspaces.com/{S3_KEY}"

# ─── Logging ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("spc_to_cdn")


def find_csv():
    """Busca el CSV en rutas típicas + fallback con find."""
    for p in CSV_CANDIDATES:
        if p.exists():
            log.info(f"CSV encontrado en: {p}")
            return p

    # Fallback: buscar con find en /home/canalmeteo
    log.info("CSV no encontrado en rutas predefinidas, buscando con find...")
    try:
        result = subprocess.run(
            ["find", "/home/canalmeteo", "-name", "spc_outlook_latest.csv",
             "-type", "f", "-not", "-path", "*/\\.*"],
            capture_output=True, text=True, timeout=30
        )
        paths = [p for p in result.stdout.strip().split("\n") if p]
        if paths:
            log.info(f"find encontró: {paths[0]}")
            return Path(paths[0])
    except Exception as e:
        log.error(f"find falló: {e}")

    return None


def load_csv(csv_path):
    """Lee el CSV. Estructura: Timestamp,Tipo,Tipo_ES,Nivel,Poblacion,Area_sq_mi,Ciudades,Fuente"""
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    log.info(f"Leídas {len(rows)} filas del CSV")
    return rows


def build_json(rows):
    """Transforma las filas del CSV a la estructura final del JSON."""
    out = {
        "categorical": {},
        "tornado": {},
        "hail": {},
        "wind": {},
    }

    csv_timestamp = ""
    fuente = ""

    for row in rows:
        tipo = (row.get("Tipo") or "").strip().lower()
        nivel = (row.get("Nivel") or "").strip()
        if tipo not in out or not nivel:
            continue

        try:
            poblacion = int(row.get("Poblacion") or 0)
        except ValueError:
            poblacion = 0
        try:
            area = int(row.get("Area_sq_mi") or 0)
        except ValueError:
            area = 0

        # Ciudades: viene separado por "..." en el CSV actual
        ciudades_raw = (row.get("Ciudades") or "").strip()
        if "..." in ciudades_raw:
            ciudades = [c.strip() for c in ciudades_raw.split("...") if c.strip()]
        elif ";" in ciudades_raw:
            ciudades = [c.strip() for c in ciudades_raw.split(";") if c.strip()]
        else:
            ciudades = [c.strip() for c in ciudades_raw.split(",") if c.strip()]

        out[tipo][nivel] = {
            "poblacion": poblacion,
            "area_sq_mi": area,
            "ciudades": ciudades[:5],
        }

        if not csv_timestamp:
            csv_timestamp = row.get("Timestamp", "")
        if not fuente:
            fuente = row.get("Fuente", "")

    # Totales por tipo
    totales = {}
    for tipo in ("categorical", "tornado", "hail", "wind"):
        totales[tipo] = sum(v.get("poblacion", 0) for v in out[tipo].values())

    # Nivel máximo en categorical
    nivel_order = {"HIGH": 5, "MDT": 4, "ENH": 3, "SLGT": 2, "MRGL": 1, "TSTM": 0}
    nivel_max = "NONE"
    for nivel in out["categorical"].keys():
        if nivel_order.get(nivel, -1) > nivel_order.get(nivel_max, -1):
            nivel_max = nivel

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "csv_timestamp": csv_timestamp,
        "fuente": fuente,
        "nivel_max": nivel_max,
        "totales": totales,
        "categorical": out["categorical"],
        "tornado": out["tornado"],
        "hail": out["hail"],
        "wind": out["wind"],
    }


def upload_to_cdn(local_path):
    """Sube a Spaces via AWS CLI (mismo patrón que alertas_nws.py)."""
    cmd = [
        "aws", "--profile", AWS_PROFILE,
        "s3", "cp", str(local_path), f"s3://{S3_BUCKET}/{S3_KEY}",
        "--endpoint-url", AWS_ENDPOINT,
        "--acl", "public-read",
        "--content-type", "application/json",
        "--cache-control", "max-age=300",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            log.info(f"✅ Subido a {S3_URL}")
            return True
        log.error(f"AWS CLI error: {result.stderr}")
        return False
    except subprocess.TimeoutExpired:
        log.error("Timeout subiendo a S3")
        return False
    except Exception as e:
        log.error(f"Error en AWS CLI: {e}")
        return False


def main():
    csv_path = find_csv()
    if not csv_path:
        log.error("No se encontró spc_outlook_latest.csv en ninguna ubicación conocida")
        log.error("Ejecuta: find /home/canalmeteo -name 'spc_outlook_latest.csv'")
        sys.exit(1)

    rows = load_csv(csv_path)
    if not rows:
        log.warning("CSV vacío, abortando")
        sys.exit(1)

    data = build_json(rows)

    totales = data["totales"]
    log.info(
        f"Categorical: {totales['categorical']:,} · Tornado: {totales['tornado']:,} "
        f"· Hail: {totales['hail']:,} · Wind: {totales['wind']:,}"
    )
    log.info(f"Nivel máx categórico: {data['nivel_max']}")

    with open(LOCAL_TMP, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    upload_to_cdn(LOCAL_TMP)


if __name__ == "__main__":
    main()
