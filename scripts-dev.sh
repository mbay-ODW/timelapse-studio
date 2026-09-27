#!/usr/bin/env bash
# Lokaler Dev-Stack: API (:8080) + Worker gegen ./dev-data
set -euo pipefail
cd "$(dirname "$0")"
RUN=${DEV_RUN:-run1}
export CONFIG_DIR=$PWD/dev-data/$RUN/config MEDIA_DIR=$PWD/dev-data/$RUN/media SOURCES_DIR=$PWD/dev-data/sources TZ=Europe/Berlin INDEX_WORKERS=4
cd backend
../.venv/bin/python -m app.worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null' EXIT
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --no-access-log --reload --reload-dir app
