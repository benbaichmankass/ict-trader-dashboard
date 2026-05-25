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

## Architecture

```
Browser ──HTTPS──▶ Streamlit Community Cloud (Python) ──HTTP──▶ Bot FastAPI :8001
                                                                 (158.178.210.252)
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
streamlit_app.py       — the dashboard (single file, ~200 lines)
requirements.txt       — Python deps (streamlit, streamlit-autorefresh, requests, pandas)
.streamlit/config.toml — theme + privacy
README.md              — deploy + dev steps
CLAUDE.md              — this file
docs/                  — ad-hoc design notes
```

## Tabs (current)

Sidebar order is operational top-to-bottom: **Overview · Performance · Strategies ·
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
| Overview | candles (`/api/bot/candles`, yfinance fallback), `/api/bot/positions`, `/api/bot/signals`, `/api/bot/stats`, `/api/bot/trades/closed`, `/api/pnl/history?days=30`, `/api/bot/strategies` — **the live chart sits at the top** (TradingView Lightweight Charts): overlay checkboxes in a left rail (Live trades / Signals / Zones / Closed / EMA / Volume), a ⛶ fullscreen button (widescreen — hides the sidebar), live PnL (computed from the last price when the bot's `unrealizedPnl` is unset), signal/closed markers, and live-position entry/SL/TP + ICT-zone levels. **NB:** the `streamlit-lightweight-charts` build renders `markers` + `Line` series but **silently ignores per-series `priceLines`** — so all horizontal levels (entry/SL/TP, FVG/sweep) are drawn as flat 2-point Line series (see `_lc_hline_series`/`_lc_overlay_series`). Below the chart: an at-a-glance snapshot (KPI row, 24h scorecard + system health, 30-day P&L sparkline, open-positions mini-table, per-strategy 24h line). The heavy analytics live on Performance. |
| Performance | `/api/bot/trades/closed`, candles (Yahoo Finance), `/api/bot/signals`, `/api/bot/positions` — **the analytics deep-dive**: a shared All/per-strategy filter driving headline metrics (trades, win rate, expectancy, total P&L) + 24h scorecard, an equity curve (cumulative realised P&L), a monthly P&L calendar heat-map, a per-day wins-vs-losses bar, a trades-by-strategy pie, and a per-strategy breakdown table — all from one client-side `/api/bot/trades/closed?limit=200&since=…` fetch. Below: per-symbol (BTCUSDT, MES) trade-context price charts (signals + open-trade entry/TP/SL + closed markers), recent (~24h) context, refreshed each cycle (not tick-live). |
| Accounts | `/api/bot/config`, `/api/bot/accounts/balances`, `/api/pnl/history?account_id=`, `/api/bot/positions`, `/api/bot/trades/closed?account_id=` — one card per account (**all accounts incl. the demo `bybit_1`** — the old separate Demo tab was folded in here): live/dry status, tracked balance (snapshot), realized·30d + unrealized PnL, open-trade count, trades·30d, a **daily realised-P&L chart** (bars + cumulative), and an expandable 7-day trade log. Uses the **no-session** `/api/pnl/history` (not the session-gated `/api/pnl`); reads its `pnl` field (renamed from `realized_usd` in S-063 — **not** `realizedPnl`). |
| Positions | `/api/bot/positions` (open) + `/api/bot/trades/closed?since=…` (closed history) — two sections: live open positions on top, and the closed-position history below with a 24h / 7d / 30d window selector (7d default) |
| Signals | `/api/bot/signals` |
| Order Packages | `/api/bot/order-packages` + `/api/bot/trades/scores` — **decision-level** table: one row per order package (strategy, symbol, dir, entry/SL/TP, status, PnL) with the per-model shadow scores (joined client-side by `linkedTradeId`) and the Claude decision grade. Replaces the old fill-level "Closed Trades" tab (that list now lives on Positions). Claude column shows — until `/health-review` scores a package. |
| Models | `/api/bot/ml/*` — per-model cards incl. the manifest `description` |
| Promotion | `/api/bot/shadow/stats`, `/api/bot/shadow/drift`, `/api/bot/trades/scores`, `/api/bot/trades/closed` — shadow-model promotion-readiness tracker (per-model volume, days-in-shadow, score range, "wired" check, KS/PSI drift, win/loss score edge) |
| Backtesting | `/api/bot/backtests/sweeps` (strategy-improvement / validation sweeps mirrored from the trainer VM — renders each run's `SUMMARY.md` table + raw per-variant metrics), `/api/bot/backtests` (on-demand `/test` runs) |
| Strategies | `/api/bot/strategies` + `/api/bot/trades/closed` — live-runtime view: pipeline-running banner + per-strategy status (Running / Loaded·stale / Configured·not-loaded / Disabled) and account routing (which accounts run it, live/dry), lifetime stats, **trades·24h + a cumulative realised-P&L curve** (client-side from the closed-trade window), config, changelog |
| Data Explorer | `/api/bot/db/tables`, `/api/bot/db/table/{name}` — read-only browse of the **federated canonical store**: the live trader's `trade_journal.db` AND the trainer-store sidecar `trainer_store.db` (trainer/ML lifecycle data: training_cycle, dataset_builds, db_pulls, model_registry, experiment_runs, backtest_sweeps). Each table is tagged with its owning `db`; reads pass `?db=` so the API routes to the right DB. Schema overview, table picker, per-column filter (eq/ne/gt/lt/gte/lte/like), ordering, and pagination |
| Health | `/api/bot/health/services`, `/api/bot/health/latest` |
| Logs | `/api/bot/logs` |

**Candles come from Yahoo Finance**, not a bot endpoint — `_fetch_candles`
maps the bot symbol to a Yahoo ticker (`BTCUSDT`→`BTC-USD`, `MES`→`ES=F`;
`ES=F` shares MES's S&P index level with deeper history than `MES=F`).
There is no `/api/bot/candles/*` route on the bot. The bot endpoints supply
the **trade context** overlaid on those candles (signals, open positions
with stop-loss/take-profit, closed trades).

**Not (yet) ported from the old React app:** TradingView candle chart
with Bybit-WS per-tick updates, Backtests, Models / ShadowModels (ML
drift charts), LiquidityMaps, TimePrice (killzone heatmap), TradeProcess,
Settings, Gemini AI analysis. These were the rich-but-fragile parts.
Port them back when there's a clear operator need — but keep each as a
separate Streamlit page or fragment so adding one doesn't break the rest.

## API contract (from ict-trading-bot)

Canonical contract lives in [`ict-trading-bot/CLAUDE.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/CLAUDE.md) § "Dashboard REST API".

Important nullability notes for renderers:

- `BotStats.vmHealth.{cpu,memory,disk}` are **nullable** — render `—`,
  not `0%`. A real `0` reading is a measurement.
- `BotStats` returns **HTTP 503** on structural DB failure (S-067).
  The Streamlit `_fetch` helper surfaces this as a per-endpoint warning
  banner rather than crashing the page.
- `Signal.{strategy,pattern,confidence,price}` are **nullable**. Skip rows with
  null `pattern` rather than aggregating them under "unknown". The Overview
  chart's per-strategy signal toggle treats a null `strategy` as "always show".
- `Signal.zones` is a (possibly empty) list of drawable ICT zones the strategy
  logged for its decision: `{kind:"fvg",low,high}`, `{kind:"sweep",price}`. The
  Overview chart's "Zones" toggle draws the latest signal's zones (FVG band +
  sweep line). The `streamlit-lightweight-charts` package can't fill boxes, so an
  FVG renders as its two bounding price-lines.
- `ClosedTrade.{realizedPnlPct,closeReason,pattern}` are **nullable**.
- `Position.{stopLoss,takeProfit,pattern}` are **nullable**.
- `BacktestRun.{totalTrades,winningTrades,losingTrades}` are **nullable**
  — an aborted backtest lands with NULL counts.

## Local dev

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
# Or hit a local bot:
BOT_API_URL=http://localhost:8001 streamlit run streamlit_app.py
```

The `BOT_API_URL` env var overrides the default
`http://158.178.210.252:8001`. On Streamlit Cloud, set it in
**Settings → Secrets** if the VPS IP ever changes; otherwise the
hardcoded default is fine.
