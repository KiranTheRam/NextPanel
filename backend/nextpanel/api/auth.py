import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ratelimit, settings_service
from ..config import config
from ..db import get_session
from ..models import User, UserSession
from ..schemas import AuthStatusOut, CredentialsIn, PasswordChangeIn, UserOut
from ..security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)
from .deps import SESSION_COOKIE, _utcnow, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_DAYS = 30
LOGIN_LIMIT, LOGIN_WINDOW = 10, 15 * 60       # per ip+username
LOGIN_GLOBAL_LIMIT = 50                        # caps total scrypt work per window
REGISTER_LIMIT, REGISTER_WINDOW = 5, 60 * 60  # per ip
REGISTER_GLOBAL_LIMIT = 20
PASSWORD_LIMIT, PASSWORD_WINDOW = 10, 15 * 60  # per ip+user
_PASSWORD_CHECKS = asyncio.Semaphore(4)


async def _user_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(User.id)))).scalar_one()


async def _start_session(
    session: AsyncSession, request: Request, response: Response, user: User
) -> None:
    token = new_session_token()
    session.add(UserSession(
        token=hash_token(token), user_id=user.id,
        expires_at=_utcnow() + timedelta(days=SESSION_DAYS),
    ))
    await session.commit()
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True, samesite="lax", path="/",
        secure=config.session_cookie_secure,
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
    body: CredentialsIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
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
    await _start_session(session, request, response, user)
    return user


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    body: CredentialsIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    if await settings_service.get(session, "registration_enabled") != "true":
        raise HTTPException(403, "Registration is disabled — ask the admin for an account")
    if await _user_count(session) == 0:
        raise HTTPException(403, "Run first-time setup instead")
    ratelimit.check("register:global", REGISTER_GLOBAL_LIMIT, REGISTER_WINDOW)
    ratelimit.check(f"register:{ratelimit.client_ip(request)}", REGISTER_LIMIT, REGISTER_WINDOW)
    username = _clean_username(body.username)
    if await _username_taken(session, username):
        raise HTTPException(409, "Username already taken")
    user = User(username=username, password_hash=hash_password(body.password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await _start_session(session, request, response, user)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    body: CredentialsIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    username = body.username.strip().lower()
    ratelimit.check("login:global", LOGIN_GLOBAL_LIMIT, LOGIN_WINDOW)
    rate_key = f"login:{ratelimit.client_ip(request)}:{username}"
    ratelimit.check(rate_key, LOGIN_LIMIT, LOGIN_WINDOW)
    result = await session.execute(
        select(User).where(func.lower(User.username) == username)
    )
    user = result.scalar_one_or_none()
    # scrypt is deliberately expensive.  Run it outside the event loop and
    # fail fast when all workers are occupied rather than accumulating work.
    if _PASSWORD_CHECKS.locked():
        raise HTTPException(429, "Too many login attempts — try again later")
    async with _PASSWORD_CHECKS:
        password_ok = await asyncio.to_thread(
            verify_password, body.password,
            user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
        )
    if user is None or not password_ok:
        raise HTTPException(401, "Invalid username or password")
    ratelimit.clear(rate_key)
    await _start_session(session, request, response, user)
    return user


@router.post("/password", response_model=UserOut)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Change your own password. Every existing session is dropped — a
    password change is how you lock out a device you no longer trust — and
    the caller is immediately issued a fresh one so they stay signed in."""
    from sqlalchemy import delete

    rate_key = f"password:{ratelimit.client_ip(request)}:{user.id}"
    ratelimit.check(rate_key, PASSWORD_LIMIT, PASSWORD_WINDOW)
    if _PASSWORD_CHECKS.locked():
        raise HTTPException(429, "Too busy — try again in a moment")
    async with _PASSWORD_CHECKS:
        current_ok = await asyncio.to_thread(
            verify_password, body.current_password, user.password_hash
        )
    if not current_ok:
        raise HTTPException(403, "Current password is incorrect")
    ratelimit.clear(rate_key)

    user.password_hash = hash_password(body.new_password)
    await session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await session.commit()
    await _start_session(session, request, response, user)
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
