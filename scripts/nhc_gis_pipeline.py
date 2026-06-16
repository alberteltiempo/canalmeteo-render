#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nhc_gis_pipeline.py — Pipeline unificado de productos tropicales del NHC para Canal Meteo. v2.

Fuente única: NHC Tropical Weather MapServer (GeoJSON nativo, sin shapefiles/KMZ).
Resuelve capas dinámicamente por el árbol /layers (parentLayerId), así que es robusto
a renumeraciones del servicio.

Productos:
  - Génesis (TWO): puntos de perturbación (prob 2d/7d) + áreas sombreadas  -> SIEMPRE
  - Vientos probabilísticos (grupo 394 -> hijas 34/50/64 kt)
  - Por tormenta (bin EPn/ATn/CPn): cono, trayectoria, puntos, watch/warning,
    radios de viento pronosticados, campo de viento (advisory), trayectoria/puntos pasados,
    swath acumulado, radios pasados, tiempo de llegada (temprano/probable).
  - Inundación/Marea son ráster (Mosaic) -> se omiten (overlay de imagen, aparte).

Metadatos por tormenta desde CurrentStorms.json.
Filtra features sin geometría (radios nulos cuando la tormenta es < umbral).
Publica a DO Spaces bajo data/tropical/ + manifiesto active_storms.json para toggles dinámicos.
Cron cada 15 min; sin tormentas -> manifiesto sólo-génesis y sale limpio.

Uso:
    python3 nhc_gis_pipeline.py --dry-run
    python3 nhc_gis_pipeline.py
    python3 nhc_gis_pipeline.py --no-prob
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# ----------------------------------------------------------------------------
MAPSERVER = ("https://mapservices.weather.noaa.gov/tropical/rest/services/"
             "tropical/NHC_tropical_weather/MapServer")
CURRENT_STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"

GENESIS_ROOT = 0     # grupo "Graphical Tropical Weather Outlook" (puntos + áreas)
PROB_ROOT = 394      # grupo "Probabilistic Winds" (hijas 34/50/64 kt)

UA = "CanalMeteoTropical/2.0 (+https://canalmeteo.tv)"
HTTP_TIMEOUT = 30
PAGE = 2000

S3_BUCKET = "s3://canalmeteo-public"
CDN_PREFIX = "data/tropical"
AWS_PROFILE = "do-tor1"
AWS_ENDPOINT = "https://sfo3.digitaloceanspaces.com"
CACHE_CONTROL = "public, max-age=60"

LOCKFILE = "/tmp/nhc_gis_pipeline.lock"
KT_TO_MPH = 1.150779


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    sys.stderr.write(f"[{now_iso()}] {msg}\n")
    sys.stderr.flush()


def kt_to_mph5(kt):
    try:
        return int(round((float(kt) * KT_TO_MPH) / 5.0) * 5)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
def http_json(url, params=None, timeout=HTTP_TIMEOUT):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def query_layer_geojson(layer_id):
    """Consulta una hoja como GeoJSON WGS84, paginado, descartando geometría nula."""
    features = []
    offset = 0
    while True:
        gj = http_json(f"{MAPSERVER}/{layer_id}/query", {
            "where": "1=1", "outFields": "*", "outSR": "4326",
            "returnGeometry": "true", "resultOffset": str(offset),
            "resultRecordCount": str(PAGE), "f": "geojson",
        })
        batch = gj.get("features", []) or []
        features.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
        if offset > 50000:
            log(f"  AVISO: capa {layer_id} excede 50k features, truncando")
            break
    # filtrar features sin geometría (p.ej. radios nulos en tormentas < umbral)
    features = [f for f in features if f.get("geometry")]
    return {"type": "FeatureCollection", "features": features}


