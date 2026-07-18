import httpx
import respx
from httpx import Response

from .conftest import register_user


async def make_request(client, provider_id=111, media_type="manga", **extra):
    body = {
        "media_type": media_type,
        "provider": "mangaupdates" if media_type == "manga" else "comicvine",
        "provider_id": provider_id,
        "title": "One Piece" if media_type == "manga" else "Batman (2016)",
        **extra,
    }
    resp = await client.post("/api/v1/requests", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_duplicate_request_conflicts(client, admin):
    await make_request(client)
    resp = await client.post("/api/v1/requests", json={
        "media_type": "manga", "provider": "mangaupdates",
        "provider_id": 111, "title": "One Piece",
    })
    assert resp.status_code == 409


async def test_deny_and_rerequest(client, configured):
    req = await make_request(client)
    resp = await client.post(f"/api/v1/requests/{req['id']}/deny", json={"reason": "nope"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "denied"
    assert resp.json()["note"] == "nope"

    # a denied title can be asked for again and returns to pending
    again = await make_request(client)
    assert again["id"] == req["id"]
    assert again["status"] == "pending"
    assert again["note"] == ""


@respx.mock
async def test_approve_adds_to_mangarr(client, configured):
    req = await make_request(client, english_title="One Piece", alt_titles=["ワンピース"])

    add_route = respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": 77, "title": "One Piece"})
    )
    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=Response(200, json={
            "id": 77, "title": "One Piece",
            "chapter_count": 1100, "downloaded_count": 0,
        })
    )
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "processing"
    assert data["remote_series_id"] == 77
    assert data["total_count"] == 1100

    sent = add_route.calls[0].request
    import json

    payload = json.loads(sent.content)
    assert payload == {
        "mangaupdates_id": 111,
        "root_folder_id": 1,
        "monitored": True,
        "search_now": True,
        "english_title": "One Piece",
        "alt_titles": ["ワンピース"],
    }
    assert sent.headers["x-api-key"] == "manga-key"


@respx.mock
async def test_approve_conflict_adopts_existing_series(client, configured):
    req = await make_request(client, provider_id=222, media_type="comic")
    respx.post("http://pullarr.test/api/v1/series").mock(
        return_value=Response(409, json={"detail": "Series already in library"})
    )
    respx.get("http://pullarr.test/api/v1/series").mock(
        return_value=Response(200, json=[
            {"id": 5, "comicvine_id": 222, "title": "Batman (2016)"},
        ])
    )
    respx.get("http://pullarr.test/api/v1/series/5").mock(
        return_value=Response(200, json={
            "id": 5, "title": "Batman (2016)",
            "issue_count": 150, "downloaded_count": 150,
        })
    )
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.status_code == 200, resp.text
    # everything already downloaded — available immediately
    assert resp.json()["status"] == "available"
    assert resp.json()["remote_series_id"] == 5


@respx.mock
async def test_approve_unreachable_app_stays_pending(client, configured):
    req = await make_request(client)
    respx.post("http://mangarr.test/api/v1/series").mock(
        side_effect=httpx.ConnectError("refused")
    )
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.status_code == 502
    listing = (await client.get("/api/v1/requests")).json()
    assert listing[0]["status"] == "pending"


async def test_approve_without_root_folder_configured(client, admin):
    req = await make_request(client)
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.status_code == 422


async def test_request_visibility_and_withdrawal(client, admin):
    admin_req = await make_request(client, provider_id=1)

    # a second signed-in user only sees + withdraws their own
    from nextpanel.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as other:
        await register_user(other, "reader")
        reader_req = await make_request(other, provider_id=2)

        mine = (await other.get("/api/v1/requests")).json()
        assert [r["id"] for r in mine] == [reader_req["id"]]

        resp = await other.delete(f"/api/v1/requests/{admin_req['id']}")
        assert resp.status_code == 403

    everything = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert len(everything) == 2
    assert {r["username"] for r in everything} == {"admin", "reader"}

    assert (await client.delete(f"/api/v1/requests/{reader_req['id']}")).status_code == 204
