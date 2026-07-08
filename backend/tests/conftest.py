"""Shared test fixtures — set required env vars before any app imports."""

import os
import tempfile

# Must be set before app.config.Settings() is instantiated on import
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

# Keep uploads/covers written by integration tests out of /data and inside
# a throwaway directory instead.
_storage_root = tempfile.mkdtemp(prefix="beepub-test-storage-")
os.environ.setdefault("BOOKS_DIR", os.path.join(_storage_root, "books"))
os.environ.setdefault("COVERS_DIR", os.path.join(_storage_root, "covers"))
os.environ.setdefault("ILLUSTRATIONS_DIR", os.path.join(_storage_root, "illustrations"))
