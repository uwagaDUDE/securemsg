import os
import sys

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_messenger.db"

from backend.app.database import engine, init_db
from backend.app.main import app
from backend.app.routers.auth import _limiter as auth_limiter
from backend.app.routers.permissions import _limiter as perm_limiter


def _reset_limiters():
    auth_limiter._store.clear()
    auth_limiter._login_failures.clear()
    auth_limiter._login_blocks.clear()
    perm_limiter._store.clear()
    perm_limiter._login_failures.clear()
    perm_limiter._login_blocks.clear()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    _reset_limiters()
    await init_db()
    yield
    _reset_limiters()
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = OFF"))
        await conn.execute(text("DELETE FROM message_reactions"))
        await conn.execute(text("DELETE FROM message_visibility"))
        await conn.execute(text("DELETE FROM shared_keys"))
        await conn.execute(text("DELETE FROM key_requests"))
        await conn.execute(text("DELETE FROM permissions"))
        await conn.execute(text("DELETE FROM blocks"))
        await conn.execute(text("DELETE FROM channel_subscribers"))
        await conn.execute(text("DELETE FROM group_shared_keys"))
        await conn.execute(text("DELETE FROM group_bans"))
        await conn.execute(text("DELETE FROM group_members"))
        await conn.execute(text("DELETE FROM messages"))
        await conn.execute(text("DELETE FROM refresh_tokens"))
        await conn.execute(text("DELETE FROM push_subscriptions"))
        await conn.execute(text("DELETE FROM attachments"))
        await conn.execute(text("DELETE FROM channels"))
        await conn.execute(text("DELETE FROM group_chats"))
        await conn.execute(text("DELETE FROM users"))
        await conn.execute(text("PRAGMA foreign_keys = ON"))


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "alice",
        "password": "Pass1234",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["access_token"], "refresh_token": data["refresh_token"], "user_id": data["user_id"], "username": "alice"}


@pytest_asyncio.fixture
async def registered_user_alice(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "socket_alice",
        "password": "Pass1234",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["access_token"], "refresh_token": data["refresh_token"], "user_id": data["user_id"], "username": "socket_alice"}


@pytest_asyncio.fixture
async def registered_user_bob(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "socket_bob",
        "password": "Pass4567",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["access_token"], "refresh_token": data["refresh_token"], "user_id": data["user_id"], "username": "socket_bob"}


@pytest_asyncio.fixture
async def registered_user_charlie(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "socket_charlie",
        "password": "Pass7890",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["access_token"], "refresh_token": data["refresh_token"], "user_id": data["user_id"], "username": "socket_charlie"}


@pytest_asyncio.fixture
async def approved_pair_alice_bob(client: AsyncClient, registered_user_alice, registered_user_bob):
    """Create an approved permission between alice->bob and return both users."""
    # bob requests alice
    await client.post("/api/permissions/request/" + str(registered_user_alice["user_id"]), headers={
        "Authorization": f"Bearer {registered_user_bob['token']}",
    })
    # alice approves
    r = await client.get("/api/permissions/incoming", headers={
        "Authorization": f"Bearer {registered_user_alice['token']}",
    })
    inc = r.json()
    await client.post(f"/api/permissions/{inc[0]['id']}/approve", headers={
        "Authorization": f"Bearer {registered_user_alice['token']}",
    })
    return registered_user_alice, registered_user_bob
