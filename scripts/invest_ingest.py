#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canal Meteo · Ingesta de INVESTS (áreas de investigación del NHC)
=================================================================

El feed de génesis (GTWO) solo trae probabilidad/riesgo de las zonas en
vigilancia. Cuando el NHC "nombra" un invest (90-99 + letra de cuenca, p.ej.
90L frente a Texas) empieza a publicar datos ATCF: posición, viento máximo
sostenido y presión. Este módulo los recoge y los emite en el MISMO formato que
una tormenta de active_storms.json, marcados con "is_invest": true, para que el
vídeo "Vistazo al Trópico" los active automáticamente igual que una depresión:
tarjeta de datos (viento/ráfaga/presión) + caja de situación (probabilidad de
formación) + precipitación a 5 días (NBM si está sobre EEUU).

Fuentes (NHC ATCF):
  - tcvitals   https://ftp.nhc.noaa.gov/atcf/com/tcvitals   → lista de sistemas
               activos (incl. invests) con posición y movimiento.
  - b-deck     https://ftp.nhc.noaa.gov/atcf/btk/b{aa}{nn}{yyyy}.dat
               → análisis actual: viento máx (kt), presión (mb), tipo.
  - génesis    {CDN}/data/tropical/genesis_points.geojson
               → probabilidad/riesgo de formación de la zona asociada.

Integración (nimbus-01): la pipeline tropical escribe active_storms.json; este
módulo añade los invests a storms[]. Dos formas:
  a) Importarlo:   from invest_ingest import build_invest_entries
                   index["storms"].extend(build_invest_entries())
  b) Por separado: tropical_pipeline.py --once --upload-cdn && \
                   invest_ingest.py --merge <out>/active_storms.json --upload-cdn

Uso CLI:
  python3 invest_ingest.py --print                 # previsualiza los invests
  python3 invest_ingest.py --merge active_storms.json [--upload-cdn]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CDN = "https://canalmeteo-public.sfo3.digitaloceanspaces.com"
TCVITALS_URL = "https://ftp.nhc.noaa.gov/atcf/com/tcvitals"
BDECK_URL = "https://ftp.nhc.noaa.gov/atcf/btk/b{basin}{cy}{year}.dat"
GENESIS_POINTS_URL = f"{CDN}/data/tropical/genesis_points.geojson"

USER_AGENT = "CanalMeteoTV/1.0 (https://canalmeteo.tv; contacto@canalmeteo.tv)"

# Subida a DO Spaces (mismo mecanismo que tropical_pipeline.py)
CDN_PREFIX = "s3://canalmeteo-public/data/tropical/"
CDN_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CDN_PROFILE = "do-tor1"

# Letra de cuenca del invest (tcvitals/ATCF) → prefijo ATCF de cuenca
BASIN_LETTER_TO_ATCF = {"L": "AL", "E": "EP", "C": "CP"}

MS_TO_KT = 1.943844
MS_TO_MPH = 2.236936


