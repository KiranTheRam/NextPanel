import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import settings_service
from .db import session_scope
from .status import poll_active_requests

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

DEFAULT_POLL_MINUTES = 10


async def _prune_expired_sessions() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import delete

    from .models import UserSession

    async with session_scope() as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.execute(delete(UserSession).where(UserSession.expires_at < now))
        await session.commit()


async def start() -> None:
    async with session_scope() as session:
        raw = await settings_service.get(session, "poll_interval_minutes")
    try:
        interval = max(1, int(raw))
    except (TypeError, ValueError):
        log.warning("invalid poll_interval_minutes %r; using %d", raw, DEFAULT_POLL_MINUTES)
        interval = DEFAULT_POLL_MINUTES

    scheduler.add_job(
        poll_active_requests, "interval", minutes=interval,
        id="status_poll", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _prune_expired_sessions, "interval", hours=12,
        id="session_prune", max_instances=1, coalesce=True,
    )
    scheduler.start()
    log.info("Scheduler started (status poll every %d min)", interval)


def reschedule_poll(minutes: int) -> None:
    if scheduler.running and scheduler.get_job("status_poll"):
        scheduler.reschedule_job("status_poll", trigger="interval", minutes=max(1, minutes))
        log.info("Status poll rescheduled to every %d min", minutes)


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
