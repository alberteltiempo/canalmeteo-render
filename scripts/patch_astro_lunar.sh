#!/bin/bash
# patch_astro_lunar.sh
# ====================
# Modifica /opt/canalmeteo/scripts/astro-lunar.py para que las URLs de imágenes
# de luna apunten al CDN propio en lugar de NASA SVS directamente.
#
# El cambio es quirúrgico:
#   - Añade constante CDN_LUNA_BASE
#   - Reemplaza el cuerpo de get_moon_image_url() por la versión CDN
#   - Mantiene CONFIG['svs_base_url'] intacto (lo usa bulk_download_luna.py)
#
# Backup automático en astro-lunar.py.bak.{timestamp}

set -euo pipefail

TARGET="/opt/canalmeteo/scripts/astro-lunar.py"
BACKUP="${TARGET}.bak.$(date +%Y%m%d_%H%M%S)"

# Colores
GREEN="\033[92m"
RED="\033[91m"
YELLOW="\033[93m"
CYAN="\033[96m"
BOLD="\033[1m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}═══ Patch astro-lunar.py para usar CDN ═══${RESET}\n"

# Validación inicial
if [ ! -f "$TARGET" ]; then
    echo -e "${RED}ERROR: no existe $TARGET${RESET}"
    exit 1
fi

# Verificar que la función original existe (firma exacta)
if ! grep -q "^def get_moon_image_url(dt, size='large'):" "$TARGET"; then
    echo -e "${RED}ERROR: no se encontró la función get_moon_image_url con la firma esperada${RESET}"
    echo "Esperaba: def get_moon_image_url(dt, size='large'):"
    exit 1
fi

# Verificar que NO se aplicó ya el patch
if grep -q "CDN_LUNA_BASE" "$TARGET"; then
    echo -e "${YELLOW}WARN: el patch ya parece aplicado (CDN_LUNA_BASE existe)${RESET}"
    echo "Si quieres re-aplicarlo, restaura el backup primero."
    exit 1
fi

# Backup
cp "$TARGET" "$BACKUP"
echo -e "${GREEN}✓${RESET} Backup creado: ${CYAN}$BACKUP${RESET}"

# Aplicar patch con Python (más fiable que sed para multi-línea)
python3 << PYEOF
import re

path = "$TARGET"
with open(path, 'r') as f:
    content = f.read()

# Patrón a reemplazar (función completa)
old_func = """def get_moon_image_url(dt, size='large'):
    frame = get_frame_number(dt)
    size_path = CONFIG['image_size_large'] if size == 'large' else CONFIG['image_size_small']
    return f"{CONFIG['svs_base_url']}/{size_path}/moon.{frame:04d}.jpg" """.rstrip()

new_func = """# CDN propio de Canal Meteo donde se sirven las imágenes de luna
# (descargadas desde NASA SVS con bulk_download_luna.py)
CDN_LUNA_BASE = 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/astro/luna'

def get_moon_image_url(dt, size='large'):
    frame = get_frame_number(dt)
    year = dt.year
    size_folder = 'grande' if size == 'large' else 'pequena'
    return f"{CDN_LUNA_BASE}/{year}/{size_folder}/moon.{frame:04d}.jpg" """.rstrip()

# Verificar count == 1
if content.count(old_func) != 1:
    print(f"ERROR: encontradas {content.count(old_func)} ocurrencias del bloque (esperaba 1)")
    print("Aborting. Revisa el archivo manualmente.")
    raise SystemExit(2)

content_new = content.replace(old_func, new_func, 1)

if content_new == content:
    print("ERROR: el reemplazo no cambió nada")
    raise SystemExit(2)

with open(path, 'w') as f:
    f.write(content_new)

print("OK: patch aplicado")
PYEOF

echo -e "${GREEN}✓${RESET} Patch aplicado a ${CYAN}$TARGET${RESET}\n"

# Verificación post-patch
echo -e "${BOLD}Verificación:${RESET}"

if python3 -c "import ast; ast.parse(open('$TARGET').read())" 2>/dev/null; then
    echo -e "  ${GREEN}✓${RESET} Sintaxis Python OK"
else
    echo -e "  ${RED}✗ Error de sintaxis después del patch! Restaurando backup...${RESET}"
    cp "$BACKUP" "$TARGET"
    echo -e "  ${YELLOW}Restaurado${RESET}"
    exit 2
fi

if grep -q "CDN_LUNA_BASE" "$TARGET"; then
    echo -e "  ${GREEN}✓${RESET} CDN_LUNA_BASE presente"
else
    echo -e "  ${RED}✗ CDN_LUNA_BASE NO encontrado${RESET}"
    exit 2
fi

if grep -q "size_folder = 'grande' if size == 'large' else 'pequena'" "$TARGET"; then
    echo -e "  ${GREEN}✓${RESET} Nueva función get_moon_image_url presente"
else
    echo -e "  ${RED}✗ La nueva función NO se aplicó${RESET}"
    exit 2
fi

echo -e "\n${BOLD}${GREEN}Patch completado.${RESET}"
echo -e "Para revertir: ${CYAN}cp $BACKUP $TARGET${RESET}\n"

echo -e "${BOLD}Próximos pasos:${RESET}"
echo "  1. Correr bulk_download_luna.py para llenar el CDN"
echo "  2. Cuando termine el bulk, correr astro-lunar.py para regenerar lunar-data.json"
echo "  3. Correr cielo_pipeline.py para regenerar cielo.json"
echo "  4. La luna aparecerá en la app Roku"
