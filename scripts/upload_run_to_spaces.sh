#!/bin/bash
# upload_run_to_spaces.sh v1.0
# Sube todos los PNGs (originales + sub-frames interpolados) y el manifest
# actualizado del último run al CDN de DO Spaces.
#
# Uso: upload_run_to_spaces.sh <product>
#   product: hrrr-18h | hrrr-48h
#
# Variables de entorno opcionales:
#   AWS_PROFILE (default: do-tor1)
#   SPACES_ENDPOINT (default: https://sfo3.digitaloceanspaces.com)
#   SPACES_BUCKET (default: canalmeteo-public)

set -euo pipefail

PRODUCT="${1:?Usage: $0 <hrrr-18h|hrrr-48h>}"
AWS_PROFILE="${AWS_PROFILE:-do-tor1}"
SPACES_ENDPOINT="${SPACES_ENDPOINT:-https://sfo3.digitaloceanspaces.com}"
SPACES_BUCKET="${SPACES_BUCKET:-canalmeteo-public}"
DATA_BASE="${DATA_BASE:-/opt/canalmeteo/data/hrrr_output}"

# Validar producto
case "$PRODUCT" in
  hrrr-18h|hrrr-48h) ;;
  *) echo "ERROR: producto inválido: $PRODUCT (debe ser hrrr-18h o hrrr-48h)" >&2; exit 1 ;;
esac

# Encontrar el último run
PRODUCT_DIR="$DATA_BASE/$PRODUCT"
if [[ ! -d "$PRODUCT_DIR" ]]; then
  echo "ERROR: no existe $PRODUCT_DIR" >&2
  exit 1
fi

LATEST_RUN=$(ls -td "$PRODUCT_DIR"/*/ 2>/dev/null | head -1 | xargs -I {} basename {})
if [[ -z "$LATEST_RUN" ]]; then
  echo "ERROR: no se encontraron runs en $PRODUCT_DIR" >&2
  exit 1
fi

RUN_DIR="$PRODUCT_DIR/$LATEST_RUN"
echo "═══ Upload run a Spaces ═══"
echo "Producto: $PRODUCT"
echo "Run:      $LATEST_RUN"
echo "Dir:      $RUN_DIR"

# Contar archivos a subir
NUM_PNGS=$(find "$RUN_DIR" -maxdepth 1 -name "*.png" | wc -l)
echo "PNGs:     $NUM_PNGS"

if [[ "$NUM_PNGS" -eq 0 ]]; then
  echo "ERROR: no hay PNGs en $RUN_DIR" >&2
  exit 1
fi

# Sync de PNGs (sólo los nuevos / cambiados)
echo ""
echo "→ Sincronizando PNGs..."
aws s3 sync "$RUN_DIR/" "s3://$SPACES_BUCKET/$PRODUCT/" \
  --profile "$AWS_PROFILE" \
  --endpoint-url "$SPACES_ENDPOINT" \
  --acl public-read \
  --exclude "*" --include "*.png" \
  --cache-control "public, max-age=3600" \
  --content-type "image/png" \
  --no-progress

# Subir el manifest (siempre, sobreescribiendo)
echo ""
echo "→ Subiendo manifest..."
aws s3 cp "$RUN_DIR/manifest.json" "s3://$SPACES_BUCKET/$PRODUCT/manifest.json" \
  --profile "$AWS_PROFILE" \
  --endpoint-url "$SPACES_ENDPOINT" \
  --acl public-read \
  --cache-control "public, max-age=60" \
  --content-type "application/json"

echo ""
echo "✓ Upload completado: $LATEST_RUN ($NUM_PNGS PNGs)"
