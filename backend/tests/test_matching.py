from nextpanel.api.discover import RequestIndex
from nextpanel.library import _index
from nextpanel.models import MediaType, Request, RequestStatus


def test_comic_volumes_with_the_same_name_do_not_match():
    library = _index(
        [{"id": 1, "comicvine_id": 10, "title": "Batman", "year": 2026}],
        {"comicvine": "comicvine_id"}, ["title"],
    )
    assert library.find("comicvine", 10, ["Batman"], 2026) is not None
    assert library.find("comicvine", 20, ["Batman"], 2026) is None

    requests = RequestIndex([Request(
        media_type=MediaType.COMIC, provider="comicvine", provider_id=10,
        title="Batman", english_title="", year=2026, status=RequestStatus.PENDING,
    )])
    assert requests.find("comic", "comicvine", 10, ["Batman"], 2026) is not None
    assert requests.find("comic", "comicvine", 20, ["Batman"], 2026) is None


def test_cross_provider_title_requires_the_same_known_year():
    library = _index(
        [{"id": 1, "mangaupdates_id": 10, "anilist_id": None,
          "title": "Blue Box", "year": 2024}],
        {"anilist": "anilist_id", "mangaupdates": "mangaupdates_id"},
        ["title"],
    )
    assert library.find("anilist", 20, ["Blue Box"], 2024) is not None
    assert library.find("anilist", 20, ["Blue Box"], 2026) is None
    assert library.find("anilist", 20, ["Blue Box"]) is None

    requests = RequestIndex([Request(
        media_type=MediaType.MANGA, provider="mangaupdates", provider_id=10,
        title="Blue Box", english_title="", year=2024, status=RequestStatus.PENDING,
    )])
    assert requests.find("manga", "anilist", 20, ["Blue Box"], 2024) is not None
    assert requests.find("manga", "anilist", 20, ["Blue Box"], 2026) is None
    assert requests.find("manga", "anilist", 20, ["Blue Box"]) is None
