import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrError, MangarrClient, PullarrClient
from ..db import get_session
from ..discover import DiscoverItem, fetch_section, sections_spec
from ..library import LibraryIndex, load_index, normalize_title
from ..models import MediaType, Request
from ..security import safe_cover_url
from .deps import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/discover", tags=["discover"], dependencies=[Depends(get_current_user)])

MAX_ITEMS_PER_SECTION = 20

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


@router.get("")
async def discover(session: AsyncSession = Depends(get_session)):
    """Recommendation rows for the home page. Titles already in a library or
    already requested are kept in place but marked, so the rows stay stable
    and the user can see what they own. Manga rows come from AniList; comic
    rows from ComicVine via pullarr."""
    values = await settings_service.get_all(session)
    errors: dict[str, str] = {}
    sections: list[dict] = []
    requests = await load_request_index(session)

    # ---- manga (AniList) ----
    mangarr = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    manga_library = await load_index(mangarr)
    specs = sections_spec()

    async def load_manga(spec: dict) -> list[DiscoverItem]:
        try:
            return await fetch_section(spec["key"], spec["variables"])
        except Exception as exc:
            log.warning("discover section %s failed: %s", spec["key"], exc)
            errors[spec["key"]] = "AniList could not be reached"
            return []

    manga_results = await asyncio.gather(*(load_manga(spec) for spec in specs))
    for spec, items in zip(specs, manga_results):
        if not items:
            continue
        sections.append({
            "key": spec["key"],
            "title": spec["title"],
            "items": [
                _annotate(_manga_item_out(i), i.titles, manga_library, requests)
                for i in items[:MAX_ITEMS_PER_SECTION]
            ],
        })

    # ---- comics (ComicVine via pullarr) ----
    pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
    if pullarr.configured:
        comic_library = await load_index(pullarr)
        for key, title, params in COMIC_SECTIONS:
            try:
                entries = await pullarr.discover_releases(**params)
            except ArrError as exc:
                log.warning("discover section %s failed: %s", key, exc)
                errors[key] = "pullarr could not be reached"
                continue
            items = []
            for entry in entries[:MAX_ITEMS_PER_SECTION]:
                item = _comic_item_out(entry)
                item = _annotate(item, [item["title"]], comic_library, requests)
                # pullarr already knows whether the volume is shelved
                item["in_library"] = item["in_library"] or bool(entry.get("in_library"))
                items.append(item)
            if items:
                sections.append({"key": key, "title": title, "items": items})
    return {"sections": sections, "errors": errors}
