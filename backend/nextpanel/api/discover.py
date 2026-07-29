import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrClient, ArrError, MangarrClient, PullarrClient
from ..db import get_session
from ..discover import DiscoverItem, fetch_section, sections_spec
from ..library import LibraryIndex, load_index_cached, normalize_title
from ..models import MediaType, Request
from ..security import safe_cover_url
from .deps import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/discover", tags=["discover"], dependencies=[Depends(get_current_user)])

MAX_ITEMS_PER_SECTION = 20
SECTION_FETCH_TIMEOUT_SECONDS = 12
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
        self.by_title: dict[tuple[str, str], Request] = {}
        for request in requests:
            key = (request.media_type.value, request.provider, request.provider_id)
            self.by_provider_id[key] = request
            for title in (request.title, request.english_title):
                if title and (n := normalize_title(title)):
                    self.by_title.setdefault((request.media_type.value, n), request)

    def find(self, media_type: str, provider: str, provider_id: int,
             titles: list[str]) -> Request | None:
        request = self.by_provider_id.get((media_type, provider, provider_id))
        if request is not None:
            return request
        for title in titles:
            if title and (request := self.by_title.get((media_type, normalize_title(title)))):
                return request
        return None


async def load_request_index(session: AsyncSession) -> RequestIndex:
    result = await session.execute(select(Request))
    return RequestIndex(list(result.scalars().all()))


def _annotate(item: dict, titles: list[str], library: LibraryIndex,
              requests: RequestIndex) -> dict:
    """Tag an item with what NextPanel already knows about it, so the UI can
    show "In Library"/status instead of a Request button."""
    series = library.find(item["provider"], item["provider_id"], titles)
    item["in_library"] = series is not None
    item["library_series_id"] = int(series["id"]) if series else None
    request = requests.find(item["media_type"], item["provider"], item["provider_id"], titles)
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


async def _load_library(client: ArrClient) -> LibraryIndex:
    try:
        return await asyncio.wait_for(
            load_index_cached(client),
            timeout=LIBRARY_LOOKUP_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        log.warning("%s library timed out while loading discovery", client.app_name)
        return LibraryIndex(available=False)


async def _load_manga_items(spec: dict, errors: dict[str, str]) -> list[DiscoverItem]:
    try:
        return await asyncio.wait_for(
            fetch_section(spec["key"], spec["variables"]),
            timeout=SECTION_FETCH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        log.warning("discover section %s failed: %s", spec["key"], exc)
        errors[spec["key"]] = "AniList could not be reached"
        return []


async def _load_comic_entries(
    pullarr: PullarrClient, key: str, params: dict, errors: dict[str, str]
) -> list[dict]:
    try:
        return await asyncio.wait_for(
            pullarr.discover_releases(**params),
            timeout=SECTION_FETCH_TIMEOUT_SECONDS,
        )
    except (ArrError, TimeoutError) as exc:
        log.warning("discover section %s failed: %s", key, exc)
        errors[key] = "pullarr could not be reached"
        return []


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
) -> list[dict]:
    items = []
    for entry in entries[:MAX_ITEMS_PER_SECTION]:
        item = _comic_item_out(entry)
        item = _annotate(item, [item["title"]], library, requests)
        # pullarr already knows whether the volume is shelved
        item["in_library"] = item["in_library"] or bool(entry.get("in_library"))
        items.append(item)
    return [{"key": key, "title": title, "items": items}] if items else []


@router.get("/sections/{section_key}")
async def discover_section(
    section_key: str,
    session: AsyncSession = Depends(get_session),
):
    """Load one independently renderable recommendation row.

    A manga request may return a paired Manga and Manhwa row because both are
    partitioned from the same compact AniList response.
    """
    values = await settings_service.get_all(session)
    errors: dict[str, str] = {}

    spec = next((item for item in sections_spec() if item["key"] == section_key), None)
    if spec:
        mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
        items, library, requests = await asyncio.gather(
            _load_manga_items(spec, errors),
            _load_library(mangarr),
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
            _load_library(pullarr),
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
            _load_library(pullarr),
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
        _load_library(mangarr),
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
