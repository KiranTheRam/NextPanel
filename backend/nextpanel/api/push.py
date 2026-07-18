from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import push
from ..db import get_session
from ..models import PushSubscription, User
from ..schemas import PushSubscriptionIn
from .deps import get_current_user

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/key")
async def vapid_public_key(user: User = Depends(get_current_user)):
    return {"key": push.public_key_b64()}


@router.post("/subscribe", status_code=204)
async def subscribe(
    body: PushSubscriptionIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not body.keys.get("p256dh") or not body.keys.get("auth"):
        raise HTTPException(422, "Subscription is missing encryption keys")
    existing = (await session.execute(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )).scalar_one_or_none()
    if existing is not None:
        # a device re-subscribing (possibly as a different user) replaces its row
        existing.user_id = user.id
        existing.p256dh = body.keys["p256dh"]
        existing.auth = body.keys["auth"]
    else:
        session.add(PushSubscription(
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.keys["p256dh"],
            auth=body.keys["auth"],
        ))
    await session.commit()


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(
    body: PushSubscriptionIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.user_id == user.id,
        )
    )
    await session.commit()
