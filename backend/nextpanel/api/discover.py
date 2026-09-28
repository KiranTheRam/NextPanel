import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrClient, ArrError, MangarrClient, PullarrClient
from ..db import get_session, session_scope
from .. import discover as anilist
from ..discover import DiscoverItem, fetch_section, sections_spec
from ..library import LibraryIndex, load_index_cached, normalize_title
from ..models import MediaType, Request, RequestStatus, User
from ..security import safe_cover_url
from .deps import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/discover", tags=["discover"], dependencies=[Depends(get_current_user)])

MAX_ITEMS_PER_SECTION = 20
SECTION_FETCH_TIMEOUT_SECONDS = 12
# A comic row waits much longer: pullarr's first load of a row takes about
# 20 s of rate-limited ComicVine calls. Rows render independently, so the
# rest of the page is not held up, and the fetch keeps going in the
# background if even this runs out.
COMIC_FETCH_TIMEOUT_SECONDS = 90
LIBRARY_LOOKUP_TIMEOUT_SECONDS = 2

COMIC_SECTIONS = [
    ("comics_week", "New Comics This Week", {"days": 7, "first_issues": False}),
    ("comics_new_series", "New Comic Series This Month", {"days": 30, "first_issues": True}),
]


class RequestIndex:
    """Existing NextPanel requests, matchable by provider id or title.

    Recommendation items carry an AniList id while a request may have been
    created from a MangaUpdates search result (or vice versa), so the title
    fallback matters as much as it does for the library.
    """

    def __init__(self, requests: list[Request]):
        self.by_provider_id: dict[tuple[str, str, int], Request] = {}
        self.by_title: dict[tuple[str, str], list[Request]] = {}
        for request in requests:
            key = (request.media_type.value, request.provider, request.provider_id)
            self.by_provider_id[key] = request
            for n in {normalize_title(t) for t in (request.title, request.english_title) if t}:
                if n:
                    self.by_title.setdefault((request.media_type.value, n), []).append(request)

    def find(self, media_type: str, provider: str, provider_id: int,
             titles: list[str], year: int | None = None) -> Request | None:
        request = self.by_provider_id.get((media_type, provider, provider_id))
        if request is not None:
            return request
        if year is None or media_type == MediaType.COMIC.value:
            return None
        for title in titles:
            if not title:
                continue
            candidates = [
                candidate
                for candidate in self.by_title.get((media_type, normalize_title(title)), [])
                if candidate.provider != provider
                and candidate.year == year
            ]
            if len(candidates) == 1:
                return candidates[0]
        return None


async def load_request_index(session: AsyncSession) -> RequestIndex:
    result = await session.execute(select(Request))
    return RequestIndex(list(result.scalars().all()))


def _annotate(item: dict, titles: list[str], library: LibraryIndex,
              requests: RequestIndex) -> dict:
    """Tag an item with what NextPanel already knows about it, so the UI can
    show "In Library"/status instead of a Request button."""
    series = library.find(item["provider"], item["provider_id"], titles, item.get("year"))
    item["in_library"] = series is not None
    item["library_series_id"] = int(series["id"]) if series else None
    request = requests.find(
        item["media_type"], item["provider"], item["provider_id"], titles, item.get("year")
    )
    item["request_id"] = request.id if request else None
    item["request_status"] = request.status.value if request else None
    return item


def _manga_item_out(item: DiscoverItem) -> dict:
    return {
        "media_type": "manga",
        "provider": "anilist",
        "provider_id": item.provider_id,
        "title": item.title,
        "english_title": item.english_title,
        "description": item.description,
        "status": item.status,
        "year": item.year,
        "cover_url": safe_cover_url(item.cover_url),
        "score": item.score,
        "subtitle": "",
        "genres": item.genres,
    }


def _comic_item_out(entry: dict) -> dict:
    store_date = entry.get("store_date") or ""
    year = None
    try:
        year = date.fromisoformat(store_date).year
    except ValueError:
        pass
    return {
        "media_type": "comic",
        "provider": "comicvine",
        "provider_id": entry["comicvine_volume_id"],
        "title": entry.get("volume_name") or "Unknown",
        "english_title": "",
        "description": entry.get("issue_name") or "",
        "status": "",
        "year": year,
        "cover_url": safe_cover_url(entry.get("cover_url") or ""),
        "score": None,
        "subtitle": entry.get("subtitle") or "",
        "genres": [],
    }


async def load_library(
    client: ArrClient,
    *,
    allow_stale: bool = True,
    timeout: float = LIBRARY_LOOKUP_TIMEOUT_SECONDS,
) -> LibraryIndex:
    """The app's library for marking titles, or an `available=False` index
    when it cannot be read in time: a slow app must not hold up the page."""
    try:
        return await asyncio.wait_for(
            load_index_cached(client, allow_stale=allow_stale), timeout=timeout
        )
    except TimeoutError:
        log.warning("%s library timed out", client.app_name)
        return LibraryIndex(available=False)


