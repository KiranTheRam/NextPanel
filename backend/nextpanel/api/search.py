import asyncio
import logging
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import discover as anilist, settings_service
from ..arr import ArrClient, ArrError, MangarrClient, PullarrClient, SearchResult
from ..db import get_session
from ..discover import DiscoverItem
from ..library import LibraryIndex, normalize_title
from ..models import MediaType
from ..schemas import SearchOut, SearchResultOut
from ..security import safe_cover_url
from .deps import get_current_user
from .discover import RequestIndex, load_library, load_request_index

log = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"], dependencies=[Depends(get_current_user)])

ANILIST_TIMEOUT_SECONDS = 12
LIBRARY_TIMEOUT_SECONDS = 5

# Search runs as the user types. The same query (retyped, or fixed after a
# typo) must not cost another ComicVine call: pullarr's key allows 200 an
# hour. Library and request state are still read fresh on every search.
APP_CACHE_TTL_SECONDS = 10 * 60
APP_CACHE_MAX_ENTRIES = 500
_app_cache: dict[tuple[str, str, str], tuple[float, list[SearchResult]]] = {}


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


async def search_app(client: ArrClient, query: str) -> list[SearchResult]:
    key = (client.app_name, client.base_url, _normalize_query(query))
    cached = _app_cache.get(key)
    if cached and time.monotonic() - cached[0] < APP_CACHE_TTL_SECONDS:
        return cached[1]
    results = await client.search(query)
    _app_cache[key] = (time.monotonic(), results)
    if len(_app_cache) > APP_CACHE_MAX_ENTRIES:
        for old in sorted(_app_cache, key=lambda k: _app_cache[k][0])[: len(_app_cache) // 10]:
            del _app_cache[old]
    return results


def clear_cache() -> None:
    """Test hook."""
    _app_cache.clear()


def _title_keys(titles: list[str]) -> set[str]:
    return {key for title in titles if title and (key := normalize_title(title))}


def _without_anilist_duplicates(
    results: list[SearchResult], anilist_items: list[DiscoverItem]
) -> list[SearchResult]:
    """MangaUpdates results for series AniList already returned (same title,
    same year). MangaUpdates stays in the search for everything AniList does
    not know, which is a lot of manhwa and older manga."""
    known = {
        (key, item.year)
        for item in anilist_items
        if item.year is not None
        for key in _title_keys(item.titles)
    }
    return [
        r for r in results
        if r.year is None
        or not any(
            (key, r.year) in known
            for key in _title_keys([r.title, r.english_title, *r.alt_titles])
        )
    ]


def _anilist_out(item: DiscoverItem) -> SearchResultOut:
    return SearchResultOut(
        media_type=MediaType.MANGA,
        provider="anilist",
        provider_id=item.provider_id,
        title=item.title,
        english_title=item.english_title,
        alt_titles=[t for t in (item.native_title, *item.synonyms) if t],
        description=item.description,
        status=item.status,
        year=item.year,
        cover_url=safe_cover_url(item.cover_url),
        total_count=item.chapters,
        score=item.score,
        country=item.country,
    )


def _app_out(r: SearchResult) -> SearchResultOut:
    return SearchResultOut(
        media_type=r.media_type,
        provider=r.provider,
        provider_id=r.provider_id,
        title=r.title,
        english_title=r.english_title,
        alt_titles=r.alt_titles,
        description=r.description,
        status=r.status,
        publisher=r.publisher,
        year=r.year,
        cover_url=safe_cover_url(r.cover_url),
        total_count=r.total_count,
        in_library=r.in_library,
    )


def _annotate(out: SearchResultOut, library: LibraryIndex, requests: RequestIndex) -> None:
    titles = [out.title, out.english_title, *out.alt_titles]
    if library.find(out.provider, out.provider_id, titles, out.year) is not None:
        out.in_library = True
    request = requests.find(out.media_type.value, out.provider, out.provider_id, titles, out.year)
    if request is not None:
        out.request_id = request.id
        out.request_status = request.status


@router.get("", response_model=SearchOut)
async def search(
    q: str = Query(min_length=1, max_length=200),
    media_type: str = Query(default="all", pattern="^(all|manga|comic)$"),
    session: AsyncSession = Depends(get_session),
):
    """Search manga on AniList and (through mangarr) MangaUpdates, and comics
    through pullarr's ComicVine search. One source being down or unconfigured
    degrades to a partial result with a per-source error, never a failed
    search."""
    values = await settings_service.get_all(session)
    mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
    want_manga = media_type in ("all", "manga")
    want_comics = media_type in ("all", "comic")
    errors: dict[str, str] = {}

    async def from_app(client: ArrClient, wanted: bool) -> list[SearchResult]:
        if not wanted:
            return []
        if not client.configured:
            errors[client.app_name] = f"{client.app_name} is not configured"
            return []
        try:
            return await search_app(client, q)
        except ArrError as exc:
            # log the detail; the message shown to (any) signed-in user must
            # not leak internal URLs or upstream error bodies
            log.warning("search via %s failed: %s", client.app_name, exc)
            errors[client.app_name] = (
                f"{client.app_name} could not be reached — ask the admin to check the connection"
            )
            return []

    async def from_anilist() -> list[DiscoverItem]:
        if not want_manga:
            return []
        try:
            return await asyncio.wait_for(anilist.search(q), timeout=ANILIST_TIMEOUT_SECONDS)
        except Exception as exc:
            log.warning("AniList search failed: %s", exc)
            errors["anilist"] = "AniList could not be reached"
            return []

    async def library(client: ArrClient, wanted: bool) -> LibraryIndex:
        if not wanted or not client.configured:
            return LibraryIndex(available=False)
        # search results must reflect series added a moment ago
        return await load_library(client, allow_stale=False, timeout=LIBRARY_TIMEOUT_SECONDS)

    (anilist_items, manga_results, comic_results, manga_library, comic_library,
     requests) = await asyncio.gather(
        from_anilist(),
        from_app(mangarr, want_manga),
        from_app(pullarr, want_comics),
        library(mangarr, want_manga),
        library(pullarr, want_comics),
        load_request_index(session),
    )

    results: list[SearchResultOut] = []
    for item in anilist_items:
        out = _anilist_out(item)
        _annotate(out, manga_library, requests)
        results.append(out)
    for r in _without_anilist_duplicates(manga_results, anilist_items):
        out = _app_out(r)
        _annotate(out, manga_library, requests)
        results.append(out)
    for r in comic_results:
        out = _app_out(r)
        _annotate(out, comic_library, requests)
        results.append(out)
    return SearchOut(results=results, errors=errors)
