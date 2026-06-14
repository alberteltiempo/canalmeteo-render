#!/bin/bash
#
# Canal Meteo TV - Data Sync Master Script
# Ejecuta todas las sincronizaciones de datos
#
# Uso: ./sync-all.sh
# Cron ejemplo: 0 */6 * * * /var/www/canalmeteo.tv/scripts/sync-all.sh >> /var/log/canalmeteo-sync.log 2>&1
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=========================================="
echo "Canal Meteo TV - Data Sync"
echo "$(date)"
echo "=========================================="

# Sincronizar incendios activos
echo ""
echo "--- Sincronizando Incendios ---"
php "$SCRIPT_DIR/sync-fires.php"
FIRES_STATUS=$?

# Sincronizar drought monitor (solo los viernes o forzado)
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" = "5" ] || [ "$1" = "--force-drought" ]; then
    echo ""
    echo "--- Sincronizando Drought Monitor ---"
    php "$SCRIPT_DIR/sync-drought.php"
    DROUGHT_STATUS=$?
else
    echo ""
    echo "--- Drought Monitor: Se sincroniza los viernes (hoy es día $DAY_OF_WEEK) ---"
    echo "    Usa --force-drought para forzar sincronización"
    DROUGHT_STATUS=0
fi

echo ""
echo "=========================================="
echo "Sincronización completada"
echo "- Incendios: $([ $FIRES_STATUS -eq 0 ] && echo '✅ OK' || echo '❌ Error')"
echo "- Sequía: $([ $DROUGHT_STATUS -eq 0 ] && echo '✅ OK' || echo '❌ Error')"
echo "=========================================="

# Retornar error si alguno falló
[ $FIRES_STATUS -eq 0 ] && [ $DROUGHT_STATUS -eq 0 ]
