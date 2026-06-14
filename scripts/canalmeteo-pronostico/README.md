# Canal Meteo TV - Pronóstico por Estado

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  DIGITALOCEAN (Droplet)                                     │
│                                                             │
│  Cron cada 6h                                               │
│  ├─ NWS API → datos de 3-6 ciudades por estado             │
│  ├─ Claude API → narrativa interpretativa en español        │
│  └─ Genera HTML → /opt/canalmeteo/output/pronostico/        │
│                                                             │
│  Luego sube via SFTP ↓                                      │
└───────────────────────┬─────────────────────────────────────┘
                        │ SFTP (sshpass/scp ó clave .ppk)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  GODADDY (Hosting canalmeteo.tv)                            │
│                                                             │
│  /home/zz7622j72pvq/public_html/canalmeteo.tv/pronostico/  │
│  ├── index.html                    ← Índice 51 estados     │
│  ├── texas/index.html              ← Página de Texas        │
│  ├── florida/index.html            ← Página de Florida      │
│  ├── california/index.html                                  │
│  └── ... (51 carpetas, una por estado + PR)                 │
└─────────────────────────────────────────────────────────────┘
```

## Qué se ejecuta en DigitalOcean

**Scripts** (en `/opt/canalmeteo/scripts/pronostico_estados/`):
- `generate_forecasts.py` — Script principal
- `states_config.py` — 50 estados + PR con ciudades y traducciones

**Cache** (en `/opt/canalmeteo/cache/pronostico_estados/`):
- Gridpoints del NWS cacheados 30 días

**Output temporal** (en `/opt/canalmeteo/output/pronostico/`):
- HTML generados antes de subir al FTP

## Qué se sube al FTP de GoDaddy

Solo archivos HTML estáticos, sin dependencias:

```
/public_html/pronostico/
├── index.html                  ← 51 estados con buscador
├── alabama/index.html
├── alaska/index.html
├── arizona/index.html
├── ...
├── texas/index.html            ← Narrativa + 6 ciudades con 5 días
├── ...
├── wyoming/index.html
└── puerto-rico/index.html
```

**Total: 52 archivos HTML** (1 índice + 51 estados). ~100-200KB cada uno.

## Instalación

### 1. En DigitalOcean

```bash
# Crear directorios
mkdir -p /opt/canalmeteo/scripts/pronostico_estados
mkdir -p /opt/canalmeteo/cache/pronostico_estados
mkdir -p /opt/canalmeteo/output/pronostico

# Copiar scripts
cp scripts/generate_forecasts.py /opt/canalmeteo/scripts/pronostico_estados/
cp scripts/states_config.py /opt/canalmeteo/scripts/pronostico_estados/

# API key de Anthropic
echo "sk-ant-api03-TU-KEY" > /opt/canalmeteo/.env_anthropic_key
chmod 600 /opt/canalmeteo/.env_anthropic_key
```

### 2. Credenciales SFTP

El script lee las credenciales del `.env` que ya usas en otros scripts:

```bash
# En /opt/canalmeteo/scripts/.env ya deberías tener:
SFTP_HOST=tu-servidor-godaddy.com
SFTP_USER=zz7622j72pvq
SFTP_PORT=22
SFTP_PASS=tu-contraseña
# O si usas clave:
SFTP_KEY=/opt/canalmeteo/scripts/sftp_key
```

Si usas `.ppk` (PuTTY), conviértela primero:
```bash
puttygen tu-clave.ppk -O private-openssh -o /opt/canalmeteo/scripts/sftp_key
chmod 600 /opt/canalmeteo/scripts/sftp_key
```

### 3. Ruta remota

La ruta configurada es `/home/zz7622j72pvq/public_html/canalmeteo.tv/pronostico`.
Si cambia, edita `CONFIG["sftp_remote_base"]` en `generate_forecasts.py`.

### 4. Test

```bash
cd /opt/canalmeteo/scripts/pronostico_estados
export ANTHROPIC_API_KEY=$(cat /opt/canalmeteo/.env_anthropic_key)

# Generar solo Texas, sin subir
/opt/canalmeteo/venv/bin/python3 generate_forecasts.py texas --no-upload

# Verificar que se generó
ls -la /opt/canalmeteo/output/pronostico/texas/

# Generar y subir solo Texas
/opt/canalmeteo/venv/bin/python3 generate_forecasts.py texas

# Generar todos (tarda ~30-40 min)
/opt/canalmeteo/venv/bin/python3 generate_forecasts.py
```

### 5. Cron

```crontab
# Pronóstico por estado - cada 6 horas
0 */6 * * * cd /opt/canalmeteo/scripts/pronostico_estados && \
    ANTHROPIC_API_KEY=$(cat /opt/canalmeteo/.env_anthropic_key) \
    /opt/canalmeteo/venv/bin/python3 generate_forecasts.py \
    >> /var/log/canalmeteo/forecast_estados.log 2>&1
```

## En GoDaddy

No hace falta configurar nada especial. Los archivos HTML son estáticos y se sirven directamente.

Solo asegúrate de que exista el directorio `/public_html/pronostico/` (el script lo crea automáticamente via SSH).

### URLs resultantes

- `https://www.canalmeteo.tv/pronostico/` → Índice
- `https://www.canalmeteo.tv/pronostico/texas/` → Texas
- `https://www.canalmeteo.tv/pronostico/florida/` → Florida

### .htaccess (si necesitas)

Si el hosting requiere reglas de rewrite:
```apache
# En /home/zz7622j72pvq/public_html/canalmeteo.tv/pronostico/.htaccess
DirectoryIndex index.html
Options -Indexes
```

## Comandos útiles

```bash
# Generar sin IA (más rápido para testing)
python3 generate_forecasts.py --no-ai

# Solo regenerar el índice
python3 generate_forecasts.py --index-only

# Usar rsync en vez de SCP (más eficiente)
python3 generate_forecasts.py --use-rsync

# Estados específicos
python3 generate_forecasts.py texas florida california new-york
```

## Costo

- **NWS API**: Gratuita, sin API key
- **Claude API**: ~$0.30/día (51 narrativas × 4 veces/día con Sonnet)
- **SFTP**: Incluido en tu hosting
