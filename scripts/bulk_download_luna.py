#!/usr/bin/env python3
"""
bulk_download_luna.py
=====================
Descarga TODOS los frames de la luna desde NASA SVS (730x730 + 216x216)
y los sube al CDN de DigitalOcean Spaces (canalmeteo-public).

Frames: 1 a 8760 (uno por hora del año)
Tamaños: grande (730x730) + pequena (216x216) = 17.520 archivos totales
Tamaño estimado: ~780 MB
Tiempo estimado: 30-60 min con 10 workers (depende de red NASA)

Estructura final en CDN:
  data/astro/luna/{YEAR}/grande/moon.NNNN.jpg
  data/astro/luna/{YEAR}/pequena/moon.NNNN.jpg

Uso:
  python3 bulk_download_luna.py              # Año actual (2026)
  python3 bulk_download_luna.py --year 2026
  python3 bulk_download_luna.py --workers 5  # menos workers si red lenta
  python3 bulk_download_luna.py --dry-run    # solo mostrar plan
  python3 bulk_download_luna.py --check      # ver cuantos ya estan en CDN

Resume:
  El script verifica si cada archivo ya existe en CDN antes de descargar.
  Puedes interrumpir con Ctrl+C y volver a correr - sigue donde lo dejaste.
"""

import os
import sys
import argparse
import time
import io
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    import boto3
    from botocore.exceptions import ClientError
    from dotenv import load_dotenv
except ImportError as e:
    print(f"ERROR: falta dependencia: {e}")
    print("Instala con: pip install requests boto3 python-dotenv")
    sys.exit(1)

# ============================================================
# Config
# ============================================================
NASA_SVS_BASE = "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/frames"
NASA_SIZE_LARGE = "730x730_1x1_30p"
NASA_SIZE_SMALL = "216x216_1x1_30p"

CDN_BUCKET = "canalmeteo-public"
CDN_REGION = "sfo3"
CDN_ENDPOINT = f"https://{CDN_REGION}.digitaloceanspaces.com"
CDN_BASE_PATH = "data/astro/luna"
CACHE_CONTROL = "public, max-age=31536000"  # 1 año (los frames no cambian)

FRAMES_TOTAL = 8760  # Frames por año (24 * 365)
MAX_RETRIES = 3
RETRY_DELAY = 2  # segundos
REQUEST_TIMEOUT = 30  # segundos

# Colores ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"


