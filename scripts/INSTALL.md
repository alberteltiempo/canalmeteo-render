# Canal Meteo TV — Radar + Avisos Severos
## Guía de instalación del backend

### Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│  CRON (cada 15s)                                         │
│  fetch_severe_warnings.py                                │
│  ├── NWS API → Tornado + Severe Thunderstorm Warnings   │
│  ├── Resuelve geometrías de zonas UGC (con cache)       │
│  ├── RainViewer API → weather-maps.json                 │
│  └── Sube todo a DigitalOcean Spaces (CDN)              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  DigitalOcean Spaces (CDN)                               │
│  canalmeteo-public/radar/                                │
│  ├── severe_warnings.json  (cache 10s)                  │
│  └── rainviewer.json       (cache 60s)                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  HTML (radar_warnings_canalmeteo.html)                   │
│  ├── fetch(Spaces/radar/severe_warnings.json) → instant │
│  ├── fetch(Spaces/radar/rainviewer.json) → instant      │
│  ├── Radar tiles: tilecache.rainviewer.com (512px webp) │
│  └── Mapa: Mapbox GL JS dark-v11                        │
└─────────────────────────────────────────────────────────┘
```

### 1. Instalar el script Python

```bash
# Crear directorio
mkdir -p /opt/canalmeteo/scripts/radar-warnings
mkdir -p /opt/canalmeteo/data/radar-warnings

# Copiar archivos
cp fetch_severe_warnings.py /opt/canalmeteo/scripts/radar-warnings/
cp run_warnings.sh /opt/canalmeteo/scripts/radar-warnings/

# Permisos
chmod +x /opt/canalmeteo/scripts/radar-warnings/*.sh
chmod +x /opt/canalmeteo/scripts/radar-warnings/*.py

# Verificar dependencias (requests ya debería estar)
/opt/canalmeteo/venv/bin/pip install requests
```

### 2. Probar manualmente

```bash
cd /opt/canalmeteo/scripts/radar-warnings
/opt/canalmeteo/venv/bin/python3 fetch_severe_warnings.py
```

Deberías ver:
```
🌪️ Canal Meteo TV — Severe Warnings Fetcher
📡 Consultando NWS: Tornado Warning...
   → X Tornado Warning(s) activo(s)
📡 Consultando NWS: Severe Thunderstorm Warning...
   → X Severe Thunderstorm Warning(s) activo(s)
📍 Con geometría directa: X | Necesitan resolución: X
🗺️ Resolviendo X zonas únicas...
✅ Total avisos con geometría: X
💾 Guardado local: /opt/canalmeteo/data/radar-warnings/severe_warnings.json
☁️ Subido a Spaces: radar/severe_warnings.json
📡 RainViewer data subido a Spaces
```

### 3. Verificar en Spaces

```bash
# Debe devolver JSON
curl -s "https://canalmeteo-public.sfo3.digitaloceanspaces.com/radar/severe_warnings.json" | python3 -m json.tool | head -20

curl -s "https://canalmeteo-public.sfo3.digitaloceanspaces.com/radar/rainviewer.json" | python3 -m json.tool | head -10
```

### 4. Configurar crontab

```bash
crontab -e
```

Añadir:
```cron
# Radar warnings - cada minuto (el wrapper ejecuta 4 veces = cada 15s)
* * * * * /opt/canalmeteo/scripts/radar-warnings/run_warnings.sh >> /opt/canalmeteo/scripts/radar-warnings/warnings.log 2>&1
```

### 5. Subir el HTML

```bash
# A dev primero
cp radar_warnings_canalmeteo.html /path/to/dev.canalmeteo.tv/radar-warnings.html

# Después a prod
cp radar_warnings_canalmeteo.html /path/to/www.canalmeteo.tv/radar-warnings.html
```

### 6. Verificar CORS en Spaces

Si hay problemas de CORS al cargar los JSON desde el HTML:

```bash
# Verificar que el bucket tiene CORS habilitado
aws s3api get-bucket-cors \
  --bucket canalmeteo-public \
  --endpoint-url https://sfo3.digitaloceanspaces.com \
  --profile do-tor1
```

Si no tiene CORS, crear `cors.json`:
```json
{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET"],
      "AllowedOrigins": ["*"],
      "MaxAgeSeconds": 3600
    }
  ]
}
```

```bash
aws s3api put-bucket-cors \
  --bucket canalmeteo-public \
  --cors-configuration file://cors.json \
  --endpoint-url https://sfo3.digitaloceanspaces.com \
  --profile do-tor1
```

### Mantenimiento

**Logs:**
```bash
tail -f /opt/canalmeteo/scripts/radar-warnings/warnings.log
```

**Cache de zonas:**
El cache de geometrías de zonas se guarda en `/opt/canalmeteo/data/radar-warnings/zone_cache.json` y se purga automáticamente cada 24 horas. Si necesitas forzar un reset:
```bash
rm /opt/canalmeteo/data/radar-warnings/zone_cache.json
```

**Archivos en Spaces:**
```
canalmeteo-public/radar/severe_warnings.json  → Cache 10s
canalmeteo-public/radar/rainviewer.json        → Cache 60s
```
