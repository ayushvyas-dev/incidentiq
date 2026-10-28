#!/bin/sh
set -e

# Apply database migrations on startup if database is configured
if [ -n "$DATABASE_URL" ] || [ -n "$DIRECT_DATABASE_URL" ]; then
  echo "Applying database migrations..."
  alembic upgrade head || echo "Migration warning: proceeding with startup..."
fi

# Start ARQ background worker in the background if Redis is configured
if [ -n "$REDIS_URL" ]; then
  echo "Starting ARQ background worker..."
  arq incidentiq.workers.queue.WorkerSettings &
fi

# Start Uvicorn API in foreground
echo "Starting Uvicorn API server on port ${PORT:-8000}..."
exec uvicorn incidentiq.main:app --host 0.0.0.0 --port "${PORT:-8000}"
