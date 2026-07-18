<p align="center">
  <img src="frontend/public/nextpanel-icon.svg" width="160" height="160" alt="NextPanel icon">
</p>

# NextPanel

Overseerr-style **request manager** for your manga/comics stack. Users search
for manga and western comics, request them, and an admin approves or denies
each request from one place. Approved requests are sent to the right backend —
[mangarr](../mangarr) for manga, [pullarr](../pullarr) for comics — which adds
the series, monitors it, and starts downloading immediately. NextPanel then
tracks each request through **Processing → Partially Available → Available**
via webhooks from both apps (with scheduled polling as a fallback).

![stack](https://img.shields.io/badge/backend-FastAPI-009688) ![stack](https://img.shields.io/badge/frontend-React-61dafb) ![stack](https://img.shields.io/badge/db-SQLite-003b57)

## Features

- **Multi-user with admin approval** — local accounts (admins create users;
  open registration is off by default and can be toggled on), users see their
  own requests, admins see everything and approve/deny with one click.
  Denials can carry a reason, and a denied title can be re-requested (it goes
  back to pending).
- **Unified search** — one search box across both libraries. Manga results
  come from mangarr's MangaUpdates search, comic results from pullarr's
  ComicVine search — NextPanel proxies the apps, so no extra API keys are
  needed and results show what's already in each library.
- **Hands-off fulfillment** — approving calls the target app's add-series API
  with `search_now`, so the series is added, monitored, and hunted
  immediately using whatever sources that app has configured. If the series is
  already in the app's library, the request adopts it instead of failing.
- **Live availability** — mangarr/pullarr fire a webhook at NextPanel on every
  import; requests show downloaded/total progress and flip to Available when
  complete. A poll job (default: every 10 min) covers missed webhooks.
- **Same stack as its siblings** — FastAPI + SQLite backend, React/Vite
  frontend, one Docker image.

## Quick start (Docker)

```bash
git clone <this repo> nextpanel && cd nextpanel
docker compose up -d
```

Open <http://localhost:6995>. The first visit asks you to create the **admin
account** (this is the account that approves requests).

Then, in **Settings** (admin only):

1. **Mangarr**: URL (e.g. `http://mangarr:6996` on a shared Docker network, or
   `http://<host>:6996`) and its API key (shown at `GET /initialize.json` or
   in the app's data dir under `api_key`). *Test Connection*, **Save**, then
   pick the **default root folder** approved manga are added to.
2. **Pullarr**: same, on port 6997.
3. **Webhooks**: *Generate* a secret and **Save**. Then in mangarr → Settings
   → Connect — Webhook: enable, URL `http://<nextpanel>:6995/api/v1/webhooks/mangarr`,
   paste the secret, *Send Test Event*. Repeat in pullarr with
   `/api/v1/webhooks/pullarr`.
4. Create accounts for your users under **Users**, or turn on **open
   registration** in Settings if you want people to sign themselves up.

## Mobile app (PWA) & push notifications

NextPanel is an installable PWA with a native-feeling mobile layout (bottom
tab bar, no input auto-zoom, safe-area aware):

- **Install**: on Android/Chrome use the browser's *Install app* prompt; on
  iOS Safari use *Share → Add to Home Screen*.
- **Push notifications**: on the **Requests** page, tap the bell button
  ("Notifications") and allow the permission. Admins are notified when a new
  request needs approval; users are notified when their request becomes
  available or is denied. Each device that should get notifications enables
  the bell once while signed in.
- **iOS note**: Apple only allows web push for PWAs that are installed to the
  home screen (iOS 16.4+), so add NextPanel to the home screen first — the
  bell button appears once push is actually available. Push also requires the
  site to be served over HTTPS (your Cloudflare tunnel provides this).
- VAPID keys are generated automatically on first use and stored in the data
  dir (`vapid_private_key.pem`). `NEXTPANEL_VAPID_SUB` optionally sets the
  contact claim (`mailto:` URI) sent to push services.

## How a request flows

1. A user searches on **Discover** and hits *Request*. Titles already in a
   library show **In Library** instead; already-requested titles show their
   current status.
2. The request appears in the admin's **Requests → Needs Approval** queue
   (with a count badge on the Requests tab), and admins with notifications
   enabled get a push.
3. **Approve** adds the series to mangarr/pullarr (monitored, with an
   immediate search) into the configured root folder; the request becomes
   **Processing**. **Deny** stops it with an optional reason.
4. As the app imports chapters/issues it webhooks NextPanel; the request shows
   progress (e.g. `41/102`) as **Partially Available** and finally
   **Available**. Ongoing series may return to Partially Available when new
   chapters are announced — that simply reflects the library.
5. If the add fails (app down, bad root folder), the request is left
   pending/failed with the error surfaced — fix the cause and hit *Retry*.

## Local development

Backend (Python ≥3.11):

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn nextpanel.main:app --port 6995 --reload
```

Frontend (Node ≥20):

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5174, proxies API to :6995
```

Tests:

```bash
cd backend && .venv/bin/python -m pytest
```

`npm run build` writes the production bundle to `backend/static/`, which the
FastAPI app serves when present.

## Configuration

Environment variables (all optional):

| Variable             | Default | Description                         |
| -------------------- | ------- | ----------------------------------- |
| `NEXTPANEL_PORT`     | `6995`  | HTTP port                           |
| `NEXTPANEL_DATA_DIR` | `data`  | SQLite DB location                  |

Everything else (app URLs/keys, root folders, webhook secret, poll interval,
registration) lives in the UI under Settings and is stored in the DB.

## Hosting publicly (e.g. Cloudflare tunnel)

NextPanel is the one piece of this stack designed to face the internet, and
ships hardened for it: brute-force rate limiting on login/registration
(keyed by `CF-Connecting-IP`/`X-Forwarded-For` when present), scrypt password
hashes with an 8-character minimum, hashed session tokens in the DB, sessions
revoked on password reset, `Secure`/`HttpOnly`/`SameSite` cookies (Secure is
applied automatically when the request arrives via HTTPS or an
`X-Forwarded-Proto: https` proxy header), security headers + CSP on every
response, registration off by default, and a per-user cap on pending
requests. Still, the deployment rules matter:

- **Create the admin account before exposing the tunnel.** On a fresh
  install, the first visitor becomes the admin.
- **Only expose NextPanel — never mangarr or pullarr.** Both siblings hand
  their API key to anyone who can reach `GET /initialize.json`; they must
  stay LAN/tunnel-internal. NextPanel talks to them server-side, so users
  never need to reach them.
- **Leave open registration off** unless you want strangers submitting
  requests; create accounts for your users instead.
- Point the tunnel at NextPanel's port only, and consider putting Cloudflare
  Access in front for an extra auth layer.

## API notes

- All routes live under `/api/v1`. User routes use a session cookie
  (`nextpanel_session`); there is no X-Api-Key like the sibling apps.
- `POST /api/v1/webhooks/{mangarr|pullarr}` is authenticated by the
  `X-Webhook-Secret` header matching the configured secret, and accepts
  `{"event": "import", "series_id": <id in that app>}`.
- Sessions expire after 30 days.