# ----------------------------------------------------------------------------
# Árbol de capas
# ----------------------------------------------------------------------------
def get_layer_tree():
    tree = http_json(MAPSERVER + "/layers", {"f": "pjson"})
    out = {}
    for ly in (tree.get("layers", []) or []):
        out[ly.get("id")] = {
            "name": ly.get("name") or "",
            "type": ly.get("type"),
            "geom": ly.get("geometryType"),
            "parent": ly.get("parentLayerId"),
            "sub": ly.get("subLayerIds") or [],
        }
    return out


def is_queryable_vector(info):
    return (info.get("type") not in ("Group Layer", "Mosaic Layer")
            and bool(info.get("geom")))


def resolve_group_leaves(group_id, tree):
    """Hojas vectoriales bajo un grupo, usando la metadata por-grupo (/MapServer/{id}
    -> campo subLayers), que es la única fuente fiable de jerarquía en este servicio.
    El /layers masivo NO puebla parentLayerId/subLayerIds."""
    out = []
    try:
        meta = http_json(f"{MAPSERVER}/{group_id}", {"f": "pjson"})
    except Exception as e:
        log(f"  AVISO: no se pudo leer subLayers de grupo {group_id}: {e}")
        return out
    for sub in (meta.get("subLayers") or []):
        cid = sub.get("id")
        info = tree.get(cid, {})
        if info.get("type") == "Group Layer":
            out.extend(resolve_group_leaves(cid, tree))
        elif is_queryable_vector(info):
            out.append(cid)
    return out


def classify_role(name_after_bin):
    """Mapea nombre de hoja (sin el prefijo del bin) a rol canónico, o None."""
    n = name_after_bin.lower()
    if "cone" in n:
        return "cone"
    if "watch" in n or "warning" in n:
        return "ww"
    if "earliest" in n:
        return "arrival_earliest"
    if "most likely" in n or "most-likely" in n or "most_likely" in n:
        return "arrival_likely"
    if "arrival" in n:
        return "arrival"
    # productos PASADOS (gate primero para no colisionar con "radii")
    if "past" in n:
        if "swath" in n:
            return "past_swath"
        if "radii" in n:
            return "past_radii"
        if "track" in n:
            return "past_track"
        if "point" in n or "pts" in n:
            return "past_points"
        return None
    # productos actuales / pronóstico
    if "advisory" in n and "wind" in n:
        return "advisory_wind"     # campo de viento actual (initial wind field)
    if "best" in n and "radii" in n:
        return "best_radii"
    if "surface" in n:
        return "surface_wind"
    if "radii" in n:
        return "forecast_radii"
    if "track" in n:
        return "track"
    if "point" in n or "pts" in n:
        return "points"
    return None


def leaves_for_bin(tree, bin_number):
    """[(layer_id, role)] de hojas vectoriales cuyo nombre empieza por el bin."""
    out = []
    prefix = bin_number + " "
    for lid, info in tree.items():
        if not is_queryable_vector(info):
            continue
        name = info["name"]
        if name.startswith(prefix) or name == bin_number:
            role = classify_role(name[len(bin_number):])
            if role:
                out.append((lid, role))
    return out


# ----------------------------------------------------------------------------
# Escritura / subida
# ----------------------------------------------------------------------------
def write_geojson(out_dir, fname, fc):
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    return path


def upload_cdn(local_path, fname, dry_run):
    dest = f"{S3_BUCKET}/{CDN_PREFIX}/{fname}"
    if dry_run:
        return f"(dry-run) {dest}"
    cmd = ["aws", "s3", "cp", local_path, dest,
           "--profile", AWS_PROFILE, "--endpoint", AWS_ENDPOINT,
           "--acl", "public-read", "--cache-control", CACHE_CONTROL,
           "--content-type", "application/geo+json"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"aws s3 cp falló para {fname}: {res.stderr.strip()}")
    return dest


def progress(done, total, label="", width=28):
    if total <= 0:
        return
    frac = done / total
    filled = int(frac * width)
    bar = "█" * filled + "░" * (width - filled)
    sys.stderr.write(f"\r  [{bar}] {int(frac*100):3d}%  {label[:40]:<40}")
    sys.stderr.flush()
    if done >= total:
        sys.stderr.write("\n")
        sys.stderr.flush()


