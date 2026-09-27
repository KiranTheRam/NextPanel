"""One pooled HTTP client for every outbound call.

mangarr, pullarr, AniList and Cloudflare's signing-key endpoint are called
repeatedly; sharing one client keeps their connections alive between calls
instead of paying a TCP (and for AniList, TLS) handshake every time. Callers
pass their own per-request timeout.
"""

import asyncio

import httpx

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def get_client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    # A connection pool belongs to the event loop that created it. The server
    # runs a single loop; tests start a new one per test.
    if _client is None or _client.is_closed or _client_loop is not loop:
        _client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        _client_loop = loop
    return _client


async def aclose() -> None:
    global _client, _client_loop
    if _client is not None and _client_loop is asyncio.get_running_loop():
        await _client.aclose()
    _client = None
    _client_loop = None
