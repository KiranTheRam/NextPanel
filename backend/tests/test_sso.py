import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response

from nextpanel.config import config


TEAM_DOMAIN = "https://nextpanel-test.cloudflareaccess.com"
AUDIENCE = "nextpanel-test-audience"
KEY_ID = "test-signing-key"


def _signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": KEY_ID, "alg": "RS256", "use": "sig"})
    return private_key, public_jwk


def _token(private_key, email="reader@example.com", **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "aud": [AUDIENCE],
        "email": email,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nbf": now,
        "iss": TEAM_DOMAIN,
        "type": "app",
        "sub": f"subject:{email}",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KEY_ID})


def _enable_sso(monkeypatch, *, local_login=False, admin_emails=""):
    monkeypatch.setattr(config, "cloudflare_access_team_domain", TEAM_DOMAIN)
    monkeypatch.setattr(config, "cloudflare_access_audience", AUDIENCE)
    monkeypatch.setattr(config, "local_login_enabled", local_login)
    monkeypatch.setattr(config, "cloudflare_access_admin_emails", admin_emails)

    from nextpanel import cloudflare_access

    monkeypatch.setattr(cloudflare_access, "_jwks", None)
    monkeypatch.setattr(cloudflare_access, "_jwks_domain", "")
    monkeypatch.setattr(cloudflare_access, "_jwks_expires_at", 0.0)
    monkeypatch.setattr(cloudflare_access, "_jwks_last_refresh_at", 0.0)


@respx.mock
async def test_sso_jit_provisions_first_admin_then_regular_user(client, monkeypatch):
    _enable_sso(monkeypatch)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )

    status = (await client.get("/api/v1/auth/status")).json()
    assert status == {
        "setup_required": True,
        "registration_enabled": False,
        "sso_enabled": True,
        "local_login_enabled": False,
    }

    resp = await client.post(
        "/api/v1/auth/sso",
        headers={"Cf-Access-Jwt-Assertion": _token(private_key, "Owner@Example.com")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "owner@example.com"
    assert resp.json()["is_admin"] is True
    assert resp.json()["sso_only"] is True

    from nextpanel.main import app
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as second_browser:
        resp = await second_browser.post(
            "/api/v1/auth/sso",
            headers={"Cf-Access-Jwt-Assertion": _token(private_key, "reader@example.com")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_admin"] is False
        assert resp.json()["sso_only"] is True


@respx.mock
async def test_sso_rejects_wrong_audience_and_non_identity_token(client, monkeypatch):
    _enable_sso(monkeypatch)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )

    wrong_audience = _token(private_key, aud=["some-other-application"])
    resp = await client.post(
        "/api/v1/auth/sso", headers={"Cf-Access-Jwt-Assertion": wrong_audience}
    )
    assert resp.status_code == 401

    wrong_issuer = _token(private_key, iss="https://other.cloudflareaccess.com")
    resp = await client.post(
        "/api/v1/auth/sso", headers={"Cf-Access-Jwt-Assertion": wrong_issuer}
    )
    assert resp.status_code == 401

    service_token = _token(private_key, email=None, sub="", common_name="service.access")
    resp = await client.post(
        "/api/v1/auth/sso", headers={"Cf-Access-Jwt-Assertion": service_token}
    )
    assert resp.status_code == 401


@respx.mock
async def test_sso_admin_allowlist_promotes_matching_user(client, monkeypatch):
    _enable_sso(monkeypatch, admin_emails="other@example.com, ADMIN@example.com")
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )

    # The configured identity is an admin even if this is no longer an empty DB.
    first = await client.post(
        "/api/v1/auth/sso",
        headers={"Cf-Access-Jwt-Assertion": _token(private_key, "owner@example.com")},
    )
    assert first.status_code == 200
    await client.post("/api/v1/auth/logout")
    promoted = await client.post(
        "/api/v1/auth/sso",
        headers={"Cf-Access-Jwt-Assertion": _token(private_key, "admin@example.com")},
    )
    assert promoted.status_code == 200
    assert promoted.json()["is_admin"] is True


@respx.mock
async def test_local_auth_endpoints_are_disabled_after_sso_is_configured(client, monkeypatch):
    _enable_sso(monkeypatch)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    await client.post(
        "/api/v1/auth/sso",
        headers={"Cf-Access-Jwt-Assertion": _token(private_key, "owner@example.com")},
    )

    assert (await client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "password1"}
    )).status_code == 403
    assert (await client.post(
        "/api/v1/auth/login", json={"username": "owner@example.com", "password": "password1"}
    )).status_code == 403
    assert (await client.post(
        "/api/v1/auth/register", json={"username": "reader", "password": "password1"}
    )).status_code == 403
    assert (await client.post(
        "/api/v1/users", json={"username": "reader", "password": "password1"}
    )).status_code == 403
    assert (await client.post(
        "/api/v1/auth/password",
        json={"current_password": "password1", "new_password": "password2"},
    )).status_code == 403


