"""AniList-powered discovery sections for the Discover home page.

AniList's browse queries are public GraphQL (no auth); results are cached
per section so the whole page costs at most four upstream requests every
half hour, well inside AniList's rate limits. Manga have no formal
"seasons", so seasonal sections use start-date quarters (Winter Jan-Mar,
Spring Apr-Jun, Summer Jul-Sep, Fall Oct-Dec).
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from typing import Any

import httpx

from .security import safe_cover_url

log = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"
CACHE_TTL_SECONDS = 30 * 60
PAGE_SIZE = 30

QUERY = """
query ($perPage: Int, $sort: [MediaSort], $startGreater: FuzzyDateInt, $startLesser: FuzzyDateInt) {
  Page(page: 1, perPage: $perPage) {
    media(type: MANGA, format_in: [MANGA], sort: $sort, isAdult: false,
          startDate_greater: $startGreater, startDate_lesser: $startLesser) {
      id
      title { romaji english }
      synonyms
      description(asHtml: false)
      coverImage { extraLarge large }
      startDate { year }
      status
      averageScore
      popularity
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
    staff(perPage: 6, sort: RELEVANCE) { edges { role node { name { full } } } }
  }
}
"""


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

    @property
    def titles(self) -> list[str]:
        return [t for t in (self.title, self.english_title, *self.synonyms) if t]


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
            "title": "Trending Now",
            "variables": {"sort": ["TRENDING_DESC"]},
        },
        {
            "key": "new_season",
            "title": f"New This Season ({_season_label(current)} {current.year})",
            # a hair before the quarter so day-one starts are included
            "variables": {
                "sort": ["POPULARITY_DESC"],
                "startGreater": _fuzzy(current) - 1,
            },
        },
        {
            "key": "top_last_season",
            "title": f"Top Rated Last Season ({_season_label(prev_start)} {prev_start.year})",
            "variables": {
                "sort": ["SCORE_DESC"],
                "startGreater": _fuzzy(prev_start) - 1,
                "startLesser": _fuzzy(prev_end),
            },
        },
        {
            "key": "all_time",
            "title": "All-Time Favorites",
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


def _to_item(media: dict) -> DiscoverItem:
    titles = media.get("title") or {}
    cover = media.get("coverImage") or {}
    return DiscoverItem(
        provider_id=int(media["id"]),
        title=titles.get("romaji") or titles.get("english") or "Untitled",
        english_title=titles.get("english") or "",
        synonyms=[s for s in (media.get("synonyms") or []) if s],
        description=_clean_description(media.get("description")),
        status=(media.get("status") or "").lower(),
        year=(media.get("startDate") or {}).get("year"),
        cover_url=safe_cover_url(cover.get("extraLarge") or cover.get("large") or ""),
        score=media.get("averageScore"),
        genres=media.get("genres") or [],
    )


# section key (or "media:<id>") -> (fetched_at, payload)
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = asyncio.Lock()


async def _cached(key: str, fetch):
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
    value = await fetch()
    async with _cache_lock:
        _cache[key] = (time.monotonic(), value)
    return value


async def _query(query: str, variables: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(ANILIST_URL, json={"query": query, "variables": variables})
        resp.raise_for_status()
        return resp.json().get("data") or {}


async def fetch_section(key: str, variables: dict) -> list[DiscoverItem]:
    async def load() -> list[DiscoverItem]:
        data = await _query(QUERY, {"perPage": PAGE_SIZE, **variables})
        return [_to_item(m) for m in (data.get("Page") or {}).get("media") or []]

    return await _cached(key, load)


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
        }

    return await _cached(f"media:{anilist_id}", load)


def clear_cache() -> None:
    """Test hook."""
    _cache.clear()
