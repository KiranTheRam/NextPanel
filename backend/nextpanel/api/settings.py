from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import settings_service
from ..arr import ArrError, client_by_app
from ..db import get_session
from ..schemas import ConnectionTestOut
from .deps import require_admin

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])

MASK = "••••••••"


@router.get("")
async def get_settings(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    values = await settings_service.get_all(session)
    for key in settings_service.SECRET_KEYS:
        if values.get(key):
            values[key] = MASK
    return values


@router.put("")
async def update_settings(
    body: dict[str, str], session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    # ignore masked secrets that the admin did not change
    to_save = {k: v for k, v in body.items() if v != MASK}
    try:
        settings_service.validate(to_save)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await settings_service.set_many(session, to_save)
    if "poll_interval_minutes" in to_save:
        from ..scheduler import reschedule_poll

        reschedule_poll(int(to_save["poll_interval_minutes"]))
    return await get_settings(session)


async def _client_with_overrides(
    session: AsyncSession, app: str, url: str | None, api_key: str | None
):
    """Build a client from stored settings, letting the request body
    override URL/key so Test works on unsaved form values."""
    values = await settings_service.get_all(session)
    if url:
        values[f"{app}_url"] = url
    if api_key and api_key != MASK:
        values[f"{app}_api_key"] = api_key
    client = client_by_app(app, values)
    if client is None:
        raise HTTPException(404, "Unknown app")
    return client


@router.post("/test/{app}", response_model=ConnectionTestOut)
async def test_connection(
    app: str, body: dict[str, str], session: AsyncSession = Depends(get_session)
):
    client = await _client_with_overrides(session, app, body.get("url"), body.get("api_key"))
    try:
        status = await client.ping()
    except ArrError as exc:
        return ConnectionTestOut(ok=False, message=str(exc))
    return ConnectionTestOut(ok=True, version=str(status.get("version", "")))


@router.get("/rootfolders/{app}")
async def root_folders(app: str, session: AsyncSession = Depends(get_session)):
    client = await _client_with_overrides(session, app, None, None)
    try:
        return await client.root_folders()
    except ArrError as exc:
        raise HTTPException(502, str(exc)) from exc
