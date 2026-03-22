"""Shared test fixtures — set required env vars before any app imports."""

import os

# Must be set before app.config.Settings() is instantiated on import
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

