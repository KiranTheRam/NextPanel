from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import push
from ..db import get_session
from ..models import Issue, IssueStatus, MediaType, User, utcnow
from ..schemas import IssueCreateIn, IssueOut, IssueResolveIn
from ..security import safe_cover_url
from .deps import get_current_user, require_admin

router = APIRouter(prefix="/issues", tags=["issues"])

# open reports one non-admin account may have at once
MAX_OPEN_PER_USER = 10


def _out(issue: Issue) -> IssueOut:
    out = IssueOut.model_validate(issue)
    out.cover_url = safe_cover_url(out.cover_url)
    out.username = issue.user.username if issue.user else ""
    out.resolved_by_username = issue.resolved_by.username if issue.resolved_by else ""
    return out


def _query():
    return select(Issue).options(selectinload(Issue.user), selectinload(Issue.resolved_by))


async def _load(session: AsyncSession, issue_id: int) -> Issue:
    # populate_existing: a reload after a change must refresh relationships
    # the session already holds (resolved_by after resolving)
    issue = (await session.execute(
        _query().where(Issue.id == issue_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if issue is None:
        raise HTTPException(404, "Issue not found")
    return issue


@router.get("", response_model=list[IssueOut])
async def list_issues(
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    status: str = Query(default="all", pattern="^(open|resolved|all)$"),
    media_type: MediaType | None = None,
    provider: str | None = None,
    provider_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Admins see every report with scope=all; everyone sees their own.
    The title filters list the reports about one title (its detail page)."""
    query = _query().order_by(Issue.created_at.desc())
    if scope == "all":
        if not user.is_admin:
            raise HTTPException(403, "Admin access required")
    else:
        query = query.where(Issue.user_id == user.id)
    if status != "all":
        query = query.where(Issue.status == IssueStatus(status))
    if media_type is not None:
        query = query.where(Issue.media_type == media_type)
    if provider is not None:
        query = query.where(Issue.provider == provider)
    if provider_id is not None:
        query = query.where(Issue.provider_id == provider_id)
    return [_out(i) for i in (await session.execute(query)).scalars().all()]


@router.post("", response_model=IssueOut, status_code=201)
async def report_issue(
    body: IssueCreateIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user.is_admin:
        open_count = (await session.execute(
            select(func.count(Issue.id)).where(
                Issue.user_id == user.id, Issue.status == IssueStatus.OPEN
            )
        )).scalar_one()
        if open_count >= MAX_OPEN_PER_USER:
            raise HTTPException(
                429, f"You already have {open_count} open reports — wait for them to be resolved"
            )
    issue = Issue(
        user_id=user.id,
        media_type=body.media_type,
        provider=body.provider,
        provider_id=body.provider_id,
        title=body.title.strip(),
        cover_url=body.cover_url,
        kind=body.kind,
        message=body.message.strip(),
    )
    session.add(issue)
    await session.commit()
    push.notify_later(push.notify_admins_new_issue(
        user.username, issue.title, issue.kind, issue.message
    ))
    return _out(await _load(session, issue.id))


@router.post("/{issue_id}/resolve", response_model=IssueOut)
async def resolve_issue(
    issue_id: int,
    body: IssueResolveIn,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    issue = await _load(session, issue_id)
    if issue.status == IssueStatus.RESOLVED:
        raise HTTPException(400, "Issue is already resolved")
    issue.status = IssueStatus.RESOLVED
    issue.resolution = body.resolution.strip()
    issue.resolved_by_id = admin.id
    issue.resolved_at = utcnow()
    await session.commit()
    if issue.user_id != admin.id:
        push.notify_later(push.notify_issue_resolved(
            issue.user_id, issue.title, issue.resolution,
            issue.media_type, issue.provider, issue.provider_id,
        ))
    return _out(await _load(session, issue_id))


@router.post("/{issue_id}/reopen", response_model=IssueOut)
async def reopen_issue(
    issue_id: int,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    issue = await _load(session, issue_id)
    issue.status = IssueStatus.OPEN
    issue.resolved_by_id = None
    issue.resolved_at = None
    await session.commit()
    return _out(await _load(session, issue_id))


@router.delete("/{issue_id}", status_code=204)
async def delete_issue(
    issue_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Reporters may withdraw their own open reports; admins may delete any."""
    issue = await _load(session, issue_id)
    if not user.is_admin:
        if issue.user_id != user.id:
            raise HTTPException(403, "Not your report")
        if issue.status != IssueStatus.OPEN:
            raise HTTPException(400, "Only open reports can be withdrawn")
    await session.delete(issue)
    await session.commit()
