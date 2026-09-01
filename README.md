# ICT Trader Dashboard

> # 🗄️ THE STREAMLIT APP IS RETIRED (2026-09-01)
>
> **The live dashboard is the Svelte SPA:**
> <https://benbaichmankass.github.io/ict-trader-dashboard/> (source: `webapp/`).
>
> The Streamlit app in this repo **no longer calls the bot API**. Its entry
> point `streamlit_app.py` is now a notice page that makes no upstream request;
> the previous 9,628-line implementation is preserved verbatim at
> [`archive/streamlit_app_RETIRED_2026-09-01.py`](archive/streamlit_app_RETIRED_2026-09-01.py)
> and in git history.
>
> **Why, and why it matters:** operator decision 2026-09-01
> (`BL-20260901-RETIRE-ANDROID-AND-STREAMLIT-FROM-THE-LIVE-FEED` in the bot
> repo) — the SPA is the only live consumer. That is the **precondition for
> gating the bot's read surface** (Phase H): a gate is only tractable once
> there is nothing else left to keep working. ⚠️ **Do not restore this app or
> point it back at the bot** without reversing that decision explicitly.
>
> Everything below describing Streamlit as live is **historical**. The SPA
> sections still apply.

## Architecture (current)

```
Browser ──HTTPS──▶ GitHub Pages (Svelte SPA) ──HTTPS──▶ Caddy on the VPS
                                                        └─▶ FastAPI :8001
```

The SPA calls the bot **browser-direct** over HTTPS via Caddy
(`https://ict-bot.duckdns.org`), so bot-side CORS **is** load-bearing.

<details>
<summary>🗄️ Retired architecture — the Streamlit transport (historical)</summary>

```
Browser ──HTTPS──▶ Streamlit Community Cloud ──HTTP──▶ VPS FastAPI :8001
                   (Python server, free tier)         (141.145.193.91)
```

The Python server made the upstream call directly. No browser
mixed-content block, no Cloudflare tunnel, no Vercel rewrite, no
transport-layer moving parts. CORS was **not** load-bearing for this path —
an exemption that retired with the app.

</details>

## 🗄️ Deploy on Streamlit Community Cloud (RETIRED — historical)

> ⚠️ **Retained only so the deployment can be found and shut down.** The
> Community Cloud app still tracks `main`, so it will redeploy the retirement
> notice. **Fully removing it is an operator action** in
> <https://share.streamlit.io> (delete the app); nothing in this repo can do
> it. Until then the app serves a notice page and reaches no bot data.

1. Push to `main` (this is your GitHub deploy trigger).
2. <https://share.streamlit.io> → sign in with the operator's GitHub.
3. **New app** → `benbaichmankass/ict-trader-dashboard` → branch `main`
   → main file `streamlit_app.py` → **Deploy**.
4. Streamlit Cloud auto-redeploys on every push to `main`.

Optional: in the app's **Settings → Secrets** tab, set
`BOT_API_URL = "http://141.145.193.91:8001"` if the VPS IP ever changes
(this is the hardcoded default, so you can skip it).

## Local dev

The SPA is the live app — see `webapp/` for its dev instructions.

<details>
<summary>🗄️ Running the retired Streamlit app locally (historical)</summary>

`streamlit run streamlit_app.py` now serves the retirement notice. To run the
archived implementation for reference:

```bash
pip install -r requirements.txt
streamlit run archive/streamlit_app_RETIRED_2026-09-01.py
# Override the upstream:
# BOT_API_URL=http://localhost:8001 streamlit run archive/streamlit_app_RETIRED_2026-09-01.py
```

⚠️ That archived file **does** call the bot API. Point it at a local bot, not
the live one.

</details>

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
