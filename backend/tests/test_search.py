import respx
from httpx import Response

from .conftest import set_settings

MANGA_RESULT = {
    "provider": "mangaupdates",
    "provider_id": "111",
    "title": "One Piece",
    "english_title": "One Piece",
    "alt_titles": ["ワンピース"],
    "description": "Pirates.",
    "status": "releasing",
    "year": 1997,
    "cover_url": "https://cdn.mangaupdates.com/op.jpg",
    "genres": [],
    "total_chapters": 1100,
    "in_library": False,
}

COMIC_RESULT = {
    "provider": "comicvine",
    "provider_id": "222",
    "title": "Batman (2016)",
    "alt_titles": [],
    "description": "Gotham.",
    "status": "continuing",
    "publisher": "DC Comics",
    "year": 2016,
    "cover_url": "https://comicvine.gamespot.com/bat.jpg",
    "genres": [],
    "total_issues": 150,
    "in_library": True,
}


@respx.mock
async def test_search_merges_both_apps(client, configured):
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT])
    )
    respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[COMIC_RESULT])
    )
    resp = await client.get("/api/v1/search", params={"q": "one"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["errors"] == {}
    kinds = {(r["media_type"], r["provider_id"]) for r in data["results"]}
    assert kinds == {("manga", 111), ("comic", 222)}
    comic = next(r for r in data["results"] if r["media_type"] == "comic")
    assert comic["in_library"] is True
    assert comic["publisher"] == "DC Comics"


@respx.mock
async def test_search_survives_one_app_down(client, configured):
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT])
    )
    respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(500, json={"detail": "boom"})
    )
    data = (await client.get("/api/v1/search", params={"q": "one"})).json()
    assert len(data["results"]) == 1
    assert "pullarr" in data["errors"]


@respx.mock
async def test_search_reports_unconfigured_app(client, admin):
    await set_settings(mangarr_url="http://mangarr.test", mangarr_api_key="k")
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[])
    )
    data = (await client.get("/api/v1/search", params={"q": "x"})).json()
    assert "pullarr" in data["errors"]
    assert "mangarr" not in data["errors"]


@respx.mock
async def test_search_annotates_existing_request(client, configured):
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT])
    )
    resp = await client.post("/api/v1/requests", json={
        "media_type": "manga", "provider": "mangaupdates",
        "provider_id": 111, "title": "One Piece",
    })
    assert resp.status_code == 201

    data = (await client.get("/api/v1/search", params={"q": "one", "media_type": "manga"})).json()
    assert data["results"][0]["request_status"] == "pending"
    assert data["results"][0]["request_id"] == resp.json()["id"]


async def test_search_requires_login(client):
    assert (await client.get("/api/v1/search", params={"q": "x"})).status_code == 401
