import httpx
import respx
from httpx import Response

from .conftest import register_user


async def as_requester(client):
    """A regular user's client. An admin's own requests are approved on the
    spot, so tests of the approval queue submit as someone else; the admin
    `client` then decides."""
    if not (await client.get("/api/v1/auth/me")).json().get("is_admin"):
        return client
    requester = getattr(client, "requester", None)
    if requester is None:
        from nextpanel.main import app

        resp = await client.post("/api/v1/users", json={
            "username": "requester", "password": "requester-pass",
        })
        assert resp.status_code == 201, resp.text
        requester = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        )
        resp = await requester.post("/api/v1/auth/login", json={
            "username": "requester", "password": "requester-pass",
        })
        assert resp.status_code == 200, resp.text
        client.requester = requester
    return requester


async def submit_request(client, body):
    return await (await as_requester(client)).post("/api/v1/requests", json=body)


async def make_request(client, provider_id=111, media_type="manga", **extra):
    body = {
        "media_type": media_type,
        "provider": "mangaupdates" if media_type == "manga" else "comicvine",
        "provider_id": provider_id,
        "title": "One Piece" if media_type == "manga" else "Batman (2016)",
        **extra,
    }
    resp = await submit_request(client, body)
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
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
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
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as other:
        await register_user(other, "reader")
        reader_req = await make_request(other, provider_id=2)

        mine = (await other.get("/api/v1/requests")).json()
        assert [r["id"] for r in mine] == [reader_req["id"]]

        resp = await other.delete(f"/api/v1/requests/{admin_req['id']}")
        assert resp.status_code == 403
        resp = await other.post(f"/api/v1/requests/{admin_req['id']}/refresh")
        assert resp.status_code == 403

    everything = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert len(everything) == 2
    assert {r["username"] for r in everything} == {"requester", "reader"}

    assert (await client.delete(f"/api/v1/requests/{reader_req['id']}")).status_code == 204


async def test_summary_counts_requests_needing_approval(client, configured):
    from nextpanel.main import app

    await make_request(client, provider_id=1)
    denied = await make_request(client, provider_id=2)
    await client.post(f"/api/v1/requests/{denied['id']}/deny", json={})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as reader:
        await register_user(reader)
        await make_request(reader, provider_id=3)
        mine = (await reader.get("/api/v1/requests/summary")).json()
    everyone = (await client.get("/api/v1/requests/summary")).json()
    assert mine == {"needs_approval": 1, "open_issues": 0}
    assert everyone == {"needs_approval": 2, "open_issues": 0}


async def test_request_list_omits_descriptions(client, admin):
    created = await make_request(client, description="A long synopsis")
    assert created["description"] == "A long synopsis"
    listing = (await client.get("/api/v1/requests", params={"scope": "all"})).json()
    assert "description" not in listing[0]


def mock_mangarr_add(series_id=77, downloaded=0, total=100):
    add = respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": series_id})
    )
    respx.get(f"http://mangarr.test/api/v1/series/{series_id}").mock(
        return_value=Response(200, json={
            "id": series_id, "title": "One Piece",
            "chapter_count": total, "downloaded_count": downloaded,
        })
    )
    return add


@respx.mock
async def test_admins_own_request_skips_the_queue(client, configured, monkeypatch):
    from nextpanel import push

    sent = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        sent.append(title)

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)
    add = mock_mangarr_add()
    resp = await client.post("/api/v1/requests", json={
        "media_type": "manga", "provider": "mangaupdates", "provider_id": 111,
        "title": "One Piece",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "processing"
    assert resp.json()["decided_by_username"] == "admin"
    assert add.called
    from .test_push import _drain_tasks

    await _drain_tasks()
    assert sent == []  # nothing for an admin to decide


@respx.mock
async def test_trusted_user_requests_skip_the_queue(client, configured):
    requester = await as_requester(client)
    me = (await requester.get("/api/v1/auth/me")).json()
    assert me["auto_approve"] is False
    first = await make_request(client, provider_id=1)
    assert first["status"] == "pending"

    resp = await client.put(f"/api/v1/users/{me['id']}", json={"auto_approve": True})
    assert resp.json()["auto_approve"] is True
    mock_mangarr_add()
    second = await make_request(client, provider_id=2)
    assert second["status"] == "processing"
    assert second["decided_by_username"] == "requester"


@respx.mock
async def test_failed_automatic_approval_waits_for_an_admin(client, configured, monkeypatch):
    from nextpanel import push

    from .test_push import _drain_tasks

    sent = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        sent.append(body)

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)
    requester = await as_requester(client)
    me = (await requester.get("/api/v1/auth/me")).json()
    await client.put(f"/api/v1/users/{me['id']}", json={"auto_approve": True})
    respx.post("http://mangarr.test/api/v1/series").mock(
        side_effect=httpx.ConnectError("refused")
    )
    req = await make_request(client)
    assert req["status"] == "failed"
    assert req["note"].startswith("Automatic approval failed: Cannot reach mangarr")
    await _drain_tasks()
    assert len(sent) == 1 and "Automatic approval failed" in sent[0]
    summary = (await client.get("/api/v1/requests/summary")).json()
    assert summary == {"needs_approval": 1, "open_issues": 0}


async def test_pending_limit_is_configurable(client, admin):
    reader = await as_requester(client)
    await client.put("/api/v1/settings", json={"max_pending_requests": "2"})
    for provider_id in (1, 2):
        await make_request(reader, provider_id=provider_id)
    resp = await submit_request(reader, {
        "media_type": "manga", "provider": "mangaupdates", "provider_id": 3, "title": "Three",
    })
    assert resp.status_code == 429

    await client.put("/api/v1/settings", json={"max_pending_requests": "0"})  # no limit
    assert (await make_request(reader, provider_id=3))["status"] == "pending"

    bad = await client.put("/api/v1/settings", json={"max_pending_requests": "-1"})
    assert bad.status_code == 422


@respx.mock
async def test_decisions_name_the_admin_who_made_them(client, configured):
    req = await make_request(client, provider_id=1)
    mock_mangarr_add()
    approved = (await client.post(f"/api/v1/requests/{req['id']}/approve", json={})).json()
    assert approved["decided_by_username"] == "admin"

    other = await make_request(client, provider_id=2)
    denied = (await client.post(f"/api/v1/requests/{other['id']}/deny", json={})).json()
    assert denied["decided_by_username"] == "admin"
