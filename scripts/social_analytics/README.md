# YouTube Analytics Collector para Canal Meteo TV

Sistema automatizado para recolectar y almacenar métricas de YouTube Analytics.

## Estructura de Archivos

```
social_analytics/
├── config/
│   ├── client_secrets.json      # Credenciales OAuth (TÚ lo descargas de Google)
│   ├── youtube_credentials.json # Tokens generados automáticamente
│   └── youtube_config.json      # Channel ID y configuración
├── scripts/
│   ├── youtube_auth_setup.py    # Autenticación OAuth (ejecutar 1 vez)
│   ├── youtube_daily_collector.py # Recolector diario (cron)
│   └── youtube_exporter.py      # Exportador JSON para dashboard
├── data/
│   ├── youtube_analytics.db     # Base de datos SQLite
│   └── exports/                 # JSONs exportados
├── logs/
│   └── youtube_collector.log    # Logs de ejecución
├── requirements.txt
├── setup.sh
└── crontab_example.txt
```

## Instalación Paso a Paso

### Paso 1: En tu servidor DigitalOcean

```bash
# Subir este directorio completo a tu servidor
scp -r social_analytics/ usuario@tu-servidor:/opt/canalmeteo/scripts/

# Conectar al servidor
ssh usuario@tu-servidor

# Ejecutar setup
cd /opt/canalmeteo/scripts/social_analytics
bash setup.sh
```

### Paso 2: Configurar Google Cloud

1. Ve a https://console.cloud.google.com/
2. Crea un nuevo proyecto: `CanalMeteoTV-Analytics`
3. Ve a **APIs & Services > Library**
4. Habilita estas APIs:
   - YouTube Data API v3
   - YouTube Analytics API
5. Ve a **APIs & Services > OAuth consent screen**
   - User Type: External
   - App name: CanalMeteoTV Analytics
   - Agrega tu email como Test User
6. Ve a **APIs & Services > Credentials**
   - Click **+ Create Credentials > OAuth client ID**
   - Application type: **Desktop app**
   - Descarga el JSON

### Paso 3: Subir credenciales y autenticar

```bash
# Subir el archivo JSON descargado
scp client_secrets.json usuario@tu-servidor:/opt/canalmeteo/scripts/social_analytics/config/

# En el servidor, ejecutar autenticación
cd /opt/canalmeteo/scripts/social_analytics
source /opt/canalmeteo/env/social_analytics/bin/activate
python3 scripts/youtube_auth_setup.py
```

**IMPORTANTE:** El script abrirá una URL. Si estás en SSH sin navegador:
1. Copia la URL que muestra
2. Ábrela en tu navegador local
3. Autoriza la app
4. Copia el código de autorización
5. Pégalo en la terminal

### Paso 4: Probar recolección

```bash
# Recolectar últimos 7 días de prueba
python3 scripts/youtube_daily_collector.py --backfill 7

# Verificar datos
sqlite3 data/youtube_analytics.db "SELECT date, views FROM channel_daily ORDER BY date DESC LIMIT 5;"

# Exportar a JSON
python3 scripts/youtube_exporter.py --local
```

### Paso 5: Configurar Cron

```bash
# Editar crontab
crontab -e

# Agregar estas líneas:
0 6 * * * /opt/canalmeteo/scripts/social_analytics/run_youtube_collector.sh
5 6 * * * /opt/canalmeteo/scripts/social_analytics/run_youtube_exporter.sh
```

## Métricas Recolectadas

### Canal (diario)
| Métrica | Descripción |
|---------|-------------|
| views | Reproducciones del día |
| estimated_minutes_watched | Tiempo de visualización total |
| average_view_duration | Duración promedio de vista |
| subscribers_gained | Suscriptores ganados |
| subscribers_lost | Suscriptores perdidos |
| likes | Me gusta totales |
| comments | Comentarios totales |
| shares | Compartidos |

### Videos (diario, top 50 activos)
| Métrica | Descripción |
|---------|-------------|
| views | Reproducciones del día |
| estimated_minutes_watched | Tiempo de visualización |
| average_view_percentage | % promedio visto (retención) |
| likes, comments, shares | Engagement |
| subscribers_gained | Suscriptores desde este video |

## Limitaciones Conocidas

1. **Retraso de datos:** YouTube Analytics tiene ~24-48h de retraso
2. **Cuota API:** 10,000 unidades/día (suficiente para ~10-20 ejecuciones)
3. **Histórico:** YouTube Analytics solo retiene ~18 meses de datos detallados
4. **Videos:** Solo se recolectan los 50 más activos por día

## Troubleshooting

### "Token has been expired or revoked"
```bash
python3 scripts/youtube_auth_setup.py
```

### "Quota exceeded"
Espera hasta mañana o solicita aumento de cuota en Google Cloud Console.

### No hay datos para cierta fecha
YouTube puede tardar hasta 72h en procesar datos. Los fines de semana son más lentos.

## Archivos de Salida

El exporter genera estos JSONs en `data/exports/`:

- `youtube_channel_summary.json` - Resumen completo del canal
- `youtube_top_videos.json` - Videos con mejor rendimiento
- `youtube_dashboard.json` - Datos optimizados para el dashboard web

Si configuras Spaces, estos archivos se suben automáticamente a:
```
https://canalmeteo-data.nyc3.cdn.digitaloceanspaces.com/analytics/youtube/
```
