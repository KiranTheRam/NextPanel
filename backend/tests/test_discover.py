from datetime import date

import pytest
import respx
from httpx import Response

from nextpanel import discover
from nextpanel.discover import _previous_season, _season_start, sections_spec

from .test_requests import make_request


@pytest.fixture(autouse=True)
def fresh_cache():
    discover.clear_cache()
    yield
    discover.clear_cache()


def anilist_media(media_id: int, romaji: str, english: str = "", year: int = 2026):
    return {
        "id": media_id,
        "title": {"romaji": romaji, "english": english or None},
        "description": "<i>Some</i> story",
        "coverImage": {"extraLarge": f"http://img/{media_id}.jpg", "large": None},
        "startDate": {"year": year},
        "status": "RELEASING",
        "averageScore": 84,
        "popularity": 12345,
        "genres": ["Action"],
    }


def anilist_response(*media):
    return Response(200, json={"data": {"Page": {"media": list(media)}}})


def test_season_math():
    assert _season_start(date(2026, 7, 18)) == date(2026, 7, 1)
    assert _previous_season(date(2026, 7, 18)) == (date(2026, 4, 1), date(2026, 7, 1))
    assert _previous_season(date(2026, 2, 2)) == (date(2025, 10, 1), date(2026, 1, 1))
    titles = [s["title"] for s in sections_spec(date(2026, 7, 18))]
    assert "New This Season (Summer 2026)" in titles
    assert "Top Rated Last Season (Spring 2026)" in titles


@respx.mock
async def test_discover_sections_and_html_stripping(client, admin):
    respx.post("https://graphql.anilist.co").mock(
        return_value=anilist_response(anilist_media(101, "Dandadan", "Dandadan"))
    )
    resp = await client.get("/api/v1/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["errors"] == {}
    assert len(data["sections"]) == 4
    item = data["sections"][0]["items"][0]
    assert item["provider"] == "anilist"
    assert item["provider_id"] == 101
    assert item["description"] == "Some story"
    assert item["score"] == 84


@respx.mock
async def test_discover_hides_requested_and_library_titles(client, configured):
    respx.get("http://pullarr.test/api/v1/discover/releases").mock(
        return_value=Response(200, json=[])
    )
    respx.post("https://graphql.anilist.co").mock(
        return_value=anilist_response(
            anilist_media(101, "Dandadan", "Dandadan"),
            anilist_media(202, "One Piece", "One Piece"),
            anilist_media(303, "Berserk"),
            anilist_media(404, "Vagabond"),
        )
    )
    # 101 already requested via anilist; One Piece requested via mangaupdates
    # (matched by title); Berserk in the mangarr library (matched by title)
    await make_anilist_request(client, 101, "Dandadan")
    r = await client.post("/api/v1/requests", json={
        "media_type": "manga", "provider": "anilist",
        "provider_id": 101, "title": "Dandadan",
    })
    assert r.status_code == 409  # sanity: dedupe by provider works
    await make_request(client, provider_id=999, media_type="manga")  # "One Piece"

    respx.get("http://mangarr.test/api/v1/series").mock(
        return_value=Response(200, json=[{
            "id": 9, "anilist_id": None, "mangaupdates_id": 555,
            "title": "Berserk", "english_title": "", "alt_titles": "Berserker\nベルセルク",
        }])
    )
    data = (await client.get("/api/v1/discover")).json()
    shown = {i["provider_id"] for i in data["sections"][0]["items"]}
    assert shown == {404}  # only Vagabond survives


async def make_anilist_request(client, provider_id, title):
    resp = await client.post("/api/v1/requests", json={
        "media_type": "manga", "provider": "anilist",
        "provider_id": provider_id, "title": title,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@respx.mock
async def test_approving_anilist_request_adds_by_anilist_id(client, configured):
    req = await make_anilist_request(client, 30013, "One Piece")
    add_route = respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": 5})
    )
    respx.get("http://mangarr.test/api/v1/series/5").mock(
        return_value=Response(200, json={
            "id": 5, "title": "One Piece",
            "chapter_count": 1100, "downloaded_count": 0,
        })
    )
    resp = await client.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert resp.status_code == 200, resp.text

    import json

    payload = json.loads(add_route.calls[0].request.content)
    assert payload["anilist_id"] == 30013
    assert "mangaupdates_id" not in payload


@respx.mock
async def test_discover_survives_anilist_down(client, admin):
    respx.post("https://graphql.anilist.co").mock(return_value=Response(500))
    data = (await client.get("/api/v1/discover")).json()
    assert data["sections"] == []
    assert len(data["errors"]) == 4


def comic_entry(volume_id, name, in_library=False, subtitle="#1 · Jul 15"):
    return {
        "comicvine_volume_id": volume_id,
        "volume_name": name,
        "issue_number": "1",
        "issue_name": "Debut",
        "store_date": "2026-07-15",
        "subtitle": subtitle,
        "cover_url": f"http://img/{volume_id}.jpg",
        "in_library": in_library,
    }


@respx.mock
async def test_discover_comic_sections(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_response())
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[]))
    releases_route = respx.get("http://pullarr.test/api/v1/discover/releases").mock(
        return_value=Response(200, json=[
            comic_entry(10, "Batman (2026)"),
            comic_entry(20, "Already Owned", in_library=True),
            comic_entry(30, "Already Requested"),
        ])
    )
    # an existing comic request hides volume 30
    r = await client.post("/api/v1/requests", json={
        "media_type": "comic", "provider": "comicvine",
        "provider_id": 30, "title": "Already Requested",
    })
    assert r.status_code == 201

    data = (await client.get("/api/v1/discover")).json()
    assert data["errors"] == {}
    comic_sections = [s for s in data["sections"] if s["key"].startswith("comics_")]
    assert [s["title"] for s in comic_sections] == [
        "New Comics This Week", "New Comic Series This Month",
    ]
    items = comic_sections[0]["items"]
    assert [i["provider_id"] for i in items] == [10]
    assert items[0]["media_type"] == "comic"
    assert items[0]["provider"] == "comicvine"
    assert items[0]["subtitle"] == "#1 · Jul 15"
    assert items[0]["year"] == 2026

    # both windows requested (7-day and 30-day first-issues)
    params = [dict(c.request.url.params) for c in releases_route.calls]
    assert {p["days"] for p in params} == {"7", "30"}
    assert {p["first_issues"] for p in params} == {"false", "true"}


@respx.mock
async def test_discover_comics_survive_pullarr_down(client, configured):
    respx.post("https://graphql.anilist.co").mock(
        return_value=anilist_response(anilist_media(1, "Test"))
    )
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[]))
    respx.get("http://pullarr.test/api/v1/discover/releases").mock(
        return_value=Response(502, json={"detail": "boom"})
    )
    data = (await client.get("/api/v1/discover")).json()
    assert len([s for s in data["sections"] if not s["key"].startswith("comics_")]) == 4
    assert "comics_week" in data["errors"]


@respx.mock
async def test_discover_cached_between_calls(client, admin):
    route = respx.post("https://graphql.anilist.co").mock(
        return_value=anilist_response(anilist_media(1, "Test"))
    )
    await client.get("/api/v1/discover")
    first = route.call_count
    await client.get("/api/v1/discover")
    assert route.call_count == first  # served from cache
