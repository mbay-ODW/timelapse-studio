#!/usr/bin/env bash
# Führt alle Backend-Tests im Laufzeit-Image aus (echtes ffmpeg mit drawtext, VAAPI-Treiber …).
set -euo pipefail
docker build -q -t timelapse-studio:test . >/dev/null
docker run --rm -u 0 -v "$PWD/backend/tests:/app/tests:ro" --entrypoint sh timelapse-studio:test \
  -c "pip install -q pytest httpx >/dev/null 2>&1 && cd /app && python -m pytest -q -p no:cacheprovider tests $*"
