from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..db import get_session
from ..models import User, UserSession
from ..schemas import AuthStatusOut, CredentialsIn, UserOut
from ..security import hash_password, new_session_token, verify_password
from .deps import SESSION_COOKIE, _utcnow, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_DAYS = 30


async def _user_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(User.id)))).scalar_one()


async def _start_session(session: AsyncSession, response: Response, user: User) -> None:
    token = new_session_token()
    session.add(UserSession(
        token=token, user_id=user.id,
        expires_at=_utcnow() + timedelta(days=SESSION_DAYS),
    ))
    await session.commit()
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True, samesite="lax", path="/",
    )


def _clean_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise HTTPException(422, "Username required")
    return username


async def _username_taken(session: AsyncSession, username: str) -> bool:
    existing = await session.execute(
        select(User).where(func.lower(User.username) == username.lower())
    )
    return existing.scalar_one_or_none() is not None


@router.get("/status", response_model=AuthStatusOut)
async def auth_status(session: AsyncSession = Depends(get_session)):
    """Public bootstrap info for the login page."""
    return AuthStatusOut(
        setup_required=await _user_count(session) == 0,
        registration_enabled=(
            await settings_service.get(session, "registration_enabled") == "true"
        ),
    )


@router.post("/setup", response_model=UserOut, status_code=201)
async def setup(
    body: CredentialsIn, response: Response, session: AsyncSession = Depends(get_session)
):
    """First-run: create the admin account. Only works while no users exist."""
    if await _user_count(session) > 0:
        raise HTTPException(403, "Setup already completed")
    user = User(
        username=_clean_username(body.username),
        password_hash=hash_password(body.password),
        is_admin=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await _start_session(session, response, user)
    return user


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    body: CredentialsIn, response: Response, session: AsyncSession = Depends(get_session)
):
    if await settings_service.get(session, "registration_enabled") != "true":
        raise HTTPException(403, "Registration is disabled — ask the admin for an account")
    if await _user_count(session) == 0:
        raise HTTPException(403, "Run first-time setup instead")
    username = _clean_username(body.username)
    if await _username_taken(session, username):
        raise HTTPException(409, "Username already taken")
    user = User(username=username, password_hash=hash_password(body.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await _start_session(session, response, user)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    body: CredentialsIn, response: Response, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(User).where(func.lower(User.username) == body.username.strip().lower())
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    await _start_session(session, response, user)
    return user


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import delete

    await session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