async def test_local_login_stays_available_for_partial_sso_configuration(client, monkeypatch):
    monkeypatch.setattr(config, "cloudflare_access_team_domain", TEAM_DOMAIN)
    monkeypatch.setattr(config, "cloudflare_access_audience", "")
    monkeypatch.setattr(config, "local_login_enabled", False)

    status = (await client.get("/api/v1/auth/status")).json()
    assert status["sso_enabled"] is False
    assert status["local_login_enabled"] is True
    resp = await client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "password1"}
    )
    assert resp.status_code == 201


@respx.mock
async def test_sso_only_account_rejects_dummy_password(client, monkeypatch):
    _enable_sso(monkeypatch, local_login=True)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    assert (await client.post('/api/v1/auth/sso', headers={
        'Cf-Access-Jwt-Assertion': _token(private_key, 'owner@example.com')
    })).status_code == 200
    await client.post('/api/v1/auth/logout')
    resp = await client.post('/api/v1/auth/login', json={
        'username': 'owner@example.com', 'password': 'nextpanel-timing-equalizer'
    })
    assert resp.status_code == 401
    assert (await client.get('/api/v1/auth/me')).status_code == 401


@respx.mock
async def test_sso_does_not_adopt_local_account(client, admin, monkeypatch):
    from .conftest import register_user
    await register_user(client, username='victim@example.com')
    _enable_sso(monkeypatch, local_login=True, admin_emails='victim@example.com')
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    resp = await client.post('/api/v1/auth/sso', headers={
        'Cf-Access-Jwt-Assertion': _token(private_key, 'victim@example.com')
    })
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "sso_link_required"
    assert (await client.get('/api/v1/auth/me')).json()['is_admin'] is False


@respx.mock
@pytest.mark.parametrize("forgot_password", [False, True])
async def test_existing_local_account_can_link_and_sign_in_after_local_login_disabled(
    client, monkeypatch, forgot_password,
):
    password = {"password": "existing-admin-password"}
    original = await client.post("/api/v1/auth/setup", json={
        "username": "Owner@Example.com", **password,
    })
    assert original.status_code == 201
    await client.post("/api/v1/auth/logout")

    _enable_sso(monkeypatch)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    headers = {"Cf-Access-Jwt-Assertion": _token(private_key, "owner@example.com")}
    blocked = await client.post("/api/v1/auth/sso", headers=headers)
    assert blocked.status_code == 409
    assert "enable local login" in blocked.json()["detail"]
    assert (await client.post("/api/v1/auth/sso", headers=headers, json=password)).status_code == 403

    if forgot_password:
        from nextpanel import reset_password

        password = {"password": "recovered-admin-password"}
        monkeypatch.setattr(reset_password, "getpass", lambda prompt: password["password"])
        await asyncio.to_thread(reset_password.main, ["Owner@Example.com"])

    monkeypatch.setattr(config, "local_login_enabled", True)
    assert (await client.post("/api/v1/auth/sso", json=password)).status_code == 401
    invalid_assertion = {"Cf-Access-Jwt-Assertion": _token(
        private_key, "owner@example.com", aud=["different-app"],
    )}
    assert (await client.post("/api/v1/auth/sso", headers=invalid_assertion, json=password)).status_code == 401
    assert (await client.post("/api/v1/auth/sso", headers=headers, json={
        "password": "wrong-password",
    })).status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    linked = await client.post("/api/v1/auth/sso", headers=headers, json=password)
    assert linked.status_code == 200, linked.text
    assert linked.json() == original.json()
    await client.post("/api/v1/auth/logout")

    monkeypatch.setattr(config, "local_login_enabled", False)
    different_subject = {"Cf-Access-Jwt-Assertion": _token(
        private_key, "owner@example.com", sub="different-person",
    )}
    assert (await client.post("/api/v1/auth/sso", headers=different_subject)).status_code == 409
    signed_in = await client.post("/api/v1/auth/sso", headers=headers)
    assert signed_in.status_code == 200, signed_in.text
    assert (await client.get("/api/v1/auth/me")).json() == original.json()


