import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrClient, ArrError, MangarrClient, PullarrClient, SearchResult
from ..db import get_session
from ..models import MediaType, Request
from ..schemas import SearchOut, SearchResultOut
from .deps import get_current_user

router = APIRouter(prefix="/search", tags=["search"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=SearchOut)
async def search(
    q: str = Query(min_length=1),
    media_type: str = Query(default="all", pattern="^(all|manga|comic)$"),
    session: AsyncSession = Depends(get_session),
):
    """Search manga and/or comics by proxying mangarr's and pullarr's own
    metadata search. One app being down or unconfigured degrades to a
    partial result with a per-app error, never a failed search."""
    values = await settings_service.get_all(session)
    clients: list[ArrClient] = []
    if media_type in ("all", "manga"):
        clients.append(MangarrClient(values["mangarr_url"], values["mangarr_api_key"]))
    if media_type in ("all", "comic"):
        clients.append(PullarrClient(values["pullarr_url"], values["pullarr_api_key"]))

    errors: dict[str, str] = {}

    async def run(client: ArrClient) -> list[SearchResult]:
        if not client.configured:
            errors[client.app_name] = f"{client.app_name} is not configured"
            return []
        try:
            return await client.search(q)
        except ArrError as exc:
            errors[client.app_name] = str(exc)
            return []

    parts = await asyncio.gather(*(run(c) for c in clients))

    # annotate results with any existing NextPanel request for the same title
    existing = {
        (r.media_type, r.provider_id): r
        for r in (await session.execute(select(Request))).scalars().all()
    }
    results: list[SearchResultOut] = []
    for part in parts:
        for r in part:
            out = SearchResultOut(
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
                cover_url=r.cover_url,
                total_count=r.total_count,
                in_library=r.in_library,
            )
            request = existing.get((r.media_type, r.provider_id))
            if request is not None:
                out.request_id = request.id
                out.request_status = request.status
            results.append(out)
    return SearchOut(results=results, errors=errors)
