import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, scheduler
from .api import auth, discover, push, requests, search, settings, users, webhooks
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
    log.info("NextPanel %s ready on %s:%d", __version__, config.host, config.port)
    yield
    scheduler.shutdown()


app = FastAPI(title="NextPanel", version=__version__, lifespan=lifespan)

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
api.include_router(requests.router)
api.include_router(users.router)
api.include_router(settings.router)
api.include_router(webhooks.router)
app.mount("/api/v1", api)


@app.get("/initialize.json")
async def initialize():
    return {"version": __version__, "urlBase": ""}


# Serve the built frontend if present (production/Docker)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path:
            # resolve + containment check: the route param is percent-decoded,
            # so "..%2f" sequences would otherwise escape the static dir
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.is_relative_to(STATIC_DIR) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:

    @app.get("/")
    async def root():
        return JSONResponse({"app": "nextpanel", "version": __version__, "ui": "not built"})


def run() -> None:
    import uvicorn

    uvicorn.run("nextpanel.main:app", host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    run()
