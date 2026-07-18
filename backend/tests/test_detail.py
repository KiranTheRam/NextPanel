import pytest
import respx
from httpx import Response

from nextpanel import discover

from .test_discover import make_anilist_request


@pytest.fixture(autouse=True)
def fresh_cache():
    discover.clear_cache()
    yield
    discover.clear_cache()


def anilist_detail(media_id=101, romaji="Dandadan"):
    return Response(200, json={"data": {"Media": {
        "id": media_id,
        "title": {"romaji": romaji, "english": "Dan Da Dan", "native": "ダンダダン"},
        "synonyms": ["Dandadan!"],
        "description": "Momo meets <b>Okarun</b>.<br><br>Then aliens.",
        "coverImage": {"extraLarge": "https://s4.anilist.co/cover.jpg", "large": None},
        "bannerImage": "https://s4.anilist.co/banner.jpg",
        "startDate": {"year": 2021},
        "endDate": {"year": None},
        "status": "RELEASING",
        "format": "MANGA",
        "chapters": 240,
        "volumes": 24,
        "averageScore": 85,
        "popularity": 1,
        "genres": ["Action", "Comedy"],
        "countryOfOrigin": "JP",
        "staff": {"edges": [{"role": "Story & Art", "node": {"name": {"full": "Yukinobu Tatsu"}}}]},
    }}})


@respx.mock
async def test_detail_from_anilist_when_not_in_library(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail())
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[]))

    data = (await client.get("/api/v1/detail/manga/anilist/101")).json()
    assert data["title"] == "Dandadan"
    assert data["english_title"] == "Dan Da Dan"
    assert data["status"] == "releasing"
    assert data["total_count"] == 240
    assert data["genres"] == ["Action", "Comedy"]
    assert data["staff"][0]["name"] == "Yukinobu Tatsu"
    # tags stripped, entities unescaped, <br> turned into breaks
    assert data["description"].startswith("Momo meets Okarun.")
    assert "<b>" not in data["description"]
    assert data["in_library"] is False
    assert data["chapters"] == []
    assert data["chapters_available"] is False


@respx.mock
async def test_detail_merges_library_chapters(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail())
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[
        {"id": 7, "anilist_id": 101, "mangaupdates_id": None, "title": "Dandadan",
         "english_title": "", "alt_titles": ""},
    ]))
    respx.get("http://mangarr.test/api/v1/series/7").mock(return_value=Response(200, json={
        "id": 7, "title": "Dandadan", "description": "stale copy", "status": "releasing",
        "cover_url": "", "genres": "Action", "total_chapters": 240, "downloaded_count": 2,
        "chapters": [
            {"number": 1.0, "volume": 1, "title": "That's How Love Starts",
             "downloaded": True, "monitored": True},
            {"number": 2.0, "volume": 1, "title": "That's a Space Alien",
             "downloaded": False, "monitored": True},
        ],
    }))

    data = (await client.get("/api/v1/detail/manga/anilist/101")).json()
    assert data["in_library"] is True
    assert data["library_series_id"] == 7
    assert data["chapters_available"] is True
    assert [c["label"] for c in data["chapters"]] == ["1", "2"]
    assert data["chapters"][0]["title"] == "That's How Love Starts"
    assert data["chapters"][0]["downloaded"] is True
    assert data["downloaded_count"] == 2
    # AniList metadata still wins over mangarr's import-time copy
    assert data["description"].startswith("Momo meets Okarun.")


@respx.mock
async def test_detail_reports_existing_request(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail())
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[]))
    await make_anilist_request(client, 101, "Dandadan")

    data = (await client.get("/api/v1/detail/manga/anilist/101")).json()
    assert data["request_status"] == "pending"
    assert data["request_id"]


@respx.mock
async def test_comic_detail_falls_back_to_metadata_search(client, configured):
    respx.get("http://pullarr.test/api/v1/series").mock(return_value=Response(200, json=[]))
    search = respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[
            {"provider": "comicvine", "provider_id": "42", "title": "Batman",
             "alt_titles": [], "description": "The Dark Knight.", "status": "ended",
             "publisher": "DC", "year": 2016, "cover_url": "", "genres": [],
             "total_issues": 100, "in_library": False},
        ])
    )
    data = (await client.get("/api/v1/detail/comic/comicvine/42?title=Batman")).json()
    assert data["title"] == "Batman"
    assert data["publisher"] == "DC"
    assert data["total_count"] == 100
    assert dict(search.calls[0].request.url.params)["q"] == "Batman"


@respx.mock
async def test_detail_404_when_nothing_found(client, configured):
    respx.post("https://graphql.anilist.co").mock(
        return_value=Response(200, json={"data": {"Media": None}})
    )
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[]))
    resp = await client.get("/api/v1/detail/manga/anilist/999")
    assert resp.status_code == 404


async def test_detail_requires_login(client, admin):
    await client.post("/api/v1/auth/logout")
    resp = await client.get("/api/v1/detail/manga/anilist/101")
    assert resp.status_code == 401
