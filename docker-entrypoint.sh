#!/bin/bash
# docker-entrypoint.sh
#
# Runs on every backend container start.
# Step 1: Apply any pending Alembic migrations.
# Step 2: Hand off to uvicorn (exec replaces this shell process so Docker
#         signals like SIGTERM reach uvicorn directly, enabling graceful shutdown).
set -e

echo "--- Running database migrations ---"
alembic upgrade head

echo "--- Starting FastAPI server ---"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
