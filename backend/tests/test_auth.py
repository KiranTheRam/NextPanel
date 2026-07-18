from .conftest import register_user, set_settings


async def test_first_run_setup_flow(client):
    status = (await client.get("/api/v1/auth/status")).json()
    assert status["setup_required"] is True

    resp = await client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "hunter22"}
    )
    assert resp.status_code == 201
    assert resp.json()["is_admin"] is True

    # setup is one-shot
    resp = await client.post(
        "/api/v1/auth/setup", json={"username": "evil", "password": "evilpass"}
    )
    assert resp.status_code == 403

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


async def test_login_logout(client, admin):
    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    resp = await client.post(
        "/api/v1/auth/login", json={"username": "ADMIN", "password": "hunter22"}
    )
    assert resp.status_code == 200  # username is case-insensitive

    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrongpass"}
    )
    assert resp.status_code == 401


async def test_registration_toggle(client, admin):
    # registration is off by default on a fresh install
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "other", "password": "otherpass"}
    )
    assert resp.status_code == 403

    await register_user(client, "friend", "friendpass")  # enables the toggle
    assert (await client.get("/api/v1/auth/me")).json()["username"] == "friend"
    assert (await client.get("/api/v1/auth/me")).json()["is_admin"] is False

    await set_settings(registration_enabled="false")
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "other", "password": "otherpass"}
    )
    assert resp.status_code == 403


async def test_duplicate_username_rejected(client, admin):
    from .conftest import set_settings as enable

    await enable(registration_enabled="true")
    resp = await client.post(
        "/api/v1/auth/register", json={"username": "Admin", "password": "whatever12"}
    )
    assert resp.status_code == 409


async def test_non_admin_cannot_touch_admin_routes(client, admin):
    await register_user(client)  # switches session cookie to the new user
    assert (await client.get("/api/v1/settings")).status_code == 403
    assert (await client.get("/api/v1/users")).status_code == 403
    assert (await client.get("/api/v1/requests", params={"scope": "all"})).status_code == 403


async def test_admin_user_management(client, admin):
    resp = await client.post(
        "/api/v1/users", json={"username": "kid", "password": "kidpassword", "is_admin": False}
    )
    assert resp.status_code == 201
    kid_id = resp.json()["id"]

    users = (await client.get("/api/v1/users")).json()
    assert {u["username"] for u in users} == {"admin", "kid"}

    # cannot demote or delete yourself
    admin_id = admin["id"]
    resp = await client.put(f"/api/v1/users/{admin_id}", json={"is_admin": False})
    assert resp.status_code == 400
    resp = await client.delete(f"/api/v1/users/{admin_id}")
    assert resp.status_code == 400

    resp = await client.delete(f"/api/v1/users/{kid_id}")
    assert resp.status_code == 204
