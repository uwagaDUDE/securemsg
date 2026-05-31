import asyncio
import base64
import os
import sys
import threading
from typing import Any

import pytest
import socketio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.auth import create_token, decode_token

pytestmark = pytest.mark.asyncio

SERVER_PORT = 18767
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"


@pytest.fixture(scope="session")
def _run_server():
    import uvicorn
    from backend.app.main import socket_app

    config = uvicorn.Config(socket_app, host="127.0.0.1", port=SERVER_PORT, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import time
    time.sleep(1.0)

    yield

    server.should_exit = True
    thread.join(timeout=5)


async def _connect(token):
    c = socketio.AsyncSimpleClient()
    await c.connect(SERVER_URL, auth={"token": token}, transports=["websocket"])
    return c


async def _collect_events(client: socketio.AsyncSimpleClient, count: int, timeout: float = 1.0):
    """Receive `count` events from client with a timeout. Returns list of (event_name, data)."""
    events = []
    try:
        for _ in range(count):
            event = await asyncio.wait_for(client.receive(), timeout=timeout)
            events.append(event)
    except (asyncio.TimeoutError, socketio.exceptions.ConnectionError):
        pass
    return events


# ── Token unit tests ──


class TestTokenUnit:
    async def test_valid_token_can_be_decoded(self, registered_user_alice):
        token = registered_user_alice["token"]
        payload = decode_token(token)
        assert payload["user_id"] == registered_user_alice["user_id"]

    async def test_invalid_token_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            decode_token("invalid.token.here")


# ── Socket Auth ──


class TestSocketAuth:
    async def test_valid_token_connects(self, _run_server, registered_user_alice):
        c = await _connect(registered_user_alice["token"])
        assert c.connected
        await c.disconnect()

    async def test_invalid_token_rejected(self, _run_server):
        c = socketio.AsyncSimpleClient()
        with pytest.raises(Exception):
            await c.connect(SERVER_URL, auth={"token": "invalid.token.here"}, transports=["websocket"])

    async def test_missing_token_rejected(self, _run_server):
        c = socketio.AsyncSimpleClient()
        with pytest.raises(Exception):
            await c.connect(SERVER_URL, auth={}, transports=["websocket"])

    async def test_nonexistent_user_rejected(self, _run_server):
        token = create_token(99999)
        c = socketio.AsyncSimpleClient()
        with pytest.raises(Exception):
            await c.connect(SERVER_URL, auth={"token": token}, transports=["websocket"])

    async def test_disconnect_cleans_session(self, _run_server, registered_user_alice):
        c = await _connect(registered_user_alice["token"])
        assert c.connected
        await c.disconnect()
        assert not c.connected


# ── Message Flow via Socket ──


class TestMessageFlow:
    async def test_send_and_receive_message(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])
        bob_sio = await _connect(bob["token"])

        await alice_sio.emit("join_room", {"target_id": bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        encrypted = base64.b64encode(b"hello bob").decode()
        await alice_sio.emit("send_message", {
            "receiver_id": bob["user_id"],
            "encrypted_content": encrypted,
        })

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "new_message"
        assert data["sender_id"] == alice["user_id"]
        assert data["receiver_id"] == bob["user_id"]
        assert data["encrypted_content"] == encrypted

        await alice_sio.disconnect()
        await bob_sio.disconnect()

    async def test_send_without_permission_blocked(self, _run_server, client, registered_user_alice, registered_user_bob):
        alice_sio = await _connect(registered_user_alice["token"])

        encrypted = base64.b64encode(b"blocked").decode()
        await alice_sio.emit("send_message", {
            "receiver_id": registered_user_bob["user_id"],
            "encrypted_content": encrypted,
        })
        await asyncio.sleep(0.3)

        r = await client.get(
            f"/api/messages/{registered_user_bob['user_id']}",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 0

        await alice_sio.disconnect()

    async def test_message_persists_in_db(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])

        encrypted = base64.b64encode(b"persist me").decode()
        await alice_sio.emit("send_message", {
            "receiver_id": bob["user_id"],
            "encrypted_content": encrypted,
        })
        await asyncio.sleep(0.2)

        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        msgs = r.json()
        user_msgs = [m for m in msgs if m["type"] == "user"]
        assert len(user_msgs) >= 1
        assert user_msgs[-1]["encrypted_content"] == encrypted

        await alice_sio.disconnect()

    async def test_typing_indicator(self, _run_server, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])
        bob_sio = await _connect(bob["token"])

        await alice_sio.emit("join_room", {"target_id": bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        await alice_sio.emit("typing", {
            "receiver_id": bob["user_id"],
            "is_typing": True,
        })

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "typing"
        assert data["is_typing"] is True
        assert data["user_id"] == alice["user_id"]

        await alice_sio.disconnect()
        await bob_sio.disconnect()

    async def test_multiple_messages(self, _run_server, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])
        bob_sio = await _connect(bob["token"])

        await alice_sio.emit("join_room", {"target_id": bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        for i in range(3):
            enc = base64.b64encode(f"msg_{i}".encode()).decode()
            await alice_sio.emit("send_message", {
                "receiver_id": bob["user_id"],
                "encrypted_content": enc,
            })
            await asyncio.sleep(0.05)

        events = await _collect_events(bob_sio, count=3, timeout=2.0)
        assert len(events) == 3
        for event_name, data in events:
            assert event_name == "new_message"

        await alice_sio.disconnect()
        await bob_sio.disconnect()


# ── Key Sharing ──


class TestKeySharing:
    async def test_share_key_event(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])
        bob_sio = await _connect(bob["token"])

        await alice_sio.emit("join_room", {"target_id": bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        encrypted_key = base64.b64encode(b"encrypted_broadcast_key_data").decode()
        await alice_sio.emit("share_key", {
            "target_id": bob["user_id"],
            "encrypted_broadcast_key": encrypted_key,
        })

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "key_shared"
        assert data["owner_id"] == alice["user_id"]

        r = await client.get(
            f"/api/messages/{alice['user_id']}/shared-key",
            headers={"Authorization": f"Bearer {bob['token']}"},
        )
        assert r.status_code == 200
        result = r.json()
        assert result is not None
        assert result["encrypted_broadcast_key"] == encrypted_key

        r = await client.get(
            f"/api/messages/{bob['user_id']}/has-my-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.json() is True

        await alice_sio.disconnect()
        await bob_sio.disconnect()

    async def test_share_key_creates_system_message(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])

        encrypted_key = base64.b64encode(b"key_data").decode()
        await alice_sio.emit("share_key", {
            "target_id": bob["user_id"],
            "encrypted_broadcast_key": encrypted_key,
        })
        await asyncio.sleep(0.3)

        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        msgs = r.json()
        system_msgs = [m for m in msgs if m["type"] == "system"]
        assert any("shared their key" in m["encrypted_content"] for m in system_msgs)

        await alice_sio.disconnect()

    async def test_share_key_without_permission_blocked(self, _run_server, registered_user_alice, registered_user_bob, client):
        alice_sio = await _connect(registered_user_alice["token"])

        encrypted_key = base64.b64encode(b"blocked").decode()
        await alice_sio.emit("share_key", {
            "target_id": registered_user_bob["user_id"],
            "encrypted_broadcast_key": encrypted_key,
        })
        await asyncio.sleep(0.2)

        r = await client.get(
            f"/api/messages/{registered_user_bob['user_id']}/has-my-key",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.json() is False

        await alice_sio.disconnect()

    async def test_revoke_key_via_http(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])

        encrypted_key = base64.b64encode(b"key_to_revoke").decode()
        await alice_sio.emit("share_key", {
            "target_id": bob["user_id"],
            "encrypted_broadcast_key": encrypted_key,
        })
        await asyncio.sleep(0.2)

        r = await client.delete(
            f"/api/messages/{bob['user_id']}/shared-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        r = await client.get(
            f"/api/messages/{bob['user_id']}/has-my-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.json() is False

        r = await client.get(
            f"/api/messages/{alice['user_id']}/shared-key",
            headers={"Authorization": f"Bearer {bob['token']}"},
        )
        assert r.json() is None

        await alice_sio.disconnect()

    async def test_revoke_key_emits_event(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        bob_sio = await _connect(bob["token"])

        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        r = await client.delete(
            f"/api/messages/{bob['user_id']}/shared-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "key_revoked"
        assert data["owner_id"] == alice["user_id"]

        await bob_sio.disconnect()


# ── Permission via Socket ──


class TestPermissionSocket:
    async def test_permission_request_event(self, _run_server, registered_user_alice, registered_user_bob):
        bob_sio = await _connect(registered_user_bob["token"])

        alice_sio = await _connect(registered_user_alice["token"])

        await alice_sio.emit("join_room", {"target_id": registered_user_bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": registered_user_alice["user_id"]})
        await asyncio.sleep(0.1)

        await alice_sio.emit("permission_requested", {
            "owner_id": registered_user_bob["user_id"],
        })

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "permission_request"
        assert data["requester_id"] == registered_user_alice["user_id"]
        assert data["requester_username"] == registered_user_alice["username"]

        await alice_sio.disconnect()
        await bob_sio.disconnect()

    async def test_permission_response_event(self, _run_server, registered_user_alice, registered_user_bob):
        alice_sio = await _connect(registered_user_alice["token"])

        bob_sio = await _connect(registered_user_bob["token"])

        await alice_sio.emit("join_room", {"target_id": registered_user_bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": registered_user_alice["user_id"]})
        await asyncio.sleep(0.1)

        await bob_sio.emit("permission_responded", {
            "requester_id": registered_user_alice["user_id"],
            "status": "approved",
        })

        events = await _collect_events(alice_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "permission_response"
        assert data["status"] == "approved"
        assert data["requester_id"] == registered_user_alice["user_id"]

        await alice_sio.disconnect()
        await bob_sio.disconnect()


# ── Key Request ──


class TestKeyRequestSocket:
    async def test_request_key_emits_event(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob

        bob_sio = await _connect(bob["token"])

        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1
        event_name, data = events[0]
        assert event_name == "key_requested"
        assert data["requester_id"] == alice["user_id"]
        assert data["requester_username"] == alice["username"]

        await bob_sio.disconnect()

    async def test_request_key_creates_system_message(self, _run_server, approved_pair_alice_bob, client):
        alice, bob = approved_pair_alice_bob
        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        msgs = r.json()
        system_msgs = [m for m in msgs if m["type"] == "system"]
        assert any("requested your key" in m["encrypted_content"] for m in system_msgs)


# ── Real-time key request delivery test ──


class TestRealTimeKeyRequest:
    async def test_key_request_received_in_realtime(self, _run_server, approved_pair_alice_bob, client):
        """Verify that key_requested event is delivered via socket in real time
        (no page refresh needed)."""
        alice, bob = approved_pair_alice_bob

        bob_sio = await _connect(bob["token"])
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1, (
            "key_requested event was NOT received in real time. "
            "User would need to refresh the page to see it."
        )
        event_name, _ = events[0]
        assert event_name == "key_requested"

        await bob_sio.disconnect()

    async def test_key_request_sender_also_receives_event(self, _run_server, approved_pair_alice_bob, client):
        """The sender (Alice) must also receive key_requested in real time
        so her chat updates without page refresh."""
        alice, bob = approved_pair_alice_bob

        alice_sio = await _connect(alice["token"])
        bob_sio = await _connect(bob["token"])

        await alice_sio.emit("join_room", {"target_id": bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        # Bob should receive it
        bob_events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(bob_events) == 1
        assert bob_events[0][0] == "key_requested"

        # Alice should ALSO receive it (shared room)
        alice_events = await _collect_events(alice_sio, count=1, timeout=2.0)
        assert len(alice_events) == 1, (
            "Sender (Alice) did NOT receive key_requested event. "
            "She would need to refresh the page."
        )
        assert alice_events[0][0] == "key_requested"
        assert alice_events[0][1]["requester_id"] == alice["user_id"]

        await alice_sio.disconnect()
        await bob_sio.disconnect()

    async def test_key_shared_received_in_realtime(self, _run_server, approved_pair_alice_bob, client):
        """Verify that key_shared event is delivered via socket in real time."""
        alice, bob = approved_pair_alice_bob

        bob_sio = await _connect(bob["token"])

        encrypted_key = base64.b64encode(b"bcast").decode()
        await asyncio.sleep(0.05)

        alice_sio = await _connect(alice["token"])
        await alice_sio.emit("join_room", {"target_id": bob["user_id"]})
        await bob_sio.emit("join_room", {"target_id": alice["user_id"]})
        await asyncio.sleep(0.1)

        await alice_sio.emit("share_key", {
            "target_id": bob["user_id"],
            "encrypted_broadcast_key": encrypted_key,
        })

        events = await _collect_events(bob_sio, count=1, timeout=2.0)
        assert len(events) == 1, (
            "key_shared event was NOT received in real time."
        )
        event_name, data = events[0]
        assert event_name == "key_shared"
        assert data["owner_id"] == alice["user_id"]

        await alice_sio.disconnect()
        await bob_sio.disconnect()
