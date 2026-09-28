import json

import pytest
import respx
from httpx import Response

from nextpanel import ntfy

from .conftest import set_settings
from .test_push import _drain_tasks
from .test_requests import make_request


def test_topic_url_is_split_into_server_and_topic():
    assert ntfy.split_topic_url("https://ntfy.sh/np-alerts") == ("https://ntfy.sh", "np-alerts")
    assert ntfy.split_topic_url("http://nas.lan/ntfy/np/") == ("http://nas.lan/ntfy", "np")
    for bad in ("https://ntfy.sh", "https://ntfy.sh/", "ftp://ntfy.sh/topic", "ntfy.sh/topic"):
        with pytest.raises(ValueError):
            ntfy.split_topic_url(bad)


@respx.mock
async def test_publish_sends_json_with_click_link_and_token():
    route = respx.post("https://ntfy.test/").mock(return_value=Response(200, json={}))
    sent = await ntfy.publish(
        {"ntfy_url": "https://ntfy.test/np", "ntfy_token": "tk_secret",
         "public_url": "https://requests.example.com/"},
        "New request awaiting approval", "reader requested ダンダダン",
        path="/requests", tags=["inbox_tray"],
    )
    assert sent is True
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer tk_secret"
    assert json.loads(request.content) == {
        "topic": "np",
        "title": "New request awaiting approval",
        "message": "reader requested ダンダダン",
        "tags": ["inbox_tray"],
        "click": "https://requests.example.com/requests",
    }


async def test_publish_is_a_no_op_when_not_configured():
    assert await ntfy.publish({"ntfy_url": ""}, "t", "m") is False


@respx.mock
async def test_new_request_is_published_for_admins(client, configured):
    route = respx.post("https://ntfy.test/").mock(return_value=Response(200, json={}))
    await set_settings(ntfy_url="https://ntfy.test/np")
    await make_request(client)
    await _drain_tasks()
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "New request awaiting approval"
    assert body["message"] == "requester requested One Piece"
    assert "click" not in body  # no public URL configured


@respx.mock
async def test_available_is_published_only_when_enabled(client, configured):
    from .test_webhooks import approve_processing_request, send_import, series_payload

    route = respx.post("https://ntfy.test/").mock(return_value=Response(200, json={}))
    await set_settings(ntfy_url="https://ntfy.test/np", ntfy_notify_available="true")
    await approve_processing_request(client)
    await _drain_tasks()
    route.reset()
    respx.get("http://mangarr.test/api/v1/series/77").mock(
        return_value=series_payload(77, 100, 100)
    )
    await send_import(client)
    await _drain_tasks()
    titles = [json.loads(call.request.content)["title"] for call in route.calls]
    assert titles == ["One Piece is available"]


@respx.mock
async def test_settings_test_button_reports_the_outcome(client, admin):
    respx.post("https://ntfy.test/").mock(
        return_value=Response(403, json={"error": "forbidden"})
    )
    resp = await client.post("/api/v1/settings/test/ntfy", json={"ntfy_url": "https://ntfy.test/np"})
    assert resp.json() == {"ok": False, "version": "", "message": "ntfy returned 403: forbidden"}

    respx.post("https://ntfy.test/").mock(return_value=Response(200, json={}))
    resp = await client.post("/api/v1/settings/test/ntfy", json={"ntfy_url": "https://ntfy.test/np"})
    assert resp.json()["ok"] is True


async def test_ntfy_settings_are_validated_and_the_token_masked(client, admin):
    bad = await client.put("/api/v1/settings", json={"ntfy_url": "https://ntfy.sh"})
    assert bad.status_code == 422
    resp = await client.put("/api/v1/settings", json={
        "ntfy_url": "https://ntfy.sh/np", "ntfy_token": "tk_secret",
    })
    assert resp.status_code == 200
    assert resp.json()["ntfy_token"] == "••••••••"
