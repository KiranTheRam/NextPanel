"""Validation for identity assertions issued by Cloudflare Access."""

import asyncio
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from .config import config

JWKS_TTL_SECONDS = 5 * 60
JWKS_MIN_REFRESH_SECONDS = 30
_jwks: dict[str, Any] | None = None
_jwks_domain = ""
_jwks_expires_at = 0.0
_jwks_last_refresh_at = 0.0
_jwks_lock = asyncio.Lock()


class AccessTokenError(ValueError):
    """The Cloudflare assertion could not be trusted as a user identity."""


async def _fetch_jwks(*, force: bool = False) -> dict[str, Any]:
    global _jwks, _jwks_domain, _jwks_expires_at, _jwks_last_refresh_at

    domain = config.cloudflare_team_domain
    now = time.monotonic()
    if (
        _jwks is not None
        and _jwks_domain == domain
        and (
            (not force and now < _jwks_expires_at)
            or (force and now - _jwks_last_refresh_at < JWKS_MIN_REFRESH_SECONDS)
        )
    ):
        return _jwks

    async with _jwks_lock:
        now = time.monotonic()
        if (
            _jwks is not None
            and _jwks_domain == domain
            and (
                (not force and now < _jwks_expires_at)
                or (force and now - _jwks_last_refresh_at < JWKS_MIN_REFRESH_SECONDS)
            )
        ):
            return _jwks
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{domain}/cdn-cgi/access/certs")
                response.raise_for_status()
                jwks = response.json()
            if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
                raise ValueError("invalid JWKS response")
        except (httpx.HTTPError, ValueError) as exc:
            raise AccessTokenError("Cloudflare signing keys are unavailable") from exc
        _jwks = jwks
        _jwks_domain = domain
        _jwks_expires_at = now + JWKS_TTL_SECONDS
        _jwks_last_refresh_at = now
        return jwks


def _key_for_id(jwks: dict[str, Any], kid: str):
    for candidate in jwks["keys"]:
        if isinstance(candidate, dict) and candidate.get("kid") == kid:
            try:
                return RSAAlgorithm.from_jwk(candidate)
            except (jwt.PyJWTError, ValueError, TypeError) as exc:
                raise AccessTokenError("Invalid Cloudflare signing key") from exc
    return None


async def verify_access_token(token: str) -> dict[str, Any]:
    """Verify signature and claims, then return an identity-token payload."""
    if not config.sso_enabled:
        raise AccessTokenError("Cloudflare Access SSO is not configured")
    if len(token) > 16 * 1024:
        raise AccessTokenError("Cloudflare Access token is too large")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AccessTokenError("Unsupported Cloudflare token")

        jwks = await _fetch_jwks()
        key = _key_for_id(jwks, header["kid"])
        if key is None:
            # Access rotates keys. Refresh immediately when an otherwise valid
            # token names a key absent from the short-lived cache.
            jwks = await _fetch_jwks(force=True)
            key = _key_for_id(jwks, header["kid"])
        if key is None:
            raise AccessTokenError("Unknown Cloudflare signing key")

        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=config.cloudflare_access_audience.strip(),
            issuer=config.cloudflare_team_domain,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "email"]},
        )
    except AccessTokenError:
        raise
    except jwt.PyJWTError as exc:
        raise AccessTokenError("Invalid Cloudflare Access token") from exc

    # Service tokens and global org tokens are not people and must never
    # create NextPanel user accounts.
    email = claims.get("email")
    subject = claims.get("sub")
    if claims.get("type") != "app" or not isinstance(email, str) or not email.strip():
        raise AccessTokenError("Cloudflare token does not contain a user identity")
    if not isinstance(subject, str) or not subject.strip():
        raise AccessTokenError("Cloudflare token does not contain a user identity")
    return claims
