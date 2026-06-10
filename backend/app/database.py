import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)

_UPDATES_DB = DATABASE_URL.replace("messenger.db", "updates.db")
engine_updates = create_async_engine(_UPDATES_DB, echo=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


@event.listens_for(engine_updates.sync_engine, "connect")
def _set_sqlite_pragma_updates(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async_session_updates = async_sessionmaker(engine_updates, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class BaseUpdates(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def get_db_updates():
    async with async_session_updates() as session:
        yield session


async def run_migrations():
    """Run Alembic migrations programmatically.

    alembic.command.upgrade is synchronous and internally calls asyncio.run(),
    so it must run in a worker thread to avoid nested-event-loop conflicts.
    """
    from alembic import command
    from alembic.config import Config

    def _sync():
        alembic_cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")

    await asyncio.to_thread(_sync)


async def init_db():
    await run_migrations()

    # Initialize updates.db (no migrations needed, just create tables)
    async with engine_updates.begin() as conn:
        from . import models
        await conn.run_sync(BaseUpdates.metadata.create_all)
