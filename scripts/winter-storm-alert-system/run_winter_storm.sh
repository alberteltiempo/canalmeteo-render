#!/bin/bash
cd /opt/canalmeteo/scripts/winter-storm-alert-system

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
fi

if [ -f /opt/canalmeteo/venv/bin/activate ]; then
    source /opt/canalmeteo/venv/bin/activate
fi

python3 winter_storm_warning.py "$@"
