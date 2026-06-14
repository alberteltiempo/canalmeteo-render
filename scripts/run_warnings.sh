#!/bin/bash
# Canal Meteo TV — Severe Warnings Cron Wrapper
# Ejecuta el fetcher cada 15 segundos durante 1 minuto
# Crontab: * * * * * /opt/canalmeteo/scripts/radar-warnings/run_warnings.sh >> /opt/canalmeteo/scripts/radar-warnings/warnings.log 2>&1

SCRIPT_DIR="/opt/canalmeteo/scripts/radar-warnings"
VENV="/opt/canalmeteo/venv/bin/python3"
LOCK="/tmp/severe_warnings.lock"

# Prevent overlapping runs
if [ -f "$LOCK" ]; then
    PID=$(cat "$LOCK")
    if kill -0 "$PID" 2>/dev/null; then
        echo "$(date): Already running (PID $PID), skipping"
        exit 0
    fi
fi

echo $$ > "$LOCK"
trap "rm -f $LOCK" EXIT

# Run 4 times per minute (every 15 seconds)
for i in 0 1 2 3; do
    $VENV "$SCRIPT_DIR/fetch_severe_warnings.py" &
    CHILD=$!
    
    # Wait for completion or timeout (12 seconds max)
    timeout 12 wait $CHILD 2>/dev/null
    
    # Sleep remaining time to hit 15-second intervals
    if [ $i -lt 3 ]; then
        sleep 15
    fi
done
