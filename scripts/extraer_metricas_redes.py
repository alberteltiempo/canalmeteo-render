#!/usr/bin/env python3
"""
Canal Meteo TV - Extractor de metricas de redes (Instagram Graph API v22.0)
===========================================================================
Saca reach, views, likes, comments, saved y shares de los reels y posts
publicados en un rango de fechas, en una o varias cuentas de Instagram
Professional. Opcionalmente filtra solo las piezas que mencionan a un
patrocinador (por palabra clave en el caption), util para aislar el alcance
de Naimeh & Salem sin contar todo el contenido.

Pensado para correr en el droplet: /opt/canalmeteo/scripts/social_analytics/

Notas de la API (junio 2026):
- impressions y video_views fueron deprecados en v22.0; se usa 'views'.
- Metricas validas a nivel de pieza: views, reach, saved, shares, likes, comments.
- Las STORIES solo devuelven insights mientras estan activas (24h). Las stories
  historicas NO se pueden recuperar; este script no las intenta sacar.
- Facebook paginas: desde nov-2025 solo queda reach a nivel de pagina. La parte
  de FB de abajo esta marcada como opcional y conviene verificar el nombre exacto
  de la metrica en tu version antes de usarla en produccion.

Uso:
  export META_TOKEN="EAAG..."          # token de larga duracion
  python3 extraer_metricas_redes.py --descubrir            # lista las IG user IDs del token
  python3 extraer_metricas_redes.py --desde 2026-01-01 --hasta 2026-05-31
  python3 extraer_metricas_redes.py --desde 2026-01-01 --hasta 2026-05-31 --filtro "naimeh,salem"
"""

import os
import sys
import csv
import time
import argparse
import datetime as dt
from urllib.parse import urlencode
import urllib.request
import urllib.error
import json

API_VERSION = "v22.0"
BASE = f"https://graph.facebook.com/{API_VERSION}"

# IG user IDs de las dos cuentas. Rellena tras correr --descubrir.
CUENTAS = {
    "alberteltiempo": "17841400161010201",
    "canalmeteotv":   "17841473920180613",
}

# Metricas a pedir por pieza. Si alguna no aplica al tipo, la API la ignora
# o devuelve error; el codigo reintenta con un set reducido.
METRICAS_BASE = ["reach", "views", "likes", "comments", "saved", "shares"]
METRICAS_MINIMAS = ["reach", "views"]

TOKEN = os.environ.get("META_TOKEN", "")


def _get(path, params):
    params = dict(params or {})
    params["access_token"] = TOKEN
    url = f"{BASE}/{path}?{urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} en {path}: {body}") from None


def descubrir_cuentas():
    """Lista las paginas de FB del token y su cuenta de IG vinculada."""
    print("Paginas y cuentas de Instagram vinculadas a este token:\n")
    data = _get("me/accounts", {"fields": "name,instagram_business_account{id,username}"})
    for pag in data.get("data", []):
        ig = pag.get("instagram_business_account")
        if ig:
            print(f"  Pagina: {pag['name']}")
            print(f"    IG user id: {ig['id']}   (@{ig.get('username','?')})\n")
        else:
            print(f"  Pagina: {pag['name']}  (sin IG vinculado)\n")
    print("Copia las IG user id en el diccionario CUENTAS de este script.")


def listar_media(ig_user_id, desde, hasta):
    """Devuelve la lista de media (reels + posts) en el rango de fechas."""
    medios = []
    campos = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
    params = {"fields": campos, "limit": 50}
    path = f"{ig_user_id}/media"
    while True:
        data = _get(path, params)
        for m in data.get("data", []):
            ts = dt.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")).date()
            if ts < desde:
                return medios          # vienen ordenados desc; ya pasamos el rango
            if ts <= hasta:
                medios.append(m)
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            break
        # extraer cursor 'after' del next
        after = nxt.split("after=")[-1].split("&")[0]
        params["after"] = after
        time.sleep(0.3)
    return medios


