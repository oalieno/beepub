import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import all models to register them with Base metadata
import app.models  # noqa: F401
from alembic import context
from app.config import settings
from app.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """What a comparison of the models with the database looks at.

    Tables and columns: all of them, both ways — a model without its
    migration, or a migration without its model, is a mistake.

    Indexes and unique constraints are written in the migrations, where
    their operator classes, expressions and sort orders can be said; the
    models do not repeat them. One the database has and the models do not
    is therefore expected, and is not offered for removal. (One a model
    declares is still compared.)
    """
    if type_ in ("index", "unique_constraint") and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
