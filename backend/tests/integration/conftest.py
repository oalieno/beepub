"""Real-service integration fixtures.

Tests under this directory run the actual FastAPI app against a real
Postgres (pgvector) and Redis — no mocked sessions. The suite:

- refuses to run unless the configured database is literally named
  ``test`` (the schema is dropped and rebuilt from migrations)
- skips entirely when the services are unreachable

CI provides the services (see .github/workflows/ci.yml). Locally::

    docker compose -f docker-compose.test.yml up -d
    cd backend
    DATABASE_URL=postgresql+asyncpg://test:test@<docker-host>:5433/test \\
    REDIS_URL=redis://<docker-host>:6380 uv run pytest tests/integration

``<docker-host>`` is wherever your docker daemon runs — localhost, or the
NAS IP when using a remote docker context.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]

ADMIN_CREDENTIALS = {"username": "admin", "password": "admin-password-123"}
USER_CREDENTIALS = {"username": "reader", "password": "reader-password-123"}


async def _ping_services() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        await redis.ping()
    finally:
        await redis.aclose()


# migrate.sh pre-creates these via psql before alembic runs (migration 001
# references them with create_type=False); mirror that here.
_ENUM_TYPES = {
    "userrole": ("admin", "user"),
    "libraryvisibility": ("public", "private"),
    "metadatasource": ("goodreads", "readmoo", "kobo_tw"),
}


async def _drop_schema() -> None:
    engine = create_async_engine(
        settings.database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            for name, values in _ENUM_TYPES.items():
                labels = ", ".join(f"'{v}'" for v in values)
                await conn.execute(text(f"CREATE TYPE {name} AS ENUM ({labels})"))
    finally:
        await engine.dispose()


async def _table_names() -> list[str]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
            return [row[0] for row in result]
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database() -> list[str]:
    """Rebuild the test database schema from migrations, once per session.

    Returns the list of application tables (used for per-test truncation).
    Running the real migration chain here means every integration run also
    verifies that ``alembic upgrade head`` works from scratch.
    """
    db_name = make_url(settings.database_url).database
    if db_name != "test":
        raise RuntimeError(
            "Integration tests DROP SCHEMA public on the configured database; "
            f"refusing to run against {db_name!r}. Point DATABASE_URL at a "
            "throwaway database named 'test'."
        )

    try:
        asyncio.run(_ping_services())
    except Exception as exc:
        pytest.skip(
            f"Postgres/Redis not reachable ({exc!r}) — start them with "
            "`docker compose -f docker-compose.test.yml up -d`"
        )

    asyncio.run(_drop_schema())
    # The alembic CLI, not the API: backend/alembic/ (the migrations
    # directory) shadows the installed package on pytest's sys.path. The
    # CLI script lives next to the running interpreter's binary.
    alembic = Path(sys.executable).parent / "alembic"
    result = subprocess.run(
        [str(alembic), "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed:\n{result.stderr}")
    return asyncio.run(_table_names())


@pytest.fixture(scope="session", autouse=True)
def _disable_rate_limits():
    # Login/register are limited per client IP, and every request from the
    # ASGI test client shares one IP — a normal-sized run would trip 429s.
    from app.rate_limit import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
async def clean_state(database: list[str]):
    """Empty every table and Redis before each test.

    The app engine is disposed afterwards because pytest-asyncio gives each
    test its own event loop, and pooled asyncpg connections are bound to
    the loop they were created on.
    """
    from app.database import engine

    tables = ", ".join(f'"{name}"' for name in database)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()

    yield
    await engine.dispose()


def _api_client() -> AsyncClient:
    from app.main import app

    # https so the client sends the auth cookies back (they are Secure).
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")


async def register_and_login(client: AsyncClient, credentials: dict[str, str]) -> dict:
    response = await client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201, response.text
    user = response.json()
    response = await client.post("/api/auth/login", data=credentials)
    assert response.status_code == 200, response.text
    return user


@pytest.fixture
async def client():
    """Anonymous client against the real app (cookie jar included)."""
    async with _api_client() as c:
        yield c


@pytest.fixture
async def admin_client():
    """Client logged in as the instance admin (the first registered user)."""
    async with _api_client() as c:
        await register_and_login(c, ADMIN_CREDENTIALS)
        yield c


@pytest.fixture
async def user_client(admin_client: AsyncClient):
    """Client logged in as a regular (non-admin) user, created by the admin."""
    response = await admin_client.post("/api/admin/users", json=USER_CREDENTIALS)
    assert response.status_code == 201, response.text
    async with _api_client() as c:
        response = await c.post("/api/auth/login", data=USER_CREDENTIALS)
        assert response.status_code == 200, response.text
        yield c