def insights_pieza(media_id):
    """Pide insights de una pieza; reintenta con set reducido si falla."""
    for metricas in (METRICAS_BASE, METRICAS_MINIMAS):
        try:
            data = _get(f"{media_id}/insights", {"metric": ",".join(metricas)})
            out = {}
            for item in data.get("data", []):
                vals = item.get("values", [{}])
                out[item["name"]] = vals[0].get("value", 0) if vals else 0
            return out
        except RuntimeError:
            continue
    return {}


def coincide_filtro(caption, palabras):
    if not palabras:
        return True
    cap = (caption or "").lower()
    return any(p.strip().lower() in cap for p in palabras)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--descubrir", action="store_true", help="lista IG user IDs del token")
    ap.add_argument("--desde", help="YYYY-MM-DD")
    ap.add_argument("--hasta", help="YYYY-MM-DD")
    ap.add_argument("--filtro", default="", help="palabras clave en caption, separadas por coma")
    ap.add_argument("--salida", default="metricas_redes.csv")
    args = ap.parse_args()

    if not TOKEN:
        sys.exit("Falta el token. Exporta META_TOKEN antes de correr.")

    if args.descubrir:
        descubrir_cuentas()
        return

    if not args.desde or not args.hasta:
        sys.exit("Indica --desde y --hasta (YYYY-MM-DD).")

    desde = dt.date.fromisoformat(args.desde)
    hasta = dt.date.fromisoformat(args.hasta)
    palabras = [p for p in args.filtro.split(",") if p.strip()] if args.filtro else []

    filas = []
    tot = {"reach": 0, "views": 0, "likes": 0, "comments": 0, "saved": 0, "shares": 0}

    for nombre, ig_id in CUENTAS.items():
        if "PEGAR" in ig_id:
            print(f"  ! Salto {nombre}: falta IG user id (corre --descubrir).")
            continue
        print(f"\nCuenta: {nombre}  ({ig_id})")
        medios = listar_media(ig_id, desde, hasta)
        print(f"  {len(medios)} piezas en el rango.")
        for m in medios:
            if not coincide_filtro(m.get("caption"), palabras):
                continue
            ins = insights_pieza(m["id"])
            fila = {
                "cuenta": nombre,
                "fecha": m["timestamp"][:10],
                "tipo": m.get("media_product_type") or m.get("media_type"),
                "permalink": m.get("permalink", ""),
                "reach": ins.get("reach", 0),
                "views": ins.get("views", 0),
                "likes": ins.get("likes", m.get("like_count", 0)),
                "comments": ins.get("comments", m.get("comments_count", 0)),
                "saved": ins.get("saved", 0),
                "shares": ins.get("shares", 0),
                "caption": (m.get("caption") or "").replace("\n", " ")[:120],
            }
            filas.append(fila)
            for k in tot:
                tot[k] += fila.get(k, 0) or 0
            time.sleep(0.4)   # cortesia con el rate limit

    # CSV
    if filas:
        with open(args.salida, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)

    # Resumen
    print("\n" + "=" * 52)
    etiqueta = f"filtradas por {palabras}" if palabras else "todas las piezas"
    print(f"RESUMEN ({etiqueta}) {args.desde} a {args.hasta}")
    print("=" * 52)
    print(f"  Piezas:        {len(filas)}")
    print(f"  Reach total:   {tot['reach']:,}")
    print(f"  Views total:   {tot['views']:,}")
    print(f"  Likes:         {tot['likes']:,}")
    print(f"  Comentarios:   {tot['comments']:,}")
    print(f"  Guardados:     {tot['saved']:,}")
    print(f"  Compartidos:   {tot['shares']:,}")
    print(f"\n  CSV: {args.salida}")
    print("\n  OJO: si una misma pieza colaborativa aparece en las dos cuentas,")
    print("  su reach se cuenta dos veces. Revisa duplicados antes de reportar")
    print("  un total combinado. El reach por cuenta es lo limpio.")


if __name__ == "__main__":
    main()
