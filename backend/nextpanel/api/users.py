from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Request, User
from ..schemas import UserCreateIn, UserOut, UserUpdateIn
from ..security import hash_password
from .auth import _clean_username, _username_taken
from .deps import require_admin

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[UserOut])
async def list_users(session: AsyncSession = Depends(get_session)):
    counts = dict(
        (await session.execute(
            select(Request.user_id, func.count(Request.id)).group_by(Request.user_id)
        )).all()
    )
    result = await session.execute(select(User).order_by(User.username))
    out = []
    for user in result.scalars().all():
        row = UserOut.model_validate(user)
        row.request_count = counts.get(user.id, 0)
        out.append(row)
    return out


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreateIn, session: AsyncSession = Depends(get_session)):
    username = _clean_username(body.username)
    if await _username_taken(session, username):
        raise HTTPException(409, "Username already taken")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdateIn,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_admin is not None:
        if user.id == admin.id and not body.is_admin:
            raise HTTPException(400, "You cannot remove your own admin access")
        user.is_admin = body.is_admin
    await session.commit()
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(400, "You cannot delete your own account")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    await session.delete(user)
    await session.commit()
