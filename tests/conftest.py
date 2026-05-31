import os
import sys

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_messenger.db"

from backend.app.database import engine, init_db
from backend.app.main import app


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM key_requests"))
        await conn.execute(text("DELETE FROM permissions"))
        await conn.execute(text("DELETE FROM shared_keys"))
        await conn.execute(text("DELETE FROM messages"))
        await conn.execute(text("DELETE FROM users"))


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "alice",
        "password": "pass123",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["token"], "user_id": data["user_id"], "username": "alice"}


@pytest_asyncio.fixture
async def registered_user_alice(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "socket_alice",
        "password": "pass123",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["token"], "user_id": data["user_id"], "username": "socket_alice"}


@pytest_asyncio.fixture
async def registered_user_bob(client: AsyncClient):
    r = await client.post("/api/auth/register", json={
        "username": "socket_bob",
        "password": "pass456",
        "public_key": "AQID",
        "encrypted_private_key": "BAUG",
        "broadcast_key": "BwgJ",
    })
    assert r.status_code == 200
    data = r.json()
    return {"token": data["token"], "user_id": data["user_id"], "username": "socket_bob"}


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
