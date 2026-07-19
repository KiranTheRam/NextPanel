from datetime import datetime, timedelta, timezone

import jwt
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