# ============================================================
# S3 / CDN setup
# ============================================================
def setup_s3_client():
    """Crear cliente S3 desde .env o variables de entorno."""
    env_paths = [
        "/opt/canalmeteo/.env",
        os.path.expanduser("~/.env"),
        ".env",
    ]
    for p in env_paths:
        if os.path.exists(p):
            load_dotenv(p)
            break

    key_id = os.getenv("DO_SPACES_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("DO_SPACES_SECRET") or os.getenv("AWS_SECRET_ACCESS_KEY")

    if not key_id or not secret:
        # Intentar leer de ~/.aws/credentials profile do-tor1
        try:
            session = boto3.Session(profile_name="do-tor1")
            return session.client(
                "s3",
                endpoint_url=CDN_ENDPOINT,
                region_name=CDN_REGION,
            )
        except Exception as e:
            print(f"{RED}ERROR: no se encontraron credenciales{RESET}")
            print("Pon en /opt/canalmeteo/.env:")
            print("  DO_SPACES_KEY=...")
            print("  DO_SPACES_SECRET=...")
            print(f"O configura profile do-tor1 en ~/.aws/credentials")
            print(f"Detalle: {e}")
            sys.exit(1)

    return boto3.client(
        "s3",
        endpoint_url=CDN_ENDPOINT,
        region_name=CDN_REGION,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )


# ============================================================
# Helpers
# ============================================================
def cdn_key(year: int, size: str, frame: int) -> str:
    """Devuelve el key S3 para un frame."""
    size_folder = "grande" if size == "large" else "pequena"
    return f"{CDN_BASE_PATH}/{year}/{size_folder}/moon.{frame:04d}.jpg"


def nasa_url(size: str, frame: int) -> str:
    """Devuelve la URL de NASA SVS para un frame."""
    size_path = NASA_SIZE_LARGE if size == "large" else NASA_SIZE_SMALL
    return f"{NASA_SVS_BASE}/{size_path}/moon.{frame:04d}.jpg"


def exists_in_cdn(s3, key: str) -> bool:
    """Verifica si un objeto existe en el CDN."""
    try:
        s3.head_object(Bucket=CDN_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        # otro error - asumir que NO existe
        return False


def list_existing_keys(s3, year: int) -> set:
    """Lista todos los keys ya en CDN (para skip en bulk)."""
    existing = set()
    prefix = f"{CDN_BASE_PATH}/{year}/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=CDN_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            existing.add(obj["Key"])
    return existing


def download_and_upload(s3, year: int, size: str, frame: int, skip_check: bool = False):
    """Descarga un frame de NASA y lo sube al CDN. Retorna (frame, size, bytes, status)."""
    key = cdn_key(year, size, frame)
    url = nasa_url(size, frame)

    if not skip_check and exists_in_cdn(s3, key):
        return (frame, size, 0, "skip")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.content
                s3.put_object(
                    Bucket=CDN_BUCKET,
                    Key=key,
                    Body=data,
                    ACL="public-read",
                    ContentType="image/jpeg",
                    CacheControl=CACHE_CONTROL,
                )
                return (frame, size, len(data), "ok")
            elif r.status_code == 404:
                return (frame, size, 0, "404")
            else:
                if attempt == MAX_RETRIES:
                    return (frame, size, 0, f"http_{r.status_code}")
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES:
                return (frame, size, 0, f"err_{type(e).__name__}")
        except Exception as e:
            if attempt == MAX_RETRIES:
                return (frame, size, 0, f"err_{type(e).__name__}")
        time.sleep(RETRY_DELAY * attempt)

    return (frame, size, 0, "fail")


def fmt_bytes(n: int) -> str:
    """Format bytes -> human readable."""
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds > 86400 * 7:
        return "--:--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def render_progress(done: int, total: int, bytes_done: int, bytes_estimated: int,
                    workers: int, elapsed: float, last_status: str, errors: int):
    """Pinta una barra de progreso."""
    pct = (done / total * 100) if total > 0 else 0
    bar_width = 30
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    speed = done / elapsed if elapsed > 0 else 0
    eta_sec = (total - done) / speed if speed > 0 else -1

    color = GREEN if errors == 0 else YELLOW
    err_str = f" · {RED}{errors} err{RESET}" if errors > 0 else ""

    line1 = (
        f"\r{color}[{bar}]{RESET} {BOLD}{pct:5.1f}%{RESET} "
        f"({done:,}/{total:,}) · {fmt_bytes(bytes_done)}/{fmt_bytes(bytes_estimated)}"
        f"{err_str}"
    )
    line2 = (
        f"\n{DIM}Workers: {workers} · Speed: {speed:.1f} imgs/s · "
        f"Elapsed: {fmt_eta(elapsed)} · ETA: {fmt_eta(eta_sec)}{RESET}"
    )
    line3 = f"\n{DIM}Last: {last_status}{RESET}"

    # Limpiar 3 líneas y volver al principio
    sys.stdout.write("\033[2K" + line1)
    sys.stdout.write("\033[2K" + line2)
    sys.stdout.write("\033[2K" + line3)
    sys.stdout.write("\033[2A")  # subir 2 líneas para próximo update
    sys.stdout.flush()


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Bulk download luna NASA -> CDN")
    parser.add_argument("--year", type=int, default=datetime.now().year,
                        help="Año a procesar (default: año actual)")
    parser.add_argument("--workers", type=int, default=10,
                        help="Workers concurrentes (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo mostrar plan, no descargar")
    parser.add_argument("--check", action="store_true",
                        help="Solo verificar qué hay en CDN")
    parser.add_argument("--size", choices=["large", "small", "both"], default="both",
                        help="Qué tamaño descargar (default: both)")
    parser.add_argument("--start", type=int, default=1, help="Frame inicial (default: 1)")
    parser.add_argument("--end", type=int, default=FRAMES_TOTAL, help=f"Frame final (default: {FRAMES_TOTAL})")
    args = parser.parse_args()

    year = args.year
    workers = args.workers
    start_frame = max(1, args.start)
    end_frame = min(FRAMES_TOTAL, args.end)

    sizes = []
    if args.size in ("large", "both"):
        sizes.append("large")
    if args.size in ("small", "both"):
        sizes.append("small")

    total_tasks = (end_frame - start_frame + 1) * len(sizes)

    print(f"{BOLD}{MAGENTA}╔══════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{MAGENTA}║  BULK DOWNLOAD LUNA - NASA SVS -> CDN           ║{RESET}")
    print(f"{BOLD}{MAGENTA}╚══════════════════════════════════════════════════╝{RESET}")
    print(f"Año:        {CYAN}{year}{RESET}")
    print(f"Frames:     {CYAN}{start_frame:04d} → {end_frame:04d}{RESET} ({end_frame - start_frame + 1:,} por tamaño)")
    print(f"Tamaños:    {CYAN}{', '.join(sizes)}{RESET}")
    print(f"Workers:    {CYAN}{workers}{RESET}")
    print(f"Total:      {CYAN}{total_tasks:,} archivos{RESET}")
    print(f"NASA URL:   {DIM}{NASA_SVS_BASE}{RESET}")
    print(f"CDN base:   {DIM}{CDN_ENDPOINT}/{CDN_BUCKET}/{CDN_BASE_PATH}/{year}/{RESET}")
    print()

    # Setup S3
    s3 = setup_s3_client()

    # Modo check: solo listar lo que hay
    if args.check:
        print(f"{YELLOW}Modo --check: listando objetos existentes en CDN...{RESET}")
        existing = list_existing_keys(s3, year)
        large_count = sum(1 for k in existing if "/grande/" in k)
        small_count = sum(1 for k in existing if "/pequena/" in k)
        print(f"  Grande (730x730):  {GREEN}{large_count:,}{RESET} / {FRAMES_TOTAL:,}")
        print(f"  Pequeña (216x216): {GREEN}{small_count:,}{RESET} / {FRAMES_TOTAL:,}")
        print(f"  Total en CDN:      {GREEN}{len(existing):,}{RESET}")
        return

    # Modo dry-run
    if args.dry_run:
        print(f"{YELLOW}Modo --dry-run: no se descargará nada{RESET}")
        sample_url_large = nasa_url("large", start_frame)
        sample_key_large = cdn_key(year, "large", start_frame)
        print(f"  Ejemplo URL NASA:  {DIM}{sample_url_large}{RESET}")
        print(f"  Ejemplo key CDN:   {DIM}{sample_key_large}{RESET}")
        return

    # Pre-listar lo que ya está en CDN para skip rápido
    print(f"{DIM}Listando objetos existentes en CDN (para resume)...{RESET}")
    existing = list_existing_keys(s3, year)
    print(f"{DIM}  → {len(existing):,} objetos ya en CDN{RESET}\n")

    # Construir lista de tareas (solo las que falten)
    tasks = []
    for frame in range(start_frame, end_frame + 1):
        for size in sizes:
            key = cdn_key(year, size, frame)
            if key not in existing:
                tasks.append((frame, size))

    skipped_initial = total_tasks - len(tasks)
    if skipped_initial > 0:
        print(f"{GREEN}✓ {skipped_initial:,} archivos ya en CDN (skip){RESET}")
    print(f"{YELLOW}→ {len(tasks):,} archivos por descargar{RESET}\n")

    if len(tasks) == 0:
        print(f"{GREEN}{BOLD}Nada que hacer. Todo está en CDN.{RESET}")
        return

    # Estimar bytes (basado en tamaños típicos)
    estimated_total_bytes = 0
    for frame, size in tasks:
        if size == "large":
            estimated_total_bytes += 75 * 1024  # ~75 KB por imagen grande
        else:
            estimated_total_bytes += 15 * 1024  # ~15 KB por imagen pequeña

    # Reservar espacio para 3 líneas de progress
    print("\n\n\n", end="")
    sys.stdout.write("\033[3A")
    sys.stdout.flush()

    # Run
    start_time = time.time()
    done = 0
    bytes_done = 0
    errors = 0
    last_status = "starting..."
    error_log = []

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(download_and_upload, s3, year, size, frame, skip_check=True): (frame, size)
                for frame, size in tasks
            }

            for future in as_completed(futures):
                frame, size, n_bytes, status = future.result()
                done += 1
                size_label = "grande" if size == "large" else "pequena"

                if status == "ok":
                    bytes_done += n_bytes
                    last_status = f"{GREEN}✓{RESET} luna/{year}/{size_label}/moon.{frame:04d}.jpg ({fmt_bytes(n_bytes)})"
                elif status == "skip":
                    last_status = f"{DIM}↷ luna/{year}/{size_label}/moon.{frame:04d}.jpg (skip){RESET}"
                else:
                    errors += 1
                    last_status = f"{RED}✗{RESET} luna/{year}/{size_label}/moon.{frame:04d}.jpg ({status})"
                    error_log.append((frame, size, status))

                # Actualizar progress cada 5 frames o al final
                if done % 5 == 0 or done == len(tasks):
                    elapsed = time.time() - start_time
                    render_progress(done, len(tasks), bytes_done, estimated_total_bytes,
                                    workers, elapsed, last_status, errors)

    except KeyboardInterrupt:
        print(f"\n\n\n{YELLOW}⚠ Interrupción detectada. Estado actual guardado.{RESET}")
        print(f"  Completados: {done:,}/{len(tasks):,}")
        print(f"  Puedes reanudar con el mismo comando.")
        sys.exit(130)

    # Imprimir resultado final
    elapsed = time.time() - start_time
    print("\n\n\n")  # bajar de las 3 líneas de progress
    print(f"{BOLD}{GREEN}═══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}{GREEN}  COMPLETADO{RESET}")
    print(f"{BOLD}{GREEN}═══════════════════════════════════════════════════{RESET}")
    print(f"  Procesados:  {done:,} archivos")
    print(f"  Bytes:       {fmt_bytes(bytes_done)}")
    print(f"  Tiempo:      {fmt_eta(elapsed)}")
    print(f"  Velocidad:   {done / elapsed:.1f} archivos/seg")
    if errors > 0:
        print(f"  {RED}Errores:     {errors}{RESET}")
        print(f"\n  Errores recientes:")
        for f, sz, st in error_log[:10]:
            print(f"    frame={f:04d} size={sz} status={st}")
        if len(error_log) > 10:
            print(f"    ... y {len(error_log) - 10} más")
        print(f"\n  {YELLOW}Vuelve a correr el script para reintentar los errores.{RESET}")
    else:
        print(f"  {GREEN}Sin errores ✓{RESET}")
    print()


if __name__ == "__main__":
    main()
