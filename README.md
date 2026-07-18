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

- **Multi-user with admin approval** — local accounts (open registration can
  be toggled off), users see their own requests, admins see everything and
  approve/deny with one click. Denials can carry a reason, and a denied title
  can be re-requested (it goes back to pending).
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
4. Optionally turn off **open registration** and create accounts for your
   users yourself under **Users**.

## How a request flows

1. A user searches on **Discover** and hits *Request*. Titles already in a
   library show **In Library** instead; already-requested titles show their
   current status.
2. The request appears as **Pending** for the admin (badge in the sidebar).
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

## API notes

- All routes live under `/api/v1`. User routes use a session cookie
  (`nextpanel_session`); there is no X-Api-Key like the sibling apps.
- `POST /api/v1/webhooks/{mangarr|pullarr}` is authenticated by the
  `X-Webhook-Secret` header matching the configured secret, and accepts
  `{"event": "import", "series_id": <id in that app>}`.
- Passwords are stored as salted scrypt hashes; sessions expire after 30 days.
- Like its siblings, NextPanel is built for a trusted LAN. Put a reverse
  proxy with TLS in front if you expose it further.
