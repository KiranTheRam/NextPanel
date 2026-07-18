"""Small in-memory rate limiter for the auth endpoints.

Public-facing password endpoints need brute-force protection; everything
else is gated by a session. In-memory is fine here: a restart resetting
counters is harmless, and NextPanel is a single process.
"""

import time

from fastapi import HTTPException, Request

_attempts: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    # Cloudflare tunnel / reverse proxies deliver the real client here; the
    # socket peer is just the proxy. Spoofable only by clients that can reach
    # the port directly, who could rotate source IPs anyway.
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def check(key: str, limit: int, window_seconds: float) -> None:
    """Record an attempt; raise 429 once `limit` attempts land in the window."""
    now = time.monotonic()
    stamps = [t for t in _attempts.get(key, []) if now - t < window_seconds]
    if len(stamps) >= limit:
        raise HTTPException(429, "Too many attempts — try again later")
    stamps.append(now)
    _attempts[key] = stamps


def clear(key: str) -> None:
    """Forget a key (e.g. after a successful login)."""
    _attempts.pop(key, None)


def reset() -> None:
    """Test hook."""
    _attempts.clear()
