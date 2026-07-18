"""Web Push notifications (VAPID).

A P-256 VAPID key pair is generated on first use and stored in the data dir;
browsers subscribe against its public key and pywebpush signs deliveries with
the private key. Sends are fire-and-forget: a dead push service must never
block or fail an API call, and 404/410 responses prune the subscription.
"""

import asyncio
import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select

from .config import config
from .db import session_scope
from .models import PushSubscription, User

log = logging.getLogger(__name__)

_KEY_FILE = "vapid_private_key.pem"


def _key_path():
    return config.data_dir / _KEY_FILE


def _load_private_key() -> ec.EllipticCurvePrivateKey:
    path = _key_path()
    if not path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        config.data_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        path.chmod(0o600)
        log.info("generated VAPID key pair at %s", path)
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def public_key_b64() -> str:
    """The applicationServerKey browsers subscribe with (base64url, no pad)."""
    point = _load_private_key().public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode()


def _send_sync(subscription: PushSubscription, payload: dict) -> bool:
    """Blocking delivery; returns False when the subscription is gone."""
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=str(_key_path()),
            vapid_claims={"sub": config.vapid_sub},
            timeout=10,
        )
        return True
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            return False
        log.warning("push to %s failed: %s", subscription.endpoint[:60], exc)
        return True  # transient — keep the subscription


async def push_to_users(user_ids: list[int], title: str, body: str, url: str = "/requests") -> None:
    """Deliver a notification to every device of the given users."""
    if not user_ids:
        return
    payload = {"title": title, "body": body, "url": url}
    async with session_scope() as session:
        result = await session.execute(
            select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
        )
        subscriptions = result.scalars().all()
        gone: list[int] = []
        for subscription in subscriptions:
            ok = await asyncio.to_thread(_send_sync, subscription, payload)
            if not ok:
                gone.append(subscription.id)
        if gone:
            await session.execute(
                delete(PushSubscription).where(PushSubscription.id.in_(gone))
            )
            await session.commit()


async def admin_user_ids() -> list[int]:
    async with session_scope() as session:
        result = await session.execute(select(User.id).where(User.is_admin))
        return [row[0] for row in result.all()]


def notify_later(coro) -> None:
    """Schedule a push send without blocking the request handler."""
    task = asyncio.get_running_loop().create_task(coro)
    task.add_done_callback(_log_push_errors)


def _log_push_errors(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.warning("push notification task failed", exc_info=task.exception())


async def notify_admins_new_request(username: str, title: str) -> None:
    await push_to_users(
        await admin_user_ids(),
        "New request awaiting approval",
        f"{username} requested {title}",
    )


async def notify_request_denied(user_id: int, title: str, reason: str) -> None:
    body = f"Your request for {title} was denied"
    if reason:
        body += f": {reason}"
    await push_to_users([user_id], "Request denied", body)


async def notify_request_available(user_id: int, title: str, count: int, media_type) -> None:
    from .models import MediaType

    unit = "chapters" if media_type == MediaType.MANGA else "issues"
    await push_to_users(
        [user_id], f"{title} is available", f"All {count} {unit} are downloaded"
    )
