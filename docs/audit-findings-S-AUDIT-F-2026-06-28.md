# S-AUDIT-F — `streamlit_app.py` full audit (2026-06-28)

Part of the M17 Full-System Audit. Slice: **`streamlit_app.py`** (6,493 lines on
`origin/main` — the local checkout was stale at 3,195 lines / old single-app-era
file; this audit was done against `origin/main`). The Accounts/balance/`api_ok`
path was already audited in PR #126 and is excluded here.

**Method:** read the file in full, line by line. Every `_fetch` / `_post` call
was cross-checked against the bot's live API table and (where field names were
load-bearing) against the actual bot router source on GitHub
(`benbaichmankass/ict-trading-bot`). Each finding is classified **real bug /
dead code / contract drift / latent risk / stale comment**.

**Verification note:** the dashboard cannot be rendered from CI/sandbox —
verification of any merged fix is live on the production Streamlit app after
merge to `main` (the app auto-redeploys).

---

## Summary

| Class | Count | Items |
|---|---|---|
| Dead code | 3 | `PAGES`, `_CLOSED_WINDOWS`, `_STAGE_ICON` |
| Stale comment | 2 | `PAGES`-referencing comment (L2539); the build marker |
| Contract drift | 0 | (every `_fetch`/`_post` field cross-checked clean) |
| Real bug | 0 | none found |
| Latent risk | 2 | `bool-and-or` ternary (L2594); deep-link pre-select edge |

No null-contract violations, no wrong/renamed field names, no orphan endpoint
calls were found. The file is in good shape; the only shippable Tier-1 fixes are
dead-code/stale-comment removals.

---

## Endpoint / field cross-check (all CLEAN)

Every endpoint the file consumes was verified against the bot's current routers:

- **`/api/bot/trades/closed`** → `realizedPnl`, `realizedPnlPct`, `pattern`,
  `closeReason`, `openedAt`, `closedAt`, `entryPrice`, `exitPrice`, `side`,
  `qty`, `account`, `accountClass`, `isDemo`, `symbol`, `id`. Dashboard's
  `_closed_trades_frame`, `_format_closed_trades_df`, `_lc_markers`,
  `_add_closed_trade_markers`, the Trades/Accounts tables all match. ✅
  (`realizedPnl` nullable → rendered as `—` everywhere; verified.)
- **`/api/bot/positions`** → `unrealizedPnl`, `unrealizedPnlSource`,
  `stopLoss`, `takeProfit`, `pattern`, `entryPrice`, `side`, `qty`, `account`,
  `accountClass`, `isDemo`, `openedAt`, `options`. All consumed correctly;
  null/`unavailable` handled via `_open_upnl`/`_sum_upnl` (never summed as $0). ✅
- **`/api/bot/performance`** → `totalPnl`, `winRate`, `expectancy`,
  `totalTrades`, `wins`, `losses`, `profitFactor`, `maxDrawdown`,
  `perAssetClass[{assetClass,trades,wins,totalPnl,winRate}]`, `perStrategy`,
  `equity`, `paper` sub-block. `_perf_for_segment` / `_combine_perf_blocks` /
  `_merge_per_asset_class` match. Real/paper/prop kept strictly separate. ✅
- **`/api/bot/shadow/stats`** → `count`, `score_mean`, `score_min`, `score_max`,
  `first_seen`, `last_seen`, `row_keys_seen`, `model_id`, `stage`. Verified
  against `ml/shadow/inspector.py` + `src/web/api/routers/shadow.py`. ✅
- **`/api/bot/shadow/drift`** → `verdict`, `ks`, `psi`, `reference_mean`,
  `current_mean`, `reference_stdev`, `current_stdev`, `reference_count`,
  `current_count`. Match. Null means handled (no fabricated shift). ✅
- **`/api/bot/strategies`** → `runtime{bot_running,last_tick_utc,
  tick_age_seconds,loaded_strategies}`, per-strategy `stats{total_trades,
  win_rate_pct,total_pnl,exit_reasons}`, `accounts[{id,live}]`, `description`,
  `changelog`, `config`, `enabled/loaded/running`, `execution`. Verified
  against `src/web/api/routers/strategies.py`. ✅
