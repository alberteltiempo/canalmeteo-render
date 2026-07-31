#!/usr/bin/env bash
# Despliega studio/ desde calamarsa → nimbus-01 y (re)arranca la web.
# Transporte: rsync sobre SSH (root@nimbus). Sólo toca /opt/canalmeteo/studio.
# Uso:  bash studio/deploy/deploy-to-nimbus.sh
set -euo pipefail

NIMBUS=root@5.78.112.51
SRC=/opt/canalmeteo/studio/
DST=/opt/canalmeteo/studio/

echo "▶ rsync studio/ → nimbus…"
rsync -az --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'studio.env' --exclude 'studio.db' \
  -e ssh "$SRC" "$NIMBUS:$DST"
ssh "$NIMBUS" "chown -R canalmeteo:canalmeteo /opt/canalmeteo/studio"

echo "▶ deps + servicio en nimbus…"
ssh "$NIMBUS" "/opt/canalmeteo/venv/bin/pip install -q -r /opt/canalmeteo/studio/web/requirements.txt && systemctl restart studio-web 2>/dev/null || true"

echo "✓ desplegado. Estado web:"
ssh "$NIMBUS" "systemctl is-active studio-web 2>/dev/null; curl -s -o /dev/null -w 'api -> HTTP %{http_code}\n' http://127.0.0.1:8787/api/jobs || true"
