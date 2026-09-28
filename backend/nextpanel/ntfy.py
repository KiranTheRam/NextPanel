"""ntfy (https://ntfy.sh) delivery for admin notifications.

Web push reaches the browsers where someone enabled it; ntfy reaches a phone
app or desktop subscriber of one topic, which suits the admin of a home
server. Messages are published as JSON to the server root so titles in any
script survive (HTTP headers, ntfy's other publishing form, are Latin-1).
"""

import logging
from urllib.parse import urlsplit

import httpx

from . import settings_service
from .db import session_scope
from .http_client import get_client

log = logging.getLogger(__name__)

PUBLISH_TIMEOUT = 10.0


class NtfyError(Exception):
    pass


def split_topic_url(url: str) -> tuple[str, str]:
    """`https://ntfy.example/alerts` -> (`https://ntfy.example`, `alerts`)."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    base_path, _, topic = path.rpartition("/")
    if parts.scheme not in ("http", "https") or not parts.netloc or not topic:
        raise ValueError("ntfy_url must be a topic URL such as https://ntfy.sh/my-topic")
    return f"{parts.scheme}://{parts.netloc}{base_path}", topic


async def publish(
    values: dict[str, str],
    title: str,
    message: str,
    *,
    path: str = "",
    tags: list[str] | None = None,
) -> bool:
    """Send one message to the configured topic. Returns False when ntfy is
    not configured; raises NtfyError when the server refuses or is down."""
    url = values.get("ntfy_url", "").strip()
    if not url:
        return False
    base, topic = split_topic_url(url)
    payload: dict = {"topic": topic, "title": title, "message": message}
    if tags:
        payload["tags"] = tags
    public_url = values.get("public_url", "").strip().rstrip("/")
    if public_url and path:
        payload["click"] = public_url + path
    headers = {}
    if token := values.get("ntfy_token", "").strip():
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = await get_client().post(
            f"{base}/", json=payload, headers=headers, timeout=PUBLISH_TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise NtfyError(f"Cannot reach ntfy at {base}: {exc}") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", "")
        except ValueError:
            detail = resp.text[:200]
        raise NtfyError(f"ntfy returned {resp.status_code}: {detail}".rstrip(": "))
    return True


async def notify(
    title: str,
    message: str,
    *,
    path: str = "",
    tags: list[str] | None = None,
    only_if: str = "",
) -> None:
    """Fire-and-forget delivery for event hooks: never raises. `only_if`
    names a "true"/"false" setting that must be on for this event."""
    async with session_scope() as session:
        values = await settings_service.get_all(session)
    if only_if and values.get(only_if) != "true":
        return
    try:
        await publish(values, title, message, path=path, tags=tags)
    except (NtfyError, ValueError) as exc:
        log.warning("ntfy notification failed: %s", exc)
