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

- **Multi-user with admin approval** — Cloudflare Access SSO with automatic
  user provisioning, plus optional local accounts (admins create users; open
  registration is off by default and can be toggled on). Users see their own
  requests; admins see everything and approve/deny with one click.
  Denials can carry a reason, and a denied title can be re-requested (it goes
  back to pending).
- **Unified search** — one search box across both libraries. Manga results
  come from mangarr's MangaUpdates search, comic results from pullarr's
  ComicVine search — NextPanel proxies the apps, so no extra API keys are
  needed and results show what's already in each library.
- **Discovery home** — the Discover page opens with recommendation rows.
  Manga rows come from AniList's public API (no key needed): Trending Now,
  New This Season, Top Rated Last Season, and All-Time Favorites. Comic rows
  come from ComicVine via pullarr's key: New Comics This Week and New Comic
  Series This Month (ComicVine has no popularity data, so comic discovery is
  recency-based — issues by store date, `#1`s marking new series). Anything
  already in a library (matched by provider id or title) or already
  requested is filtered out, and every card is one tap to request. AniList
  results are cached for 30 minutes; ComicVine results for 6 hours inside
  pullarr, to stay well within both APIs' rate limits.
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
| `NEXTPANEL_SESSION_COOKIE_SECURE` | `true` | Set `false` only for local HTTP development |
| `NEXTPANEL_CLOUDFLARE_ACCESS_TEAM_DOMAIN` | empty | Access issuer, e.g. `https://your-team.cloudflareaccess.com` |
| `NEXTPANEL_CLOUDFLARE_ACCESS_AUDIENCE` | empty | Application Audience (AUD) tag; both SSO values are required |
| `NEXTPANEL_CLOUDFLARE_ACCESS_ADMIN_EMAILS` | empty | Optional comma-separated SSO identities to promote to admin |
| `NEXTPANEL_LOCAL_LOGIN_ENABLED` | `true` | Set `false` to disable setup, login, registration, password changes, and local user creation after SSO is configured |

Everything else (app URLs/keys, root folders, webhook secret, poll interval,
registration) lives in the UI under Settings and is stored in the DB.

## Cloudflare Zero Trust SSO

NextPanel consumes the signed identity assertion that Cloudflare Access sends
to the origin. It verifies the JWT signature against your team's rotating
public keys as well as its issuer, application audience, expiry, token type,
and user identity. It does not trust an email header by itself.

### Initial setup

1. In **Cloudflare Zero Trust → Access controls → Applications**, add a
   self-hosted application for the complete public NextPanel hostname. Add an
   Allow policy containing the emails, groups, or IdP rules that may use
   NextPanel. Do not create a Bypass policy for the main application.
2. Open the application's **Additional settings** and copy its **Application
   Audience (AUD) Tag**. Your team domain is
   `https://<team-name>.cloudflareaccess.com`.
3. Set the following on the NextPanel container and recreate it:

   ```yaml
   environment:
     NEXTPANEL_CLOUDFLARE_ACCESS_TEAM_DOMAIN: https://your-team.cloudflareaccess.com
     NEXTPANEL_CLOUDFLARE_ACCESS_AUDIENCE: paste-the-application-aud-tag
     NEXTPANEL_CLOUDFLARE_ACCESS_ADMIN_EMAILS: you@example.com
     NEXTPANEL_LOCAL_LOGIN_ENABLED: "true"
   ```

4. Visit NextPanel using the Cloudflare-protected hostname. NextPanel signs
   you in automatically. On an empty database, the first SSO identity is the
   admin. On an existing installation, an SSO email matching a local username
   uses that account; otherwise a new non-admin profile is created. The
   optional admin-email variable also promotes matching identities.
5. After verifying SSO and admin access, set
   `NEXTPANEL_LOCAL_LOGIN_ENABLED: "false"` and recreate the container. This
   removes and rejects every username/password entry point. The flag only
   takes effect when both valid-looking SSO settings are present, which avoids
   disabling local login due to an incomplete configuration.

Cloudflare normally protects the webhook URLs too. Mangarr and pullarr do not
currently send Cloudflare Access credentials, so create a more-specific
self-hosted Access application for `/api/v1/webhooks/*` with a Bypass policy,
and leave NextPanel's webhook secret enabled. This exposes only the webhook
route, which still requires `X-Webhook-Secret`; never bypass the whole
hostname.

Cloudflare documents the assertion header, signing-key endpoint, issuer, and
AUD validation in [Validate JWTs](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).
The NextPanel sign-out button also opens Cloudflare's documented
[`/cdn-cgi/access/logout` endpoint](https://developers.cloudflare.com/cloudflare-one/faq/authentication-faq/),
so signing out does not immediately and silently sign the same Access identity
back in.

### Adding and removing SSO-only users

- To add a user, add their email/group to the NextPanel application's
  Cloudflare Access Allow policy. There is nothing to create in NextPanel and
  no password to distribute. Their non-admin NextPanel profile appears on
  their first visit.
- To grant NextPanel admin rights, toggle **Admin** for their profile under
  **Users** after that first visit, or add the exact email to
  `NEXTPANEL_CLOUDFLARE_ACCESS_ADMIN_EMAILS` and restart.
- To remove access, remove the identity from the Cloudflare Allow policy (and
  revoke its Access session when immediate removal is needed). You may then
  delete the old profile under **Users** to remove its NextPanel data.

SSO-only profiles have an unusable password hash. If local login is later
re-enabled, those users still cannot use it unless an admin explicitly resets
their password.

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

- **Create the admin account before exposing the tunnel, or configure Access
  first.** On a fresh install the first local setup or verified SSO identity
  becomes the admin.
- **Only expose NextPanel — never mangarr or pullarr.** Both siblings hand
  their API key to anyone who can reach `GET /initialize.json`; they must
  stay LAN/tunnel-internal. NextPanel talks to them server-side, so users
  never need to reach them.
- **Leave open registration off** unless you want strangers submitting
  requests; create accounts for your users instead.
- Point the tunnel at NextPanel's port only. Keep the origin private so every
  browser request is forced through the Access policy.

## API notes

- All routes live under `/api/v1`. User routes use a session cookie
  (`nextpanel_session`); there is no X-Api-Key like the sibling apps.
- `POST /api/v1/webhooks/{mangarr|pullarr}` is authenticated by the
  `X-Webhook-Secret` header matching the configured secret, and accepts
  `{"event": "import", "series_id": <id in that app>}`.
- Sessions expire after 30 days.
