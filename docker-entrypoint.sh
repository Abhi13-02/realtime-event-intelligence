#!/bin/bash
# docker-entrypoint.sh
#
# Runs on every backend container start.
#
# Migrations are NOT run here any more. They belong to the one-shot `migrate`
# service in docker-compose.yml, which every schema-reading service waits on.
# Running them per-container was a race as soon as the backend had more than
# one replica: each would run `alembic upgrade head` against the same database
# simultaneously.
#
# exec replaces this shell process so Docker signals like SIGTERM reach uvicorn
# directly, enabling graceful shutdown.
set -e

# Ensure /app is in PYTHONPATH so reloader can always find the 'app' module
export PYTHONPATH=$PYTHONPATH:/app

# --reload is the local dev default. Production passes --no-reload (see
# deploy/docker-compose.prod.yml) because the file watcher and its supervising
# process are pure overhead on a 2-vCPU box.
RELOAD_FLAG="--reload"
if [ "$1" = "--no-reload" ]; then
  RELOAD_FLAG=""
fi

echo "--- Starting FastAPI server ---"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 $RELOAD_FLAG
