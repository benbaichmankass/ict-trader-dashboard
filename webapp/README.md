# ICT Trader — Web App (Svelte SPA)

An investment-grade, free-tier replacement for the Streamlit dashboard. A
static Svelte + Vite single-page app hosted on **GitHub Pages**, talking
**browser-direct** to the bot's FastAPI over HTTPS. No server, no Streamlit
cold-starts, no per-interaction full-page reruns.

```
Browser ──HTTPS──▶ GitHub Pages (static CDN, this SPA)
   │
   └──HTTPS/WSS──▶ ict-bot.duckdns.org  ──▶ Caddy ──▶ localhost:8001 (bot FastAPI)
                   (Let's Encrypt cert)      reverse proxy
```

## Why this over Streamlit

- **Fast:** a static bundle off a CDN + client-side rendering. First paint is
  instant; data streams in. No 30-blocking-fetch page reruns.
- **Live:** the Overview chart + positions stream over the bot's `/ws/market`
  WebSocket (per-tick), not a polling loop that remounts the page.
- **Free:** GitHub Pages hosting + Let's Encrypt certs (via Caddy) + the OCI
  free-tier VM the bot already runs on. $0.

## HTTPS on the API (Phase 0 — prerequisite)

A GitHub Pages page is HTTPS, so a mixed-content `http://…:8001` fetch is
hard-blocked by the browser. The bot API therefore needs a public HTTPS
front. That is **Caddy** on the live VM, reverse-proxying `localhost:8001`,
with an automatic Let's Encrypt cert for `ict-bot.duckdns.org` (the DuckDNS
hostname pointed at the VM). Wiring + deploy live in the bot repo
(`ict-trading-bot`): the `Caddyfile`, the `vm-caddy-deploy` workflow, and the
CORS allow-list entry for the Pages origin. Ports 443 (+80) are opened via the
`vm-cloud-fix` / `vm-net-fix` workflows.

Until Phase 0 is deployed, run the app against a local bot over plain HTTP
(localhost is exempt from mixed-content) or point Settings at any reachable
HTTPS bot URL.

## Configuration

The API base URL resolves as (first wins):

1. **Settings → Bot API base URL** (runtime, stored in `localStorage`) — repoint
   without a redeploy.
2. `VITE_BOT_API_URL` build-time env (set in the Pages workflow if desired).
3. The built-in default: `https://ict-bot.duckdns.org`.

## Signing in (the Data Explorer only)

Almost everything here reads ungated endpoints and works signed out. **One tab
does not:** the **Data Explorer** reads `/api/bot/db/tables` and
`/api/bot/db/table/{name}`, which the bot gates behind `require_session` and
refuses with **401 before opening any database**. That fail-closed behaviour is
deliberate and correct — those routes read the money DB.

**Settings → Session** holds the login form. It POSTs to the bot's
`/api/auth/login` (its only mint path) and stores the returned 1-hour HS256 JWT
in `localStorage` under `ict.authSession`. The password is never stored — it is
sent once and dropped. The token is attached as `Authorization: Bearer` by
`lib/api.ts::get`, the app's single network chokepoint, so it reaches every REST
path; a 401 clears the token and puts the form back in front of you.

⚠️ **A session is only mintable if the BOT HOST carries three env vars**
(`JWT_SIGNING_KEY`, `ALLOWED_EMAIL`, `WEBAPP_PASSWORD_SHA256`). Without them
`/api/auth/login` returns **500 `auth_unavailable`** and no password will work —
the form says so explicitly rather than reporting a bad password. Setting them is
an operator action in the bot repo; the runbook is
[`docs/runbooks/restore-webapp-auth.md`](https://github.com/benbaichmankass/Metis-Insights/blob/main/docs/runbooks/restore-webapp-auth.md).
**Measured 2026-09-11:** the live host returned `500 auth_unavailable`, so the
tab is still dark — the client half is ready and waiting on the host half.

⚠️ `/ws/market` is **not** gated and is not covered by any of this: a browser
`WebSocket` cannot send an `Authorization` header at all. If the read gate ever
widens to the socket it needs a query-param or subprotocol scheme, which is a
genuine auth build rather than a header.

## Develop

```bash
cd webapp
npm install
# against the live HTTPS bot (default):
npm run dev
# or against a local bot over plain HTTP:
VITE_BOT_API_URL=http://localhost:8001 npm run dev
```

- `npm run build` → static bundle in `webapp/dist/`
- `npm run check` → `svelte-check` type/template check

## Checks

Three zero-dependency node checkers run on every PR (see `.github/workflows/ci.yml`).
Each carries a `--self-test` that plants the historical defect and requires the
checker to catch it — a gate that cannot fail proves nothing.

```bash
node tests/api-contract.mjs      # a field a route reads must exist in its payload
node tests/ws-frame-scope.mjs    # a symbol-scoped WS frame must not define row membership
node tests/auth-bearer.mjs       # every call to the bot API must carry the session bearer
```

Plus one **manual** browser check (not in CI — it needs Playwright + Chromium):

```bash
npm run build && node tests/manual/auth-e2e.mjs
```

## Deploy

Push to `main` touching `webapp/**` → the **Deploy webapp to GitHub Pages**
Action builds and publishes. Live at
`https://<owner>.github.io/ict-trader-dashboard/` (Vite `base` is the repo
name; override with `VITE_BASE` for a custom domain).

## Status

Phase 1 skeleton: Overview (exec-summary metrics + live candlestick chart +
open-positions table) on `/api/bot/stats`, `/api/bot/performance`, and the
`/ws/market` live stream. More screens (Trades, Performance deep-dive,
Strategies, Accounts, Reports, …) port over incrementally; Streamlit stays the
production app until this reaches parity.
