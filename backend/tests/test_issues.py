import json

import httpx
import respx
from httpx import Response

from nextpanel import push

from .conftest import set_settings
from .test_push import _drain_tasks
from .test_requests import as_requester

REPORT = {
    "media_type": "manga", "provider": "anilist", "provider_id": 101,
    "title": "Dandadan", "cover_url": "https://s4.anilist.co/101.jpg",
    "kind": "missing", "message": "Chapters 40-45 are not there",
}


def capture_pushes(monkeypatch):
    sent = []

    async def fake_push_to_users(user_ids, title, body, url="/requests"):
        sent.append({"to": sorted(user_ids), "title": title, "body": body, "url": url})

    monkeypatch.setattr(push, "push_to_users", fake_push_to_users)
    return sent


@respx.mock
async def test_report_and_resolve_an_issue(client, admin, monkeypatch):
    sent = capture_pushes(monkeypatch)
    ntfy = respx.post("https://ntfy.test/").mock(return_value=Response(200, json={}))
    await set_settings(ntfy_url="https://ntfy.test/np")
    reader = await as_requester(client)
    reader_id = (await reader.get("/api/v1/auth/me")).json()["id"]

    resp = await reader.post("/api/v1/issues", json=REPORT)
    assert resp.status_code == 201
    issue = resp.json()
    assert issue["status"] == "open" and issue["username"] == "requester"
    assert issue["cover_url"] == REPORT["cover_url"]
    await _drain_tasks()
    assert sent == [{
        "to": [admin["id"]], "title": "Issue reported",
        "body": "requester reported missing chapters or issues for Dandadan: "
                "Chapters 40-45 are not there",
        "url": "/requests?view=issues",
    }]
    assert json.loads(ntfy.calls.last.request.content)["title"] == "Issue reported"

    summary = (await client.get("/api/v1/requests/summary")).json()
    assert summary["open_issues"] == 1
    everything = (await client.get("/api/v1/issues", params={"scope": "all"})).json()
    assert [i["id"] for i in everything] == [issue["id"]]
    for_title = (await reader.get("/api/v1/issues", params={
        "media_type": "manga", "provider": "anilist", "provider_id": 101, "status": "open",
    })).json()
    assert [i["id"] for i in for_title] == [issue["id"]]

    sent.clear()
    resolved = (await client.post(
        f"/api/v1/issues/{issue['id']}/resolve", json={"resolution": "Re-downloaded them"}
    )).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by_username"] == "admin"
    await _drain_tasks()
    assert sent == [{
        "to": [reader_id], "title": "Issue resolved",
        "body": "Your report about Dandadan was resolved: Re-downloaded them",
        "url": "/title/manga/anilist/101?title=Dandadan",
    }]
    assert (await client.get("/api/v1/requests/summary")).json()["open_issues"] == 0

    reopened = (await client.post(f"/api/v1/issues/{issue['id']}/reopen")).json()
    assert reopened["status"] == "open" and reopened["resolved_at"] is None


async def test_issue_visibility_and_withdrawal(client, admin):
    from nextpanel.main import app

    reader = await as_requester(client)
    mine = (await reader.post("/api/v1/issues", json=REPORT)).json()
    admins = (await client.post("/api/v1/issues", json={**REPORT, "kind": "other"})).json()

    assert (await reader.get("/api/v1/issues", params={"scope": "all"})).status_code == 403
    assert [i["id"] for i in (await reader.get("/api/v1/issues")).json()] == [mine["id"]]
    assert (await reader.delete(f"/api/v1/issues/{admins['id']}")).status_code == 403
    assert (await reader.post(f"/api/v1/issues/{mine['id']}/resolve", json={})).status_code == 403

    await client.post(f"/api/v1/issues/{mine['id']}/resolve", json={})
    assert (await reader.delete(f"/api/v1/issues/{mine['id']}")).status_code == 400
    assert (await client.delete(f"/api/v1/issues/{mine['id']}")).status_code == 204

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as anonymous:
        assert (await anonymous.get("/api/v1/issues")).status_code == 401


async def test_open_reports_are_capped(client, admin):
    reader = await as_requester(client)
    for n in range(10):
        resp = await reader.post("/api/v1/issues", json={**REPORT, "provider_id": n})
        assert resp.status_code == 201
    resp = await reader.post("/api/v1/issues", json={**REPORT, "provider_id": 99})
    assert resp.status_code == 429


async def test_report_validation(client, admin):
    bad_kind = await client.post("/api/v1/issues", json={**REPORT, "kind": "angry"})
    assert bad_kind.status_code == 422
    cover = await client.post("/api/v1/issues", json={
        **REPORT, "cover_url": "https://attacker.example/pixel.png",
    })
    assert cover.json()["cover_url"] == ""


async def test_deleting_a_user_removes_their_reports(client, admin):
    reader = await as_requester(client)
    reader_id = (await reader.get("/api/v1/auth/me")).json()["id"]
    await reader.post("/api/v1/issues", json=REPORT)
    assert (await client.delete(f"/api/v1/users/{reader_id}")).status_code == 204
    assert (await client.get("/api/v1/issues", params={"scope": "all"})).json() == []
