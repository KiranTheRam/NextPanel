import httpx
import pytest
from sqlalchemy import text
from starlette.applications import Starlette

from nextpanel import http_client, main
from nextpanel.db import engine


async def test_fingerprinted_assets_are_cached_for_good(tmp_path):
    (tmp_path / "index-abc123.js").write_text("console.log(1)")
    app = Starlette()
    app.mount("/assets", main.FingerprintedStaticFiles(directory=tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        hit = await client.get("/assets/index-abc123.js")
        miss = await client.get("/assets/index-old999.js")
    assert hit.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert miss.status_code == 404
    assert "cache-control" not in miss.headers


@pytest.mark.skipif(not main.STATIC_DIR.is_dir(), reason="frontend not built")
async def test_page_and_service_worker_are_revalidated(client):
    for path in ("/", "/requests", "/sw.js"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"


async def test_large_responses_are_compressed(client):
    resp = await client.get("/api/v1/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert resp.headers["content-encoding"] == "gzip"
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_outbound_calls_share_one_client():
    first = http_client.get_client()
    assert http_client.get_client() is first
    await http_client.aclose()
    assert first.is_closed
    assert http_client.get_client() is not first


async def test_connections_use_normal_sync():
    async with engine.connect() as conn:
        # 1 = NORMAL
        assert (await conn.execute(text("PRAGMA synchronous"))).scalar_one() == 1


async def test_small_responses_are_not_compressed(client):
    resp = await client.get("/initialize.json", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in resp.headers
