import asyncio

import httpx
import respx
from httpx import Response
from sqlalchemy import select

from nextpanel import push
from nextpanel.db import session_scope
from nextpanel.models import PushSubscription

from .conftest import register_user
from .test_requests import make_request

SUB = {
    "endpoint": "https://push.example/send/abc123",
    "expirationTime": None,
    "keys": {"p256dh": "pkey", "auth": "akey"},
}


async def test_vapid_key_endpoint(client, admin):
    resp = await client.get("/api/v1/push/key")
    assert resp.status_code == 200
    key = resp.json()["key"]
    assert len(key) > 60 and "=" not in key  # base64url, unpadded


async def test_subscribe_and_replace(client, admin):
    assert (await client.post("/api/v1/push/subscribe", json=SUB)).status_code == 204
    # same device subscribing again (e.g. re-login) replaces, not duplicates
    assert (await client.post("/api/v1/push/subscribe", json=SUB)).status_code == 204
    async with session_scope() as session:
        rows = (await session.execute(select(PushSubscription))).scalars().all()
    assert len(rows) == 1
    assert rows[0].endpoint == SUB["endpoint"]

    assert (await client.post("/api/v1/push/unsubscribe", json=SUB)).status_code == 204
    async with session_scope() as session:
        rows = (await session.execute(select(PushSubscription))).scalars().all()
    assert rows == []


async def test_push_requires_login(client):
    assert (await client.get("/api/v1/push/key")).status_code == 401
    assert (await client.post("/api/v1/push/subscribe", json=SUB)).status_code == 401


async def _drain_tasks():
    # let notify_later fire-and-forget tasks run
    for _ in range(3):
        await asyncio.sleep(0.02)


async def test_new_request_notifies_admins(client, admin, monkeypatch):
    sent: list[tuple[list[int], str, str, str]] = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        sent.append((sorted(user_ids), title, body, url))

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)

    from nextpanel.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as reader:
        await register_user(reader)
        await make_request(reader)
    await _drain_tasks()

    assert len(sent) == 1
    user_ids, title, body, url = sent[0]
    assert user_ids == [admin["id"]]
    assert "reader" in body and "One Piece" in body
    assert url == "/requests"


async def test_deny_notifies_owner(client, configured, monkeypatch):
    sent = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        sent.append((user_ids, title, body, url))

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)

    req = await make_request(client)
    await client.post(f"/api/v1/requests/{req['id']}/deny", json={"reason": "already have it"})
    await _drain_tasks()

    denied = [s for s in sent if s[1] == "Request denied"]
    assert len(denied) == 1
    assert denied[0][0] == [admin_id_of(req)] or denied[0][0] == [1]
    assert "already have it" in denied[0][2]
    assert denied[0][3] == "/title/manga/mangaupdates/111?title=One+Piece"


def admin_id_of(req):
    return 1  # the admin fixture is user id 1 and made the request


@respx.mock
async def test_available_transition_notifies_owner(client, configured, monkeypatch):
    sent = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        sent.append((user_ids, title, body, url))

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)

    req = await make_request(client)
    respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": 77})
    )
    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 100, "downloaded_count": 100,
        })
    )
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.json()["status"] == "available"
    await _drain_tasks()

    available = [s for s in sent if "available" in s[1]]
    assert len(available) == 1
    assert available[0][1] == "One Piece is available"
    assert "100 chapters" in available[0][2]
    assert available[0][3] == "/title/manga/mangaupdates/111?title=One+Piece"


async def test_gone_subscription_pruned(client, admin, monkeypatch):
    await client.post("/api/v1/push/subscribe", json=SUB)

    def fake_send_sync(subscription, payload):
        return False  # push service says 410 Gone

    monkeypatch.setattr(push, "_send_sync", fake_send_sync)
    await push.push_to_users([admin["id"]], "t", "b")
    async with session_scope() as session:
        rows = (await session.execute(select(PushSubscription))).scalars().all()
    assert rows == []
