# ICT Trader Dashboard

Read-only live dashboard for the ICT Trading Bot's FastAPI on the VPS.
Server-rendered Streamlit app on Streamlit Community Cloud (free).

## Architecture

```
Browser ──HTTPS──▶ Streamlit Community Cloud ──HTTP──▶ VPS FastAPI :8001
                   (Python server, free tier)         (141.145.193.91)
```

The Python server makes the upstream call directly. No browser
mixed-content block, no Cloudflare tunnel, no Vercel rewrite, no
transport-layer moving parts.

## Deploy on Streamlit Community Cloud (one-time, operator)

1. Push to `main` (this is your GitHub deploy trigger).
2. <https://share.streamlit.io> → sign in with the operator's GitHub.
3. **New app** → `benbaichmankass/ict-trader-dashboard` → branch `main`
   → main file `streamlit_app.py` → **Deploy**.
4. Streamlit Cloud auto-redeploys on every push to `main`.

Optional: in the app's **Settings → Secrets** tab, set
`BOT_API_URL = "http://141.145.193.91:8001"` if the VPS IP ever changes
(this is the hardcoded default, so you can skip it).

## Local dev

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
# Override the upstream:
# BOT_API_URL=http://localhost:8001 streamlit run streamlit_app.py
```

## Sections

The sidebar is organized into **6 sections** — Overview · Performance ·
Strategies & Models · Accounts · Activity · Admin — each a landing of summary
cards that drill into the detail sub-pages (Overview, Performance, Insights,
Accounts, Positions, **Trades**, Signals, News, Exit Ladder, Prop, Order
Packages, Models, Promotion, Backtesting, Strategies, Data Explorer, Health,
Reports, Logs). The full per-sub-page endpoint map lives in
[`CLAUDE.md`](./CLAUDE.md) § "Sub-pages (endpoint reference)".

Full API contract: [`ict-trading-bot/CLAUDE.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/CLAUDE.md) § Dashboard REST API.

## Why not React + Vercel

The dashboard was a Vite/React SPA on Vercel for its first 5 days. Five
different transport architectures (direct HTTP, Vercel Edge Function,
Cloudflare Worker, CF quick tunnel, named CF tunnel) were all tried
because Vercel Hobby blocks plain-HTTP outbound from rewrites and from
user functions. The Streamlit pivot eliminates the entire problem.
Full rationale: [`CLAUDE.md`](./CLAUDE.md) § "Why not React + Vercel"
and [the audit doc in the bot repo](https://github.com/benbaichmankass/ict-trading-bot/blob/main/docs/audit/vercel-edge-vs-cf-worker.md).

**Do not reintroduce React + Vercel for this dashboard.** If a future
feature needs a richer UI, see CLAUDE.md for the alternatives to
consider first.