async def _load_manga_items(spec: dict, errors: dict[str, str]) -> list[DiscoverItem]:
    try:
        return await asyncio.wait_for(
            fetch_section(spec["key"], spec["variables"]),
            timeout=SECTION_FETCH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        log.warning("discover section %s failed: %r", spec["key"], exc)
        errors[spec["key"]] = "AniList could not be reached"
        return []


async def _load_comic_entries(
    pullarr: PullarrClient, key: str, params: dict, errors: dict[str, str]
) -> list[dict]:
    try:
        return await asyncio.wait_for(
            anilist.fetch_comic_releases(pullarr, **params),
            timeout=COMIC_FETCH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        log.warning("discover section %s is still loading from pullarr", key)
        errors[key] = "New releases are still loading from ComicVine — try again in a minute"
        return []
    except ArrError as exc:
        log.warning("discover section %s failed: %r", key, exc)
        errors[key] = "pullarr could not be reached"
        return []


async def warm_comic_rows() -> None:
    """Start pullarr's slow first load of the comic rows at startup, so the
    first visitor finds them ready (the AniList rows are warmed likewise)."""
    async with session_scope() as session:
        values = await settings_service.get_all(session)
    pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
    if not pullarr.configured:
        return
    errors: dict[str, str] = {}
    await asyncio.gather(*(
        _load_comic_entries(pullarr, key, params, errors) for key, _title, params in COMIC_SECTIONS
    ))
    if errors:
        log.warning("comic row warm-up incomplete: %s", ", ".join(sorted(errors)))
    else:
        log.info("comic recommendation rows warmed")


def _manga_sections(
    spec: dict,
    items: list[DiscoverItem],
    library: LibraryIndex,
    requests: RequestIndex,
) -> list[dict]:
    sections = []
    manga_items = [item for item in items if item.country != "KR"]
    korean_items = [item for item in items if item.country == "KR"]
    for key, title, regional_items in (
        (spec["key"], spec["title"], manga_items),
        (f"manhwa_{spec['key']}", spec["korean_title"], korean_items),
    ):
        if not regional_items:
            continue
        sections.append({
            "key": key,
            "title": title,
            "items": [
                _annotate(_manga_item_out(item), item.titles, library, requests)
                for item in regional_items[:MAX_ITEMS_PER_SECTION]
            ],
        })
    return sections


def _comic_section(
    key: str,
    title: str,
    entries: list[dict],
    library: LibraryIndex,
    requests: RequestIndex,
    limit: int | None = MAX_ITEMS_PER_SECTION,
) -> list[dict]:
    items = []
    for entry in entries[:limit]:
        item = _comic_item_out(entry)
        item = _annotate(item, [item["title"]], library, requests)
        # pullarr already knows whether the volume is shelved
        item["in_library"] = item["in_library"] or bool(entry.get("in_library"))
        items.append(item)
    return [{"key": key, "title": title, "items": items}] if items else []


# How many of a user's latest AniList requests to try for a "Because you
# requested" row (an obscure title may have no recommendations).
BECAUSE_SEEDS = 3


async def _because_you_requested(
    session: AsyncSession, user: User, mangarr: MangarrClient, errors: dict[str, str]
) -> list[dict]:
    seeds = (await session.execute(
        select(Request)
        .where(
            Request.user_id == user.id,
            Request.media_type == MediaType.MANGA,
            Request.provider == "anilist",
            Request.status != RequestStatus.DENIED,
        )
        .order_by(Request.created_at.desc())
        .limit(BECAUSE_SEEDS)
    )).scalars().all()
    for seed in seeds:
        try:
            media = await asyncio.wait_for(
                anilist.fetch_media(seed.provider_id), timeout=SECTION_FETCH_TIMEOUT_SECONDS
            )
        except Exception as exc:
            log.warning("recommendations for %s failed: %s", seed.provider_id, exc)
            errors["because"] = "AniList could not be reached"
            return []
        items = [
            item for item in (media or {}).get("recommendations", [])
            if item.provider_id != seed.provider_id
        ]
        if not items:
            continue
        library, requests = await asyncio.gather(
            load_library(mangarr), load_request_index(session)
        )
        return [{
            "key": "because",
            "title": f"Because you requested {seed.english_title or seed.title}",
            "items": [
                _annotate(_manga_item_out(item), item.titles, library, requests)
                for item in items[:MAX_ITEMS_PER_SECTION]
            ],
        }]
    return []


@router.get("/genres")
async def genres() -> list[str]:
    return anilist.GENRES


MAX_BROWSE_PAGE = 50


@router.get("/browse")
async def browse(
    source: str = Query(max_length=40),
    genre: str | None = Query(default=None, max_length=40),
    origin: str = Query(default="all", pattern="^(all|manga|manhwa)$"),
    page: int = Query(default=1, ge=1, le=MAX_BROWSE_PAGE),
    session: AsyncSession = Depends(get_session),
):
    """The full, paged listing behind a row's "See all", or a genre.
    `source` is a manga row key, a comic row key, or "genre"."""
    values = await settings_service.get_all(session)
    errors: dict[str, str] = {}

    comic_spec = next((item for item in COMIC_SECTIONS if item[0] == source), None)
    if comic_spec:
        # ComicVine rows are a date window pullarr returns whole; one page
        key, title, params = comic_spec
        pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
        if not pullarr.configured or page > 1:
            return {"title": title, "items": [], "has_more": False, "errors": {}}
        entries, library, requests = await asyncio.gather(
            _load_comic_entries(pullarr, key, params, errors),
            load_library(pullarr),
            load_request_index(session),
        )
        section = _comic_section(key, title, entries, library, requests, limit=None)
        items = section[0]["items"] if section else []
        return {"title": title, "items": items, "has_more": False, "errors": errors}

    if source == "genre":
        if genre not in anilist.GENRES:
            raise HTTPException(404, "Unknown genre")
        variables: dict = {"sort": ["POPULARITY_DESC"]}
        noun = {"manga": "Manga", "manhwa": "Manhwa"}.get(origin, "Manga & Manhwa")
        title = f"{genre} {noun}"
    else:
        spec = next((item for item in sections_spec() if item["key"] == source), None)
        if spec is None:
            raise HTTPException(404, "Unknown recommendation section")
        variables = spec["variables"]
        genre = None
        title = spec["korean_title"] if origin == "manhwa" else spec["title"]

    mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    try:
        (items, has_more), library, requests = await asyncio.gather(
            asyncio.wait_for(
                anilist.browse(variables, page=page, genre=genre, origin=origin),
                timeout=SECTION_FETCH_TIMEOUT_SECONDS,
            ),
            load_library(mangarr),
            load_request_index(session),
        )
    except Exception as exc:
        log.warning("browse %s/%s page %d failed: %s", source, genre, page, exc)
        return {"title": title, "items": [], "has_more": False,
                "errors": {source: "AniList could not be reached"}}
    return {
        "title": title,
        "items": [
            _annotate(_manga_item_out(item), item.titles, library, requests) for item in items
        ],
        "has_more": has_more,
        "errors": errors,
    }


@router.get("/sections/{section_key}")
async def discover_section(
    section_key: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Load one independently renderable recommendation row.

    A manga request may return a paired Manga and Manhwa row because both are
    partitioned from the same compact AniList response.
    """
    values = await settings_service.get_all(session)
    errors: dict[str, str] = {}

    if section_key == "because":
        mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
        sections = await _because_you_requested(session, user, mangarr, errors)
        return {"sections": sections, "errors": errors}

    spec = next((item for item in sections_spec() if item["key"] == section_key), None)
    if spec:
        mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
        items, library, requests = await asyncio.gather(
            _load_manga_items(spec, errors),
            load_library(mangarr),
            load_request_index(session),
        )
        return {
            "sections": _manga_sections(spec, items, library, requests),
            "errors": errors,
        }

    comic_spec = next(
        (item for item in COMIC_SECTIONS if item[0] == section_key),
        None,
    )
    if comic_spec:
        key, title, params = comic_spec
        pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
        if not pullarr.configured:
            return {"sections": [], "errors": {}}
        entries, library, requests = await asyncio.gather(
            _load_comic_entries(pullarr, key, params, errors),
            load_library(pullarr),
            load_request_index(session),
        )
        return {
            "sections": _comic_section(key, title, entries, library, requests),
            "errors": errors,
        }

    raise HTTPException(status_code=404, detail="Unknown recommendation section")


@router.get("")
async def discover(session: AsyncSession = Depends(get_session)):
    """Recommendation rows for the home page. Titles already in a library or
    already requested are kept in place but marked, so the rows stay stable
    and the user can see what they own. Manga rows come from AniList; comic
    rows from ComicVine via pullarr."""
    values = await settings_service.get_all(session)
    errors: dict[str, str] = {}
    sections: list[dict] = []

    mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
    specs = sections_spec()

    async def load_comics() -> tuple[LibraryIndex, list[list[dict]]]:
        if not pullarr.configured:
            return LibraryIndex(available=False), []
        comic_library, comic_results = await asyncio.gather(
            load_library(pullarr),
            asyncio.gather(
                *(
                    _load_comic_entries(pullarr, key, params, errors)
                    for key, _title, params in COMIC_SECTIONS
                )
            ),
        )
        return comic_library, comic_results

    # None of these reads depend on one another. Keeping both providers, both
    # libraries, the request index, and every recommendation row in flight at
    # once makes a cold page load take roughly the duration of the slowest
    # dependency instead of the sum of all of them.
    requests, manga_library, manga_results, comic_payload = await asyncio.gather(
        load_request_index(session),
        load_library(mangarr),
        asyncio.gather(*(_load_manga_items(spec, errors) for spec in specs)),
        load_comics(),
    )
    comic_library, comic_results = comic_payload

    # ---- manga and Korean manhwa (AniList) ----
    for spec, items in zip(specs, manga_results):
        sections.extend(_manga_sections(spec, items, manga_library, requests))

    # ---- comics (ComicVine via pullarr) ----
    if pullarr.configured:
        for (key, title, _params), entries in zip(COMIC_SECTIONS, comic_results):
            sections.extend(
                _comic_section(key, title, entries, comic_library, requests)
            )
    return {"sections": sections, "errors": errors}
