#!/bin/sh
# Dev mode: two celery workers with watchfiles auto-reload.

set -e

uv sync --frozen --no-install-project

DEFAULT_CMD="celery -A app.celeryapp:celery worker \
  -Q default \
  --loglevel=info \
  --concurrency=2 \
  --max-tasks-per-child=50 \
  --max-memory-per-child=1500000 \
  -n default@%h"

BULK_CMD="celery -A app.celeryapp:celery worker \
  -Q bulk \
  --loglevel=info \
  --concurrency=2 \
  --max-tasks-per-child=50 \
  --max-memory-per-child=1500000 \
  -n bulk@%h"

uv run --with watchfiles watchfiles --filter python "$DEFAULT_CMD" /app/app &
uv run --with watchfiles watchfiles --filter python "$BULK_CMD" /app/app &

wait -n
kill 0
