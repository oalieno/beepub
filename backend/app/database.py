from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


def create_task_session() -> async_sessionmaker[AsyncSession]:
    """Create a fresh engine+sessionmaker for use inside Celery tasks.

    Each ``asyncio.run()`` call in a Celery worker gets its own event loop,
    so we must not reuse the global engine (whose pool is bound to a
    different loop).  This helper creates a throwaway engine with a small
    pool that is safe to use inside a single ``asyncio.run()`` invocation.
    """
    task_engine = create_async_engine(
        settings.database_url, echo=False, pool_size=1, max_overflow=0,
    )
    return async_sessionmaker(
        task_engine, class_=AsyncSession, expire_on_commit=False,
    )
