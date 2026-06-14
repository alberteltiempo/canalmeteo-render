#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Canal Meteo — MRMS Radar HD Pipeline Installation
# ══════════════════════════════════════════════════════════════

set -e

echo "════════════════════════════════════════════════"
echo " Canal Meteo Radar HD (MRMS) — Install"
echo "════════════════════════════════════════════════"

# ─── Step 1: Verify dependencies ────────────────────────────────
echo ""
echo "[1/4] Verifying Python dependencies..."
source /opt/canalmeteo/venv/bin/activate

# These should already be installed from earlier work (NBM/GFS pipelines)
python3 -c "import cfgrib, xarray, numpy, matplotlib, PIL; print('  ✅ all deps present')" || {
    echo "Missing dependencies. Installing..."
    pip install cfgrib xarray numpy matplotlib Pillow requests
}

# ─── Step 2: Copy script ────────────────────────────────────────
echo ""
echo "[2/4] Copying pipeline script..."
cp mrms_pipeline.py /opt/canalmeteo/scripts/
chmod +x /opt/canalmeteo/scripts/mrms_pipeline.py
mkdir -p /var/log/canalmeteo
touch /var/log/canalmeteo/mrms.log

# ─── Step 3: First-run smoke test ───────────────────────────────
echo ""
echo "[3/4] Running pipeline once (first run may take 3-5 minutes)..."
/opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/mrms_pipeline.py --once
echo ""
echo "  Manifest URL:"
echo "  https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/mrms/manifest.json"

# ─── Step 4: Install cron entry ─────────────────────────────────
echo ""
echo "[4/4] Installing cron entry..."
echo ""
echo "  Add this line to your crontab (crontab -e):"
echo ""
echo "  # ─── Radar HD (MRMS) ───────────────────────"
echo "  */2 * * * * flock -n /tmp/mrms.lock /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/mrms_pipeline.py --once >> /var/log/canalmeteo/mrms.log 2>&1"
echo ""

echo "════════════════════════════════════════════════"
echo " Installation complete"
echo "════════════════════════════════════════════════"
echo ""
echo "Commands:"
echo "  View logs:     tail -f /var/log/canalmeteo/mrms.log"
echo "  Test manually: /opt/canalmeteo/venv/bin/python3 /opt/canalmeteo/scripts/mrms_pipeline.py --once"
echo ""
echo "Check manifest:"
echo "  curl -s https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/mrms/manifest.json | python3 -m json.tool"
