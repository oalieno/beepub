from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def create_task_engine() -> AsyncIterator[
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
]:
    """Create a fresh engine+sessionmaker for use inside Celery tasks.

    Each ``asyncio.run()`` call in a Celery worker gets its own event loop,
    so we must not reuse the global engine (whose pool is bound to a
    different loop).  This context manager creates a throwaway engine with a
    small pool and **disposes it on exit** to prevent connection/memory leaks.
    """
    task_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=1,
    )
    session_factory = async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        yield task_engine, session_factory
    finally:
        await task_engine.dispose()
