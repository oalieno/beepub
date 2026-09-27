#!/bin/sh
set -e

# Before anything writes to /data (including SECRET_KEY generation): move
# pre-0.14 installs' per-kind volumes into the single data volume.
uv run python scripts/merge_data_volumes.py

# Convert postgresql+asyncpg:// to postgresql:// for psql.
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
