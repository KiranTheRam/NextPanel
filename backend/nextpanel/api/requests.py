from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import push, settings_service
from ..arr import ArrConflict, ArrError, client_for
from ..db import get_session
from ..models import MediaType, Request, RequestStatus, User
from ..schemas import ApproveIn, DenyIn, RequestCreateIn, RequestOut
from ..security import safe_cover_url
from ..status import refresh_request
from .deps import get_current_user, require_admin

router = APIRouter(prefix="/requests", tags=["requests"])

# per-user cap on undecided requests, so one account can't flood the
# admin queue on a publicly reachable instance
MAX_PENDING_PER_USER = 25


def _out(request: Request) -> RequestOut:
    out = RequestOut.model_validate(request)
    out.cover_url = safe_cover_url(out.cover_url)
    out.username = request.user.username if request.user else ""
    out.decided_by_username = request.decided_by.username if request.decided_by else ""
    return out


async def _load(session: AsyncSession, request_id: int) -> Request:
    result = await session.execute(
        select(Request)
        .options(selectinload(Request.user), selectinload(Request.decided_by))
        .where(Request.id == request_id)
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(404, "Request not found")
    return request


@router.get("", response_model=list[RequestOut])
async def list_requests(
    scope: str = "mine",
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    query = (
        select(Request)
        .options(selectinload(Request.user), selectinload(Request.decided_by))
        .order_by(Request.created_at.desc())
    )
    if scope == "all":
        if not user.is_admin:
            raise HTTPException(403, "Admin access required")
    else:
        query = query.where(Request.user_id == user.id)
    result = await session.execute(query)
    return [_out(r) for r in result.scalars().all()]


@router.post("", response_model=RequestOut, status_code=201)
async def create_request(
    body: RequestCreateIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import func

    pending_count = (await session.execute(
        select(func.count(Request.id)).where(
            Request.user_id == user.id,
            Request.status == RequestStatus.PENDING,
        )
    )).scalar_one()
    if pending_count >= MAX_PENDING_PER_USER and not user.is_admin:
        raise HTTPException(
            429, f"You already have {pending_count} pending requests — "
            "wait for the admin to review them"
        )

    existing = (await session.execute(
        select(Request).where(
            Request.media_type == body.media_type,
            Request.provider == body.provider,
            Request.provider_id == body.provider_id,
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.status == RequestStatus.DENIED:
            # a denied title may be asked for again — the new ask replaces
            # the old decision and goes back to the admin
            existing.user_id = user.id
            existing.status = RequestStatus.PENDING
            existing.note = ""
            existing.decided_by_id = None
            await session.commit()
            push.notify_later(push.notify_admins_new_request(user.username, existing.title))
            return _out(await _load(session, existing.id))
        raise HTTPException(409, "Already requested")
    request = Request(
        user_id=user.id,
        media_type=body.media_type,
        provider=body.provider,
        provider_id=body.provider_id,
        title=body.title.strip() or "Untitled",
        english_title=body.english_title,
        alt_titles="\n".join(body.alt_titles),
        year=body.year,
        cover_url=body.cover_url,
        description=body.description,
    )
    session.add(request)
    try:
        await session.commit()
    except IntegrityError:
        # pre-provider-column databases enforce uniqueness on
        # (media_type, provider_id) only — surface it as a duplicate
        await session.rollback()
        raise HTTPException(409, "Already requested") from None
    push.notify_later(push.notify_admins_new_request(user.username, request.title))
    return _out(await _load(session, request.id))


@router.delete("/{request_id}", status_code=204)
async def delete_request(
    request_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Withdraw a request. Users may remove their own pending requests;
    admins may remove any (this does not delete the series in the app)."""
    request = await _load(session, request_id)
    if not user.is_admin:
        if request.user_id != user.id:
            raise HTTPException(403, "Not your request")
        if request.status != RequestStatus.PENDING:
            raise HTTPException(400, "Only pending requests can be withdrawn")
    await session.delete(request)
    await session.commit()


@router.post("/{request_id}/approve", response_model=RequestOut)
async def approve_request(
    request_id: int,
    body: ApproveIn,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    request = await _load(session, request_id)
    if request.status not in (RequestStatus.PENDING, RequestStatus.FAILED):
        raise HTTPException(400, f"Request is already {request.status.value}")

    values = await settings_service.get_all(session)
    client = client_for(request.media_type, values)
    default_key = (
        "mangarr_root_folder_id"
        if request.media_type == MediaType.MANGA
        else "pullarr_root_folder_id"
    )
    root_folder_id = body.root_folder_id
    if root_folder_id is None:
        raw = values[default_key].strip()
        if not raw:
            raise HTTPException(
                422,
                f"No default root folder configured for {client.app_name} — "
                "set one in Settings or pass one with the approval",
            )
        root_folder_id = int(raw)

    try:
        remote_id = await client.add_series(
            request.provider_id,
            root_folder_id,
            provider=request.provider,
            english_title=request.english_title,
            alt_titles=[t for t in request.alt_titles.split("\n") if t],
        )
    except ArrConflict:
        # already in the app's library — adopt the existing series
        try:
            remote_id = await client.find_series_id(request.provider_id, request.provider)
        except ArrError as exc:
            raise HTTPException(502, str(exc)) from exc
        if remote_id is None:
            raise HTTPException(
                502,
                f"{client.app_name} reports the series exists but it could not be found",
            ) from None
    except ArrError as exc:
        raise HTTPException(502, str(exc)) from exc

    request.remote_series_id = remote_id
    request.status = RequestStatus.PROCESSING
    request.note = ""
    request.decided_by_id = admin.id
    # first sync right away so an already-downloaded series shows available
    await refresh_request(session, request, client)
    await session.commit()
    return _out(await _load(session, request_id))


@router.post("/{request_id}/deny", response_model=RequestOut)
async def deny_request(
    request_id: int,
    body: DenyIn,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    request = await _load(session, request_id)
    if request.status != RequestStatus.PENDING:
        raise HTTPException(400, f"Request is already {request.status.value}")
    request.status = RequestStatus.DENIED
    request.note = body.reason.strip()
    request.decided_by_id = admin.id
    await session.commit()
    push.notify_later(
        push.notify_request_denied(
            request.user_id,
            request.title,
            request.note,
            request.media_type,
            request.provider,
            request.provider_id,
        )
    )
    return _out(await _load(session, request_id))


@router.post("/{request_id}/refresh", response_model=RequestOut)
async def refresh_one(
    request_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """On-demand status sync against the app (any signed-in user)."""
    request = await _load(session, request_id)
    if not user.is_admin and request.user_id != user.id:
        raise HTTPException(403, "Not your request")
    if request.remote_series_id is not None and request.status not in (
        RequestStatus.DENIED, RequestStatus.PENDING
    ):
        values = await settings_service.get_all(session)
        await refresh_request(session, request, client_for(request.media_type, values))
        await session.commit()
    return _out(await _load(session, request_id))
