"""Password hashing (stdlib scrypt) and session token generation."""

import hashlib
import hmac
import secrets
from urllib.parse import urlparse

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex),
            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    """Sessions are stored as digests so a leaked DB/backup can't be replayed
    as live cookies."""
    return hashlib.sha256(token.encode()).hexdigest()


# verified against when a login names a nonexistent user, so the response
# takes as long as a real password check (no username enumeration by timing)
DUMMY_PASSWORD_HASH = hash_password("nextpanel-timing-equalizer")


# Covers are displayed in other users' browsers.  Do not let a requester turn
# an admin's browser into a client for arbitrary HTTPS endpoints.
_COVER_HOST_SUFFIXES = (
    ".anilist.co",
    ".mangaupdates.com",
    ".mangadex.org",
    ".mangadex.network",
    ".gamespot.com",
)


def safe_cover_url(value: str) -> str:
    """Return an approved public cover URL, or an empty string.

    The source APIs currently use the allowlisted domains above.  Matching is
    suffix-based but requires a dot prefix, so e.g. ``evilgamespot.com`` is
    not accepted as a Gamespot image host.
    """
    try:
        parsed = urlparse(value)
    except (TypeError, ValueError):
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return ""
    if any(host.endswith(suffix) for suffix in _COVER_HOST_SUFFIXES):
        return value
    return ""
