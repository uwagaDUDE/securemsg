from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        from . import models
        await conn.run_sync(Base.metadata.create_all)

    # migrate existing databases — add missing columns
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        cols = {row[1] for row in result}
        if "is_read" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN is_read BOOLEAN DEFAULT 0"))
        if "type" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN type VARCHAR(16) DEFAULT 'user'"))
        result2 = await conn.execute(text("PRAGMA table_info(key_requests)"))
        cols2 = {row[1] for row in result2}
        if "requester_id" not in cols2:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS key_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_id INTEGER NOT NULL REFERENCES users(id),
                    target_id INTEGER NOT NULL REFERENCES users(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # migrate existing databases — add online status columns
    async with engine.begin() as conn:
        result3 = await conn.execute(text("PRAGMA table_info(users)"))
        cols3 = {row[1] for row in result3}
        if "last_seen" not in cols3:
            await conn.execute(text("ALTER TABLE users ADD COLUMN last_seen DATETIME"))
        if "is_online" not in cols3:
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_online BOOLEAN DEFAULT 0"))
