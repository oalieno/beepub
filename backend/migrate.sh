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
-- Only a database that has never been migrated needs this one: migration
-- 001 expects it, 054 removes it for good.
DO $$ BEGIN
    IF to_regclass('public.alembic_version') IS NULL THEN
        CREATE TYPE metadatasource AS ENUM ('goodreads', 'readmoo', 'kobo_tw');
    END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
SQL

echo "Running Alembic migrations..."
uv run alembic upgrade head

# Earlier versions of this script made the type above on every start, so
# an upgraded install carries one that nothing uses. (In use — a database
# held below 054 — it is left alone.)
psql "$PSQL_URL" <<'SQL'
DO $$ BEGIN
    DROP TYPE IF EXISTS metadatasource;
EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
END $$;
SQL
