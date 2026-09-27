"""Request status reconciliation against mangarr/pullarr.

A request that has been approved (added to its app) advances as the app
downloads: processing -> partially_available -> available. The webhook
receiver, the fallback poll job and manual refreshes all record the app's
answer through _apply_status().
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import settings_service
from .arr import ArrClient, ArrError, SeriesStatus, client_for
from .db import session_scope
from .models import MediaType, Request, RequestStatus

log = logging.getLogger(__name__)

# Completed ongoing series must still be checked: newly announced chapters can
# move them back to partially available, and removed series must be surfaced.
ACTIVE_STATUSES = (
    RequestStatus.PROCESSING,
    RequestStatus.PARTIALLY_AVAILABLE,
    RequestStatus.AVAILABLE,
)


def _status_for(downloaded: int, total: int) -> RequestStatus:
    if total > 0 and downloaded >= total:
        return RequestStatus.AVAILABLE
    if downloaded > 0:
        return RequestStatus.PARTIALLY_AVAILABLE
    return RequestStatus.PROCESSING


async def _fetch_status(client: ArrClient, series_id: int) -> SeriesStatus | ArrError:
    try:
        return await client.series_status(series_id)
    except ArrError as exc:
        return exc


def _apply_status(request: Request, result: SeriesStatus | ArrError, app_name: str) -> bool:
    """Record one app answer on a request. Returns True when it changed."""
    if isinstance(result, ArrError):
        # a 404 means the series was deleted in the app — surface that
        # instead of silently polling forever
        if result.status_code == 404:
            request.status = RequestStatus.FAILED
            request.note = f"Series was removed from {app_name}"
            return True
        log.warning("status refresh for request %d failed: %s", request.id, result)
        return False
    changed = (
        result.downloaded_count != request.downloaded_count
        or result.total_count != request.total_count
    )
    request.downloaded_count = result.downloaded_count
    request.total_count = result.total_count
    new_status = _status_for(result.downloaded_count, result.total_count)
    # an ongoing series can gain new chapters after being fully downloaded;
    # let AVAILABLE drop back to PARTIALLY_AVAILABLE so the state stays honest
    if new_status != request.status:
        # ...but tell the requester only the first time it completes, not
        # again every time a newly announced chapter finishes downloading
        if new_status == RequestStatus.AVAILABLE and not request.available_notified:
            from . import push

            request.available_notified = True
            push.notify_later(push.notify_request_available(
                request.user_id,
                request.title,
                result.total_count,
                request.media_type,
                request.provider,
                request.provider_id,
            ))
        request.status = new_status
        changed = True
    return changed


async def refresh_request(session: AsyncSession, request: Request, client: ArrClient) -> bool:
    """Sync one request's status from its app. Returns True when it changed.
    The caller commits."""
    if request.remote_series_id is None:
        return False
    result = await _fetch_status(client, request.remote_series_id)
    return _apply_status(request, result, client.app_name)


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
        remote = await _fetch_status(client, series_id)
        changed = sum(_apply_status(request, remote, client.app_name) for request in requests)
        await session.commit()
        return changed


# Parallel status reads per poll. Enough to finish a large library quickly
# without flooding mangarr/pullarr, which serve their own UIs from the same
# process.
POLL_CONCURRENCY = 8
# Completed series only change when new chapters are announced (webhooks
# already report downloads), so they are checked on every Nth poll only.
AVAILABLE_POLL_EVERY = 6
_poll_cycle = 0


async def poll_active_requests() -> None:
    """Scheduled fallback: sync every in-flight request."""
    global _poll_cycle
    statuses = (
        ACTIVE_STATUSES
        if _poll_cycle % AVAILABLE_POLL_EVERY == 0
        else (RequestStatus.PROCESSING, RequestStatus.PARTIALLY_AVAILABLE)
    )
    _poll_cycle += 1
    async with session_scope() as session:
        values = await settings_service.get_all(session)
        result = await session.execute(
            select(Request).where(
                Request.status.in_(statuses),
                Request.remote_series_id.is_not(None),
            )
        )
        clients = {media_type: client_for(media_type, values) for media_type in MediaType}
        # Requests from different providers can point at the same app series;
        # ask the app about each series once.
        series: dict[tuple[MediaType, int], list[Request]] = {}
        for request in result.scalars().all():
            if clients[request.media_type].configured:
                key = (request.media_type, request.remote_series_id)
                series.setdefault(key, []).append(request)

        limit = asyncio.Semaphore(POLL_CONCURRENCY)

        async def fetch(media_type: MediaType, series_id: int) -> SeriesStatus | ArrError:
            async with limit:
                return await _fetch_status(clients[media_type], series_id)

        remotes = await asyncio.gather(*(fetch(*key) for key in series))
        for ((media_type, _series_id), requests), remote in zip(series.items(), remotes):
            for request in requests:
                _apply_status(request, remote, clients[media_type].app_name)
        await session.commit()