@respx.mock
async def test_sso_link_attempts_share_the_local_password_limit(client, monkeypatch):
    from nextpanel.api import auth

    username = "owner@example.com"
    password = "existing-admin-password"
    assert (await client.post("/api/v1/auth/setup", json={
        "username": username, "password": password,
    })).status_code == 201
    await client.post("/api/v1/auth/logout")
    _enable_sso(monkeypatch, local_login=True)
    monkeypatch.setattr(auth, "LOGIN_LIMIT", 2)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    headers = {"Cf-Access-Jwt-Assertion": _token(private_key, username)}

    assert (await client.post("/api/v1/auth/login", json={
        "username": username, "password": "wrong-password",
    })).status_code == 401
    assert (await client.post("/api/v1/auth/sso", headers=headers, json={
        "password": "wrong-password",
    })).status_code == 401
    assert (await client.post("/api/v1/auth/sso", headers=headers, json={
        "password": password,
    })).status_code == 429


@respx.mock
async def test_sso_binding_survives_password_reset_and_rejects_new_subject(client, monkeypatch):
    _enable_sso(monkeypatch, local_login=True)
    private_key, public_jwk = _signing_material()
    respx.get(f"{TEAM_DOMAIN}/cdn-cgi/access/certs").mock(
        return_value=Response(200, json={"keys": [public_jwk]})
    )
    headers = {'Cf-Access-Jwt-Assertion': _token(private_key, 'owner@example.com')}
    user = (await client.post('/api/v1/auth/sso', headers=headers)).json()
    assert (await client.put(f"/api/v1/users/{user['id']}", json={'password':'newpassword1'})).status_code == 200
    assert (await client.post('/api/v1/auth/sso', headers=headers)).status_code == 200
    assert (await client.post('/api/v1/auth/sso', headers={
        'Cf-Access-Jwt-Assertion': _token(private_key, 'owner@example.com', sub='different-person')
    })).status_code == 409


@pytest.mark.parametrize("password", [None, "legacy-password"])
async def test_legacy_sso_binding_has_only_one_winner(client, admin, monkeypatch, password):
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession
    from nextpanel.api import auth
    from nextpanel.db import session_scope
    from nextpanel.models import User
    from nextpanel.security import UNUSABLE_PASSWORD_HASH, hash_password
    from nextpanel.main import app

    async with session_scope() as session:
        session.add(User(
            username="legacy@example.com",
            password_hash=hash_password(password) if password else UNUSABLE_PASSWORD_HASH,
        ))
        await session.commit()
    _enable_sso(monkeypatch, local_login=True)
    async def verify(assertion):
        return {'email':'legacy@example.com', 'iss':TEAM_DOMAIN, 'sub':assertion}
    monkeypatch.setattr(auth, 'verify_access_token', verify)
    original_execute = AsyncSession.execute
    both_read = asyncio.Event()
    reads = 0
    async def gated_execute(self, statement, *args, **kwargs):
        nonlocal reads
        result = await original_execute(self, statement, *args, **kwargs)
        if str(statement).startswith('SELECT users.') and 'lower(users.username)' in str(statement):
            reads += 1
            if reads == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), 5)
        return result
    monkeypatch.setattr(AsyncSession, 'execute', gated_execute)
    body = {"password": password} if password else None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://test') as other:
        responses = await asyncio.gather(
            client.post('/api/v1/auth/sso', headers={'Cf-Access-Jwt-Assertion':'subject-a'}, json=body),
            other.post('/api/v1/auth/sso', headers={'Cf-Access-Jwt-Assertion':'subject-b'}, json=body),
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
