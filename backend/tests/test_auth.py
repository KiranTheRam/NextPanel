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


async def test_change_own_password(client, admin):
    resp = await client.post("/api/v1/auth/password", json={
        "current_password": "hunter22", "new_password": "newpassword1",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "admin"

    # the caller keeps working on a freshly issued session
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    # and the new password is the one that logs in
    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "hunter22"}
    )
    assert resp.status_code == 401
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "newpassword1"}
    )
    assert resp.status_code == 200


async def test_change_password_requires_the_current_one(client, admin):
    resp = await client.post("/api/v1/auth/password", json={
        "current_password": "notmypassword", "new_password": "newpassword1",
    })
    assert resp.status_code == 403
    assert "Current password" in resp.json()["detail"]

    # unchanged: the original password still works
    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "hunter22"}
    )
    assert resp.status_code == 200


async def test_change_password_rejects_short_new_password(client, admin):
    resp = await client.post("/api/v1/auth/password", json={
        "current_password": "hunter22", "new_password": "short",
    })
    assert resp.status_code == 422


async def test_change_password_requires_login(client):
    resp = await client.post("/api/v1/auth/password", json={
        "current_password": "hunter22", "new_password": "newpassword1",
    })
    assert resp.status_code == 401
