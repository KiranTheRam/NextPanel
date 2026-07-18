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

import httpx

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


@dataclass
class DiscoverItem:
    provider_id: int
    title: str
    english_title: str = ""
    description: str = ""
    status: str = ""
    year: int | None = None
    cover_url: str = ""
    score: int | None = None
    genres: list[str] = field(default_factory=list)


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


_TAG_RE = re.compile(r"<[^>]+>")


def _clean_description(raw: str | None) -> str:
    text = _TAG_RE.sub("", raw or "").replace("&quot;", '"').replace("&amp;", "&")
    return text.strip()[:600]


def _to_item(media: dict) -> DiscoverItem:
    titles = media.get("title") or {}
    cover = media.get("coverImage") or {}
    return DiscoverItem(
        provider_id=int(media["id"]),
        title=titles.get("romaji") or titles.get("english") or "Untitled",
        english_title=titles.get("english") or "",
        description=_clean_description(media.get("description")),
        status=(media.get("status") or "").lower(),
        year=(media.get("startDate") or {}).get("year"),
        cover_url=cover.get("extraLarge") or cover.get("large") or "",
        score=media.get("averageScore"),
        genres=media.get("genres") or [],
    )


# section key -> (fetched_at, items)
_cache: dict[str, tuple[float, list[DiscoverItem]]] = {}
_cache_lock = asyncio.Lock()


async def fetch_section(key: str, variables: dict) -> list[DiscoverItem]:
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(ANILIST_URL, json={
            "query": QUERY,
            "variables": {"perPage": PAGE_SIZE, **variables},
        })
        resp.raise_for_status()
        payload = resp.json()
    media = (payload.get("data") or {}).get("Page", {}).get("media", [])
    items = [_to_item(m) for m in media]
    async with _cache_lock:
        _cache[key] = (time.monotonic(), items)
    return items


def clear_cache() -> None:
    """Test hook."""
    _cache.clear()


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())
