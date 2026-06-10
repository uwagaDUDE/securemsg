import base64
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# ── Auth Extended (refresh, logout) ──


class TestAuthExtended:
    async def test_refresh_token(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/refresh", json={
            "refresh_token": registered_user["refresh_token"],
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_invalid_token(self, client: AsyncClient):
        r = await client.post("/api/auth/refresh", json={
            "refresh_token": "invalid.refresh.token",
        })
        assert r.status_code == 401

    async def test_logout_with_token(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/logout", json={
            "refresh_token": registered_user["refresh_token"],
        }, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    async def test_logout_without_body(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/logout", json={}, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    async def test_logout_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/auth/logout", json={})
        assert r.status_code in (401, 403)

    async def test_register_invalid_username(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "user name!", "password": "Pass1234",
        })
        assert r.status_code == 422

    async def test_register_short_username(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "ab", "password": "Pass1234",
        })
        assert r.status_code == 422


# ── Blocks ──


class TestBlocks:
    async def test_block_user(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "block_target", "password": "Pass1234",
        })
        target_id = r2.json()["user_id"]

        r = await client.post(f"/api/blocks/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

    async def test_block_self(self, client: AsyncClient, registered_user: dict):
        r = await client.post(f"/api/blocks/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_block_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/blocks/99999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_block_duplicate(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "block_dup", "password": "Pass1234",
        })
        target_id = r2.json()["user_id"]

        await client.post(f"/api/blocks/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        r = await client.post(f"/api/blocks/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

    async def test_block_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/blocks/1")
        assert r.status_code in (401, 403)

    async def test_list_blocks_empty(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/blocks", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_blocks(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "block_list", "password": "Pass1234",
        })
        target_id = r2.json()["user_id"]

        await client.post(f"/api/blocks/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        r = await client.get("/api/blocks", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        blocks = r.json()
        assert len(blocks) == 1
        assert blocks[0]["username"] == "block_list"
        assert blocks[0]["id"] == target_id
        assert "blocked_at" in blocks[0]

    async def test_list_blocks_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/blocks")
        assert r.status_code in (401, 403)

    async def test_unblock_user(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "unblock_me", "password": "Pass1234",
        })
        target_id = r2.json()["user_id"]

        await client.post(f"/api/blocks/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        r = await client.delete(f"/api/blocks/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

        r = await client.get("/api/blocks", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.json() == []

    async def test_unblock_nonexistent_block(self, client: AsyncClient, registered_user: dict):
        r = await client.delete("/api/blocks/99999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_unblock_requires_auth(self, client: AsyncClient):
        r = await client.delete("/api/blocks/1")
        assert r.status_code in (401, 403)


# ── Messages: HTTP send, edit, delete, reactions ──


class TestMessageSend:
    async def test_send_message_http(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        encrypted = base64.b64encode(b"hello via http").decode()
        r = await client.post(
            f"/api/messages/{bob['user_id']}/send",
            json={"encrypted_content": encrypted},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "message_id" in data

    async def test_send_message_self(self, client: AsyncClient, registered_user: dict):
        r = await client.post(
            f"/api/messages/{registered_user['user_id']}/send",
            json={"encrypted_content": "test"},
            headers={"Authorization": f"Bearer {registered_user['token']}"},
        )
        assert r.status_code == 400

    async def test_send_message_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.post(
            "/api/messages/99999/send",
            json={"encrypted_content": "test"},
            headers={"Authorization": f"Bearer {registered_user['token']}"},
        )
        assert r.status_code == 404

    async def test_send_message_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/messages/1/send", json={"encrypted_content": "test"})
        assert r.status_code in (401, 403)


class TestMessageEdit:
    async def _send_msg(self, client, alice, bob) -> int:
        encrypted = base64.b64encode(b"original").decode()
        r = await client.post(
            f"/api/messages/{bob['user_id']}/send",
            json={"encrypted_content": encrypted},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        return r.json()["message_id"]

    async def test_edit_message(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)
        new_encrypted = base64.b64encode(b"edited").decode()

        r = await client.put(
            f"/api/messages/{msg_id}",
            json={"encrypted_content": new_encrypted},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 200
        assert r.json()["encrypted_content"] == new_encrypted
        assert r.json()["edited_at"] is not None

    async def test_edit_other_message(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        r = await client.put(
            f"/api/messages/{msg_id}",
            json={"encrypted_content": "hacked"},
            headers={"Authorization": f"Bearer {bob['token']}"},
        )
        assert r.status_code == 403

    async def test_edit_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.put(
            "/api/messages/99999",
            json={"encrypted_content": "test"},
            headers={"Authorization": f"Bearer {registered_user['token']}"},
        )
        assert r.status_code == 404

    async def test_edit_requires_auth(self, client: AsyncClient):
        r = await client.put("/api/messages/1", json={"encrypted_content": "test"})
        assert r.status_code in (401, 403)


class TestMessageDelete:
    async def _send_msg(self, client, alice, bob, content: str = "to_delete") -> int:
        encrypted = base64.b64encode(content.encode()).decode()
        r = await client.post(
            f"/api/messages/{bob['user_id']}/send",
            json={"encrypted_content": encrypted},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        return r.json()["message_id"]

    async def test_delete_for_me(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        r = await client.delete(
            f"/api/messages/{msg_id}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        user_msgs = [m for m in r.json() if m["type"] == "user"]
        assert all(m["id"] != msg_id for m in user_msgs)

    async def test_delete_for_all(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        r = await client.delete(
            f"/api/messages/{msg_id}?delete_for_all=true",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        user_msgs = [m for m in r.json() if m["type"] == "user"]
        assert all(m["id"] != msg_id for m in user_msgs)

    async def test_delete_other_message(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        r = await client.delete(
            f"/api/messages/{msg_id}",
            headers={"Authorization": f"Bearer {bob['token']}"},
        )
        assert r.status_code == 400

    async def test_delete_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.delete(
            "/api/messages/99999",
            headers={"Authorization": f"Bearer {registered_user['token']}"},
        )
        assert r.status_code == 404

    async def test_delete_requires_auth(self, client: AsyncClient):
        r = await client.delete("/api/messages/1")
        assert r.status_code in (401, 403)


class TestReactions:
    async def _send_msg(self, client, alice, bob) -> int:
        encrypted = base64.b64encode(b"react to me").decode()
        r = await client.post(
            f"/api/messages/{bob['user_id']}/send",
            json={"encrypted_content": encrypted},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        return r.json()["message_id"]

    async def test_add_reaction(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        r = await client.post(
            f"/api/messages/{msg_id}/reactions",
            json={"emoji": "\U0001f44d"},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

    async def test_remove_reaction(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        await client.post(
            f"/api/messages/{msg_id}/reactions",
            json={"emoji": "\U0001f44d"},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )

        r = await client.delete(
            f"/api/messages/{msg_id}/reactions/%F0%9F%91%8D",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

    async def test_add_reaction_nonexistent_message(self, client: AsyncClient, registered_user: dict):
        r = await client.post(
            "/api/messages/99999/reactions",
            json={"emoji": "\U0001f44d"},
            headers={"Authorization": f"Bearer {registered_user['token']}"},
        )
        assert r.status_code == 404

    async def test_add_duplicate_reaction(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        msg_id = await self._send_msg(client, alice, bob)

        await client.post(
            f"/api/messages/{msg_id}/reactions",
            json={"emoji": "\U0001f44d"},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )

        r = await client.post(
            f"/api/messages/{msg_id}/reactions",
            json={"emoji": "\U0001f44d"},
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

    async def test_add_reaction_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/messages/1/reactions", json={"emoji": "\U0001f44d"})
        assert r.status_code in (401, 403)

    async def test_remove_reaction_requires_auth(self, client: AsyncClient):
        r = await client.delete("/api/messages/1/reactions/%F0%9F%91%8D")
        assert r.status_code in (401, 403)


# ── Channels ──


class TestChannels:
    async def test_create_channel(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={
            "name": "Test Channel",
            "description": "A test channel",
        }, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Test Channel"
        assert data["owner_id"] == registered_user["user_id"]
        assert data["is_subscribed"] is True

    async def test_create_channel_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/channels", json={"name": "Test"})
        assert r.status_code in (401, 403)

    async def test_list_channels(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/channels", json={"name": "Channel One"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        await client.post("/api/channels", json={"name": "Channel Two"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})

        r = await client.get("/api/channels", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        channels = r.json()
        assert len(channels) >= 2
        names = [ch["name"] for ch in channels]
        assert "Channel One" in names
        assert "Channel Two" in names

    async def test_list_channels_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/channels")
        assert r.status_code in (401, 403)

    async def test_subscribe_channel(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Sub Channel"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "subscriber", "password": "Pass1234",
        })
        sub_token = r2.json()["access_token"]

        r = await client.post(f"/api/channels/{channel_id}/subscribe", headers={
            "Authorization": f"Bearer {sub_token}",
        })
        assert r.status_code == 204

    async def test_subscribe_twice(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Sub2"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        r = await client.post(f"/api/channels/{channel_id}/subscribe", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

        r = await client.post(f"/api/channels/{channel_id}/subscribe", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

    async def test_subscribe_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels/99999/subscribe", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_unsubscribe_channel(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Unsub"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        r = await client.delete(f"/api/channels/{channel_id}/subscribe", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

    async def test_post_to_channel(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Post Channel"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        r = await client.post(f"/api/channels/{channel_id}/post", json={
            "content": "Hello channel!",
        }, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["content"] == "Hello channel!"
        assert data["channel_id"] == channel_id
        assert data["sender_id"] == registered_user["user_id"]

    async def test_post_to_channel_not_owner(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Owner Channel"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "not_owner", "password": "Pass1234",
        })
        other_token = r2.json()["access_token"]

        r = await client.post(f"/api/channels/{channel_id}/post", json={
            "content": "Should fail",
        }, headers={
            "Authorization": f"Bearer {other_token}",
        })
        assert r.status_code == 403

    async def test_post_to_channel_empty_content(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Empty Channel"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        r = await client.post(f"/api/channels/{channel_id}/post", json={
            "content": "",
        }, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_post_to_nonexistent_channel(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels/99999/post", json={
            "content": "Hello",
        }, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_get_channel_messages(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/channels", json={"name": "Msg Channel"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        channel_id = r.json()["id"]

        await client.post(f"/api/channels/{channel_id}/post", json={"content": "Msg 1"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        await client.post(f"/api/channels/{channel_id}/post", json={"content": "Msg 2"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})

        r = await client.get(f"/api/channels/{channel_id}/messages", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        msgs = r.json()
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Msg 1"
        assert msgs[1]["content"] == "Msg 2"

    async def test_get_channel_messages_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/channels/99999/messages", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_channel_requires_auth(self, client: AsyncClient):
        for method, path in [
            ("GET", "/api/channels"),
            ("POST", "/api/channels"),
            ("POST", "/api/channels/1/subscribe"),
            ("DELETE", "/api/channels/1/subscribe"),
            ("POST", "/api/channels/1/post"),
            ("GET", "/api/channels/1/messages"),
        ]:
            r = await client.request(method, path)
            assert r.status_code in (401, 403), f"{method} {path} should require auth"


class TestPermissionsExtended:
    async def test_cancel_outgoing_request(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "cancel_target", "password": "Pass1234",
        })
        target_id = r2.json()["user_id"]

        r = await client.post(f"/api/permissions/request/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        perm_id = r.json()["id"]

        r = await client.delete(f"/api/permissions/outgoing/{target_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

        r = await client.get("/api/permissions/outgoing", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert all(p["id"] != perm_id for p in r.json())

    async def test_cancel_outgoing_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.delete("/api/permissions/outgoing/99999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_cancel_outgoing_requires_auth(self, client: AsyncClient):
        r = await client.delete("/api/permissions/outgoing/1")
        assert r.status_code in (401, 403)


class TestGroups:
    async def test_create_group(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Test Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Test Group"
        assert data["owner_id"] == registered_user["user_id"]
        assert data["is_member"] is True
        assert data["invite_code"] is not None
        assert data["member_count"] == 1

    async def test_create_group_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/groups", json={"name": "Test"})
        assert r.status_code in (401, 403)

    async def test_list_groups_empty(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/groups", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_groups(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/groups", json={"name": "Group A"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})

        r = await client.get("/api/groups", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        groups = r.json()
        assert len(groups) == 1
        assert groups[0]["name"] == "Group A"

    async def test_list_groups_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/groups")
        assert r.status_code in (401, 403)

    async def test_get_group(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "My Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r = await client.get(f"/api/groups/{group_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "My Group"
        assert data["owner_id"] == registered_user["user_id"]

    async def test_get_group_non_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Private Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "not_member", "password": "Pass1234",
        })
        other_token = r2.json()["access_token"]

        r = await client.get(f"/api/groups/{group_id}", headers={
            "Authorization": f"Bearer {other_token}",
        })
        assert r.status_code == 403

    async def test_get_group_nonexistent(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/groups/99999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_join_group(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Joinable Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        invite_code = r.json()["invite_code"]

        r2 = await client.post("/api/auth/register", json={
            "username": "joiner", "password": "Pass1234",
        })
        joiner_token = r2.json()["access_token"]

        r = await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {joiner_token}",
        })
        assert r.status_code == 200
        assert r.json()["is_member"] is True
        assert r.json()["member_count"] == 2

    async def test_join_nonexistent_invite(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups/join/invalid_code_12345", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_join_twice(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Join Twice"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        invite_code = r.json()["invite_code"]

        r = await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200

    async def test_get_members(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Member Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r = await client.get(f"/api/groups/{group_id}/members", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        members = r.json()
        assert len(members) == 1
        assert members[0]["user_id"] == registered_user["user_id"]
        assert members[0]["username"] == "alice"
        assert members[0]["role"] == "owner"

    async def test_get_members_non_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Member Check"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "nonmember2", "password": "Pass1234",
        })

        r = await client.get(f"/api/groups/{group_id}/members", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })
        assert r.status_code == 403

    async def test_generate_invite(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Invite Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]
        old_code = r.json()["invite_code"]

        r = await client.post(f"/api/groups/{group_id}/generate-invite", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        new_code = r.json()["invite_code"]
        assert new_code != old_code

    async def test_generate_invite_non_owner(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Owner Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "not_owner2", "password": "Pass1234",
        })
        other_token = r2.json()["access_token"]

        r = await client.post(f"/api/groups/{group_id}/generate-invite", headers={
            "Authorization": f"Bearer {other_token}",
        })
        assert r.status_code == 403

    async def test_leave_group(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Leave Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "leaver", "password": "Pass1234",
        })
        joiner_token = r2.json()["access_token"]

        await client.post(f"/api/groups/join/{r.json()['invite_code']}", headers={
            "Authorization": f"Bearer {joiner_token}",
        })

        r = await client.delete(f"/api/groups/{group_id}/leave", headers={
            "Authorization": f"Bearer {joiner_token}",
        })
        assert r.status_code == 204

    async def test_leave_by_owner(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Owner Leave"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r = await client.delete(f"/api/groups/{group_id}/leave", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_leave_non_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Non Member Leave"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "not_member3", "password": "Pass1234",
        })

        r = await client.delete(f"/api/groups/{group_id}/leave", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })
        assert r.status_code == 404

    async def test_kick_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Kick Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]
        invite_code = r.json()["invite_code"]

        r2 = await client.post("/api/auth/register", json={
            "username": "kick_me", "password": "Pass1234",
        })
        kick_user_id = r2.json()["user_id"]
        kick_token = r2.json()["access_token"]

        await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {kick_token}",
        })

        r = await client.delete(f"/api/groups/{group_id}/members/{kick_user_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

    async def test_kick_non_owner(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Kick Auth"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]
        invite_code = r.json()["invite_code"]

        r2 = await client.post("/api/auth/register", json={
            "username": "kick_auth1", "password": "Pass1234",
        })
        user1_token = r2.json()["access_token"]
        user1_id = r2.json()["user_id"]

        r3 = await client.post("/api/auth/register", json={
            "username": "kick_auth2", "password": "Pass1234",
        })
        user2_token = r3.json()["access_token"]
        user2_id = r3.json()["user_id"]

        await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {user1_token}",
        })
        await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {user2_token}",
        })

        r = await client.delete(f"/api/groups/{group_id}/members/{user2_id}", headers={
            "Authorization": f"Bearer {user1_token}",
        })
        assert r.status_code == 403

    async def test_kick_nonexistent_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Kick Nonexistent"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r = await client.delete(f"/api/groups/{group_id}/members/99999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_ban_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Ban Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]
        invite_code = r.json()["invite_code"]

        r2 = await client.post("/api/auth/register", json={
            "username": "ban_me", "password": "Pass1234",
        })
        ban_user_id = r2.json()["user_id"]
        ban_token = r2.json()["access_token"]

        await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {ban_token}",
        })

        r = await client.post(f"/api/groups/{group_id}/ban/{ban_user_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

    async def test_ban_non_owner(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Ban Auth"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]
        invite_code = r.json()["invite_code"]

        r2 = await client.post("/api/auth/register", json={
            "username": "ban_auth1", "password": "Pass1234",
        })
        user_token = r2.json()["access_token"]
        user2_id = r2.json()["user_id"]

        await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {user_token}",
        })

        r = await client.post(f"/api/groups/{group_id}/ban/{user2_id}", headers={
            "Authorization": f"Bearer {user_token}",
        })
        assert r.status_code == 403

    async def test_list_bans(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Ban List"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "banned_user", "password": "Pass1234",
        })
        ban_user_id = r2.json()["user_id"]

        await client.post(f"/api/groups/{group_id}/ban/{ban_user_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        r = await client.get(f"/api/groups/{group_id}/bans", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        bans = r.json()
        assert len(bans) == 1
        assert bans[0]["user_id"] == ban_user_id
        assert bans[0]["username"] == "banned_user"

    async def test_list_bans_non_owner(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Ban List Auth"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]
        invite_code = r.json()["invite_code"]

        r2 = await client.post("/api/auth/register", json={
            "username": "ban_viewer", "password": "Pass1234",
        })

        await client.post(f"/api/groups/join/{invite_code}", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })

        r = await client.get(f"/api/groups/{group_id}/bans", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })
        assert r.status_code == 403

    async def test_unban_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Unban Test"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "unban_me", "password": "Pass1234",
        })
        ban_user_id = r2.json()["user_id"]

        await client.post(f"/api/groups/{group_id}/ban/{ban_user_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        r = await client.delete(f"/api/groups/{group_id}/ban/{ban_user_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 204

        r = await client.get(f"/api/groups/{group_id}/bans", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.json() == []

    async def test_join_when_banned(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Banned Join"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "banned_joiner", "password": "Pass1234",
        })
        ban_user_id = r2.json()["user_id"]
        ban_token = r2.json()["access_token"]

        await client.post(f"/api/groups/{group_id}/ban/{ban_user_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        # Try to join — should be rejected even without invite_code knowledge
        r = await client.post(f"/api/groups/join/{r.json()['invite_code']}", headers={
            "Authorization": f"Bearer {ban_token}",
        })
        assert r.status_code == 403

    async def test_group_send_message(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Msg Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        encrypted = base64.b64encode(b"group message").decode()
        r = await client.post(f"/api/groups/{group_id}/send", json={
            "encrypted_content": encrypted,
        }, headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["encrypted_content"] == encrypted
        assert data["sender_id"] == registered_user["user_id"]
        assert data["group_chat_id"] == group_id

    async def test_group_send_non_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Non Member Msg"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "non_member_msg", "password": "Pass1234",
        })

        r = await client.post(f"/api/groups/{group_id}/send", json={
            "encrypted_content": "test",
        }, headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })
        assert r.status_code == 403

    async def test_get_group_messages(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Msg Get"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        enc1 = base64.b64encode(b"hello group").decode()
        await client.post(f"/api/groups/{group_id}/send", json={"encrypted_content": enc1},
            headers={"Authorization": f"Bearer {registered_user['token']}"})

        r = await client.get(f"/api/groups/{group_id}/messages", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        msgs = r.json()
        assert len(msgs) >= 1
        assert msgs[0]["encrypted_content"] == enc1

    async def test_get_group_messages_non_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Msg Non Member"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "non_member_view", "password": "Pass1234",
        })

        r = await client.get(f"/api/groups/{group_id}/messages", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })
        assert r.status_code == 403

    async def test_group_shared_key_no_key(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Key Group"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r = await client.get(f"/api/groups/{group_id}/shared-key/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() is None

    async def test_group_shared_key_non_member(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/groups", json={"name": "Key Non Member"},
            headers={"Authorization": f"Bearer {registered_user['token']}"})
        group_id = r.json()["id"]

        r2 = await client.post("/api/auth/register", json={
            "username": "key_non_member", "password": "Pass1234",
        })

        r = await client.get(f"/api/groups/{group_id}/shared-key/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })
        assert r.status_code == 403

    async def test_group_requires_auth(self, client: AsyncClient):
        for method, path in [
            ("GET", "/api/groups"),
            ("POST", "/api/groups"),
            ("GET", "/api/groups/1"),
            ("GET", "/api/groups/1/members"),
            ("POST", "/api/groups/1/generate-invite"),
            ("DELETE", "/api/groups/1/leave"),
            ("DELETE", "/api/groups/1/members/1"),
            ("POST", "/api/groups/1/ban/1"),
            ("GET", "/api/groups/1/bans"),
            ("DELETE", "/api/groups/1/ban/1"),
            ("GET", "/api/groups/1/shared-key/1"),
            ("GET", "/api/groups/1/messages"),
            ("POST", "/api/groups/1/send"),
            ("POST", "/api/groups/join/test"),
        ]:
            r = await client.request(method, path)
            assert r.status_code in (401, 403), f"{method} {path} should require auth"
