#!/bin/bash
# Start two celery workers: one for default queue, one for bulk queue.
# Both run in the same container. SIGTERM/SIGINT will kill both.

set -e

# Worker 1: default queue (user-triggered tasks, low latency)
uv run celery -A app.celeryapp:celery worker \
  -Q default \
  --loglevel=info \
  --concurrency=2 \
  --max-tasks-per-child=50 \
  --max-memory-per-child=1500000 \
  -n default@%h &

# Worker 2: bulk queue (backfill jobs, high volume)
uv run celery -A app.celeryapp:celery worker \
  -Q bulk \
  --loglevel=info \
  --concurrency=2 \
  --max-tasks-per-child=50 \
  --max-memory-per-child=1500000 \
  -n bulk@%h &

# Wait for either to exit — if one dies, kill the other
wait -n
kill 0