- **`/api/bot/strategies/{name}/review`** and **`/tune`** — present in the
  contract; envelope shapes (`present`, `packet{…}`, `results[…]`) match. ✅
- **`/api/bot/candles`** — `_ALLOWED_INTERVALS` on the bot is
  `{1m,5m,15m,30m,1h,2h,4h,1d}`; the dashboard's `CHART_INTERVALS`
  (`1m,5m,15m,1h,4h,1d`) is a strict subset, so every offered interval is
  accepted. `MAX_LIMIT=1000` on the bot; Overview passes `limit=1000`. ✅
- **`/api/bot/news/recent`** → `present`, `records[{ts,decision,adjustment,veto,
  item_count,reason,strategy,query,symbol,side,event_risk,factor,action}]`.
  Verified against `src/news/news_audit.py`. `_news_sentiment` /`page_news`
  match (incl. the `item_count>0` "scored" filter). ✅
- **`/api/bot/exit-ladder/soak`** → `present`, `summary{total_scanned,by_venue,
  differing,differing_pct}`, `records[{ts,venue,account_id,strategy,symbol,
  direction,single_target{qty,tp,sl},ladder{targets,n_rungs},
  differs_from_single_target}]`. Match. ✅
- **`/api/bot/prop/{status,fills,tickets,reconcile}`** + **`/prop/report`** —
  `rule_distance` keys (`equity`, `distance_to_dd_floor_usd`,
  `static_dd_floor_usd`, `distance_to_daily_loss_usd`, `daily_loss_limit_usd`,
  `day_pnl`, `as_of`) verified against `src/prop/prop_reconcile.py`. `_post`
  sends the `DASHBOARD_API_TOKEN` bearer (matches `_check_admin_token`). The
  prop report POST is the dashboard's only write — confirmed read-only
  everywhere else. ✅
- **`/api/bot/ml/{status,cycle,sessions,registry,builds,db_pulls,runs/…}`**,
  **`/insights/{summary,recent,strategy,health,usage,history}`**,
  **`/reports[/{id}]`**, **`/db/{tables,table}`**, **`/trades/scores`**,
  **`/order-packages`**, **`/pnl/history`**, **`/health/{services,latest}`**,
  **`/logs`**, **`/signals`**, **`/backtests[/sweeps]`**, **`/config`**,
  **`/accounts/balances`** — all consumed with `.get()` defensively and the
  field names match the contract. ✅

---

## Findings

### F-1 — DEAD CODE: `PAGES` list is unused (L419-427)
**Class:** dead code + stale comment.
The flat `PAGES` list predates the 2026-06-22 6-section nav redesign. The
sidebar now renders `SECTION_NAMES`; routing is via `SECTIONS` / `_section_for`
/ `_detail_dispatch`. `PAGES` is never read anywhere — the only reference is a
stale comment at L2539 ("page labels match the PAGES list"). The page labels are
actually defined in `SECTIONS` / `PAGE_DESC`.
**Fix:** delete the `PAGES` list; fix the L2539 comment to reference `SECTIONS`.
**Tier:** 1. → **PR (F-1)**.

### F-2 — DEAD CODE: `_CLOSED_WINDOWS` is unused (L3403-3404)
**Class:** dead code.
`_CLOSED_WINDOWS` (a `{label: days}` map) is a leftover from the pre-split
Positions page that carried the closed-trade window selector. After Trades was
split out (2026-06-20) the window math moved to `_WINDOW_DAYS` / `_window_control`.
`_CLOSED_WINDOWS` is now referenced only in a comment at L1521. Dead.
**Fix:** delete `_CLOSED_WINDOWS`; the L1521 comment already explains the
"10-year lookback = All" trick generically, so adjust it to not name the dead
symbol.
**Tier:** 1. → **PR (F-2)**.

