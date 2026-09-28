import json

import respx
from httpx import Response

from .conftest import set_settings
from .test_requests import submit_request

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


def anilist_search(*media):
    return Response(200, json={"data": {"Page": {"media": list(media)}}})


def anilist_manga(media_id, romaji, english="", year=2020, native="", synonyms=(), country="JP"):
    return {
        "id": media_id, "title": {"romaji": romaji, "english": english or None, "native": native},
        "synonyms": list(synonyms), "description": "A story.",
        "coverImage": {"extraLarge": f"https://s4.anilist.co/{media_id}.jpg"},
        "startDate": {"year": year}, "status": "RELEASING", "chapters": None,
        "averageScore": 80, "countryOfOrigin": country, "genres": ["Action"],
    }


def mock_sources(anilist=(), mangarr_library=(), pullarr_library=()):
    """Stub the reads every search makes besides the app searches."""
    route = respx.post("https://graphql.anilist.co").mock(return_value=anilist_search(*anilist))
    respx.get("http://mangarr.test/api/v1/series").mock(
        return_value=Response(200, json=list(mangarr_library))
    )
    respx.get("http://pullarr.test/api/v1/series").mock(
        return_value=Response(200, json=list(pullarr_library))
    )
    return route


@respx.mock
async def test_search_merges_both_apps(client, configured):
    mock_sources()
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
    mock_sources()
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
    mock_sources()
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[])
    )
    data = (await client.get("/api/v1/search", params={"q": "x"})).json()
    assert "pullarr" in data["errors"]
    assert "mangarr" not in data["errors"]


@respx.mock
async def test_search_annotates_existing_request(client, configured):
    mock_sources()
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT])
    )
    resp = await submit_request(client, {
        "media_type": "manga", "provider": "mangaupdates",
        "provider_id": 111, "title": "One Piece",
    })
    assert resp.status_code == 201

    data = (await client.get("/api/v1/search", params={"q": "one", "media_type": "manga"})).json()
    assert data["results"][0]["request_status"] == "pending"
    assert data["results"][0]["request_id"] == resp.json()["id"]


async def test_search_requires_login(client):
    assert (await client.get("/api/v1/search", params={"q": "x"})).status_code == 401


@respx.mock
async def test_manga_search_puts_anilist_first_without_duplicates(client, configured):
    anilist_route = mock_sources(anilist=[
        anilist_manga(30013, "ONE PIECE", "One Piece", year=1997, native="ワンピース"),
        anilist_manga(105398, "Na Honjaman Level Up", "Solo Leveling", year=2018, country="KR"),
    ])
    niche = {**MANGA_RESULT, "provider_id": "999", "title": "One Piece Party",
             "english_title": "", "alt_titles": [], "year": 2015}
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT, niche])  # MU One Piece (1997) + extra
    )
    respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[COMIC_RESULT])
    )
    data = (await client.get("/api/v1/search", params={"q": "one piece"})).json()

    order = [(r["provider"], r["provider_id"]) for r in data["results"]]
    assert order == [("anilist", 30013), ("anilist", 105398),
                     ("mangaupdates", 999), ("comicvine", 222)]
    solo = data["results"][1]
    assert solo["country"] == "KR" and solo["score"] == 80
    assert solo["alt_titles"] == []
    assert data["results"][0]["alt_titles"] == ["ワンピース"]

    sent = json.loads(anilist_route.calls.last.request.content)
    assert sent["variables"] == {"search": "one piece", "perPage": 20}
    assert "format_in: [MANGA, ONE_SHOT]" in sent["query"]
    assert "isAdult: false" in sent["query"]


@respx.mock
async def test_anilist_results_know_about_the_library_and_requests(client, configured):
    shelved = {"id": 7, "mangaupdates_id": 5, "anilist_id": None, "title": "Berserk",
               "english_title": "", "alt_titles": "", "year": 1989}
    mock_sources(
        anilist=[
            anilist_manga(30002, "Berserk", year=1989),
            anilist_manga(30013, "ONE PIECE", "One Piece", year=1997),
        ],
        mangarr_library=[shelved],
    )
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[])
    )
    # requested earlier from a MangaUpdates result
    await submit_request(client, {
        "media_type": "manga", "provider": "mangaupdates", "provider_id": 111,
        "title": "One Piece", "year": 1997,
    })
    data = (await client.get(
        "/api/v1/search", params={"q": "b", "media_type": "manga"}
    )).json()
    berserk, one_piece = data["results"]
    assert berserk["in_library"] is True  # shelved under its MangaUpdates id
    assert one_piece["request_status"] == "pending"


@respx.mock
async def test_repeated_searches_reuse_app_results(client, configured):
    mock_sources()
    manga = respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT])
    )
    comics = respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[COMIC_RESULT])
    )
    for query in ("one", "One ", " ONE"):
        assert (await client.get("/api/v1/search", params={"q": query})).status_code == 200
    assert manga.call_count == 1
    assert comics.call_count == 1


@respx.mock
async def test_comic_search_skips_anilist(client, configured):
    anilist_route = mock_sources()
    respx.get("http://pullarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[COMIC_RESULT])
    )
    data = (await client.get("/api/v1/search", params={"q": "bat", "media_type": "comic"})).json()
    assert [r["provider"] for r in data["results"]] == ["comicvine"]
    assert not anilist_route.called


@respx.mock
async def test_search_survives_anilist_down(client, configured):
    mock_sources()
    respx.post("https://graphql.anilist.co").mock(return_value=Response(503))
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(
        return_value=Response(200, json=[MANGA_RESULT])
    )
    data = (await client.get("/api/v1/search", params={"q": "one", "media_type": "manga"})).json()
    assert [r["provider"] for r in data["results"]] == ["mangaupdates"]
    assert data["errors"] == {"anilist": "AniList could not be reached"}
