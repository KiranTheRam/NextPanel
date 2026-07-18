from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import User, UserSession

SESSION_COOKIE = "nextpanel_session"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    if not token:
        raise HTTPException(401, "Not signed in")
    row = await session.get(UserSession, token)
    if row is None or row.expires_at < _utcnow():
        raise HTTPException(401, "Session expired")
    user = await session.get(User, row.user_id)
    if user is None:
        raise HTTPException(401, "Session expired")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user
