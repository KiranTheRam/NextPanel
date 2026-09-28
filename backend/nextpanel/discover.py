"""AniList-powered discovery sections for the Discover home page.

AniList's browse queries are public GraphQL (no auth); results are cached
per section so the whole page costs at most four upstream requests every
half hour, well inside AniList's rate limits. Manga have no formal
"seasons", so seasonal sections use start-date quarters (Winter Jan-Mar,
Spring Apr-Jun, Summer Jul-Sep, Fall Oct-Dec). AniList's country metadata
also lets the API keep Korean manhwa out of the general manga rows.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from typing import Any

from .http_client import get_client
from .security import safe_cover_url

log = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"
CACHE_TTL_SECONDS = 30 * 60
PAGE_SIZE = 30
# Searches and title pages each add an entry; keep the cache bounded.
MAX_CACHE_ENTRIES = 1000
SEARCH_RESULTS = 20

QUERY = """
query ($perPage: Int, $sort: [MediaSort], $startGreater: FuzzyDateInt, $startLesser: FuzzyDateInt) {
  Page(page: 1, perPage: $perPage) {
    media(type: MANGA, format_in: [MANGA], sort: $sort, isAdult: false,
          startDate_greater: $startGreater, startDate_lesser: $startLesser) {
      id
      title { romaji english native }
      synonyms
      coverImage { extraLarge large }
      startDate { year }
      averageScore
      countryOfOrigin
    }
  }
}
"""

# "See all" and genre pages: the rows' query plus paging, a genre and an
# origin country. Unused filters must be left out of the variables: AniList
# reads `countryOfOrigin: null` as "has no country" and matches nothing.
BROWSE_QUERY = """
query ($page: Int, $perPage: Int, $sort: [MediaSort], $startGreater: FuzzyDateInt,
       $startLesser: FuzzyDateInt, $genre: String, $country: CountryCode) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    media(type: MANGA, format_in: [MANGA], sort: $sort, isAdult: false,
          startDate_greater: $startGreater, startDate_lesser: $startLesser,
          genre: $genre, countryOfOrigin: $country) {
      id
      title { romaji english native }
      synonyms
      coverImage { extraLarge large }
      startDate { year }
      averageScore
      countryOfOrigin
    }
  }
}
"""
BROWSE_PAGE_SIZE = 40

# AniList's genre list, less Hentai (adult titles are never shown).
GENRES = [
    "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy", "Horror",
    "Mahou Shoujo", "Mecha", "Music", "Mystery", "Psychological", "Romance",
    "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller",
]

# Manga search. Light novels and adult titles are left out, as they are from
# the recommendation rows: mangarr downloads comics-format manga.
SEARCH_QUERY = """
query ($search: String, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(search: $search, type: MANGA, format_in: [MANGA, ONE_SHOT], isAdult: false,
          sort: SEARCH_MATCH) {
      id
      title { romaji english native }
      synonyms
      description(asHtml: false)
      coverImage { extraLarge large }
      startDate { year }
      status
      chapters
      averageScore
      countryOfOrigin
      genres
    }
  }
}
"""

# One title's full metadata for the detail page. AniList has no chapter
# listing, so a chapter/volume count is the most granular thing available
# until the series is in mangarr.
MEDIA_QUERY = """
query ($id: Int) {
  Media(id: $id, type: MANGA) {
    id
    title { romaji english native }
    synonyms
    description(asHtml: false)
    coverImage { extraLarge large }
    bannerImage
    startDate { year }
    endDate { year }
    status
    format
    chapters
    volumes
    averageScore
    popularity
    genres
    countryOfOrigin
    siteUrl
    externalLinks { site url type language }
    staff(perPage: 6, sort: RELEVANCE) { edges { role node { name { full } } } }
    relations { edges { relationType(version: 2) node { ...Card } } }
    recommendations(sort: RATING_DESC, perPage: 15) {
      nodes { mediaRecommendation { ...Card } }
    }
  }
}

