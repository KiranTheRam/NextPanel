import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..db import get_session
from ..models import MediaType
from ..schemas import WebhookIn
from ..status import refresh_series

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

APP_MEDIA = {"mangarr": MediaType.MANGA, "pullarr": MediaType.COMIC}


@router.post("/{app}", status_code=204)
async def receive_webhook(
    app: str,
    body: WebhookIn,
    session: AsyncSession = Depends(get_session),
    x_webhook_secret: str = Header(default=""),
):
    """Called by mangarr/pullarr when they import files for a series.
    Authenticated by the shared webhook secret, not a user session."""
    media_type = APP_MEDIA.get(app)
    if media_type is None:
        raise HTTPException(404, "Unknown app")
    secret = await settings_service.get(session, "webhook_secret")
    if not secret:
        raise HTTPException(403, "Webhooks are disabled (no secret configured)")
    if not hmac.compare_digest(x_webhook_secret, secret):
        raise HTTPException(401, "Bad webhook secret")
    changed = await refresh_series(media_type, body.series_id)
    log.info("webhook from %s: series %d (%s) — %d request(s) updated",
             app, body.series_id, body.event or "import", changed)