def fetch_merge(layer_ids, tree):
    """Consulta y fusiona varias hojas en una FeatureCollection, etiquetando origen."""
    feats = []
    multi = len(layer_ids) > 1
    for lid in layer_ids:
        fc = query_layer_geojson(lid)
        if multi:
            src = tree.get(lid, {}).get("name", str(lid))
            for f in fc["features"]:
                f.setdefault("properties", {})["_src"] = src
        feats.extend(fc["features"])
    return {"type": "FeatureCollection", "features": feats}


# ----------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------
def run(args):
    t0 = time.time()
    os.makedirs(args.out_dir, exist_ok=True)

    log("Leyendo CurrentStorms.json…")
    try:
        cur = http_json(CURRENT_STORMS)
    except Exception as e:
        log(f"ERROR fatal CurrentStorms.json: {e}")
        return 1
    storms_meta = cur.get("activeStorms", []) or []
    log(f"Tormentas activas: {len(storms_meta)}")

    log("Resolviendo árbol de capas…")
    try:
        tree = get_layer_tree()
    except Exception as e:
        log(f"ERROR fatal árbol de capas: {e}")
        return 1

    manifest = {
        "updated": now_iso(),
        "genesis": {"points": None, "areas": None},
        "probabilistic_winds": None,
        "storms": [],
    }

    # --- Plan de trabajo: cada item = (layer_ids, fname, target) ---
    plan = []

    # Génesis: hojas del grupo 0 (puntos de perturbación + áreas sombreadas)
    gen_leaves = resolve_group_leaves(GENESIS_ROOT, tree)
    gen_points = [l for l in gen_leaves if tree[l]["geom"] == "esriGeometryPoint"]
    gen_areas = [l for l in gen_leaves if tree[l]["geom"] != "esriGeometryPoint"]
    if gen_points:
        plan.append((gen_points, "genesis_points.geojson", ("genesis", "points")))
    if gen_areas:
        plan.append((gen_areas, "genesis_areas.geojson", ("genesis", "areas")))
    log(f"Génesis: {len(gen_points)} capa(s) puntos {gen_points}, "
        f"{len(gen_areas)} capa(s) áreas {gen_areas}")

    # Vientos probabilísticos: descendientes del grupo 394
    if not args.no_prob:
        prob_leaves = resolve_group_leaves(PROB_ROOT, tree)
        log(f"Prob-winds: {len(prob_leaves)} capa(s) {prob_leaves}")
        if prob_leaves:
            plan.append((prob_leaves, "prob_winds.geojson", ("prob",)))

    # Por tormenta
    for s in storms_meta:
        sid = s.get("id")
        bin_n = s.get("binNumber")
        entry = {
            "id": sid,
            "bin": bin_n,
            "basin": (sid[:2].upper() if sid else None),
            "name": s.get("name"),
            "classification": s.get("classification"),
            "intensity_kt": _to_int(s.get("intensity")),
            "intensity_mph": kt_to_mph5(s.get("intensity")),
            "pressure_mb": _to_int(s.get("pressure")),
            "lat": s.get("latitudeNumeric"),
            "lon": s.get("longitudeNumeric"),
            "movement_dir": s.get("movementDir"),
            "movement_kt": s.get("movementSpeed"),
            "movement_mph": kt_to_mph5(s.get("movementSpeed")),
            "last_update": s.get("lastUpdate"),
            "advisory_url": (s.get("publicAdvisory") or {}).get("url"),
            "layers": {},
        }
        manifest["storms"].append(entry)
        if not bin_n:
            log(f"  AVISO: {sid} sin binNumber, se omiten capas")
            continue
        for lid, role in leaves_for_bin(tree, bin_n):
            plan.append(([lid], f"{sid}_{role}.geojson", ("storm", sid, role)))

    # --- Ejecutar ---
    total = len(plan)
    log(f"Trabajos a procesar: {total}")
    done = 0
    written = []
    last_cdn = None
    for layer_ids, fname, target in plan:
        progress(done, total, fname)
        try:
            fc = fetch_merge(layer_ids, tree)
            n = len(fc["features"])
            if n == 0:
                done += 1
                continue
            path = write_geojson(args.out_dir, fname, fc)
            upload_cdn(path, fname, args.dry_run)
            written.append((fname, n))
            rel = f"{CDN_PREFIX}/{fname}"
            if target[0] == "genesis":
                manifest["genesis"][target[1]] = rel
            elif target[0] == "prob":
                manifest["probabilistic_winds"] = rel
            elif target[0] == "storm":
                _, sid, role = target
                for st in manifest["storms"]:
                    if st["id"] == sid:
                        st["layers"][role] = rel
                        break
        except Exception as e:
            log(f"\n  ERROR {fname} (capas {layer_ids}): {e}")
        done += 1
    progress(total, total, "completo")

    # --- Invests (ATCF) ---
    # CurrentStorms.json solo trae sistemas nombrados; los invests (90-99 + letra
    # de cuenca) llegan por ATCF. invest_ingest los emite en el MISMO formato que
    # storms[] (con is_invest=True) para que el vídeo "Vistazo al Trópico" los
    # active automáticamente. Reutilizamos genesis_points ya generado para la
    # probabilidad/riesgo de la zona. Aislado en try/except: si falla, el
    # manifiesto sigue con los sistemas nombrados.
    if not args.no_invest:
        try:
            from invest_ingest import build_invest_entries
            gen_fc = None
            gp_path = os.path.join(args.out_dir, "genesis_points.geojson")
            if os.path.exists(gp_path):
                with open(gp_path, encoding="utf-8") as f:
                    gen_fc = json.load(f)
            invs = build_invest_entries(genesis_fc=gen_fc)
            manifest["storms"].extend(invs)
            log(f"Invests (ATCF): {len(invs)} añadido(s)"
                + (f" — {', '.join(i['name'] for i in invs)}" if invs else ""))
        except Exception as e:
            log(f"AVISO: ingesta de invests falló (se omite): {e}")

    # --- Manifiesto (siempre) ---
    mpath = write_geojson(args.out_dir, "active_storms.json", manifest)
    try:
        last_cdn = upload_cdn(mpath, "active_storms.json", args.dry_run)
    except Exception as e:
        log(f"ERROR subiendo manifiesto: {e}")
        return 1

    dt = time.time() - t0
    log("─" * 60)
    log(f"Manifiesto: {last_cdn}")
    log(f"Capas publicadas: {len(written)} / {total}")
    for fname, n in written:
        log(f"   • {fname:<36} {n:>5} features")
    log(f"Tormentas: {len(manifest['storms'])} | "
        f"génesis pts: {'sí' if manifest['genesis']['points'] else 'no'} | "
        f"áreas: {'sí' if manifest['genesis']['areas'] else 'no'} | "
        f"prob: {'sí' if manifest['probabilistic_winds'] else 'no'}")
    log(f"Tiempo total: {dt:.1f}s {'(DRY-RUN)' if args.dry_run else ''}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Pipeline GIS tropical NHC -> Canal Meteo")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", default="/tmp/nhc_tropical")
    ap.add_argument("--no-prob", action="store_true")
    ap.add_argument("--no-invest", action="store_true",
                    help="No añadir invests (ATCF) al manifiesto")
    args = ap.parse_args()

    lock_fh = None
    if _HAS_FCNTL:
        lock_fh = open(LOCKFILE, "w")
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Otra instancia en ejecución, saliendo.")
            return 0
    try:
        return run(args)
    finally:
        if lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()


if __name__ == "__main__":
    sys.exit(main())