fragment Card on Media {
  id
  type
  format
  isAdult
  status
  title { romaji english native }
  synonyms
  coverImage { extraLarge large }
  startDate { year }
  averageScore
  countryOfOrigin
}
"""

# Relations worth showing on a manga's page, in AniList's version-2 terms.
# CHARACTER (shared characters only) is left out as noise.
RELATION_LABELS = {
    "PREQUEL": "Prequel",
    "SEQUEL": "Sequel",
    "PARENT": "Parent story",
    "SIDE_STORY": "Side story",
    "SPIN_OFF": "Spin-off",
    "ALTERNATIVE": "Alternative version",
    "SUMMARY": "Summary",
    "COMPILATION": "Compilation",
    "CONTAINS": "Contains",
    "SOURCE": "Source",
    "ADAPTATION": "Adaptation",
    "OTHER": "Related",
}


@dataclass
class DiscoverItem:
    provider_id: int
    title: str
    english_title: str = ""
    synonyms: list[str] = field(default_factory=list)
    description: str = ""
    status: str = ""
    year: int | None = None
    cover_url: str = ""
    score: int | None = None
    genres: list[str] = field(default_factory=list)
    country: str = ""
    native_title: str = ""
    chapters: int | None = None

    @property
    def titles(self) -> list[str]:
        return [
            t for t in (self.title, self.english_title, self.native_title, *self.synonyms) if t
        ]


def _season_start(day: date) -> date:
    quarter_month = ((day.month - 1) // 3) * 3 + 1
    return date(day.year, quarter_month, 1)


def _previous_season(day: date) -> tuple[date, date]:
    """(start, end-exclusive) of the quarter before the current one."""
    current = _season_start(day)
    if current.month == 1:
        return date(current.year - 1, 10, 1), current
    return date(current.year, current.month - 3, 1), current


def _fuzzy(day: date) -> int:
    return day.year * 10000 + day.month * 100 + day.day


def _season_label(start: date) -> str:
    return {1: "Winter", 4: "Spring", 7: "Summer", 10: "Fall"}[start.month]


def sections_spec(today: date | None = None) -> list[dict]:
    today = today or date.today()
    current = _season_start(today)
    prev_start, prev_end = _previous_season(today)
    return [
        {
            "key": "trending",
            "title": "Trending Manga",
            "korean_title": "Trending Manhwa",
            "variables": {"sort": ["TRENDING_DESC"]},
        },
        {
            "key": "new_season",
            "title": f"New Manga This Season ({_season_label(current)} {current.year})",
            "korean_title": f"New Manhwa This Season ({_season_label(current)} {current.year})",
            # a hair before the quarter so day-one starts are included
            "variables": {
                "sort": ["POPULARITY_DESC"],
                "startGreater": _fuzzy(current) - 1,
            },
        },
        {
            "key": "top_last_season",
            "title": (
                f"Top Rated Manga Last Season "
                f"({_season_label(prev_start)} {prev_start.year})"
            ),
            "korean_title": (
                f"Top Rated Manhwa Last Season "
                f"({_season_label(prev_start)} {prev_start.year})"
            ),
            "variables": {
                "sort": ["SCORE_DESC"],
                "startGreater": _fuzzy(prev_start) - 1,
                "startLesser": _fuzzy(prev_end),
            },
        },
        {
            "key": "all_time",
            "title": "All-Time Manga Favorites",
            "korean_title": "All-Time Manhwa Favorites",
            "variables": {"sort": ["FAVOURITES_DESC"]},
        },
    ]


_TAG_RE = re.compile(r"<\s*br\s*/?\s*>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def _clean_description(raw: str | None, limit: int = 600) -> str:
    text = _ANY_TAG_RE.sub("", _TAG_RE.sub("\n", raw or ""))
    text = unescape(text).strip()
    # collapse the blank-line runs AniList's <br><br> markup leaves behind
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit] if limit else text


def _is_requestable_manga(media: dict | None) -> bool:
    """What mangarr can take: manga-format, non-adult (as in the rows)."""
    return bool(
        media
        and media.get("type") == "MANGA"
        and media.get("format") in ("MANGA", "ONE_SHOT")
        and not media.get("isAdult")
    )


# official links shown on a title page, in AniList's order
MAX_EXTERNAL_LINKS = 6


def _https_links(raw: list[dict] | None) -> list[dict[str, str]]:
    links = [
        (str(link.get("site") or ""), str(link.get("url") or ""), link.get("language") or "")
        for link in raw or []
    ]
    links = [(site, url, language) for site, url, language in links
             if site and url.startswith("https://")][:MAX_EXTERNAL_LINKS]
    sites = [site for site, _url, _language in links]
    # a publisher often has one link per region: tell them apart
    return [
        {"label": f"{site} ({language})" if language and sites.count(site) > 1 else site,
         "url": url}
        for site, url, language in links
    ]


def _to_item(media: dict) -> DiscoverItem:
    titles = media.get("title") or {}
    cover = media.get("coverImage") or {}
    return DiscoverItem(
        provider_id=int(media["id"]),
        title=titles.get("romaji") or titles.get("english") or "Untitled",
        english_title=titles.get("english") or "",
        native_title=titles.get("native") or "",
        synonyms=[s for s in (media.get("synonyms") or []) if s],
        description=_clean_description(media.get("description")),
        status=(media.get("status") or "").lower(),
        year=(media.get("startDate") or {}).get("year"),
        cover_url=safe_cover_url(cover.get("extraLarge") or cover.get("large") or ""),
        score=media.get("averageScore"),
        genres=media.get("genres") or [],
        country=media.get("countryOfOrigin") or "",
        chapters=media.get("chapters"),
    )


# section key (or "media:<id>") -> (fetched_at, payload)
_cache: dict[str, tuple[float, Any]] = {}
_inflight: dict[str, asyncio.Task] = {}
_cache_lock = asyncio.Lock()


async def _load_and_cache(key: str, fetch):
    task = asyncio.current_task()
    try:
        try:
            value = await fetch()
        except Exception:
            # An expired value is preferable to dropping a row during a
            # transient refresh failure. Cold-cache failures still propagate.
            async with _cache_lock:
                stale = _cache.get(key)
            if stale:
                log.warning("refresh for cached AniList key %s failed; serving stale data", key)
                return stale[1]
            raise
        async with _cache_lock:
            _cache[key] = (time.monotonic(), value)
            if len(_cache) > MAX_CACHE_ENTRIES:
                for old in sorted(_cache, key=lambda k: _cache[k][0])[: len(_cache) // 10]:
                    del _cache[old]
        return value
    finally:
        async with _cache_lock:
            if _inflight.get(key) is task:
                _inflight.pop(key, None)


async def _cached(key: str, fetch):
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        task = _inflight.get(key)
        if task is None:
            task = asyncio.create_task(_load_and_cache(key, fetch))
            _inflight[key] = task
        if cached:
            # Stale-while-revalidate keeps every visit after the first one
            # instant while a single background task refreshes the row.
            return cached[1]
    # One cold-cache request serves every user who opens Discover at the same
    # time. Shielding keeps a disconnected client from cancelling the shared
    # upstream request for the remaining waiters.
    return await asyncio.shield(task)


async def _query(query: str, variables: dict) -> dict:
    resp = await get_client().post(
        ANILIST_URL, json={"query": query, "variables": variables}, timeout=15
    )
    resp.raise_for_status()
    return resp.json().get("data") or {}


async def fetch_section(key: str, variables: dict) -> list[DiscoverItem]:
    async def load() -> list[DiscoverItem]:
        data = await _query(QUERY, {"perPage": PAGE_SIZE, **variables})
        return [_to_item(m) for m in (data.get("Page") or {}).get("media") or []]

    return await _cached(key, load)


async def warm_sections() -> None:
    """Populate recommendation caches in the background at server startup."""
    specs = sections_spec()
    results = await asyncio.gather(
        *(fetch_section(spec["key"], spec["variables"]) for spec in specs),
        return_exceptions=True,
    )
    failures = sum(isinstance(result, BaseException) for result in results)
    if failures:
        log.warning("AniList cache warm-up failed for %d section(s)", failures)
    else:
        log.info("AniList recommendation cache warmed")


async def browse(
    variables: dict, *, page: int, genre: str | None, origin: str
) -> tuple[list[DiscoverItem], bool]:
    """One page of a row's full listing or of a genre. `origin` is "manga"
    (everything but Korean titles, like the rows), "manhwa" or "all"."""
    query_vars = {**variables, "page": page, "perPage": BROWSE_PAGE_SIZE}
    query_vars.setdefault("sort", ["POPULARITY_DESC"])
    if genre:
        query_vars["genre"] = genre
    if origin == "manhwa":
        query_vars["country"] = "KR"
    key = "browse:" + ",".join(f"{k}={query_vars[k]}" for k in sorted(query_vars)) + f":{origin}"

    async def load() -> tuple[list[DiscoverItem], bool]:
        data = await _query(BROWSE_QUERY, query_vars)
        page_data = data.get("Page") or {}
        items = [_to_item(m) for m in page_data.get("media") or []]
        if origin == "manga":
            # AniList cannot exclude a country, so Korean titles are dropped
            # here; pages may come back a little short
            items = [item for item in items if item.country != "KR"]
        return items, bool((page_data.get("pageInfo") or {}).get("hasNextPage"))

    return await _cached(key, load)


async def search(query: str) -> list[DiscoverItem]:
    """AniList manga matching a search, cached like the rows."""
    normalized = " ".join(query.lower().split())

    async def load() -> list[DiscoverItem]:
        data = await _query(SEARCH_QUERY, {"search": normalized, "perPage": SEARCH_RESULTS})
        return [_to_item(m) for m in (data.get("Page") or {}).get("media") or []]

    return await _cached(f"search:{normalized}", load)


async def fetch_media(anilist_id: int) -> dict | None:
    """Full metadata for one AniList title (detail page)."""

    async def load() -> dict | None:
        data = await _query(MEDIA_QUERY, {"id": anilist_id})
        media = data.get("Media")
        if not media:
            return None
        titles = media.get("title") or {}
        cover = media.get("coverImage") or {}
        staff = [
            {"name": (e.get("node") or {}).get("name", {}).get("full", ""), "role": e.get("role", "")}
            for e in ((media.get("staff") or {}).get("edges") or [])
        ]
        return {
            "provider_id": int(media["id"]),
            "title": titles.get("romaji") or titles.get("english") or "Untitled",
            "english_title": titles.get("english") or "",
            "native_title": titles.get("native") or "",
            "synonyms": [s for s in (media.get("synonyms") or []) if s],
            "description": _clean_description(media.get("description"), limit=0),
            "status": (media.get("status") or "").lower(),
            "format": (media.get("format") or "").lower(),
            "year": (media.get("startDate") or {}).get("year"),
            "end_year": (media.get("endDate") or {}).get("year"),
            "cover_url": safe_cover_url(cover.get("extraLarge") or cover.get("large") or ""),
            "banner_url": safe_cover_url(media.get("bannerImage") or ""),
            "total_count": media.get("chapters"),
            "volumes": media.get("volumes"),
            "score": media.get("averageScore"),
            "genres": media.get("genres") or [],
            "country": media.get("countryOfOrigin") or "",
            "staff": [s for s in staff if s["name"]],
            "site_url": media.get("siteUrl") or "",
            "external_links": _https_links(media.get("externalLinks")),
            # (label, item) in AniList's order: prequels and sequels first
            "relations": [
                (RELATION_LABELS[edge["relationType"]], _to_item(edge["node"]))
                for edge in ((media.get("relations") or {}).get("edges") or [])
                if edge.get("relationType") in RELATION_LABELS
                and _is_requestable_manga(edge.get("node"))
            ],
            "recommendations": [
                _to_item(node["mediaRecommendation"])
                for node in ((media.get("recommendations") or {}).get("nodes") or [])
                if _is_requestable_manga(node.get("mediaRecommendation"))
            ],
        }

    return await _cached(f"media:{anilist_id}", load)


def clear_cache() -> None:
    """Test hook."""
    _cache.clear()
    for task in _inflight.values():
        task.cancel()
    _inflight.clear()
