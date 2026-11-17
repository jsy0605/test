#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
source scripts/central-ros-env.bash
exec python3 app.py
