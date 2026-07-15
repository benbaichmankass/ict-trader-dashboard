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
