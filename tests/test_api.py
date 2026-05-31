import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAuth:
    async def test_register_success(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "bob", "password": "pass",
            "public_key": "AQID",
        })
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["username"] == "bob"
        assert isinstance(data["user_id"], int)

    async def test_register_duplicate(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={
            "username": "alice", "password": "other",
        })
        assert r.status_code == 400
        assert "already taken" in r.json()["detail"]

    async def test_login_success(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "pass123",
        })
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
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

    async def test_me_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/auth/me")
        assert r.status_code in (401, 403)

    async def test_login_empty_password(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "",
        })
        assert r.status_code == 401

    async def test_login_long_password(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/login", json={
            "username": "alice", "password": "x" * 100,
        })
        assert r.status_code == 401, "long pw should NOT cause 500"

    async def test_register_empty_password(self, client: AsyncClient):
        r = await client.post("/api/auth/register", json={
            "username": "emptypw", "password": "",
        })
        assert r.status_code == 200, "empty pw should register"

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
        r = await client.post("/api/auth/register", json={
            "username": "bob", "password": "pass",
        })
        bob_token = r.json()["token"]
        # bob requests alice — now alice sees bob in list
        await client.post("/api/permissions/request/1", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        users = r.json()
        assert len(users) == 1
        assert users[0]["username"] == "bob"
        assert users[0]["id"] != registered_user["user_id"]
        assert users[0]["permission_status"] == "pending"

    async def test_list_users_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/users")
        assert r.status_code in (401, 403)


class TestUserSearch:
    async def test_search_no_query(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        r = await client.get("/api/users/search", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["username"] == "bob"
        assert r.json()[0]["permission_status"] == "none"

    async def test_search_by_query(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bobmarley", "password": "pass"})
        await client.post("/api/auth/register", json={"username": "bobalice", "password": "pass"})
        r = await client.get("/api/users/search?q=bob", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        usernames = [u["username"] for u in r.json()]
        assert "bobmarley" in usernames
        assert "bobalice" in usernames
        assert "alice" not in usernames

    async def test_search_partial(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "johnwick", "password": "pass"})
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
        await client.post("/api/auth/register", json={"username": "Charlie", "password": "pass"})
        r = await client.get("/api/users/search?q=charlie", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert len(r.json()) == 1

    async def test_search_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/users/search?q=alice")
        assert r.status_code in (401, 403)


class TestMessages:
    async def test_history_empty(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={
            "username": "bob", "password": "pass",
        })
        r = await client.get("/api/messages/2", headers={
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
        await client.post("/api/auth/register", json={
            "username": "bob", "password": "pass",
        })
        r = await client.get("/api/messages/2/shared-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() is None

    async def test_shared_key_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/messages/1/shared-key")
        assert r.status_code in (401, 403)

    async def test_has_my_key_none_by_default(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        r = await client.get("/api/messages/2/has-my-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json() is False

    async def test_has_my_key_requires_auth(self, client: AsyncClient):
        r = await client.get("/api/messages/1/has-my-key")
        assert r.status_code in (401, 403)

    async def test_revoke_shared_key(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})

        r1 = await client.get("/api/messages/2/has-my-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r1.json() is False

        r2 = await client.delete("/api/messages/2/shared-key", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r2.status_code == 204

    async def test_revoke_shared_key_requires_auth(self, client: AsyncClient):
        r = await client.delete("/api/messages/1/shared-key")
        assert r.status_code in (401, 403)


class TestPermissions:
    async def test_request_permission(self, client: AsyncClient, registered_user: dict):
        r2 = await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
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
        await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        await client.post("/api/permissions/request/2", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        r = await client.post("/api/permissions/request/2", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 400

    async def test_approve_permission(self, client: AsyncClient, registered_user: dict):
        await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        # bob (user 2) requests alice (user 1)
        r = await client.post("/api/permissions/request/1", json={"username": "bob2", "password": "pass"})
        # actually need bob's token. Let's do alice -> bob, then bob approves
        await client.post("/api/permissions/request/2", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        r = await client.get("/api/permissions/incoming")
        # use alice token as "bob" ... need separate registration
        pass

    async def test_approve_permission_flow(self, client: AsyncClient, registered_user: dict):
        # bob registers
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        bob_data = r.json()
        bob_token = bob_data["token"]

        # bob requests alice
        r = await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        assert r.status_code == 200

        # alice sees incoming
        r = await client.get("/api/permissions/incoming", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        inc = r.json()
        assert len(inc) == 1
        assert inc[0]["requester_id"] == bob_data["user_id"]
        perm_id = inc[0]["id"]

        # alice approves
        r = await client.post(f"/api/permissions/{perm_id}/approve", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        # bob sees approved
        r = await client.get("/api/permissions/outgoing", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        out = r.json()
        assert out[0]["status"] == "approved"

    async def test_reject_permission(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        bob_token = r.json()["token"]

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

    async def test_approved_list_shows_both_directions(self, client: AsyncClient, registered_user: dict):
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        bob_token = r.json()["token"]

        # bob requests alice -> alice approves
        r = await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        perm_id = r.json()["id"]
        await client.post(f"/api/permissions/{perm_id}/approve", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })

        # both see it in /approved
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
        r = await client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
        bob_token = r.json()["token"]

        # bob requests alice
        await client.post(f"/api/permissions/request/{registered_user['user_id']}", headers={
            "Authorization": f"Bearer {bob_token}",
        })

        # alice sees bob as "pending" in user list
        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {registered_user['token']}",
        })
        bob_entry = [u for u in r.json() if u["username"] == "bob"]
        assert len(bob_entry) == 1
        assert bob_entry[0]["permission_status"] == "pending"

        # bob sees alice as "pending" in user list
        r = await client.get("/api/users", headers={
            "Authorization": f"Bearer {bob_token}",
        })
        alice_entry = [u for u in r.json() if u["username"] == "alice"]
        assert len(alice_entry) == 1
        assert alice_entry[0]["permission_status"] == "pending"
