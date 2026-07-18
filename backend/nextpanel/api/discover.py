import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrError, MangarrClient, PullarrClient
from ..db import get_session
from ..discover import DiscoverItem, fetch_section, normalize_title, sections_spec
from ..models import MediaType, Request
from .deps import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/discover", tags=["discover"], dependencies=[Depends(get_current_user)])

MAX_ITEMS_PER_SECTION = 20

COMIC_SECTIONS = [
    ("comics_week", "New Comics This Week", {"days": 7, "first_issues": False}),
    ("comics_new_series", "New Comic Series This Month", {"days": 30, "first_issues": True}),
]


async def _hidden_sets(
    session: AsyncSession, media_type: MediaType, provider: str
) -> tuple[set[int], set[str]]:
    """Provider ids and normalized titles already requested for a media type."""
    ids: set[int] = set()
    titles: set[str] = set()
    result = await session.execute(
        select(Request).where(Request.media_type == media_type)
    )
    for request in result.scalars().all():
        if request.provider == provider:
            ids.add(request.provider_id)
        for title in (request.title, request.english_title):
            if title and (n := normalize_title(title)):
                titles.add(n)
    return ids, titles


async def _manga_hidden(session: AsyncSession, values: dict[str, str]) -> tuple[set[int], set[str]]:
    """Requested manga plus everything in the mangarr library."""
    ids, titles = await _hidden_sets(session, MediaType.MANGA, "anilist")
    client = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    if client.configured:
        try:
            for series in await client.list_series():
                if series.get("anilist_id"):
                    ids.add(int(series["anilist_id"]))
                names = [series.get("title", ""), series.get("english_title", "")]
                names += (series.get("alt_titles") or "").split("\n")
                for name in names:
                    if name and (n := normalize_title(name)):
                        titles.add(n)
        except ArrError as exc:
            # library unavailable -> can only filter by requests; fine
            log.warning("mangarr library unavailable for discover filtering: %s", exc)
    return ids, titles


def _visible(item: DiscoverItem, hidden_ids: set[int], hidden_titles: set[str]) -> bool:
    if item.provider_id in hidden_ids:
        return False
    for title in (item.title, item.english_title):
        if title and normalize_title(title) in hidden_titles:
            return False
    return True


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
        "cover_url": item.cover_url,
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
        "cover_url": entry.get("cover_url") or "",
        "score": None,
        "subtitle": entry.get("subtitle") or "",
        "genres": [],
    }


@router.get("")
async def discover(session: AsyncSession = Depends(get_session)):
    """Recommendation rows for the home page, with everything already in
    the libraries or already requested filtered out. Manga rows come from
    AniList; comic rows from ComicVine via pullarr."""
    values = await settings_service.get_all(session)
    errors: dict[str, str] = {}
    sections: list[dict] = []

    # ---- manga (AniList) ----
    manga_ids, manga_titles = await _manga_hidden(session, values)
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
        visible = [i for i in items if _visible(i, manga_ids, manga_titles)]
        if visible:
            sections.append({
                "key": spec["key"],
                "title": spec["title"],
                "items": [_manga_item_out(i) for i in visible[:MAX_ITEMS_PER_SECTION]],
            })

    # ---- comics (ComicVine via pullarr) ----
    pullarr = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])
    if pullarr.configured:
        comic_ids, comic_titles = await _hidden_sets(session, MediaType.COMIC, "comicvine")
        for key, title, params in COMIC_SECTIONS:
            try:
                entries = await pullarr.discover_releases(**params)
            except ArrError as exc:
                log.warning("discover section %s failed: %s", key, exc)
                errors[key] = "pullarr could not be reached"
                continue
            items = []
            for entry in entries:
                if entry.get("in_library"):
                    continue
                item = _comic_item_out(entry)
                if item["provider_id"] in comic_ids:
                    continue
                if normalize_title(item["title"]) in comic_titles:
                    continue
                items.append(item)
            if items:
                sections.append({
                    "key": key,
                    "title": title,
                    "items": items[:MAX_ITEMS_PER_SECTION],
                })
    return {"sections": sections, "errors": errors}
