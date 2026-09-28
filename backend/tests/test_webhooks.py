import asyncio

import respx
from httpx import Response
from sqlalchemy import select

from nextpanel import push, status
from nextpanel.arr import ArrError
from nextpanel.db import session_scope
from nextpanel.models import MediaType, Request, RequestStatus, User

from .test_push import _drain_tasks
from .test_requests import make_request


async def approve_processing_request(client, provider_id=111):
    """A request approved against mocked mangarr, left in processing."""
    req = await make_request(client, provider_id=provider_id)
    respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": 77})
    )
    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 100, "downloaded_count": 0,
        })
    )
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.json()["status"] == "processing"
    return req["id"]


@respx.mock
async def test_webhook_advances_status(client, configured):
    request_id = await approve_processing_request(client)

    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 100, "downloaded_count": 40,
        })
    )
    resp = await client.post(
        "/api/v1/webhooks/mangarr",
        json={"event": "import", "series_id": 77},
        headers={"X-Webhook-Secret": "hook-secret"},
    )
    assert resp.status_code == 204
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    row = next(r for r in listing if r["id"] == request_id)
    assert row["status"] == "partially_available"
    assert row["downloaded_count"] == 40

    # everything downloaded -> available
    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 100, "downloaded_count": 100,
        })
    )
    await client.post(
        "/api/v1/webhooks/mangarr",
        json={"event": "import", "series_id": 77},
        headers={"X-Webhook-Secret": "hook-secret"},
    )
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert listing[0]["status"] == "available"

    # Ongoing series can gain new chapters after being fully downloaded.
    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 101, "downloaded_count": 100,
        })
    )
    await client.post(
        "/api/v1/webhooks/mangarr",
        json={"event": "import", "series_id": 77},
        headers={"X-Webhook-Secret": "hook-secret"},
    )
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert listing[0]["status"] == "partially_available"
    assert listing[0]["total_count"] == 101


@respx.mock
async def test_webhook_auth(client, configured):
    resp = await client.post(
        "/api/v1/webhooks/mangarr", json={"series_id": 1},
        headers={"X-Webhook-Secret": "wrong"},
    )
    assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/webhooks/nonsense", json={"series_id": 1},
        headers={"X-Webhook-Secret": "hook-secret"},
    )
    assert resp.status_code == 404


async def test_webhook_disabled_without_secret(client, admin):
    resp = await client.post(
        "/api/v1/webhooks/mangarr", json={"series_id": 1},
        headers={"X-Webhook-Secret": ""},
    )
    assert resp.status_code == 403


@respx.mock
async def test_poll_job_updates_requests(client, configured):
    request_id = await approve_processing_request(client)

    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 100, "downloaded_count": 100,
        })
    )
    from nextpanel import status
    from nextpanel.status import poll_active_requests

    await poll_active_requests()
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    row = next(r for r in listing if r["id"] == request_id)
    assert row["status"] == "available"

    series = respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 101, "downloaded_count": 100,
        })
    )
    # completed series are only rechecked on every Nth poll
    calls_before = series.call_count
    for _ in range(status.AVAILABLE_POLL_EVERY - 1):
        await poll_active_requests()
    assert series.call_count == calls_before
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert listing[0]["status"] == "available"

    await poll_active_requests()
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert listing[0]["status"] == "partially_available"


@respx.mock
async def test_deleted_remote_series_marks_failed(client, configured):
    request_id = await approve_processing_request(client)

    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(404, json={"detail": "Series not found"})
    )
    from nextpanel.status import poll_active_requests

    await poll_active_requests()
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    row = next(r for r in listing if r["id"] == request_id)
    assert row["status"] == "failed"
    assert "removed" in row["note"]


async def send_import(client, series_id=77):
    resp = await client.post(
        "/api/v1/webhooks/mangarr",
        json={"event": "import", "series_id": series_id},
        headers={"X-Webhook-Secret": "hook-secret"},
    )
    assert resp.status_code == 204


def series_payload(series_id, total, downloaded):
    return Response(200, json={
        "id": series_id, "title": "One Piece",
        "chapter_count": total, "downloaded_count": downloaded,
    })


@respx.mock
async def test_available_is_announced_once_per_fulfillment(client, configured, monkeypatch):
    sent = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        if title.endswith("is available"):
            sent.append(title)

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)
    request_id = await approve_processing_request(client)

    # completes, gains a chapter, completes again: one notification
    for total, downloaded in ((100, 100), (101, 100), (101, 101)):
        respx.get("http://mangarr.test/api/v1/series/77").mock(
            return_value=series_payload(77, total, downloaded)
        )
        await send_import(client)
    await _drain_tasks()
    assert sent == ["One Piece is available"]

    # the series is deleted and the admin retries: a new fulfillment
    respx.get("http://mangarr.test/api/v1/series/77").mock(return_value=Response(404))
    await send_import(client)
    respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": 78})
    )
    respx.get("http://mangarr.test/api/v1/series/78").mock(
        return_value=series_payload(78, 101, 101)
    )
    resp = await client.post(f"/api/v1/requests/{request_id}/approve", json={})
    assert resp.json()["status"] == "available"
    await _drain_tasks()
    assert sent == ["One Piece is available"] * 2


def test_only_a_404_status_marks_the_series_removed():
    request = Request(id=1, status=RequestStatus.PROCESSING, note="",
                      downloaded_count=0, total_count=0)
    # an unreachable app whose address happens to contain "404"
    unreachable = ArrError("Cannot reach mangarr at http://10.0.4.40:4040: timed out")
    assert status._apply_status(request, unreachable, "mangarr") is False
    server_error = ArrError("mangarr returned 500: lookup 404 failed", 500)
    assert status._apply_status(request, server_error, "mangarr") is False
    assert request.status == RequestStatus.PROCESSING

    missing = ArrError("mangarr returned 404: Not Found", 404)
    assert status._apply_status(request, missing, "mangarr") is True
    assert request.status == RequestStatus.FAILED


async def add_processing_requests(series_ids):
    async with session_scope() as session:
        user = (await session.execute(select(User))).scalars().first()
        for n, series_id in enumerate(series_ids):
            session.add(Request(
                user_id=user.id, media_type=MediaType.MANGA, provider="mangaupdates",
                provider_id=5000 + n, title=f"Series {n}",
                status=RequestStatus.PROCESSING, remote_series_id=series_id,
            ))
        await session.commit()


@respx.mock
async def test_poll_reads_each_series_once(client, configured):
    # e.g. an AniList and a MangaUpdates request that adopted the same series
    await add_processing_requests([77, 77])
    series = respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=series_payload(77, 100, 40)
    )
    await status.poll_active_requests()
    assert series.call_count == 1
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert [r["status"] for r in listing] == ["partially_available"] * 2


@respx.mock
async def test_poll_reads_series_concurrently_within_the_limit(client, configured):
    series_ids = list(range(100, 100 + status.POLL_CONCURRENCY * 2))
    await add_processing_requests(series_ids)
    active = peak = 0

    async def slow_series(request, series_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return series_payload(int(series_id), 10, 10)

    respx.get(url__regex=r"http://mangarr\.test/api/v1/series/(?P<series_id>\d+)").mock(
        side_effect=slow_series
    )
    await status.poll_active_requests()
    assert peak == status.POLL_CONCURRENCY
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert {r["status"] for r in listing} == {"available"}
