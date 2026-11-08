#!/bin/bash
# cortar_region.sh <REG>  — pasa una región al motor único remotion/tiempo
# (render.sh → PROJECT_DIR, worker de previews → UNIFIED), comete y despliega
# en nimbus-03. Ejecutar en nimbus-01 dentro de /opt/canalmeteo/render.
# Rollback: volver a poner tiempo_<REG> en PROJECT_DIR y quitar el slug de UNIFIED.
set -eu
REG=${1:?región (NE|FL|MW|NP|NW|SW|SE|CONUS)}; reg=$(echo "$REG" | tr A-Z a-z); slug="tiempo-$reg"
cd /opt/canalmeteo/render
RS=remotion/tiempo_$REG/render.sh
grep -q "^PROJECT_DIR=\"/opt/canalmeteo/remotion/tiempo_$REG\"" $RS || { echo "$RS no apunta al fork (¿ya cortada?)"; exit 1; }
sed -i "s|^PROJECT_DIR=\"/opt/canalmeteo/remotion/tiempo_$REG\"|PROJECT_DIR=\"/opt/canalmeteo/remotion/tiempo\"   # motor único (fase 2, $(date -u +%d/%m/%Y)); rollback: tiempo_$REG|" $RS
python3 - "$slug" <<'PY'
import re, sys
slug=sys.argv[1]; p="scripts/escaleta_preview_worker.py"; s=open(p).read()
m=re.search(r'^UNIFIED: set\[str\] = \{([^}]*)\}', s, re.M) or re.search(r'^UNIFIED: set\[str\] = set\(\)', s, re.M)
assert m
cur=[x.strip().strip('"') for x in (m.group(1).split(",") if m.lastindex else []) if x.strip()]
if slug not in cur: cur.append(slug)
s=s.replace(m.group(0), 'UNIFIED: set[str] = {' + ", ".join(f'"{x}"' for x in cur) + '}')
open(p,"w").write(s); print("UNIFIED =", cur)
PY
bash -n $RS && python3 -m py_compile scripts/escaleta_preview_worker.py
git add $RS scripts/escaleta_preview_worker.py
git -c user.name="Albert (Canal Meteo)" -c user.email="albert@canalmeteo.tv" commit -q -m "Corte de tiempo_$REG al motor único remotion/tiempo (previews incluidas)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push -q nimbus03 main
ssh -o ConnectTimeout=10 nimbus-03 "cd /opt/canalmeteo && chown canalmeteo:canalmeteo $RS scripts/escaleta_preview_worker.py && git log -1 --format='%h %s' && grep -n '^PROJECT_DIR=' $RS"
echo "✓ $REG cortada $(date -u +%H:%M)Z"
