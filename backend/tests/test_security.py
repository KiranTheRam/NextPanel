import hashlib

import httpx
import respx
from httpx import Response
from sqlalchemy import select

from nextpanel.db import session_scope
from nextpanel.models import UserSession

from .conftest import register_user


async def test_login_rate_limited(client, admin):
    for _ in range(10):
        resp = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrongpassword"}
        )
        assert resp.status_code == 401
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrongpassword"}
    )
    assert resp.status_code == 429
    # the limiter is per-username: even the right password is throttled now,
    # but a different account is unaffected
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "hunter22"}
    )
    assert resp.status_code == 429


async def test_short_passwords_rejected(client):
    resp = await client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "short"}
    )
    assert resp.status_code == 422


async def test_unknown_username_login_is_401(client, admin):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "whatever12"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


async def test_session_tokens_stored_hashed(client, admin):
    cookie = client.cookies.get("nextpanel_session")
    assert cookie
    async with session_scope() as session:
        rows = (await session.execute(select(UserSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].token != cookie
    assert rows[0].token == hashlib.sha256(cookie.encode()).hexdigest()


async def test_password_reset_invalidates_sessions(client, admin):
    from nextpanel.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as reader:
        user = await register_user(reader)
        assert (await reader.get("/api/v1/auth/me")).status_code == 200

        resp = await client.put(f"/api/v1/users/{user['id']}", json={"password": "newpassword1"})
        assert resp.status_code == 200
        assert (await reader.get("/api/v1/auth/me")).status_code == 401


async def test_security_headers_present(client):
    for path in ("/", "/api/v1/auth/status"):
        resp = await client.get(path)
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in resp.headers["content-security-policy"]


async def test_secure_cookie_behind_https_proxy(client):
    resp = await client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "hunter22"},
        headers={"X-Forwarded-Proto": "https"},
    )
    set_cookie = resp.headers["set-cookie"]
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


async def test_secure_cookie_and_hsts_are_default(client):
    resp = await client.get("/api/v1/auth/status")
    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    setup = await client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "hunter22"}
    )
    assert "Secure" in setup.headers["set-cookie"]


async def test_login_global_limit_cannot_be_bypassed_with_forwarded_ip(client, admin, monkeypatch):
    from nextpanel.api import auth

    monkeypatch.setattr(auth, "LOGIN_GLOBAL_LIMIT", 2)
    for username, ip in (("one", "198.51.100.1"), ("two", "198.51.100.2")):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "wrongpassword"},
            headers={"X-Forwarded-For": ip},
        )
        assert resp.status_code == 401
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "three", "password": "wrongpassword"},
        headers={"X-Forwarded-For": "198.51.100.3"},
    )
    assert resp.status_code == 429


async def test_request_cover_url_is_allowlisted(client, admin):
    resp = await client.post("/api/v1/requests", json={
        "media_type": "manga", "provider": "mangaupdates", "provider_id": 123,
        "title": "Example", "cover_url": "https://attacker.example/track.png",
    })
    assert resp.status_code == 201
    assert resp.json()["cover_url"] == ""


async def test_oversized_request_body_rejected(client):
    resp = await client.post(
        "/api/v1/auth/login", content=b"x" * (64 * 1024 + 1),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


@respx.mock
async def test_search_errors_hide_internal_urls(client, configured):
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(500, json={"detail": "internal explosion"})
    )
    respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[])
    )
    data = (await client.get("/api/v1/search", params={"q": "x"})).json()
    message = data["errors"]["mangarr"]
    assert "mangarr.test" not in message
    assert "explosion" not in message


async def test_pending_request_cap(client, admin):
    from nextpanel.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as reader:
        await register_user(reader)
        for i in range(25):
            resp = await reader.post("/api/v1/requests", json={
                "media_type": "manga", "provider": "mangaupdates",
                "provider_id": 1000 + i, "title": f"Series {i}",
            })
            assert resp.status_code == 201
        resp = await reader.post("/api/v1/requests", json={
            "media_type": "manga", "provider": "mangaupdates",
            "provider_id": 9999, "title": "One too many",
        })
        assert resp.status_code == 429
