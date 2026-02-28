#!/bin/sh
set -e

# In dev mode, ensure deps are installed (venv volume may be empty)
if [ "$DEV" = "1" ]; then
    echo "Installing dependencies..."
    uv sync --frozen --no-install-project
fi

# Convert postgresql+asyncpg:// → postgresql:// for psql
PSQL_URL=$(echo "$DATABASE_URL" | sed 's/+asyncpg//')

echo "Creating enum types via psql..."
psql "$PSQL_URL" <<'SQL'
DO $$ BEGIN
    CREATE TYPE userrole AS ENUM ('admin', 'user');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE libraryvisibility AS ENUM ('public', 'private');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE metadatasource AS ENUM ('goodreads', 'readmoo', 'kobo_tw');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
SQL

echo "Running Alembic migrations..."
uv run alembic upgrade head

if [ "$DEV" = "1" ]; then
    echo "Starting FastAPI dev server (reload enabled)..."
    exec uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000
else
    echo "Starting uvicorn..."
    exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