def _get(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_text(url: str, timeout: int = 30) -> str:
    try:
        return _get(url, timeout).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[invest] aviso: no se pudo leer {url}: {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# Parsing ATCF
# ---------------------------------------------------------------------------

def _coord(token: str) -> float | None:
    """'264N' -> 26.4 ; '1000W' -> -100.0 (décimas de grado + hemisferio)."""
    m = re.fullmatch(r"(\d+)([NSEW])", token.strip())
    if not m:
        return None
    val = int(m.group(1)) / 10.0
    if m.group(2) in ("S", "W"):
        val = -val
    return val


def parse_tcvitals(text: str) -> list[dict]:
    """Sistemas activos de tcvitals que son invests (id NN + L/E/C)."""
    out: list[dict] = []
    for line in text.splitlines():
        toks = line.split()
        if len(toks) < 9:
            continue
        sid = toks[1]
        if not re.fullmatch(r"\d{2}[LEC]", sid):
            continue  # solo invests (90-99 con letra de cuenca)
        # Localiza el token de latitud ('264N'); lon/dir/vel van a continuación.
        lat_i = next(
            (i for i, t in enumerate(toks) if re.fullmatch(r"\d{2,4}[NS]", t)), None
        )
        if lat_i is None or lat_i + 3 >= len(toks):
            continue
        lat = _coord(toks[lat_i])
        lon = _coord(toks[lat_i + 1])
        try:
            mov_dir = int(toks[lat_i + 2])
        except ValueError:
            mov_dir = None
        try:
            spd_ms = int(toks[lat_i + 3]) / 10.0  # décimas de m/s
        except ValueError:
            spd_ms = None
        date = toks[lat_i - 2] if lat_i >= 2 else None
        time_ = toks[lat_i - 1] if lat_i >= 1 else None
        out.append({
            "id": sid,
            "lat": lat,
            "lon": lon,
            "mov_dir": mov_dir,
            "mov_mph": round(spd_ms * MS_TO_MPH) if spd_ms is not None else None,
            "date": date,
            "time": time_,
        })
    return out


def parse_bdeck_latest(text: str) -> dict | None:
    """Última línea BEST del b-deck → viento (kt), presión (mb), posición, tipo."""
    best = None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 11 or parts[4] != "BEST":
            continue
        best = parts  # el fichero es cronológico → nos quedamos con la última
    if not best:
        return None

    def _num(s: str) -> int | None:
        try:
            v = int(s)
            return v if v not in (0, -999) or s == "0" else v
        except ValueError:
            return None

    vmax = _num(best[8])
    mslp = _num(best[9])
    dt = best[2]  # YYYYMMDDHH
    last_update = None
    if re.fullmatch(r"\d{10}", dt):
        last_update = datetime.strptime(dt, "%Y%m%d%H").replace(
            tzinfo=timezone.utc
        ).isoformat().replace("+00:00", "Z")
    return {
        "vmax_kt": vmax if (vmax and vmax > 0) else None,
        "mslp_mb": mslp if (mslp and 800 < mslp < 1100) else None,
        "lat": _coord(best[6]),
        "lon": _coord(best[7]),
        "type": best[10] or None,
        "last_update": last_update,
    }


# ---------------------------------------------------------------------------
# Génesis (probabilidad/riesgo) → emparejar con el invest por cercanía
# ---------------------------------------------------------------------------

def _prob_num(v) -> int | None:
    m = re.search(r"-?\d+", str(v or ""))
    return int(m.group(0)) if m else None


def parse_genesis_points(gj: dict) -> list[dict]:
    pts = []
    for f in (gj or {}).get("features", []):
        coords = (f.get("geometry") or {}).get("coordinates")
        if not (isinstance(coords, list) and len(coords) >= 2):
            continue
        p = f.get("properties") or {}
        pts.append({
            "lon": coords[0],
            "lat": coords[1],
            "prob": _prob_num(p.get("prob7day")) or _prob_num(p.get("prob2day")),
            "risk": p.get("risk7day") or p.get("risk2day"),
        })
    return pts


def load_genesis_points(fc: dict | None = None) -> list[dict]:
    """Puntos de génesis (prob/riesgo). Si se pasa `fc` (FeatureCollection ya
    cargada, p.ej. la que acaba de generar la pipeline), se usa esa; si no, se
    descarga del CDN."""
    if fc is None:
        raw = _get_text(GENESIS_POINTS_URL)
        if not raw:
            return []
        try:
            fc = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return parse_genesis_points(fc)


def nearest_genesis(lon, lat, pts: list[dict], max_deg: float = 5.0) -> dict | None:
    if lon is None or lat is None:
        return None
    best, best_d = None, max_deg
    for p in pts:
        d = math.hypot(p["lon"] - lon, p["lat"] - lat)
        if d < best_d:
            best, best_d = p, d
    return best


# ---------------------------------------------------------------------------
# Construcción de entradas de invest (formato active_storms.json → storms[])
# ---------------------------------------------------------------------------

def build_invest_entries(year: int | None = None, genesis_fc: dict | None = None) -> list[dict]:
    """Entradas de invest en formato storms[]. `genesis_fc` opcional: la
    FeatureCollection de genesis_points ya cargada (evita ir al CDN)."""
    year = year or datetime.now(timezone.utc).year
    vitals = parse_tcvitals(_get_text(TCVITALS_URL))
    if not vitals:
        return []
    genesis = load_genesis_points(genesis_fc)
    entries: list[dict] = []
    for v in vitals:
        sid = v["id"]                      # p.ej. "90L"
        letter = sid[-1]
        cy = sid[:2]
        atcf_basin = BASIN_LETTER_TO_ATCF.get(letter)
        if not atcf_basin:
            continue
        bdeck = parse_bdeck_latest(
            _get_text(BDECK_URL.format(basin=atcf_basin.lower(), cy=cy, year=year))
        ) or {}

        lon = bdeck.get("lon") if bdeck.get("lon") is not None else v["lon"]
        lat = bdeck.get("lat") if bdeck.get("lat") is not None else v["lat"]
        g = nearest_genesis(lon, lat, genesis)

        entries.append({
            "id": f"{atcf_basin}{cy}",      # "AL90" → stormBasin() lo resuelve
            "name": f"Invest {sid}",        # "Invest 90L"
            "is_invest": True,
            "intensity_kt": bdeck.get("vmax_kt"),
            "gust_kt": None,                # el ATCF no publica ráfaga de un invest
            "mslp_mb": bdeck.get("mslp_mb"),
            "lon": lon,
            "lat": lat,
            "last_update": bdeck.get("last_update"),
            "movement_dir": v.get("mov_dir"),
            "movement_mph": v.get("mov_mph"),
            "genesis_prob": (g or {}).get("prob"),
            "genesis_risk": (g or {}).get("risk"),
            "layers": {},                   # un invest no tiene cono/trayectoria
        })
    return entries


# ---------------------------------------------------------------------------
# Merge / CLI
# ---------------------------------------------------------------------------

def merge_into(path: Path, entries: list[dict]) -> None:
    """Añade/refresca los invests en storms[] de un active_storms.json local."""
    data = json.loads(path.read_text(encoding="utf-8"))
    storms = [s for s in (data.get("storms") or []) if not s.get("is_invest")]
    storms.extend(entries)
    data["storms"] = storms
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    tmp.replace(path)


def upload_active_storms(path: Path) -> bool:
    cmd = [
        "aws", "s3", "cp", str(path), f"{CDN_PREFIX}active_storms.json",
        "--profile", CDN_PROFILE, "--acl", "public-read",
        "--content-type", "application/json", "--endpoint-url", CDN_ENDPOINT,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return True
    except Exception as e:
        print(f"[invest] subida CDN falló: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingesta de invests del NHC")
    ap.add_argument("--print", action="store_true", dest="do_print",
                    help="Previsualiza las entradas de invest (JSON)")
    ap.add_argument("--merge", type=Path, metavar="ACTIVE_STORMS_JSON",
                    help="Añade los invests a storms[] de este active_storms.json")
    ap.add_argument("--upload-cdn", action="store_true",
                    help="Sube el active_storms.json fusionado al CDN")
    args = ap.parse_args()

    entries = build_invest_entries()
    print(f"[invest] {len(entries)} invest(s) detectado(s): "
          + ", ".join(e["name"] for e in entries), file=sys.stderr)

    if args.do_print or not args.merge:
        print(json.dumps(entries, ensure_ascii=False, indent=2))

    if args.merge:
        if not args.merge.exists():
            print(f"[invest] no existe {args.merge}", file=sys.stderr)
            return 1
        merge_into(args.merge, entries)
        print(f"[invest] fusionados en {args.merge}", file=sys.stderr)
        if args.upload_cdn and not upload_active_storms(args.merge):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
