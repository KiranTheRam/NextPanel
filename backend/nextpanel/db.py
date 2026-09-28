import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import config

engine = create_async_engine(config.db_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    # With WAL (enabled once per file by migrations.migrate), NORMAL is still
    # corruption-safe and avoids an fsync on every commit.
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """For background jobs that need their own session."""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from . import migrations, models  # noqa: F401 — register mappings

    config.data_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(migrations.migrate, config.db_path)
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
        # A new database was just created at the current schema; an upgraded
        # one is already stamped by migrate().
        version = (await conn.exec_driver_sql("PRAGMA user_version")).scalar_one()
        if version < migrations.LATEST:
            await conn.exec_driver_sql(f"PRAGMA user_version = {migrations.LATEST}")
