#!/bin/bash
# Publica el buzón del editor de escaletas (intranet) a Spaces.
# El PHP (www-data) NO tiene credenciales S3 a propósito: escribe los JSON en
# /opt/canalmeteo/escaleta/outbox y este cron de root los sube cada minuto.
#   <slug>.json           → data/escaleta/<slug>.json      (config del producto)
#   preview_<...>.json    → data/escaleta/requests/        (peticiones de preview
#                            que atiende escaleta_preview_worker.py en calamarsa)
# Cron (root@nimbus-01):
#   * * * * * flock -n /tmp/escaleta_push.lock /opt/canalmeteo/scripts/escaleta_push.sh >> /var/log/canalmeteo/escaleta_push.log 2>&1
set -u
OUT=/opt/canalmeteo/escaleta/outbox
SENT=/opt/canalmeteo/escaleta/sent
BUCKET=s3://canalmeteo-public
EP=https://sfo3.digitaloceanspaces.com
mkdir -p "$SENT"
shopt -s nullglob
for f in "$OUT"/*.json; do
    b=$(basename "$f")
    if ! python3 -m json.tool "$f" > /dev/null 2>&1; then
        echo "$(date -u +%FT%TZ) JSON inválido, apartado: $b"
        mv "$f" "$SENT/invalid-$(date +%s)-$b"
        continue
    fi
    case "$b" in
        preview_*) dest="$BUCKET/data/escaleta/requests/$b" ;;
        *)         dest="$BUCKET/data/escaleta/$b" ;;
    esac
    if aws s3 cp "$f" "$dest" --profile do-tor1 --endpoint-url "$EP" \
        --content-type application/json --acl public-read --cache-control no-cache --quiet; then
        echo "$(date -u +%FT%TZ) publicado: $b"
        mv "$f" "$SENT/$b"
    else
        echo "$(date -u +%FT%TZ) FALLO al subir: $b (reintento en el próximo ciclo)"
    fi
done
# Histórico acotado (el "última buena" real es el propio CDN + este espejo)
find "$SENT" -type f -mtime +14 -delete 2>/dev/null
