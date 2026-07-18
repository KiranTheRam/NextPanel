"""One title's full metadata, for the detail page.

The best available source depends on where the title already lives. A series
in mangarr/pullarr can answer with its real chapter/issue list and download
state; anything else falls back to the metadata provider — AniList by id for
manga, or the app's own metadata search for providers with no by-id lookup.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrClient, ArrError, MangarrClient, PullarrClient
from ..db import get_session
from ..discover import fetch_media
from ..library import load_index
from ..models import MediaType
from ..schemas import ChapterOut, TitleDetailOut
from ..security import safe_cover_url
from .deps import get_current_user
from .discover import load_request_index

log = logging.getLogger(__name__)

router = APIRouter(prefix="/detail", tags=["detail"], dependencies=[Depends(get_current_user)])


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _chapters_from_series(series: dict, media_type: MediaType) -> list[ChapterOut]:
    key = "chapters" if media_type == MediaType.MANGA else "issues"
    out = []
    for entry in series.get(key) or []:
        number = entry.get("number")
        out.append(ChapterOut(
            number=number,
            label=entry.get("display_number") or (
                f"{number:g}" if isinstance(number, (int, float)) else ""
            ),
            title=entry.get("title") or "",
            volume=entry.get("volume"),
            downloaded=bool(entry.get("downloaded")),
            monitored=bool(entry.get("monitored")),
        ))
    return out


def _from_library(series: dict, media_type: MediaType) -> TitleDetailOut:
    total = series.get("total_chapters") if media_type == MediaType.MANGA else series.get("total_issues")
    return TitleDetailOut(
        media_type=media_type,
        provider="",
        provider_id=0,
        title=series.get("title") or "",
        english_title=series.get("english_title") or "",
        description=series.get("description") or "",
        status=(series.get("status") or "").lower(),
        year=series.get("year"),
        cover_url=safe_cover_url(series.get("cover_url") or ""),
        banner_url=safe_cover_url(series.get("banner_url") or ""),
        genres=_split(series.get("genres")),
        publisher=series.get("publisher") or "",
        total_count=total,
        chapters=_chapters_from_series(series, media_type),
        chapters_available=True,
        downloaded_count=int(series.get("downloaded_count") or 0),
    )


async def _from_metadata_search(client: ArrClient, provider_id: int,
                                title_hint: str) -> TitleDetailOut | None:
    """Providers without a by-id endpoint (MangaUpdates, ComicVine) are looked
    up by re-running the metadata search the user came from and picking the
    matching id."""
    if not title_hint:
        return None
    try:
        results = await client.search(title_hint)
    except ArrError as exc:
        log.warning("detail lookup via %s failed: %s", client.app_name, exc)
        return None
    match = next((r for r in results if r.provider_id == provider_id), None)
    if match is None:
        return None
    return TitleDetailOut(
        media_type=match.media_type,
        provider=match.provider,
        provider_id=match.provider_id,
        title=match.title,
        english_title=match.english_title,
        description=match.description,
        status=(match.status or "").lower(),
        year=match.year,
        cover_url=safe_cover_url(match.cover_url),
        genres=[],
        publisher=match.publisher,
        total_count=match.total_count,
    )


def _from_anilist(media: dict) -> TitleDetailOut:
    return TitleDetailOut(
        media_type=MediaType.MANGA,
        provider="anilist",
        provider_id=media["provider_id"],
        title=media["title"],
        english_title=media["english_title"],
        native_title=media["native_title"],
        description=media["description"],
        status=media["status"],
        format=media["format"],
        year=media["year"],
        end_year=media["end_year"],
        cover_url=media["cover_url"],
        banner_url=media["banner_url"],
        genres=media["genres"],
        score=media["score"],
        total_count=media["total_count"],
        volumes=media["volumes"],
        country=media["country"],
        staff=media["staff"],
    )


@router.get("/{media_type}/{provider}/{provider_id}", response_model=TitleDetailOut)
async def title_detail(
    media_type: MediaType,
    provider: str,
    provider_id: int,
    title: str = Query(default="", max_length=200, description="title hint for by-title lookups"),
    session: AsyncSession = Depends(get_session),
):
    values = await settings_service.get_all(session)
    if media_type == MediaType.MANGA:
        client: ArrClient = MangarrClient(values["mangarr_url"], values["mangarr_api_key"])
    else:
        client = PullarrClient(values["pullarr_url"], values["pullarr_api_key"])

    detail: TitleDetailOut | None = None
    titles = [t for t in (title,) if t]

    # AniList first for manga: it is the richest source and stays available
    # even when the series is already shelved (mangarr keeps only what it
    # imported at add time).
    if media_type == MediaType.MANGA and provider == "anilist":
        try:
            media = await fetch_media(provider_id)
        except Exception as exc:
            log.warning("AniList detail for %s failed: %s", provider_id, exc)
            media = None
        if media:
            detail = _from_anilist(media)
            titles = [t for t in [media["title"], media["english_title"], *media["synonyms"]] if t]

    library = await load_index(client)
    series = library.find(provider, provider_id, titles)
    if series is not None:
        try:
            full = await client.series_detail(int(series["id"]))
        except ArrError as exc:
            log.warning("%s detail for series %s failed: %s", client.app_name, series["id"], exc)
            full = series
        shelved = _from_library(full, media_type)
        if detail is None:
            detail = shelved
            detail.provider = provider
            detail.provider_id = provider_id
        else:
            # keep the richer provider metadata, take the library's truth
            # about what actually exists on disk
            detail.chapters = shelved.chapters
            detail.chapters_available = True
            detail.downloaded_count = shelved.downloaded_count
            detail.total_count = detail.total_count or shelved.total_count
            if not detail.description:
                detail.description = shelved.description
        detail.in_library = True
        detail.library_series_id = int(series["id"])

    if detail is None:
        detail = await _from_metadata_search(client, provider_id, title)
    if detail is None:
        raise HTTPException(404, "No metadata found for this title")

    detail.provider = detail.provider or provider
    detail.provider_id = detail.provider_id or provider_id
    requests = await load_request_index(session)
    request = requests.find(media_type.value, provider, provider_id, titles or [detail.title])
    if request is not None:
        detail.request_id = request.id
        detail.request_status = request.status
    return detail
