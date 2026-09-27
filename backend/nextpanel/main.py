import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, discover as discover_service, http_client, scheduler
from .api import auth, detail, discover, push, requests, search, settings, users, webhooks
from .config import config
from .db import init_db

logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("nextpanel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await scheduler.start()
    # Do not make application startup wait on AniList, but start filling the
    # recommendation cache before the first browser asks for it.
    discover_warmup = asyncio.create_task(discover_service.warm_sections())
    log.info("NextPanel %s ready on %s:%d", __version__, config.host, config.port)
    try:
        yield
    finally:
        discover_warmup.cancel()
        await asyncio.gather(discover_warmup, return_exceptions=True)
        scheduler.shutdown()
        await http_client.aclose()


app = FastAPI(title="NextPanel", version=__version__, lifespan=lifespan)
# Cloudflare compresses at its edge already; this covers LAN access and the
# tunnel hop. Added before the header middleware below so it sits inside it
# and sees each response whole, which is what lets it skip small ones.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# NextPanel is built to sit behind a public reverse proxy (e.g. a Cloudflare
# tunnel); browsers get defense-in-depth headers on every response. The CSP
# allows external https images (series covers) and inline style attributes
# (React), nothing else beyond same-origin.
_CSP = (
    "default-src 'self'; img-src 'self' data: https://*.anilist.co https://*.mangaupdates.com "
    "https://*.mangadex.org https://*.mangadex.network https://*.gamespot.com; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'"
)
MAX_REQUEST_BODY_BYTES = 64 * 1024


@app.middleware("http")
async def security_headers(request, call_next):
    # Reject oversized declared bodies before JSON parsing or password work.
    # Cloudflare should enforce the same limit at the edge for chunked bodies.
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BODY_BYTES:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# Unlike mangarr/pullarr's single X-Api-Key gate, routes carry their own
# auth: session cookie for users, shared secret for inbound webhooks.
api = FastAPI()
api.include_router(auth.router)
api.include_router(push.router)
api.include_router(search.router)
api.include_router(discover.router)
api.include_router(detail.router)
api.include_router(requests.router)
api.include_router(users.router)
api.include_router(settings.router)
api.include_router(webhooks.router)
app.mount("/api/v1", api)


@app.get("/initialize.json")
async def initialize():
    return {"version": __version__, "urlBase": ""}


class FingerprintedStaticFiles(StaticFiles):
    """Vite puts a content hash in every /assets file name, so the bytes at
    a given URL never change and browsers need not revalidate them."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


# The page and the service worker are not fingerprinted: always revalidate
# them so a new release is picked up on the next load.
_REVALIDATE = {"Cache-Control": "no-cache"}

# Serve the built frontend if present (production/Docker)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/assets", FingerprintedStaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path:
            # resolve + containment check: the route param is percent-decoded,
            # so "..%2f" sequences would otherwise escape the static dir
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.is_relative_to(STATIC_DIR) and candidate.is_file():
                if candidate.name in ("index.html", "sw.js"):
                    return FileResponse(candidate, headers=_REVALIDATE)
                return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html", headers=_REVALIDATE)
else:

    @app.get("/")
    async def root():
        return JSONResponse({"app": "nextpanel", "version": __version__, "ui": "not built"})


def run() -> None:
    import uvicorn

    uvicorn.run("nextpanel.main:app", host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    run()
