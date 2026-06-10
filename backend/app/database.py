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


async def init_db():
    async with engine.begin() as conn:
        from . import models
        await conn.run_sync(Base.metadata.create_all)

    # ── migrate existing databases — add missing columns ──
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        cols = {row[1] for row in result}
        if "is_read" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN is_read BOOLEAN DEFAULT 0"))
        if "read_at" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN read_at DATETIME"))
        if "type" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN type VARCHAR(16) DEFAULT 'user'"))
        if "edited_at" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN edited_at DATETIME"))
        if "deleted_at" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN deleted_at DATETIME"))
        if "channel_id" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN channel_id INTEGER REFERENCES channels(id)"))
        if "group_chat_id" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN group_chat_id INTEGER REFERENCES group_chats(id)"))
        if "content" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN content TEXT"))
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

    # ── CRITICAL: make receiver_id nullable for groups/channels ──
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        rows = [(r[1], r[3]) for r in result]  # (name, notnull)
        receiver_notnull = next((n for name, n in rows if name == "receiver_id"), 0)
        if receiver_notnull == 1:
            print("[migrate] making receiver_id nullable...")
            old_cols = [name for name, _ in rows]
            new_cols = ["id", "sender_id", "receiver_id", "channel_id", "group_chat_id",
                        "type", "encrypted_content", "content", "is_read",
                        "edited_at", "deleted_at", "created_at"]
            # map old columns to new, use NULL for missing ones
            sel_parts = []
            for nc in new_cols:
                if nc in old_cols:
                    sel_parts.append(nc)
                else:
                    sel_parts.append("NULL")
            sel = ", ".join(sel_parts)

            await conn.execute(text("PRAGMA foreign_keys = OFF"))
            await conn.execute(text(f"""
                CREATE TABLE messages_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    receiver_id INTEGER REFERENCES users(id),
                    channel_id INTEGER REFERENCES channels(id),
                    group_chat_id INTEGER REFERENCES group_chats(id),
                    type VARCHAR(16) DEFAULT 'user',
                    encrypted_content TEXT,
                    content TEXT,
                    is_read BOOLEAN DEFAULT 0,
                    edited_at DATETIME,
                    deleted_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(f"INSERT INTO messages_new SELECT {sel} FROM messages"))
            await conn.execute(text("DROP TABLE messages"))
            await conn.execute(text("ALTER TABLE messages_new RENAME TO messages"))
            await conn.execute(text("PRAGMA foreign_keys = ON"))
            print("[migrate] receiver_id is now nullable")

    # ── Recover scrambled data from bad SELECT * migration ──
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM messages WHERE typeof(channel_id) = 'text'"))
        scrambled = result.scalar()
        if scrambled and scrambled > 0:
            print(f"[migrate] recovering {scrambled} scrambled rows...")
            await conn.execute(text("""
                UPDATE messages SET
                  type = 'user',
                  is_read = 0,
                  created_at = COALESCE(created_at, encrypted_content),
                  encrypted_content = channel_id,
                  channel_id = NULL,
                  group_chat_id = NULL,
                  content = NULL,
                  edited_at = NULL,
                  deleted_at = NULL
                WHERE typeof(channel_id) = 'text'
            """))
            print("[migrate] scrambled data recovered")

            # ── Fix rows broken by PREVIOUS bad recovery (created_at=0/1) ──
            await conn.execute(text("""
                UPDATE messages SET
                  created_at = '1970-01-01T00:00:00+00:00',
                  encrypted_content = CASE
                    WHEN encrypted_content IN ('user', 'system') THEN '[encrypted]'
                    ELSE encrypted_content
                  END
                WHERE typeof(created_at) = 'integer' AND created_at IN (0, 1) AND deleted_at IS NULL
            """))
            print("[migrate] bad recovery rows fixed")
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        cols = {row[1] for row in result}
        if "is_read" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN is_read BOOLEAN DEFAULT 0"))
        if "read_at" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN read_at DATETIME"))
        if "type" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN type VARCHAR(16) DEFAULT 'user'"))
        if "edited_at" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN edited_at DATETIME"))
        if "deleted_at" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN deleted_at DATETIME"))
        if "channel_id" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN channel_id INTEGER REFERENCES channels(id)"))
        if "group_chat_id" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN group_chat_id INTEGER REFERENCES group_chats(id)"))
        if "content" not in cols:
            await conn.execute(text("ALTER TABLE messages ADD COLUMN content TEXT"))
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

    # ── migrate — group_bans table
    async with engine.begin() as conn:
        result6 = await conn.execute(text("PRAGMA table_info(group_bans)"))
        cols6 = {row[1] for row in result6}
        if not cols6:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS group_bans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL REFERENCES group_chats(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_id, user_id)
                )
            """))
            print("[migrate] group_bans table created")

    # migrate — attachments table
    async with engine.begin() as conn:
        result5 = await conn.execute(text("PRAGMA table_info(attachments)"))
        cols5 = {row[1] for row in result5}
        if not cols5:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER REFERENCES messages(id),
                    uploader_id INTEGER NOT NULL REFERENCES users(id),
                    encrypted_blob BLOB NOT NULL,
                    mime_type VARCHAR(32) DEFAULT 'image/jpeg',
                    original_size INTEGER DEFAULT 0,
                    compressed_size INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

    # ── fix datetime columns: convert integer/NULL created_at to proper ISO strings ──
    async with engine.begin() as conn:
        # Fix messages.created_at: integer (0/1 from scrambled data) or NULL → epoch
        await conn.execute(text("""
            UPDATE messages SET created_at = '1970-01-01T00:00:00+00:00'
            WHERE created_at IS NULL OR typeof(created_at) != 'text'
        """))
        # Fix edited_at / deleted_at: NULL is fine for these nullable columns,
        # but non-text values must be converted
        await conn.execute(text("""
            UPDATE messages SET edited_at = NULL
            WHERE edited_at IS NOT NULL AND typeof(edited_at) != 'text'
        """))
        await conn.execute(text("""
            UPDATE messages SET deleted_at = NULL
            WHERE deleted_at IS NOT NULL AND typeof(deleted_at) != 'text'
        """))
        # Fix created_at in all other main tables
        for tbl in ("users", "attachments", "message_reactions", "message_visibility",
                     "blocks", "channels", "channel_subscribers", "group_chats",
                     "group_members", "group_shared_keys", "group_bans", "key_requests",
                     "push_subscriptions", "permissions"):
            await conn.execute(text(f"""
                UPDATE {tbl} SET created_at = '1970-01-01T00:00:00+00:00'
                WHERE created_at IS NULL OR typeof(created_at) != 'text'
            """))
        print("[migrate] datetime columns normalized")

    # ── updates.db ──
    async with engine_updates.begin() as conn:
        await conn.run_sync(BaseUpdates.metadata.create_all)
