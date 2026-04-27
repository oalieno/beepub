#!/bin/sh
set -e

# In dev mode, ensure deps are installed (venv volume may be empty)
if [ "$DEV" = "1" ]; then
    echo "Installing dependencies..."
    uv sync --frozen --no-install-project
fi

if [ "$DEV" = "1" ]; then
    echo "Starting FastAPI dev server (reload enabled)..."
    exec uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000
else
    echo "Starting uvicorn..."
    exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
