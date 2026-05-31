import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.auth import create_token

pytestmark = pytest.mark.asyncio


class TestSocketAuth:
    """Test socket authentication via HTTP side effects."""

    async def test_valid_token_can_be_decoded(self, registered_user_alice):
        token = registered_user_alice["token"]
        from backend.app.auth import decode_token
        payload = decode_token(token)
        assert payload["user_id"] == registered_user_alice["user_id"]

    async def test_invalid_token_raises(self):
        from backend.app.auth import decode_token
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            decode_token("invalid.token.here")


class TestMessageFlow:
    """Test message flow via HTTP + verify persistence."""

    async def test_system_message_on_revoke(self, client, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob

        # send a message to create history
        await client.post(f"/api/permissions/request/{bob['user_id']}", headers={
            "Authorization": f"Bearer {alice['token']}",
        })

        # revoke key — triggers system message persistence
        r = await client.delete(
            f"/api/messages/{bob['user_id']}/shared-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        # check history for system message about revoke
        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        msgs = r.json()
        system_msgs = [m for m in msgs if m.get("type") == "system"]
        assert len(system_msgs) >= 1
        assert "revoked" in system_msgs[-1]["encrypted_content"]

    async def test_message_history_includes_type(self, client, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        for msg in r.json():
            assert "type" in msg, f"message {msg['id']} missing 'type' field"
            assert msg["type"] in ("user", "system")


class TestPermissionFlow:
    """Test permission request/approve/reject flow."""

    async def test_request_approve_flow(self, client, registered_user_alice, registered_user_bob):
        # bob requests alice
        r = await client.post(
            f"/api/permissions/request/{registered_user_alice['user_id']}",
            headers={"Authorization": f"Bearer {registered_user_bob['token']}"},
        )
        assert r.status_code == 200
        perm_id = r.json()["id"]

        # alice approves
        r = await client.post(
            f"/api/permissions/{perm_id}/approve",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        # verify both see it in /approved
        r = await client.get(
            "/api/permissions/approved",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert any(p["status"] == "approved" for p in r.json())

    async def test_request_reject_cleans_shared_keys(self, client, registered_user_alice, registered_user_bob):
        # bob requests alice
        r = await client.post(
            f"/api/permissions/request/{registered_user_alice['user_id']}",
            headers={"Authorization": f"Bearer {registered_user_bob['token']}"},
        )
        perm_id = r.json()["id"]

        # alice rejects
        r = await client.post(
            f"/api/permissions/{perm_id}/reject",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


class TestUserSearch:
    """Test user search with special characters."""

    async def test_search_with_percent(self, client, registered_user_alice):
        await client.post("/api/auth/register", json={
            "username": "test%user", "password": "pass",
        })
        r = await client.get(
            "/api/users/search?q=test%25",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "test%user"

    async def test_search_with_underscore(self, client, registered_user_alice):
        await client.post("/api/auth/register", json={
            "username": "test_user", "password": "pass",
        })
        r = await client.get(
            "/api/users/search?q=test_",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "test_user"


class TestKeyRequest:
    async def test_request_key_basic(self, client, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        # verify system message was created
        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        msgs = r.json()
        system_msgs = [m for m in msgs if m["type"] == "system"]
        assert any("requested your key" in m["encrypted_content"] for m in system_msgs)

    async def test_request_key_self_not_allowed(self, client, registered_user_alice):
        r = await client.post(
            f"/api/messages/{registered_user_alice['user_id']}/request-key",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 400

    async def test_request_key_invalid_user(self, client, registered_user_alice):
        r = await client.post(
            "/api/messages/999/request-key",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 404

    async def test_request_key_rate_limit(self, client, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        # send 3 requests (should all succeed)
        for _ in range(3):
            r = await client.post(
                f"/api/messages/{bob['user_id']}/request-key",
                headers={"Authorization": f"Bearer {alice['token']}"},
            )
            assert r.status_code == 204

        # 4th should be rate limited
        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 429
        assert "3/hour" in r.json()["detail"].lower()
