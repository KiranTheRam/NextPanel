"""A snapshot of what a mangarr/pullarr library already holds.

Discover rows and title detail both need the same question answered — "is
this thing already in the library?" — for items that may only be known by a
metadata provider id or by a set of titles. Matching by provider id is exact;
the title fallback catches series added under the other provider (a mangarr
series added by MangaUpdates id has no AniList id to compare against).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .arr import ArrClient, ArrError, MangarrClient

log = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


@dataclass
class LibraryIndex:
    """Series keyed by every id and title they can be recognised by."""

    by_provider_id: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    by_title: dict[str, dict[str, Any]] = field(default_factory=dict)
    # the library could not be read; matches are unknown rather than absent
    available: bool = True

    def find(self, provider: str, provider_id: int, titles: list[str]) -> dict[str, Any] | None:
        series = self.by_provider_id.get((provider, provider_id))
        if series is not None:
            return series
        for title in titles:
            if title and (series := self.by_title.get(normalize_title(title))):
                return series
        return None


def _index(series_list: list[dict[str, Any]], id_keys: dict[str, str],
           title_keys: list[str]) -> LibraryIndex:
    index = LibraryIndex()
    for series in series_list:
        for provider, key in id_keys.items():
            if series.get(key) is not None:
                index.by_provider_id[(provider, int(series[key]))] = series
        names: list[str] = []
        for key in title_keys:
            value = series.get(key) or ""
            # mangarr stores alt titles newline-joined in a single column
            names.extend(value.split("\n") if key == "alt_titles" else [value])
        for name in names:
            if name and (n := normalize_title(name)):
                index.by_title.setdefault(n, series)
    return index


async def load_index(client: ArrClient) -> LibraryIndex:
    """Index the client's library; an unreachable app yields an empty,
    `available=False` index so callers degrade to "unknown" instead of
    claiming nothing is owned."""
    if not client.configured:
        return LibraryIndex(available=False)
    try:
        series_list = await client.list_series()
    except ArrError as exc:
        log.warning("%s library unavailable: %s", client.app_name, exc)
        return LibraryIndex(available=False)
    if isinstance(client, MangarrClient):
        return _index(
            series_list,
            {"anilist": "anilist_id", "mangaupdates": "mangaupdates_id"},
            ["title", "english_title", "alt_titles"],
        )
    return _index(series_list, {"comicvine": "comicvine_id"}, ["title"])
