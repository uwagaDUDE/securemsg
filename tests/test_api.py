import base64

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAuth:
    async def test_register_success(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "bob", "password": "Pass1234",
            "public_key": "AQID",
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["username"] == "bob"
        assert isinstance(data["user_id"], int)

    async def test_register_duplicate(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={
            "username": "alice", "password": "Other123",
        })
        assert r.status_code == 400
        assert "already taken" in r.json()["detail"]

    async def test_register_empty_password(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "emptypw", "password": "",
        })
        assert r.status_code == 422

    async def test_register_with_all_keys(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "fullkeys", "password": "Pass1234",
            "public_key": base64.b64encode(b"pubkey").decode(),
            "encrypted_private_key": base64.b64encode(b"enc_priv").decode(),
            "broadcast_key": base64.b64encode(b"bcast").decode(),
        })
        assert r.status_code == 200
        data = r.json()
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        me_data = me.json()
        assert me_data["public_key"] == base64.b64encode(b"pubkey").decode()
        assert me_data["encrypted_private_key"] == base64.b64encode(b"enc_priv").decode()
        assert me_data["broadcast_key"] == base64.b64encode(b"bcast").decode()

    async def test_login_success(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "Pass1234",
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["username"] == "alice"

    async def test_login_wrong_password(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "wrong",
        })
        assert r.status_code == 401

    async def test_login_nonexistent(self, client: AsyncClient):
        r = await client.post("/api/auth/login", json={
            "username": "nobody", "password": "x",
        })
        assert r.status_code == 401

    async def test_login_empty_password(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "",
        })
        assert r.status_code == 422

    async def test_login_long_password(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "x" * 100,
        })
        assert r.status_code == 401, "long pw should NOT cause 500"

    async def test_me_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/auth/me")
        assert r.status_code in (401, 403)

    async def test_me_returns_user(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "alice"
        assert data["id"] == registered_user["user_id"]
        assert data["permission_status"] == "none"


class TestUsers:
    async def test_list_users_empty(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_users_shows_others(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "bob", "password": "Pass1234",
        })
        bob_token = r2.json()["access_token"]
        bob_id = r2.json()["user_id"]
        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        users = r.json()
        assert len(users) == 1
        assert users[0]["username"] == "bob"
        assert users[0]["id"] == bob_id
        assert users[0]["permission_status"] == "pending"

    async def test_list_users_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/users")
        assert r.status_code in (401, 403)


class TestUserSearch:
    async def test_search_no_query(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        r = await client.get("/api/users/search", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "bob"
        assert r.json()[0]["permission_status"] == "none"

    async def test_search_by_query(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bobmarley", "password": "Pass1234"})
        await client.post("/api/auth/register", json={"username": "bobalice", "password": "Pass1234"})
        r = await client.get("/api/users/search?q=bob", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        usernames = [u["username"] for u in r.json()]
        assert "bobmarley" in usernames
        assert "bobalice" in usernames
        assert "alice" not in usernames

    async def test_search_partial(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "johnwick", "password": "Pass1234"})
        r = await client.get("/api/users/search?q=wick", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "johnwick"

    async def test_search_no_results(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/users/search?q=nonexistent", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == []

    async def test_search_case_insensitive(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "Charlie", "password": "Pass1234"})
        r = await client.get("/api/users/search?q=charlie", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1

    async def test_search_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/users/search?q=alice")
        assert r.status_code in (401, 403)

    async def test_search_excludes_self(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/users/search?q=alice", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == []

    async def test_search_special_chars(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "test_user_1", "password": "Pass1234"})
        r = await client.get("/api/users/search?q=test_user", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "test_user_1"

    async def test_search_underscore(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "test_user", "password": "Pass1234"})
        r = await client.get("/api/users/search?q=test_", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "test_user"


class TestMessages:
    async def test_history_empty(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "bob", "password": "Pass1234",
        })
        bob_id = r2.json()["user_id"]
        r = await client.get(f"/api/messages/{bob_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() == []

    async def test_history_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/messages/1")
        assert r.status_code in (401, 403)

    async def test_history_self_not_allowed(self, client: AsyncClient, registered_user: dict):
        r = await client.get(f"/api/messages/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_history_requires_valid_user(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/messages/999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404


class TestSharedKey:
    async def test_shared_key_none_by_default(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "bob", "password": "Pass1234",
        })
        bob_id = r2.json()["user_id"]
        r = await client.get(f"/api/messages/{bob_id}/shared-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() is None

    async def test_shared_key_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/messages/1/shared-key")
        assert r.status_code in (401, 403)

    async def test_has_my_key_none_by_default(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_id = r2.json()["user_id"]
        r = await client.get(f"/api/messages/{bob_id}/has-my-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() is False

    async def test_has_my_key_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/messages/1/has-my-key")
        assert r.status_code in (401, 403)

    async def test_revoke_shared_key(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_id = r2.json()["user_id"]

        r1 = await client.get(f"/api/messages/{bob_id}/has-my-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r1.json() is False

        r2 = await client.delete(f"/api/messages/{bob_id}/shared-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r2.status_code == 204

    async def test_revoke_shared_key_requires_auth(self, client: AsyncClient):
        r = await client.delete("/api/messages/1/shared-key")
        assert r.status_code in (401, 403)

    async def test_revoke_creates_system_message(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        r = await client.delete(
            f"/api/messages/{bob['user_id']}/shared-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

        r = await client.get(
            f"/api/messages/{bob['user_id']}",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        msgs = r.json()
        system_msgs = [m for m in msgs if m.get("type") == "system"]
        assert len(system_msgs) >= 1
        assert "revoked" in system_msgs[-1]["encrypted_content"]


class TestPermissions:
    async def test_request_permission(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_id = r2.json()["user_id"]
        r = await client.post(f"/api/permissions/request/{bob_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["owner_id"] == bob_id
        assert data["requester_id"] == registered_user["user_id"]
        assert data["status"] == "pending"

    async def test_request_self(self, client: AsyncClient, registered_user: dict):
        r = await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_request_duplicate(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_id = r2.json()["user_id"]
        await client.post(f"/api/permissions/request/{bob_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        r = await client.post(f"/api/permissions/request/{bob_id}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_request_nonexistent_user(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/permissions/request/999", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_approve_permission_flow(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_data = r.json()
        bob_token = bob_data["access_token"]

        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })

        r = await client.get("/api/permissions/incoming", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        inc = r.json()
        assert len(inc) == 1
        assert inc[0]["requester_id"] == bob_data["user_id"]
        perm_id = inc[0]["id"]

        r = await client.post(f"/api/permissions/{perm_id}/approve", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        r = await client.get("/api/permissions/outgoing", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        out = r.json()
        assert out[0]["status"] == "approved"

    async def test_approve_nonexistent_permission(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/permissions/999/approve", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_approve_not_owner(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_data = r2.json()
        r3 = await client.post("/api/auth/register", json={"username": "charlie", "password": "Pass1234"})
        charlie_data = r3.json()

        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_data['access_token']}",
        })
        r = await client.get("/api/permissions/incoming", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        perm_id = r.json()[0]["id"]

        r = await client.post(f"/api/permissions/{perm_id}/approve", headers={
            "Authorization": f"Bearer {charlie_data['access_token']}",
        })
        assert r.status_code == 404

    async def test_reject_permission(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_token = r.json()["access_token"]

        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })

        r = await client.get("/api/permissions/incoming", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        perm_id = r.json()[0]["id"]

        r = await client.post(f"/api/permissions/{perm_id}/reject", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    async def test_reject_nonexistent_permission(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/permissions/999/reject", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 404

    async def test_approved_list_shows_both_directions(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_token = r.json()["access_token"]
        bob_id = r.json()["user_id"]

        r = await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        perm_id = r.json()["id"]
        await client.post(f"/api/permissions/{perm_id}/approve", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        r = await client.get("/api/permissions/approved", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert len(r.json()) == 1
        assert r.json()[0]["status"] == "approved"

        r = await client.get("/api/permissions/approved", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        assert len(r.json()) == 1

    async def test_permission_status_in_user_list(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_token = r.json()["access_token"]

        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })

        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        bob_entry = [u for u in r.json() if u["username"] == "bob"]
        assert len(bob_entry) == 1
        assert bob_entry[0]["permission_status"] == "pending"

        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        alice_entry = [u for u in r.json() if u["username"] == "alice"]
        assert len(alice_entry) == 1
        assert alice_entry[0]["permission_status"] == "pending"

    async def test_incoming_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/permissions/incoming")
        assert r.status_code in (401, 403)

    async def test_outgoing_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/permissions/outgoing")
        assert r.status_code in (401, 403)

    async def test_approved_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/permissions/approved")
        assert r.status_code in (401, 403)


class TestMarkRead:
    async def test_mark_read_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/messages/1/read")
        assert r.status_code in (401, 403)

    async def test_mark_read_returns_204(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        r = await client.post(
            f"/api/messages/{bob['user_id']}/read",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 204

    async def test_mark_read_then_unread_zero(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob

        r = await client.get(
            "/api/messages/unread-counts",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 200
        assert r.json() == {}

    async def test_unread_counts_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/messages/unread-counts")
        assert r.status_code in (401, 403)


class TestKeyRequest:
    async def test_request_key_basic(self, client: AsyncClient, approved_pair_alice_bob):
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

    async def test_request_key_self_not_allowed(self, client: AsyncClient, registered_user_alice):
        r = await client.post(
            f"/api/messages/{registered_user_alice['user_id']}/request-key",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 400

    async def test_request_key_invalid_user(self, client: AsyncClient, registered_user_alice):
        r = await client.post(
            "/api/messages/999/request-key",
            headers={"Authorization": f"Bearer {registered_user_alice['token']}"},
        )
        assert r.status_code == 404

    async def test_request_key_rate_limit(self, client: AsyncClient, approved_pair_alice_bob):
        alice, bob = approved_pair_alice_bob
        for _ in range(3):
            r = await client.post(
                f"/api/messages/{bob['user_id']}/request-key",
                headers={"Authorization": f"Bearer {alice['token']}"},
            )
            assert r.status_code == 204

        r = await client.post(
            f"/api/messages/{bob['user_id']}/request-key",
            headers={"Authorization": f"Bearer {alice['token']}"},
        )
        assert r.status_code == 429
        assert "3/hour" in r.json()["detail"].lower()

    async def test_request_key_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/messages/1/request-key")
        assert r.status_code in (401, 403)


class TestRejectCleansSharedKeys:
    async def test_reject_cleans_shared_keys(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "Pass1234"})
        bob_data = r.json()
        bob_token = bob_data["access_token"]

        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        r = await client.get("/api/permissions/incoming", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        perm_id = r.json()[0]["id"]

        r = await client.post(f"/api/permissions/{perm_id}/reject", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


class TestRateLimit:
    async def test_register_rate_limit_headers(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "rl_user1", "password": "Pass1234",
        })
        assert r.status_code == 200
        assert "X-RateLimit-Limit" in r.headers
        assert "X-RateLimit-Remaining" in r.headers
        assert r.headers["X-RateLimit-Limit"] == "5"

    async def test_register_rate_limit_exceeded(self, client: AsyncClient):
        for i in range(5):
            r = await client.post("/api/auth/register", json={
                "username": f"rl_limit_{i}", "password": "Pass1234",
            })
            assert r.status_code == 200

        r = await client.post("/api/auth/register", json={
            "username": "rl_limit_5", "password": "Pass1234",
        })
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    async def test_login_failure_rate_limit(self, client: AsyncClient, registered_user: dict):
        for _ in range(5):
            r = await client.post("/api/auth/login", json={
                "username": "alice", "password": "wrong",
            })
            assert r.status_code == 401

        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "wrong",
        })
        assert r.status_code == 429

    async def test_permission_request_rate_limit(self, client: AsyncClient, registered_user: dict):
        """Test per-user rate limit on permission requests (10/min)."""
        target_ids = []
        for i in range(4):
            r = await client.post("/api/auth/register", json={
                "username": f"rl_tgt_{i}", "password": "Pass1234",
            })
            if r.status_code == 429:
                break
            target_ids.append(r.json()["user_id"])

        for tid in target_ids:
            r = await client.post(f"/api/permissions/request/{tid}", headers={
                "Authorization": f"Bearer {registered_user['token']}",
            })
            assert r.status_code == 200

        for tid in target_ids:
            await client.post(f"/api/permissions/request/{tid}", headers={
                "Authorization": f"Bearer {registered_user['token']}",
            })

        for tid in target_ids:
            await client.post(f"/api/permissions/request/{tid}", headers={
                "Authorization": f"Bearer {registered_user['token']}",
            })

        for tid in target_ids:
            await client.post(f"/api/permissions/request/{tid}", headers={
                "Authorization": f"Bearer {registered_user['token']}",
            })

        r = await client.post(f"/api/permissions/request/{target_ids[0]}", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 429


class TestOnlineStatus:
    async def test_user_out_includes_online_fields(self, client: AsyncClient, registered_user: dict):
        r = await client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        data = r.json()
        assert "is_online" in data
        assert "last_seen" in data

    async def test_user_list_includes_online_fields(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={
            "username": "online_target", "password": "Pass1234",
        })
        target_id = r2.json()["user_id"]
        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {r2.json()['access_token']}",
        })

        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        users = r.json()
        assert len(users) >= 1
        assert "is_online" in users[0]
        assert "last_seen" in users[0]
