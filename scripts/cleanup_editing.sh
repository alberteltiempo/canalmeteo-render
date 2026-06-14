#!/bin/bash
# Cleanup automático de comentarios en estado 'editing' por más de 24h
# Se ejecuta diariamente a las 3:00 AM via cron

LOG_FILE="/opt/canalmeteo/scripts/cleanup_editing.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TIMESTAMP] Iniciando cleanup de editing huérfanos..." >> "$LOG_FILE"

docker exec n8n-db psql -U n8n -d n8n -c "
  UPDATE youtube_comments_pending 
  SET status='discarded', 
      decided_at=NOW(), 
      error_message='Auto-discarded: editing timeout (24h)' 
  WHERE status='editing' 
    AND detected_at < NOW() - INTERVAL '24 hours'
  RETURNING id, comment_id;
" >> "$LOG_FILE" 2>&1

echo "[$TIMESTAMP] Cleanup terminado." >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"
