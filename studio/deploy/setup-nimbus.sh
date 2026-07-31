#!/usr/bin/env bash
# Despliegue de la web de Studio en NIMBUS-01.
# Requiere: el repo en /opt/canalmeteo (con studio/) y venv en /opt/canalmeteo/venv.
# Uso:  bash studio/deploy/setup-nimbus.sh
set -euo pipefail

ROOT=/opt/canalmeteo
cd "$ROOT"

echo "▶ Instalando dependencias de la web…"
"$ROOT/venv/bin/pip" install -r studio/web/requirements.txt

echo "▶ Enlazando frontend → /var/www/html/studio (symlink, se mantiene en sync con el repo)…"
sudo mkdir -p /var/www/html
sudo ln -sfn "$ROOT/studio/web/static" /var/www/html/studio

echo "▶ Preparando entorno…"
[ -f studio/deploy/studio.env ] || cp studio/deploy/studio.env.example studio/deploy/studio.env

echo "▶ Servicio systemd (uvicorn 127.0.0.1:8787)…"
sudo cp studio/deploy/studio-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now studio-web

echo "▶ nginx (studio.canalmeteo.tv)…"
sudo cp studio/deploy/nginx-studio.conf /etc/nginx/sites-available/studio.canalmeteo.tv
sudo ln -sfn /etc/nginx/sites-available/studio.canalmeteo.tv /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo
echo "✓ Web desplegada en nimbus. Comprueba:  curl -s http://127.0.0.1:8787/api/jobs"
echo "  Pendiente (tú):"
echo "   1) DNS en GoDaddy:  A  studio  →  <IP pública IPv4 de nimbus-01>"
echo "   2) TLS (tras propagar DNS):  sudo certbot --nginx -d studio.canalmeteo.tv"
echo "   3) CORS del bucket (una vez):  ver studio/README.md"
