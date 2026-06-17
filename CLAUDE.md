# ICT Trader Dashboard — CLAUDE.md

> **Production environment — live money is at risk.** This dashboard renders
> live trader and trainer state. It is a **read-only consumer** of the bot's
> REST API and holds no runtime state of its own.

## Operating rules live in the bot repo

There is **one** set of operating rules for both repos — they live in
[`benbaichmankass/ict-trading-bot`](https://github.com/benbaichmankass/ict-trading-bot)
and govern your work here too. They are deliberately *not* duplicated in this
file (duplication is how the two repos drift apart). Read them at the start of
any session that touches this repo:

- [`ict-trading-bot/CLAUDE.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/CLAUDE.md) — how you operate: instruction hierarchy, access & autonomy, honesty, permission tiers.
- [`ict-trading-bot/docs/CLAUDE-RULES-CANONICAL.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/docs/CLAUDE-RULES-CANONICAL.md) — the canonical rules in full.

You have full autonomous access to both VMs and the databases through the
GitHub Actions relays **in the `ict-trading-bot` repo** (the SSH key and diag
token are wired there). When you need live trader/trainer state to build or
debug a dashboard wiring, fetch it yourself via the diag-relay issues **in that
repo** — not here. The rest of this file is the **dashboard-specific**
reference (architecture, API contract, tabs).

## What this is

Streamlit dashboard for the ICT Trading Bot's FastAPI on the VPS.
Read-only — polls the bot's REST API and renders stats, positions,
signals, closed trades, logs, and health. Hosted on Streamlit Community
Cloud (free), auto-redeploys from `main`.

- Entry point: [`streamlit_app.py`](./streamlit_app.py)
- Deploy + local-dev steps: [`README.md`](./README.md)
- Migration history: [PR #32](https://github.com/benbaichmankass/ict-trader-dashboard/pull/32)

## Preview app + branch (adopted 2026-05-25) — READ BEFORE BUILDING UI

There are **two** Streamlit Community Cloud apps:

| App | Tracks branch | Audience |
|---|---|---|
| **Production** | `main` | the operator's live dashboard — auto-redeploys on merge to `main` |
| **Preview** | **`claude/web-app-preview`** (the standing preview branch) | a staging app the operator eyeballs **before** changes hit production |

**The standing preview branch is `claude/web-app-preview`** — the preview app is
pointed at it permanently, so the operator never has to create/re-point an app
per feature.

**Workflow for ANY dashboard UI/feature change** (this is the rule — follow it):
1. Build the change and push it to **`claude/web-app-preview`** (the preview app
   auto-redeploys from it within a minute or two).
2. Open the PR against `main` as usual and tell the operator to preview on the
   preview app.
3. Only after the operator approves the preview, **merge to `main`** (production).

Keep `claude/web-app-preview` **long-lived — never delete it.** After a change
lands on `main`, re-sync the preview branch onto `main` (so it starts the next
change from the released base) or stack the next WIP on it. Because the
dashboard can't be rendered from a sandbox/CI, **the preview app is the
verification step** — don't merge UI changes to `main` unverified.

**Preview app config:** set **`DASHBOARD_PREVIEW=1`** in the preview app's
Streamlit **Secrets**. That makes the sidebar **"Live data" toggle default OFF**
on the preview app, so it doesn't poll the bot's API as a second always-on
client — flip it ON only while actively testing. Production leaves the env var
unset → Live data defaults ON (auto-refresh every `POLL_INTERVAL_S`).

## Architecture

```
Browser ──HTTPS──▶ Streamlit Community Cloud (Python) ──HTTP──▶ Bot FastAPI :8001
                                                                 (141.145.193.91)
```

Streamlit's Python server makes the upstream call directly. The browser
only sees Streamlit's HTTPS-rendered page, so there's no mixed-content
block, no CORS surface, no transport-layer intermediaries. The list of
things that can break the dashboard collapses to:

- Streamlit Cloud being down (free-tier SLA, ~ok)
- The VM's FastAPI being down (`ict-web-api.service`)
- This script's code

No tunnel, no worker, no rewrite, no V8 isolate.

## Why not React + Vercel (history)

For the first 5 days the dashboard was a Vite/React SPA on Vercel.
Five different transport architectures were tried (direct HTTP → Vercel
Edge Function → Cloudflare Worker → CF quick tunnel → named CF tunnel)
because **Vercel Hobby blocks plain-HTTP outbound** from rewrites and
from user functions. Every option except the named tunnel rotated, and
the named tunnel adds a cloudflared daemon plus a CF-account dependency.
The Streamlit pivot in PR #32 eliminates the transport-layer problem
entirely by moving the upstream call to the dashboard's Python server.

Full investigation: [`ict-trading-bot/docs/audit/vercel-edge-vs-cf-worker.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/docs/audit/vercel-edge-vs-cf-worker.md).

**Do not reintroduce React + Vercel for this dashboard.** It looked
simpler than it is. If a future feature genuinely needs a richer
front-end, evaluate three options first: (a) a Streamlit Custom
Component in this same app, (b) a separate static site on a host
without the Hobby HTTP-outbound block (Cloudflare Pages, Netlify), or
(c) Vercel Pro — in that order.

## Bot-side authority split (consumer note, adopted 2026-05-11)

The dashboard is a **pure read-only consumer** of the bot's REST API
— it never mutates live trading state directly, so the bot-side
[VM authority split](https://github.com/benbaichmankass/ict-trading-bot/blob/main/CLAUDE.md#vm-authority-split-adopted-2026-05-11)
governs the bot, not this repo. But Claude sessions touching the
dashboard should know which side of the split each endpoint comes from:

| Endpoint family | Source VM | Authority side |
|---|---|---|
| `/api/bot/{stats,positions,signals,logs,trades/*,liquidity,config,backtests,pnl/*}` | Live trader | Restricted. Dashboard renderer is autonomous-Claude; bot-side endpoint additions follow the bot's Tier-1/2/3 rules. |
| `/api/bot/shadow/{predictions,stats,drift}` | Live trader | Restricted on the bot side; dashboard renderer autonomous. |
| `/api/bot/health/{latest,history,snapshot,services}` | Live trader | Restricted (live-VM health); dashboard renderer autonomous. |

**Hard limit that survives the split:** any dashboard wiring that would
*initiate* a live-trade action (FORCED STOP, promote-to-live, halt, etc.)
is **operator-gated at the bot-side endpoint**, not at the dashboard.
The dashboard PR is autonomous; the bot-side endpoint is Tier-3 per
[`vm-operator-mode.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/docs/claude/vm-operator-mode.md).

## What's in this repo

```
streamlit_app.py       — the dashboard (single file, ~3800 lines)
requirements.txt       — Python deps (streamlit, streamlit-autorefresh, requests, pandas, plotly, yfinance)
.streamlit/config.toml — theme + privacy
README.md              — deploy + dev steps
CLAUDE.md              — this file
docs/                  — ad-hoc design notes
```

## Tabs (current)

Sidebar order is operational top-to-bottom: **Overview · Performance · Insights · Strategies ·
Models · Accounts · Order Packages · Positions · Signals** (live/ops), then
**Backtesting · Promotion · Health** (diagnostics), then **Data Explorer · Logs**
(dev tools). The list/registry pages — **Strategies, Models, Accounts** — share a
uniform **collapsible-row** layout: each row is an `st.expander` whose label is a
status dot (🟢 live · 🔵 shadow · 🟡 stale · 🔴 bad · ⚫ off) + name + a couple of
summary stats; expanding shows detail metrics + a visualization, then the logs
(trade log / changelog / training+stage history) **open by default, capped at 10
rows with a "Show all" toggle**, then the **config shown last (always open)**.
Nested expanders are illegal in Streamlit, so the in-row "Show all" + config use
`st.checkbox` / `st.json`, not expanders.

| Tab | Endpoints |
|---|---|
| Overview | candles (`/api/bot/candles`, yfinance fallback), `/api/bot/positions`, `/api/bot/signals`, `/api/bot/trades/closed`, `/api/bot/stats`, `/api/pnl/history?days=30`, `/api/bot/strategies` — **one live chart per ACTIVE symbol at the top** (every instrument a strategy is paper/live-trading, enumerated live via `_discover_symbols()`; symbols holding an open position float to the top, the rest keep config order — never a single dropdown). Each chart is a **custom lightweight-charts v4 embed** (`render_tv_chart` + `_TV_CHART_HTML`, loaded through `st.components.v1.html`; the lib comes from a jsDelivr CDN; localStorage namespaced per symbol so the stacked charts don't share scroll/toggle state). Built because the `streamlit-lightweight-charts` wrapper silently drops per-series `priceLines` — the v4 API gives native `createPriceLine()` (live-position entry/SL/TP + current + ICT zones), `setMarkers()` (signals + closed trades), an **on-canvas control bar** (Live/Signals/Closed/Zones/EMA/Volume checkboxes, localStorage-persisted) and a **⤢ fullscreen button**. A single interval selector drives every chart; each open chart shows the symbol's live PnL. Below the charts: the snapshot (KPI row, 24h scorecard + system health, 30-day P&L sparkline, open-positions mini-table **incl. Account**, per-strategy 24h line). Heavy analytics live on Performance. |
| Performance | `/api/bot/trades/closed`, candles (`/api/bot/candles`, yfinance fallback), `/api/bot/signals`, `/api/bot/positions` — **the analytics deep-dive**: a shared All/per-strategy filter driving headline metrics (trades, win rate, expectancy, total P&L) + 24h scorecard, an equity curve (cumulative realised P&L), a monthly P&L calendar heat-map, a per-day wins-vs-losses bar, a trades-by-strategy pie, and a per-strategy breakdown table — all from one client-side `/api/bot/trades/closed?limit=200&since=…` fetch. Below: per-symbol trade-context price charts (signals + open-trade entry/TP/SL + closed markers) — **one tab per traded symbol, enumerated live via `_discover_symbols()`** (union of `/api/bot/config` account+strategy `symbols` and open-position symbols; never hardcoded, so a newly wired instrument appears with no dashboard change), recent (~24h) context, refreshed each cycle (not tick-live). |
| Insights | `/api/bot/insights/{summary,recent,strategy/{name},health}` — AI Analyst (M13 S1). Renders the cached LLM narrative + grade pill + signals list for each of the four endpoints. The grade is 🟢 good / 🟡 mixed / 🔴 concerning; signals are bullet-tagged by severity. Per-strategy section uses a selectbox populated from `/api/bot/strategies` (falls back to the canonical 6-strategy list). The router returns a 200 placeholder envelope when the cache hasn't been written yet, so this tab renders cleanly even before the generator's first run; the Overview page also surfaces the `summary` payload as a compact "Latest Analyst Read" card at the top. **Read-only** — nothing here calls Anthropic (that's the bot's `ict-insights-generator.service`). |
| Accounts | `/api/bot/config`, `/api/bot/accounts/balances`, `/api/pnl/history?account_id=`, `/api/bot/positions`, `/api/bot/trades/closed?account_id=` — one card per account (**all accounts incl. the demo `bybit_1`** — the old separate Demo tab was folded in here): live/dry status, tracked balance (snapshot), realized·30d + unrealized PnL, open-trade count, trades·30d, a **daily realised-P&L chart** (bars + cumulative), and an expandable 7-day trade log. Uses the **no-session** `/api/pnl/history` (not the session-gated `/api/pnl`); reads its `pnl` field (renamed from `realized_usd` in S-063 — **not** `realizedPnl`). |
| Positions | `/api/bot/positions` (open) + `/api/bot/trades/closed?since=…` (closed history) + `/api/bot/order-packages` + `/api/bot/signals` — two sections: **open positions render as full detail cards** (`_render_trade_card`) — symbol + LONG/SHORT, **account** + strategy, entry/SL/TP/qty/uPnL, an **evaluation row** (Risk:Reward, stop/target distance %, confidence/PnL%), the linked order package's decision & reasoning (`signalLogic` + `meta{setup_type,killzone,bias}` + Claude review), the per-model **ML scores persisted on the order package** (`modelScores` `{model_id:{stage,score}}` — a cheap field read, NOT the `/api/bot/trades/scores` recompile), and the best-effort triggering signal (correlated by symbol+strategy+time). SL/TP carry a "set at entry" note (the bot doesn't trail/modify them post-open, and no SL/TP-modification history exists anywhere). The join data (order-packages + signals) is fetched **concurrently + time-boxed** (`_fetch_parallel`) so a slow endpoint can't wedge the page. Closed history below with a 24h / 7d / 30d window selector (7d default) — **rows stay tabular but are clickable** (`st.dataframe` single-row select, with a selectbox fallback on older Streamlit) to open the same full card. |
| Signals | `/api/bot/signals` |
| News | `/api/bot/news/recent` — M9 news layer shadow-soak feed: per-actionable-signal news decision (veto / boost / reduce / neutral, `adjustment`, `event_risk`) + applied reductive influence downsizes (`factor`/`action`). Headline counts (decisions / vetoes / boost·reduce / neutral) + a decisions table. Renders an explicit "not active yet" state until the bot's news layer is active — activation is source-driven (`NEWS_SOURCE=rss`, or `newsapi` + `NEWS_API_KEY`; the legacy `NEWS_ENABLED` flag was removed bot-side 2026-06-10) — the log is empty until then. **Read-only.** |
| Order Packages | `/api/bot/order-packages` + `/api/bot/trades/scores` — **decision-level** table: one row per order package (strategy, symbol, dir, entry/SL/TP, status, PnL) with the per-model shadow scores (joined client-side by `linkedTradeId`) and the Claude decision grade. Replaces the old fill-level "Closed Trades" tab (that list now lives on Positions). Claude column shows — until `/health-review` scores a package. |
| Models | `/api/bot/ml/*` — per-model cards incl. the manifest `description` |
| Promotion | `/api/bot/shadow/stats`, `/api/bot/shadow/drift`, `/api/bot/trades/scores`, `/api/bot/trades/closed` — shadow-model promotion-readiness tracker (per-model volume, days-in-shadow, score range, "wired" check, KS/PSI drift, win/loss score edge) |
| Backtesting | `/api/bot/backtests/sweeps` (strategy-improvement / validation sweeps mirrored from the trainer VM — renders each run's `SUMMARY.md` table + raw per-variant metrics), `/api/bot/backtests` (on-demand `/test` runs) |
| Strategies | `/api/bot/strategies` + `/api/bot/trades/closed` + `/api/bot/strategies/{name}/review` — live-runtime view: pipeline-running banner + per-strategy status (Running / Loaded·stale / Configured·not-loaded / Disabled) and account routing (which accounts run it, live/dry), lifetime stats, **trades·24h + a cumulative realised-P&L curve** (client-side from the closed-trade window), config, changelog. **M7 review packet** (gate doc: bot repo `docs/strategy-review-gate.md`) renders per-strategy: coloured action badge (`KILL`/`DEMOTE_SHADOW`/`TUNE`/`HOLD`/`PROMOTE`), n_closed / win_rate / expectancy / pnl_total, the matrix's `reasons[]`, Tier-3 SLA due-by when present, and a collapsed full-JSON drill-down. Renders a ghost caption pointing at the `generate-strategy-review-packets` operator action when no packet has been generated yet. |
| Data Explorer | `/api/bot/db/tables`, `/api/bot/db/table/{name}` — read-only browse of the **federated canonical store**: the live trader's `trade_journal.db` AND the trainer-store sidecar `trainer_store.db` (trainer/ML lifecycle data: training_cycle, dataset_builds, db_pulls, model_registry, experiment_runs, backtest_sweeps). Each table is tagged with its owning `db`; reads pass `?db=` so the API routes to the right DB. Schema overview, table picker, per-column filter (eq/ne/gt/lt/gte/lte/like), ordering, and pagination |
| Health | `/api/bot/health/services`, `/api/bot/health/latest` |
| Logs | `/api/bot/logs` |

**Candles: bot endpoint first, Yahoo Finance fallback.** `_fetch_candles`
calls the bot's **`/api/bot/candles?symbol=&interval=&limit=`** route first
(OHLCV from the same exchange the strategy trades — BTCUSDT→Bybit, MES→IBKR,
matching the bot's own view), and falls back to yfinance only on an empty/error
response. The yfinance fallback maps the bot symbol to a Yahoo ticker via
`_yf_ticker`: a small explicit map for the symbols that need translating
(`BTCUSDT`→`BTC-USD`, `MES`→`ES=F`, `MGC`/`XAUUSD`→`GC=F`, `MHG`→`HG=F`;
`ES=F` shares MES's S&P index level with deeper history than `MES=F`) plus
rules for everything else (`*USDT`→`*-USD`; equities/ETFs like SPY/QQQ/GLD
pass through unchanged) — so a new instrument gets a sensible fallback
without a dashboard edit. The symbol selectors themselves (Overview chart +
Performance per-symbol tabs) enumerate the traded symbols live via
`_discover_symbols()`, never from a hardcoded list. The other bot endpoints
supply the **trade context** overlaid on those candles (signals, open
positions with stop-loss/take-profit, closed trades).

**Not (yet) ported from the old React app:** TradingView candle chart
with Bybit-WS per-tick updates, Backtests, Models / ShadowModels (ML
drift charts), LiquidityMaps, TimePrice (killzone heatmap), TradeProcess,
Settings, Gemini AI analysis. These were the rich-but-fragile parts.
Port them back when there's a clear operator need — but keep each as a
separate Streamlit page or fragment so adding one doesn't break the rest.

## API contract (from ict-trading-bot)

Canonical contract lives in [`ict-trading-bot/CLAUDE.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/CLAUDE.md) § "Dashboard REST API".

**Field nullability is canonical in
[`ict-trading-bot/CLAUDE.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/CLAUDE.md)
§ "Dashboard REST API"** — don't re-declare which fields are nullable here
(a second copy drifts). The general rule: render any null as an em-dash
(`—`), never `0` or `"unknown"`. A real `0` reading (e.g. a `vmHealth`
measurement) is data, not a missing value.

Dashboard-specific rendering rules (these are ours, not the bot's contract):

- `BotStats` returns **HTTP 503** on structural DB failure (S-067). The
  Streamlit `_fetch` helper surfaces this as a per-endpoint warning banner
  rather than crashing the page.
- **Signals:** skip rows with a null `pattern` rather than aggregating them
  under "unknown". The Overview chart's per-strategy signal toggle treats a
  null `strategy` as "always show".
- **Signal zones:** `Signal.zones` is a (possibly empty) list of drawable ICT
  zones the strategy logged (`{kind:"fvg",low,high}`, `{kind:"sweep",price}`).
  The Overview chart's "Zones" toggle draws the latest signal's zones (FVG band
  + sweep line). The `streamlit-lightweight-charts` package can't fill boxes, so
  an FVG renders as its two bounding price-lines.

## Local dev

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
# Or hit a local bot:
BOT_API_URL=http://localhost:8001 streamlit run streamlit_app.py
```

The `BOT_API_URL` env var overrides the default
`http://141.145.193.91:8001` (the Ampere live trader `ict-bot-arm` since
the 2026-06-14 cutover; was the retired x86 micro `158.178.210.252`). On
Streamlit Cloud, set it in **Settings → Secrets** if the VPS IP ever
changes; otherwise the hardcoded default is fine.
