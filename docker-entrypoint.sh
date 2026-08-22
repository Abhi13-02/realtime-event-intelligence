#!/bin/bash
# docker-entrypoint.sh
#
# Runs on every backend container start.
# Step 1: Apply any pending Alembic migrations.
# Step 2: Hand off to uvicorn (exec replaces this shell process so Docker
#         signals like SIGTERM reach uvicorn directly, enabling graceful shutdown).
set -e

# Ensure /app is in PYTHONPATH so reloader can always find the 'app' module
export PYTHONPATH=$PYTHONPATH:/app

echo "--- Running database migrations ---"
alembic upgrade head

# --reload is the local dev default. Production passes --no-reload (see
# deploy/docker-compose.prod.yml) because the file watcher and its supervising
# process are pure overhead on a 2-vCPU box.
RELOAD_FLAG="--reload"
if [ "$1" = "--no-reload" ]; then
  RELOAD_FLAG=""
fi

echo "--- Starting FastAPI server ---"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 $RELOAD_FLAG
