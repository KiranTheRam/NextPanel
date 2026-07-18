"""Request status reconciliation against mangarr/pullarr.

A request that has been approved (added to its app) advances as the app
downloads: processing -> partially_available -> available. Both the webhook
receiver and the fallback poll job funnel through refresh_request().
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import settings_service
from .arr import ArrClient, ArrError, client_for
from .db import session_scope
from .models import Request, RequestStatus

log = logging.getLogger(__name__)

ACTIVE_STATUSES = (RequestStatus.PROCESSING, RequestStatus.PARTIALLY_AVAILABLE)


def _status_for(downloaded: int, total: int) -> RequestStatus:
    if total > 0 and downloaded >= total:
        return RequestStatus.AVAILABLE
    if downloaded > 0:
        return RequestStatus.PARTIALLY_AVAILABLE
    return RequestStatus.PROCESSING


async def refresh_request(session: AsyncSession, request: Request, client: ArrClient) -> bool:
    """Sync one request's status from its app. Returns True when it changed.
    The caller commits."""
    if request.remote_series_id is None:
        return False
    try:
        remote = await client.series_status(request.remote_series_id)
    except ArrError as exc:
        # a 404 means the series was deleted in the app — surface that
        # instead of silently polling forever
        if "404" in str(exc):
            request.status = RequestStatus.FAILED
            request.note = f"Series was removed from {client.app_name}"
            return True
        log.warning("status refresh for request %d failed: %s", request.id, exc)
        return False
    changed = (
        remote.downloaded_count != request.downloaded_count
        or remote.total_count != request.total_count
    )
    request.downloaded_count = remote.downloaded_count
    request.total_count = remote.total_count
    new_status = _status_for(remote.downloaded_count, remote.total_count)
    # an ongoing series can gain new chapters after being fully downloaded;
    # let AVAILABLE drop back to PARTIALLY_AVAILABLE so the state stays honest
    if new_status != request.status:
        request.status = new_status
        changed = True
    return changed


async def refresh_series(app_media_type, series_id: int) -> int:
    """Refresh every active request tied to one app series (webhook path)."""
    async with session_scope() as session:
        values = await settings_service.get_all(session)
        result = await session.execute(
            select(Request).where(
                Request.media_type == app_media_type,
                Request.remote_series_id == series_id,
                Request.status.in_(ACTIVE_STATUSES),
            )
        )
        requests = result.scalars().all()
        if not requests:
            return 0
        client = client_for(app_media_type, values)
        changed = 0
        for request in requests:
            if await refresh_request(session, request, client):
                changed += 1
        await session.commit()
        return changed


async def poll_active_requests() -> None:
    """Scheduled fallback: sync every in-flight request."""
    async with session_scope() as session:
        values = await settings_service.get_all(session)
        result = await session.execute(
            select(Request).where(Request.status.in_(ACTIVE_STATUSES))
        )
        requests = result.scalars().all()
        for request in requests:
            client = client_for(request.media_type, values)
            if not client.configured:
                continue
            await refresh_request(session, request, client)
        await session.commit()
