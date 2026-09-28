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


def card(media_id, romaji, *, type="MANGA", format="MANGA", adult=False, year=2020):
    return {
        "id": media_id, "type": type, "format": format, "isAdult": adult,
        "status": "FINISHED", "title": {"romaji": romaji, "english": None, "native": None},
        "synonyms": [], "coverImage": {"large": f"https://s4.anilist.co/{media_id}.jpg"},
        "startDate": {"year": year}, "averageScore": 70, "countryOfOrigin": "JP",
    }


def anilist_detail(media_id=101, romaji="Dandadan", **extra):
    return Response(200, json={"data": {"Media": {**extra,
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
async def test_detail_falls_back_to_saved_request_during_app_outage(client, configured):
    from .test_requests import make_request

    request = await make_request(client, provider_id=42, description="Saved overview", year=2026)
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(502))
    respx.get("http://mangarr.test/api/v1/search/metadata").mock(return_value=Response(502))

    response = await client.get("/api/v1/detail/manga/mangaupdates/42?title=One%20Piece")
    assert response.status_code == 200
    assert response.json()["description"] == "Saved overview"
    assert response.json()["request_id"] == request["id"]


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


@respx.mock
async def test_detail_reuses_the_library_snapshot(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail())
    listing = respx.get("http://mangarr.test/api/v1/series").mock(
        return_value=Response(200, json=[])
    )
    for _ in range(3):
        assert (await client.get("/api/v1/detail/manga/anilist/101")).status_code == 200
    assert listing.call_count == 1


@respx.mock
async def test_approval_refreshes_the_library_snapshot(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail())
    shelved = {"id": 77, "anilist_id": 101, "mangaupdates_id": None, "title": "Dandadan",
               "english_title": "", "alt_titles": ""}
    listing = respx.get("http://mangarr.test/api/v1/series").mock(side_effect=[
        Response(200, json=[]),
        Response(200, json=[shelved]),
    ])
    respx.post("http://mangarr.test/api/v1/series").mock(
        return_value=Response(201, json={"id": 77})
    )
    respx.get("http://mangarr.test/api/v1/series/77").mock(return_value=Response(200, json={
        **shelved, "chapter_count": 10, "downloaded_count": 0, "chapters": [],
    }))

    assert (await client.get("/api/v1/detail/manga/anilist/101")).json()["in_library"] is False
    req = await make_anilist_request(client, 101, "Dandadan")
    await client.post(f"/api/v1/requests/{req['id']}/approve", json={})

    # the series added by the approval shows immediately, not after the TTL
    assert (await client.get("/api/v1/detail/manga/anilist/101")).json()["in_library"] is True
    assert listing.call_count == 2



@respx.mock
async def test_detail_lists_related_manga_recommendations_and_links(client, configured):
    respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail(
        siteUrl="https://anilist.co/manga/101",
        externalLinks=[
            {"site": "MANGA Plus", "url": "https://mangaplus.shueisha.co.jp/titles/1",
             "type": "STREAMING", "language": "English"},
            {"site": "MANGA Plus", "url": "https://mangaplus.shueisha.co.jp/titles/2",
             "type": "STREAMING", "language": "Spanish"},
            {"site": "VIZ", "url": "https://www.viz.com/dandadan", "type": "STREAMING",
             "language": "English"},
            {"site": "VIZ", "url": "https://www.viz.com/read/dandadan", "type": "STREAMING",
             "language": "English"},
            {"site": "Sketchy", "url": "javascript:alert(1)", "type": "INFO"},
        ],
        relations={"edges": [
            {"relationType": "SEQUEL", "node": card(201, "Dandadan Part 2")},
            {"relationType": "ADAPTATION", "node": card(301, "Dandadan (anime)", type="ANIME", format="TV")},
            {"relationType": "SPIN_OFF", "node": card(202, "Dandadan: Light Novel", format="NOVEL")},
            {"relationType": "CHARACTER", "node": card(203, "Crossover")},
        ]},
        recommendations={"nodes": [
            {"mediaRecommendation": card(401, "Chainsaw Man")},
            {"mediaRecommendation": card(402, "Adult Title", adult=True)},
            {"mediaRecommendation": None},
        ]},
    ))
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[
        {"id": 9, "anilist_id": 401, "title": "Chainsaw Man", "year": 2018},
    ]))

    data = (await client.get("/api/v1/detail/manga/anilist/101")).json()
    assert [(r["provider_id"], r["subtitle"]) for r in data["related"]] == [(201, "Sequel")]
    assert data["related"][0]["provider"] == "anilist"
    assert [r["provider_id"] for r in data["recommendations"]] == [401]
    assert data["recommendations"][0]["in_library"] is True
    assert data["links"] == [
        {"label": "AniList", "url": "https://anilist.co/manga/101"},
        {"label": "MANGA Plus (English)", "url": "https://mangaplus.shueisha.co.jp/titles/1"},
        {"label": "MANGA Plus (Spanish)", "url": "https://mangaplus.shueisha.co.jp/titles/2"},
        {"label": "VIZ (English)", "url": "https://www.viz.com/dandadan"},
    ]


@respx.mock
async def test_shelved_mangaupdates_series_uses_its_anilist_id(client, configured):
    anilist = respx.post("https://graphql.anilist.co").mock(return_value=anilist_detail(
        relations={"edges": [{"relationType": "PREQUEL", "node": card(200, "Before")}]},
        recommendations={"nodes": []},
    ))
    respx.get("http://mangarr.test/api/v1/series").mock(return_value=Response(200, json=[
        {"id": 7, "anilist_id": 101, "mangaupdates_id": 55099564912, "title": "One Piece"},
    ]))
    respx.get("http://mangarr.test/api/v1/series/7").mock(return_value=Response(200, json={
        "id": 7, "title": "One Piece", "chapters": [], "downloaded_count": 0,
    }))
    data = (await client.get(
        "/api/v1/detail/manga/mangaupdates/55099564912", params={"title": "One Piece"}
    )).json()
    assert data["title"] == "One Piece"  # the library's metadata, not AniList's
    assert [r["subtitle"] for r in data["related"]] == ["Prequel"]
    assert {link["label"]: link["url"] for link in data["links"]} == {
        "AniList": "https://anilist.co/manga/101",
        "MangaUpdates": "https://www.mangaupdates.com/series/pb8uwds",
    }
    assert anilist.called


@respx.mock
async def test_comic_detail_links_to_comicvine(client, configured):
    respx.get("http://pullarr.test/api/v1/series").mock(return_value=Response(200, json=[]))
    respx.get("http://pullarr.test/api/v1/search/metadata").mock(return_value=Response(200, json=[
        {"provider": "comicvine", "provider_id": "796", "title": "Batman", "year": 1940},
    ]))
    data = (await client.get("/api/v1/detail/comic/comicvine/796", params={"title": "Batman"})).json()
    assert data["links"] == [
        {"label": "ComicVine", "url": "https://comicvine.gamespot.com/volume/4050-796/"}
    ]
    assert data["related"] == [] and data["recommendations"] == []
