import respx
from httpx import Response

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
    listing = (await client.get("/api/v1/requests")).json()
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
    listing = (await client.get("/api/v1/requests")).json()
    assert listing[0]["status"] == "available"


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
    from nextpanel.status import poll_active_requests

    await poll_active_requests()
    listing = (await client.get("/api/v1/requests")).json()
    row = next(r for r in listing if r["id"] == request_id)
    assert row["status"] == "available"


@respx.mock
async def test_deleted_remote_series_marks_failed(client, configured):
    request_id = await approve_processing_request(client)

    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(404, json={"detail": "Series not found"})
    )
    from nextpanel.status import poll_active_requests

    await poll_active_requests()
    listing = (await client.get("/api/v1/requests")).json()
    row = next(r for r in listing if r["id"] == request_id)
    assert row["status"] == "failed"
    assert "removed" in row["note"]