### F-3 — DEAD CODE: `_STAGE_ICON` is unused (L4124-4127)
**Class:** dead code.
`_STAGE_ICON` (a stage→emoji map) is a leftover from before the operator's
3-bucket deployment view. The Models page renders buckets via `_BUCKET_PILL`
and `_normalize_bucket`; `_STAGE_ICON` is never indexed in any render path (its
only other mention is the explanatory comment block right below it). Dead.
**Fix:** delete `_STAGE_ICON`. The comment block below it explains the legacy
7→3 stage aliasing and is genuinely useful context for `_normalize_bucket`, so
keep that block but drop its now-confusing back-reference to `_STAGE_ICON`.
**Tier:** 1. → **PR (F-3)**.

### F-4 — LATENT RISK (NOT fixed): `bool and X or Y` ternary (L2594)
**Class:** latent risk / readability.
In the Overview News card's 30-day count loop:
```python
if (t.tzinfo and t or t.replace(tzinfo=dt.timezone.utc)) >= cutoff30:
```
This is the classic `cond and A or B` idiom. It is *currently correct* (a parsed
`datetime` `t` is always truthy, so the `and t` branch can't accidentally fall
through to the `or`), but it is fragile and hard to read. A plain
`t if t.tzinfo else t.replace(tzinfo=...)` would be clearer. **Not shipped** —
it changes no behaviour and is purely cosmetic; logged here so a future cleanup
pass can simplify it. (The same tz-normalisation is done cleanly in
`_news_sentiment` a few lines up, so the two could share a helper.)

### F-5 — LATENT RISK (NOT fixed): Reports deep-link pre-select (L6361-6367)
**Class:** latent risk (benign).
`_consume_report_deeplink` forces `reports_window="All"` and stashes
`_deep_report_id`; `page_reports` then pops it and sets `reports_pick` to the
matching index. This works, but if the deep-linked id is NOT in the (capped at
200) report list — e.g. a very old report — the pre-select silently no-ops and
the user lands on whatever was selected before. This is acceptable graceful
degradation (the list is newest-first and 200 deep), not a bug. Logged only.

---

## Things explicitly checked and found CORRECT

- **Null → em-dash contract:** `fmt_pct`/`fmt_usd`/`fmt_num`/`_fmt_age`/`_money`
  all return `—` for `None`. `vmHealth.{cpu,memory,disk}` rendered via `fmt_pct`
  (null→`—`, real 0 preserved). `realizedPnl` null → `—`. uPnL `unavailable` →
  `—` (never $0). No `0`/`"unknown"` fabrications found.
- **Real / paper / prop never blended:** `_is_real_money` excludes both paper
  AND prop from real headlines; `_segment_filter_*` honour the split; the
  Overview/Positions/Accounts header bands keep paper a secondary caption and
  prop a separate caption; the "All" view is explicit + labeled + drops
  non-combinable metrics (`profitFactor`/`maxDrawdown`) to `—`. Compliant.
- **Read-only invariant:** the ONLY writes are `_post("/api/bot/prop/report", …)`
  (3 call sites, all in `page_prop`) — matches the documented exception. No
  other POST/PUT/PATCH/DELETE anywhere.
- **Feature-detection for older Streamlit:** `_df_row_selection_supported`,
  `_segmented_or_radio` fallbacks, nested-expander avoidance (checkbox-gated
  `st.json`) — all handled, keeps the page importable across Cloud rollout
  windows.
- **`py_compile` + `ruff check`:** both clean at baseline.

---

## PRs

| PR | Finding(s) | Concern |
|---|---|---|
| (F-1) | F-1 | remove unused `PAGES` + fix stale comment |
| (F-2) | F-2 | remove unused `_CLOSED_WINDOWS` + adjust comment |
| (F-3) | F-3 | remove unused `_STAGE_ICON` + adjust comment |

All opened as DRAFT against `main`; each notes "verify live after merge". No
operator-facing behaviour changes (pure dead-code removal), so none need
operator sign-off beyond the standard verify-live step.
