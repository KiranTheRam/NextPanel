import os
import tempfile

# must land before nextpanel.config is imported anywhere
os.environ.setdefault("NEXTPANEL_DATA_DIR", tempfile.mkdtemp(prefix="nextpanel-test-"))

import httpx
import pytest

from nextpanel import models
from nextpanel.db import engine, session_scope


@pytest.fixture(autouse=True)
async def clean_db():
    from nextpanel import ratelimit

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)
    ratelimit.reset()
    yield


@pytest.fixture
async def client():
    from nextpanel.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin(client):
    """First-run setup: creates + signs in the admin account."""
    resp = await client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "hunter22"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def configured(admin, client):
    """Admin session with both apps configured against test URLs."""
    resp = await client.put("/api/v1/settings", json={
        "mangarr_url": "http://mangarr.test",
        "mangarr_api_key": "manga-key",
        "mangarr_root_folder_id": "1",
        "pullarr_url": "http://pullarr.test",
        "pullarr_api_key": "comic-key",
        "pullarr_root_folder_id": "2",
        "webhook_secret": "hook-secret",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


async def register_user(client, username="reader", password="readerpass"):
    # open registration ships disabled; tests that register turn it on
    await set_settings(registration_enabled="true")
    resp = await client.post(
        "/api/v1/auth/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def set_settings(**values):
    from nextpanel import settings_service

    async with session_scope() as session:
        await settings_service.set_many(session, {k: str(v) for k, v in values.items()})
