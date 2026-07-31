# Canal Meteo Studio

Editor de vídeo automatizado. Un meteorólogo sube un vídeo + guion y marca qué
operaciones quiere (quitar silencios, subtítulos, croma, zooms, boxes, b-roll);
el sistema procesa en GPU y devuelve el resultado descargable.

## Arquitectura

Dos máquinas que **sólo se comunican por DO Spaces** (el CDN):

```
Navegador ──PUT prefirmado──▶ Spaces (origen)
   │                              ▲
   └─ POST /jobs ─▶ NIMBUS-01 ────┘   web FastAPI (studio.canalmeteo.tv)
                      │ escribe job.json
                      ▼
                   Spaces ◀── status.json / out/ ──┐
                      │                             │
                      └── sondeo ──▶ CALAMARSA ─────┘   worker GPU
```

- **nimbus-01** (`studio/web`): UI + API. No renderiza. No recibe el vídeo de 2 GB
  (va directo del navegador a Spaces con URL prefirmada).
- **calamarsa** (`studio/worker`): sondea Spaces, procesa, sube el resultado.
- **`studio/shared`**: contrato `job.json`/`status.json` + cliente Spaces, común a ambas.

Claves en el bucket: `studio/jobs/<job_id>/{source.*, job.json, status.json, out/*}`.

## Estado: Fase 1 (esqueleto end-to-end)

El worker hace **passthrough** (copia el origen a `out/`) para validar el circuito
completo sin tocar GPU. Las operaciones del checklist aún se ignoran. Próximas fases:
transcripción+subtítulos → auto-editor (silencios) → FFmpeg (croma/zooms) → Remotion (boxes) → b-roll.

## Instalación

### 0. Una vez — CORS del bucket (para el PUT prefirmado del navegador)

```bash
aws s3api put-bucket-cors --bucket canalmeteo-public \
  --endpoint-url https://sfo3.digitaloceanspaces.com --profile do-tor1 \
  --cors-configuration file:///opt/canalmeteo/studio/deploy/spaces-cors.json
```

### 1. nimbus-01 (web)

```bash
cd /opt/canalmeteo
venv/bin/pip install -r studio/web/requirements.txt
cp studio/deploy/studio.env.example studio/deploy/studio.env   # edita si hace falta
sudo cp studio/deploy/studio-web.service /etc/systemd/system/
sudo systemctl enable --now studio-web
sudo cp studio/deploy/nginx-studio.conf /etc/nginx/sites-available/studio.canalmeteo.tv
sudo ln -s /etc/nginx/sites-available/studio.canalmeteo.tv /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d studio.canalmeteo.tv
```

### 2. calamarsa (worker)

```bash
cd /opt/canalmeteo
venv/bin/pip install -r studio/worker/requirements.txt
cp studio/deploy/studio.env.example studio/deploy/studio.env
sudo cp studio/deploy/studio-worker.service /etc/systemd/system/
sudo systemctl enable --now studio-worker
```

## Prueba rápida (local, sin systemd)

```bash
cd /opt/canalmeteo
# terminal 1 (web)
venv/bin/uvicorn studio.web.app.main:app --port 8787
# terminal 2 (worker)
venv/bin/python -m studio.worker.poller
# navegador → http://localhost:8787  (CORS incluye http://localhost:8787)
```
