#!/bin/bash
cd /opt/canalmeteo/scripts
source /opt/canalmeteo/env/bin/activate
export $(cat .env | grep -v '^#' | xargs)
python3 tornado_warning.py "$@"
