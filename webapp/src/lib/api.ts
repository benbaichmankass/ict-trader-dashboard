// Thin typed fetch client for the bot's Tier-1 read API. The interface here is
// the authoritative list of endpoints this app depends on — keep it in sync
// with ict-trading-bot/CLAUDE.md § "Dashboard REST API". Rename-resilient:
// unknown fields are ignored, a missing field stays undefined and renders as
// an em-dash downstream.

import { getBotApiUrl } from "./config";
import { authHeaders, handleUnauthorized } from "./auth";
import type { DbOverview } from "./dbOverview";
import { buildSignalsCatalogQuery, type SignalsCatalogQuery } from "./signalsCatalog";
import { buildCatalogQuery, type CatalogQuery, type CatalogResponse, type CatalogDetail } from "./catalog";
import { buildGatesQuery, type GateFilters, type GatesResponse, type GateDetailResponse } from "./gates";

/**
 * A read the bot refused for want of a session. Thrown instead of the generic
 * `Error` so a route can tell "you are not signed in" from "the endpoint is
 * broken" and offer the form rather than a raw status line.
 */
export class AuthRequiredError extends Error {
  readonly status: number;
  constructor(status: number, path: string) {
    super(
      status === 403
        ? `Not allowlisted for ${path} (403).`
        : `Sign-in required for ${path} (401).`,
    );
    this.name = "AuthRequiredError";
    this.status = status;
  }
}

export interface BotStats {
  pnl24h?: number | null;
  totalPnL?: number | null;
  openTrades?: number | null;
  winRate?: number | null;
  status?: string | null;
  datasource?: string | null;
  vmHealth?: { cpu?: number | null; memory?: number | null; disk?: number | null } | null;
  paperOpenTrades?: number | null;
  paper?: { pnl24h?: number | null; totalPnL?: number | null; openTrades?: number | null; winRate?: number | null } | null;
}

export interface Position {
  id: string;
  account?: string | null;
  accountClass?: string | null;
  assetClass?: string | null;
  symbol: string;
  side?: string | null;
  qty?: number | null;
  entryPrice?: number | null;
  unrealizedPnl?: number | null;
  unrealizedPnlSource?: string | null;
  unrealizedPnlProvenance?: string | null;
  openedAt?: string | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  pattern?: string | null;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
}

export interface PerfStrategy {
  name: string;
  trades: number;
  wins?: number | null;
  winRate?: number | null;
  totalPnl?: number | null;
  expectancy?: number | null;
}

export interface Performance {
  window?: string;
  totalTrades?: number | null;
  wins?: number | null;
  losses?: number | null;
  winRate?: number | null;
  totalPnl?: number | null;
  expectancy?: number | null;
  profitFactor?: number | null;
  maxDrawdown?: number | null;
  // PnL provenance (bot P0.3, 2026-07-31): how much of the window's realized
  // PnL rests on a broker-measured exit. Absent on an older bot.
  pnlCoverage?: number | null;
  pnlMeasuredCount?: number | null;
  pnlEstimatedCount?: number | null;
  pnlFabricatedCount?: number | null;
  pnlUnverifiedCount?: number | null;
  perAssetClass?: Array<{ assetClass: string; trades: number; winRate?: number | null; totalPnl?: number | null }>;
  perStrategy?: PerfStrategy[];
  equity?: Array<{ t: number | string; cum: number }>;
  paper?: Partial<Performance> | null;
  // "Paper" funding view scopes to the live-portfolio-mirror books
  // (`paper_role: portfolio`) — the bot serves this sub-block (same shape as
  // `paper`), falling it back to the all-paper `paper` block server-side when no
  // portfolio accounts are declared. Prefer it over `paper` for the Paper
  // segment so the soak roster stays off every tab but Accounts.
  paperPortfolio?: Partial<Performance> | null;
}

export interface ClosedTrade {
  id?: string | number;
  symbol: string;
  account?: string | null;
  accountClass?: string | null;
  assetClass?: string | null;
  strategy?: string | null;
  side?: string | null;
  direction?: string | null;
  qty?: number | null;
  entryPrice?: number | null;
  exitPrice?: number | null;
  pnl?: number | null;
  // The bot serialises closed-trade PnL/strategy under these names; the loader
  // normalises them into pnl/strategy so consumers can read one field.
  realizedPnl?: number | null;
  realizedPnlPct?: number | null;
  pattern?: string | null;
  closeReason?: string | null;
  closedAt?: string | null;
  openedAt?: string | null;
  // "measured" | "estimated" | "fabricated" | "unverified" — is realizedPnl a
  // broker measurement or a manufacture? Null when pnl is null / older bot.
  pnlProvenance?: string | null;
}

export interface Strategy {
  name: string;
  status?: string | null;
  loaded?: boolean | null;
  running?: boolean | null;
  execution?: string | null;
  accounts?: Array<{ id: string; live?: boolean }> | null;
  symbols?: string[] | null;
  trades?: number | null;
  winRate?: number | null;
  totalPnl?: number | null;
  description?: { short?: string | null } | null;
}

// THE app's one network chokepoint: every REST path below goes through here,
// so attaching the bearer here attaches it everywhere. `authHeaders()` adds
// `Authorization: Bearer` only when a usable token is held — the ~35 ungated
// routes are unaffected and keep working signed out, exactly as before.
//
// ⚠️ If you add a second `fetch` anywhere under `webapp/src`, it will NOT carry
// the bearer and any gated route it calls will 401. `webapp/tests/auth-bearer.mjs`
// makes that a build failure rather than a silently dark tab.
//
// Writes go through the same call site (`init.method` + `init.body`), so a POST
// carries the bearer exactly as a GET does. The SPA's only bot-API write here is
// the trade-approval decision (session-gated, `require_session`).
async function rawFetch(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<Response> {
  const url = `${getBotApiUrl()}${path}`;
  const hasBody = init.body !== undefined;
  const res = await fetch(url, {
    signal: init.signal,
    method: init.method ?? "GET",
    headers: authHeaders(hasBody ? { "Content-Type": "application/json" } : undefined),
    body: hasBody ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 401 || res.status === 403) {
    // Drop the dead session and surface the form. Throwing a distinct type
    // lets the route render a sign-in affordance instead of a status line.
    handleUnauthorized(res.status, path);
    throw new AuthRequiredError(res.status, path);
  }
  return res;
}

async function getRaw(path: string, signal?: AbortSignal): Promise<Response> {
  const res = await rawFetch(path, { signal });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res;
}

/** GET that returns { status, body } for every non-auth status instead of throwing (401/403 still go to the sign-in flow). */
async function statusGet(path: string, signal?: AbortSignal): Promise<{ status: number; body: any }> {
  const res = await rawFetch(path, { signal });
  return { status: res.status, body: await res.json().catch(() => null) };
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return (await getRaw(path, signal)).json() as Promise<T>;
}

/** The bot's raw answer to a write: status + parsed JSON (or null) + raw text. Never thrown on a 4xx/5xx. */
export interface PostResult {
  ok: boolean;
  status: number;
  body: unknown;
  text: string;
}

// The SPA's one authenticated WRITE path to /api/bot/*. Same bearer as `getRaw`
// (`authHeaders()` — the device session, else the password JWT), so a route
// gated by `require_session` sees exactly the session the reads carry.
//
// Unlike `get`, it does NOT throw on a non-2xx: a write's refusal is an answer
// the operator must see verbatim (the gate registry shows the server's
// `detail` next to the row). A 401/403 still drops the dead session and puts
// the sign-in form up, as for reads. Only a network failure throws.
async function post(path: string, body: unknown, signal?: AbortSignal): Promise<PostResult> {
  const url = `${getBotApiUrl()}${path}`;
  const res = await fetch(url, {
    method: "POST",
    signal,
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (res.status === 401 || res.status === 403) handleUnauthorized(res.status, path);
  const text = await res.text().catch(() => "");
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  return { ok: res.ok, status: res.status, body: parsed, text };
}

function normalizeClosedTrade(r: ClosedTrade): ClosedTrade {
  // Normalise the bot's field names so every consumer reads pnl/strategy: the
  // endpoint returns `realizedPnl` (not `pnl`) and carries the strategy in
  // `pattern` (not `strategy`). Without this, Trades/Accounts/Overview show
  // Net P&L / Win rate / Strategy as "—" despite real closed trades.
  return { ...r, pnl: r.pnl ?? r.realizedPnl ?? null, strategy: r.strategy ?? r.pattern ?? null };
}

/**
 * One operator ask from `src/runtime/trade_approvals.py::offer` (bot), served by
 * `GET /api/bot/trade-approvals` (require_session). Same store the Telegram
 * Approve/Reject buttons decide: whichever surface decides first wins.
 * `kind` is absent on trade asks; any other kind (e.g. a future `ops_job`) gets
 * the same Approve / Reject — the bot decides what it accepts.
 */
export interface TradeApprovalAsk {
  token: string;
  kind?: string | null;
  review_id?: string | null;
  order_package_id?: string | null;
  leg?: string | null;
  symbol?: string | null;
  accounts?: string[] | null;
  row_action?: string | null;
  directed?: { action?: string | null; level?: number | null; fraction?: number | null } | null;
  ev_delta_r?: number | null;
  basis?: string | null;
  confidence?: string | null;
  reason?: string | null;
  mechanics?: string | null;
  route?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
  state?: string | null; // pending | approved | rejected | expired | refused
  decided_at?: string | null;
  record_id?: string | null;
  title?: string | null;
  summary?: string | null;
}

/**
 * One LTR review / Claude decision on a trade, for chart markers (UI-REDESIGN-2026-11
 * addendum 5). PROVISIONAL shape asked of the bot (source: comms/live_review/
 * reviews.jsonl + live-review/rows + directed_actions receipts); no route serves it yet.
 */
export interface TradeDecision {
  review_id?: string | null;
  reviewed_at?: string | null; // ISO; `at` accepted as an alias
  at?: string | null;
  action?: string | null; // hold | tighten | partial_close | close | move_tp | …
  disposition?: string | null; // applied | advice_only | refused
}

/** `POST /api/bot/trade-approvals/{token}` answer (`trade_approvals.decide`). */
export interface TradeApprovalDecision {
  outcome?: string | null; // approved | rejected | unknown | expired | already_<state> | refused | error
  token?: string | null;
  record_id?: string | null;
  reply?: string | null;
}

/** One row of `GET /api/bot/performance/categories` (bot `src/runtime/perf_category.py::category_metrics`). */
export interface PerfCategoryRow {
  category: string; // live | prop | paper_portfolio | paper_testing
  accounts?: string[] | null;
  read_state?: string | null;
  n_closed?: number | null;
  net_pnl_usd?: number | null;
  measured_usd?: number | null;
  n_measured?: number | null;
  not_measured_usd?: number | null;
  n_not_measured?: number | null;
  win_rate?: number | null; // fraction 0..1
  n_priced?: number | null;
  avg_realised_r?: number | null;
  n_r_graded?: number | null;
  r_insufficient_n?: boolean | null;
  profit_factor?: number | null;
  avg_hold_days?: number | null;
  n_no_hold?: number | null;
  return_on_time_in_trade_bps_per_notional_day?: number | null;
  return_on_time_in_trade_all_rows_bps_per_notional_day?: number | null;
  capital_utilisation?: number | null;
  capital_utilisation_read_state?: string | null;
  max_drawdown_usd?: number | null;
  fees_usd?: number | null;
  n_fees?: number | null;
  funding_usd?: number | null;
  n_funding?: number | null;
  n_excluded_null_pnl?: number | null;
}

export interface PerfCategories {
  as_of?: string | null;
  window?: string | null;
  // bot #25241: start/end (inclusive UTC days) are echoed when asked for; `total`
  // is the bot's own roll-up of the four rows (additive fields summed, ratios
  // recomputed, max DD null + max_drawdown_read_state "not_additive").
  start?: string | null;
  end?: string | null;
  read_state?: string | null;
  categories?: PerfCategoryRow[];
  total?: (PerfCategoryRow & { max_drawdown_read_state?: string | null; label?: string | null; provenance?: Record<string, string> | null }) | null;
  capital_flows?: { read_state?: string | null; reason?: string | null; effect?: string | null } | null;
  excluded?: Array<{ account_id?: string; reason?: string }>;
  population?: {
    window?: string;
    since?: string | null;
    n_closed?: number | null;
    rows_excluded_null_pnl?: number | null;
    also_excluded?: string | null;
  } | null;
}

export interface PnlPoint {
  date: string; // YYYY-MM-DD (utc_day bucket) or an ISO instant (trade bucket, window=7d)
  pnl_usd?: number | null;
  n?: number | null;
  cum_pnl_usd?: number | null;
  cum_pnl_all_rows_usd?: number | null;
  cum_pct?: number | null; // PERCENT units (cum / start capital * 100); null = no capital record
  cum_pct_all_rows?: number | null;
}

export interface PnlSeries {
  as_of?: string | null;
  window?: string | null;
  read_state?: string | null;
  measured_only?: boolean | null;
  bucket?: string | null;
  series?: Array<{
    category: string;
    start_capital_usd?: number | null;
    capital_read_state?: string | null;
    n_rows?: number | null;
    read_state?: string | null;
    points?: PnlPoint[];
  }>;
  population?: { window?: string; since?: string | null; n_rows?: number | null; filters?: Record<string, string | null> } | null;
}

export interface BracketLevel {
  kind: "sl" | "tp" | string;
  price: number;
  from_ts?: string | null;
  to_ts?: string | null; // null = still in force
  source?: string | null;
  detail?: string | null;
  provenance?: string | null;
}
export interface BracketUpdate {
  ts?: string | null;
  kind: "sl" | "tp" | string;
  from?: number | null;
  to?: number | null;
  source?: string | null;
  detail?: string | null;
  bar_ts?: string | null;
}
export interface BracketHistory {
  read_state?: string | null; // measured | partial | no_record
  partial_reasons?: string[] | null;
  tp_history?: unknown;
  direction?: string | null;
  levels?: BracketLevel[];
  updates?: BracketUpdate[];
}

export const api = {
  // PERF-PAGE-CATEGORY-TABLE / PERF-PAGE-PNL-CHART (bot #24893). Windows are
  // 7d|30d|90d|all — the bot answers 400 for anything else (24h included).
  perfCategories: (window = "30d", signal?: AbortSignal) =>
    get<PerfCategories>(`/api/bot/performance/categories?window=${encodeURIComponent(window)}`, signal),
  // Exact inclusive UTC-day range (bot #25241). The caller must check the echoed
  // start/end: an older bot ignores the params and answers its default window.
  perfCategoriesRange: (start: string, end: string, signal?: AbortSignal) =>
    get<PerfCategories>(`/api/bot/performance/categories?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, signal),
  pnlSeries: (
    opts: { window?: string; category?: string[]; strategy?: string; symbol?: string; assetClass?: string; measuredOnly?: boolean } = {},
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams();
    q.set("window", opts.window ?? "30d");
    if (opts.category && opts.category.length) q.set("category", opts.category.join(","));
    if (opts.strategy) q.set("strategy", opts.strategy);
    if (opts.symbol) q.set("symbol", opts.symbol);
    if (opts.assetClass) q.set("asset_class", opts.assetClass);
    q.set("measured_only", String(opts.measuredOnly ?? true));
    return get<PnlSeries>(`/api/bot/performance/pnl-series?${q.toString()}`, signal);
  },

  // UI-CHART-BRACKET-HISTORY (bot #24893): SL/TP levels over time + one marker
  // per update. Exactly one of order_package_id / prop_fill_id; interval must be
  // one the bot knows (1m..1d) or it answers 400.
  bracketsHistory: (sel: { orderPackageId?: string; propFillId?: number }, interval = "15m", signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (sel.orderPackageId) q.set("order_package_id", sel.orderPackageId);
    if (sel.propFillId != null) q.set("prop_fill_id", String(sel.propFillId));
    q.set("interval", interval);
    return get<BracketHistory>(`/api/bot/brackets/history?${q.toString()}`, signal);
  },

  // FEATURE-IMPACT-MAP (bot #24926). measure: gain_share | split_share; by:
  // asset_class | ml_type | stage — the bot answers 400 for anything else.
  featureImpactHeatmap: (by = "asset_class", measure = "gain_share", signal?: AbortSignal) =>
    get<any>(`/api/bot/feature-impact/heatmap?by=${encodeURIComponent(by)}&measure=${encodeURIComponent(measure)}`, signal),
  featureImpactDetail: (
    opts: { family?: string; assetClass?: string; stage?: string; measure?: string } = {},
    signal?: AbortSignal,
  ) => {
    const q = new URLSearchParams();
    if (opts.family) q.set("family", opts.family);
    if (opts.assetClass) q.set("asset_class", opts.assetClass);
    if (opts.stage) q.set("stage", opts.stage);
    q.set("measure", opts.measure ?? "gain_share");
    return get<any>(`/api/bot/feature-impact/detail?${q.toString()}`, signal);
  },
  featureImpactInvest: (signal?: AbortSignal) => get<any>("/api/bot/feature-impact/invest", signal),

  // SIGNALS-CATALOG (bot #25199, UI-UPGRADE-1 item 8). Filters are server-side:
  // limit/offset/family/kind/q/consumer(any|with|without). Uncached ~2-3 s.
  // Returns the raw Response so the route can show the HTTP status on a non-200.
  signalsCatalog: (o: SignalsCatalogQuery = {}, signal?: AbortSignal) =>
    rawFetch(`/api/bot/signals/catalog?${buildSignalsCatalogQuery(o)}`, { signal }),

  // Trade approvals (TRADE-ACTION-DIRECT-PATH phase 1b, bot #25046) — both
  // routes are behind `require_session`; a 401 surfaces the sign-in form.
  tradeApprovals: (signal?: AbortSignal) =>
    get<{ readState?: string; count?: number; asks?: TradeApprovalAsk[] }>("/api/bot/trade-approvals", signal),
  // The decision is returned for every non-auth status: 404 unknown, 410
  // expired and 409 already-decided all carry a `reply` the operator must see,
  // so they are NOT thrown as errors.
  decideTradeApproval: async (token: string, choice: "approve" | "reject"): Promise<TradeApprovalDecision & { status: number }> => {
    const res = await rawFetch(`/api/bot/trade-approvals/${encodeURIComponent(token)}`, {
      method: "POST",
      body: { choice },
    });
    const body = (await res.json().catch(() => ({}))) as TradeApprovalDecision & { detail?: unknown };
    if (!res.ok && !body.reply) {
      body.reply = typeof body.detail === "string" ? body.detail : `${res.status} ${res.statusText}`;
    }
    return { ...body, status: res.status };
  },

  stats: (signal?: AbortSignal) => get<BotStats>("/api/bot/stats", signal),
  positions: (signal?: AbortSignal) =>
    get<Position[]>("/api/bot/positions?include_paper=true", signal),
  performance: (window = "7d", signal?: AbortSignal) =>
    get<Performance>(`/api/bot/performance?window=${encodeURIComponent(window)}`, signal),
  candles: (symbol: string, interval = "15m", limit = 200, signal?: AbortSignal) =>
    get<{ candles: Candle[]; source?: string; error?: string }>(
      `/api/bot/candles?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${limit}`,
      signal,
    ),
  closedTrades: (opts: { since?: string; includePaper?: boolean; limit?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.since) q.set("since", opts.since);
    if (opts.includePaper) q.set("include_paper", "true");
    // `/api/bot/trades/closed` caps `limit` at 200 (422 above it — the bot's
    // own Query(..., le=200), trades_closed.py). Callers that need more than
    // one page must use `closedTradesPage` below and walk `offset`.
    q.set("limit", String(opts.limit ?? 200));
    return get<ClosedTrade[]>(`/api/bot/trades/closed?${q.toString()}`, signal).then((rows) =>
      (Array.isArray(rows) ? rows : []).map(normalizeClosedTrade),
    );
  },
  // Same endpoint as `closedTrades`, but surfaces the pagination headers the
  // bot returns (`X-Total-Count` / `X-Has-More`) so a caller can walk `offset`
  // past the 200-row cap instead of silently truncating a wide window.
  closedTradesPage: (
    opts: { since?: string; includePaper?: boolean; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) =>
    (async () => {
      const q = new URLSearchParams();
      if (opts.since) q.set("since", opts.since);
      if (opts.includePaper) q.set("include_paper", "true");
      q.set("limit", String(Math.min(opts.limit ?? 200, 200)));
      q.set("offset", String(opts.offset ?? 0));
      const res = await getRaw(`/api/bot/trades/closed?${q.toString()}`, signal);
      const rows = (await res.json()) as ClosedTrade[];
      const normalized = (Array.isArray(rows) ? rows : []).map(normalizeClosedTrade);
      const totalHeader = res.headers.get("X-Total-Count");
      return {
        rows: normalized,
        total: totalHeader != null ? Number(totalHeader) : normalized.length,
        hasMore: res.headers.get("X-Has-More") === "true",
      };
    })(),
  // /api/bot/strategies returns per-strategy config + a top-level runtime block;
  // shape varies, so fetch loosely and normalize in the view.
  strategies: (signal?: AbortSignal) => get<any>("/api/bot/strategies", signal),
  balances: (signal?: AbortSignal) => get<any>("/api/bot/accounts/balances", signal),
  config: (signal?: AbortSignal) => get<any>("/api/bot/config", signal),
  reports: (signal?: AbortSignal) => get<any>("/api/bot/reports?limit=50", signal),
  report: (id: string, signal?: AbortSignal) =>
    get<any>(`/api/bot/reports/${encodeURIComponent(id)}`, signal),
  news: (limit = 50, signal?: AbortSignal) =>
    get<any>(`/api/bot/news/recent?limit=${limit}`, signal),
  pnlHistory: (days = 30, signal?: AbortSignal) =>
    get<Array<{ date?: string; pnl?: number | null }>>(`/api/pnl/history?days=${days}`, signal),
  signals: (signal?: AbortSignal) => get<any>("/api/bot/signals", signal),
  orderPackages: (opts: { since?: string; strategy?: string; linkedTradeId?: string; includePaper?: boolean; limit?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.linkedTradeId) q.set("linked_trade_id", opts.linkedTradeId);
    if (opts.since) q.set("since", opts.since);
    if (opts.strategy) q.set("strategy", opts.strategy);
    if (opts.includePaper) q.set("include_paper", "true");
    q.set("limit", String(opts.limit ?? 100));
    return get<any>(`/api/bot/order-packages?${q.toString()}`, signal);
  },
  insight: (endpoint: string, signal?: AbortSignal) => get<any>(`/api/bot/insights/${endpoint}`, signal),
  roadmap: (signal?: AbortSignal) => get<any>("/api/bot/roadmap", signal),
  work: (signal?: AbortSignal) => get<any>("/api/bot/work", signal),
  // The work store's item list (WSD-S1, ungated read). Filters are the route's own:
  // state, due (the due_now view), since (ISO), kind, limit<=1000, offset. NOTE:
  // `total` is the WHOLE store's count (count_items()), not the filtered count, and
  // there is no next_offset — a full page is the only "maybe more" signal.
  // bot #25542 adds: state=open (every non-terminal state), owner_prefix, week_lane, q,
  // counts=1 (owner x state over the whole filtered set) and latest_note=1; an extended
  // read also answers `matched` (the filtered count). An older bot ignores them.
  workItems: (
    q: { state?: string; due?: boolean; since?: string; kind?: string; parent?: string; limit?: number; offset?: number;
         ownerPrefix?: string; weekLane?: string; q?: string; counts?: boolean; latestNote?: boolean } = {},
    signal?: AbortSignal,
  ) => {
    const u = new URLSearchParams();
    if (q.state) u.set("state", q.state);
    if (q.due) u.set("due", "1");
    if (q.since) u.set("since", q.since);
    if (q.kind) u.set("kind", q.kind);
    if (q.parent) u.set("parent", q.parent);
    if (q.ownerPrefix) u.set("owner_prefix", q.ownerPrefix);
    if (q.weekLane) u.set("week_lane", q.weekLane);
    if (q.q) u.set("q", q.q);
    if (q.counts) u.set("counts", "1");
    if (q.latestNote) u.set("latest_note", "1");
    u.set("limit", String(q.limit ?? 50));
    u.set("offset", String(q.offset ?? 0));
    return get<any>(`/api/bot/work/items?${u.toString()}`, signal);
  },
  // Per-AM lane cards (bot #25542): moved_today / working_now / stuck / next, each
  // {read_state, count, items[]}, plus week_lanes totals. 404 until that PR deploys.
  workLanes: (nextN = 5, signal?: AbortSignal) => statusGet(`/api/bot/work/lanes?next_n=${nextN}`, signal),

  // The manager checklist, graded by the bot. ⚠️ `status.value` and
  // `status.basis` arrive ALREADY RECONCILED — the file carries two competing
  // status fields (`state` and `status`, 13 of 244 rows disagreeing as of
  // 2026-09-10) and `src/runtime/manager_status.py::effective_state` is their
  // ONE owner. Do NOT merge them again here or in a component: a second merge
  // is a second definition of an item's status, free to drift from the one the
  // manager guards read.
  workChecklist: (signal?: AbortSignal) =>
    get<any>("/api/bot/work/checklist", signal),

  // The decision inbox — what is waiting on the operator. Read-only; the
  // submit route is token-gated and fail-closed and is not called from here.
  workDecisions: (signal?: AbortSignal) =>
    get<any>("/api/bot/work/decisions", signal),

  // The daily brief (A3) — six fixed sections rendered live from the pipeline
  // store, the checklist, and config/mandates.yaml. §0 (what came due) + the
  // §5 unrouted count are the forcing function for the follow-through
  // pipeline (A7): this is the ONLY consumer that puts them on the
  // operator's own page. `present: false` arrives WITH a `reason` — never a
  // 5xx — and `inputs` carries a three-way read state per source
  // (read/absent/unreadable) that must not be collapsed. Read-only.
  workBrief: (signal?: AbortSignal) => get<any>("/api/bot/work/brief", signal),
  // UI-UPGRADE-1: the Overview's work-queue glance (~6 KB; the full checklist is
  // ~435 KB). closedRecent / openNow / next / waitingOnOperator, `present:false`
  // with a reason when the store is unreadable — never empty lists as "no work".
  workSnapshot: (signal?: AbortSignal) => get<any>("/api/bot/work/snapshot", signal),
  // WORK-TOPIC-TAXONOMY (bot #24927) and INSIGHTS-LEDGER (bot #24919): topic
  // roll-up of every work row, and pipeline items with kind:"insight".
  workTopics: (signal?: AbortSignal) => get<any>("/api/bot/work/topics", signal),
  workLedger: (signal?: AbortSignal) => get<any>("/api/bot/work/ledger", signal),
  // The alerts ledger (ungated read). `since` keeps the payload small — the
  // whole 500-row default window is ~330 KB.
  alerts: (opts: { since?: string; kind?: string; limit?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.since) q.set("since", opts.since);
    if (opts.kind) q.set("kind", opts.kind);
    q.set("limit", String(opts.limit ?? 200));
    return get<any>(`/api/bot/alerts?${q.toString()}`, signal);
  },
  // Features catalog (docs/reference/signal-catalog.yaml joined with the served +
  // candidate model.json feature lists; ungated, ~220 KB). `coverage` carries the
  // bot's own counts, incl. n_models_missing_from_catalog (operator u8).
  catalogFeatures: (signal?: AbortSignal) => get<any>("/api/bot/catalog/features", signal),

  // The work schedule (A9) — cadenced sessions (the daily sync, the three
  // project-level reviews) · decisions owed · monitoring coming due · cron
  // cadences, rendered live from SCHEDULE.json + the pipeline store +
  // .github/workflows/*.yml. Same contract as workBrief: `present: false`
  // arrives WITH a `reason`, never a 5xx; `inputs` carries a three-way read
  // state per source (read/absent/unreadable) that must not be collapsed.
  // Read-only.
  workSchedule: (signal?: AbortSignal) => get<any>("/api/bot/work/schedule", signal),

  // Prop (Breakout manual-bridge) — isolated journal, never blended into real/paper.
  propStatus: (accountId = "breakout_1", signal?: AbortSignal) =>
    get<any>(`/api/bot/prop/status?account_id=${encodeURIComponent(accountId)}`, signal),
  propFills: (limit = 50, signal?: AbortSignal) => get<any>(`/api/bot/prop/fills?limit=${limit}`, signal),
  propTickets: (limit = 50, signal?: AbortSignal) => get<any>(`/api/bot/prop/tickets?limit=${limit}`, signal),
  // Whole prop book for the Overview (equity over fresh accounts, open trades,
  // windowed realized P&L) — DASH-PROP-OVERVIEW. 404 on a bot older than the endpoint.
  propOverview: (window = "7d", signal?: AbortSignal) =>
    get<any>(`/api/bot/prop/overview?window=${encodeURIComponent(window)}`, signal),
  propReconcile: (accountId = "breakout_1", signal?: AbortSignal) =>
    get<any>(`/api/bot/prop/reconcile?account_id=${encodeURIComponent(accountId)}`, signal),

  // Admin — health / logs / data explorer.
  healthServices: (signal?: AbortSignal) => get<any>("/api/bot/health/services", signal),
  // Wake-notification switches (ungated read; the POST is service-token gated bot-side).
  wakeToggles: (signal?: AbortSignal) => get<any>("/api/bot/wake-toggles", signal),
  // ── Backend routes from JTA-Trader #25216 / #25231 (held at the time of writing).
  // Each returns { status, body } and does NOT throw on 404/4xx, so a page can say
  // "not available yet" / "could not look" instead of inventing a state.
  // Closed trade's STORED chart snapshot (built once at close; read_state measured |
  // partial | not_built; snapshot null when not built; 404 while the trade is open).
  tradeSnapshot: (tradeId: string | number) => statusGet(`/api/bot/trades/${encodeURIComponent(String(tradeId))}/snapshot`),
  propTradeSnapshot: (fillId: string | number) => statusGet(`/api/bot/prop-trades/${encodeURIComponent(String(fillId))}/snapshot`),
  // Open trade's markers: entry, entry_signal, brackets, decisions (LTR reviews).
  tradeMarkers: (tradeId: string | number, interval = "1h") =>
    statusGet(`/api/bot/trades/${encodeURIComponent(String(tradeId))}/markers?interval=${encodeURIComponent(interval)}`),
  propTradeMarkers: (fillId: string | number, interval = "1h") =>
    statusGet(`/api/bot/prop-trades/${encodeURIComponent(String(fillId))}/markers?interval=${encodeURIComponent(interval)}`),
  // Infra health: components trader_vm, ib_gateway, phone_app, trainer_vm, kaggle,
  // hugging_face; state ok | degraded | down | could_not_look.
  healthInfra: () => statusGet("/api/bot/health/infra"),
  // /performance over an explicit calendar range (bot #25231). Date-only strings;
  // `until` is inclusive. ⚠️ A bot without the feature IGNORES since/until and
  // answers all-time, so the caller must check the echo `window === "range"`.
  performanceRange: (since: string, until: string) =>
    statusGet(`/api/bot/performance?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}`),
  // The weekly performance-review outputs: list + one review's content (bot #25231).
  performanceReviews: (limit = 50) => statusGet(`/api/bot/performance/reviews?limit=${limit}`),
  performanceReview: (id: string) => statusGet(`/api/bot/performance/reviews/${encodeURIComponent(id)}`),
  // Work "testing queue": { read_state, n_running (nullable), running[], sources[], hf_jobs }.
  testingQueue: () => statusGet("/api/bot/work/testing-queue"),
  healthLatest: (signal?: AbortSignal) => get<any>("/api/bot/health/latest", signal),
  // Prop manual-bridge phone app's recent step runs (ungated) — the health bar reads
  // the newest run's `last_at` as the phone's last-seen time.
  phoneSteps: (signal?: AbortSignal) => get<any>("/api/bot/prop/phone_steps", signal),
  notifications: (signal?: AbortSignal) => get<any>("/api/bot/notifications", signal),
  logs: (opts: { limit?: number; level?: string } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    q.set("limit", String(opts.limit ?? 200));
    if (opts.level) q.set("level", opts.level);
    return get<any>(`/api/bot/logs?${q.toString()}`, signal);
  },
  // Session-gated, cached 60 s bot-side. `quick` runs PRAGMA quick_check and
  // can be slow on the journal — only ever request it from an explicit button.
  // 404 until the route is deployed; callers render "not available yet".
  dbOverview: (integrity: "off" | "quick" = "off", signal?: AbortSignal) =>
    get<DbOverview>(`/api/bot/db/overview?integrity=${integrity}`, signal),
  dbTables: (signal?: AbortSignal) => get<any>("/api/bot/db/tables", signal),
  dbTable: (name: string, opts: { db?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.db) q.set("db", opts.db);
    q.set("limit", String(opts.limit ?? 50));
    if (opts.offset) q.set("offset", String(opts.offset));
    return get<any>(`/api/bot/db/table/${encodeURIComponent(name)}?${q.toString()}`, signal);
  },

  // Research catalog — UNGATED, public-repo data; works signed out. The detail
  // route 400s on a malformed id and answers `present:false` for an unknown one.
  researchCatalog: (q: CatalogQuery, signal?: AbortSignal) =>
    get<CatalogResponse>(`/api/bot/research/catalog?${buildCatalogQuery(q)}`, signal),
  researchUnit: (id: string, signal?: AbortSignal) =>
    get<CatalogDetail>(`/api/bot/research/catalog/${encodeURIComponent(id)}`, signal),

  // Admin → Gates: the gate registry (operator ask 2026-11-12). Reads go
  // through `get` like every other route; the decision is the one write.
  gates: (f: GateFilters = {}, signal?: AbortSignal) => {
    const q = buildGatesQuery(f);
    return get<GatesResponse>(`/api/bot/gates${q ? `?${q}` : ""}`, signal);
  },
  gate: (id: string, signal?: AbortSignal) =>
    get<GateDetailResponse>(`/api/bot/gates/${encodeURIComponent(id)}`, signal),
  gateDecision: (id: string, decision: string, note: string, signal?: AbortSignal) =>
    post(`/api/bot/gates/${encodeURIComponent(id)}/decision`, { decision, note }, signal),

  // Work → Plans (bot #25554, design § "Tab 5: Plans"). All reads are statusGet so a
  // 404 (route not deployed) renders "not available yet", never an empty list.
  //  - the frontier sub-queue: FRONTIER-Q-* rows are children of FRONTIER-RESEARCH
  //  - the ML development plan: plan items joined to their carrying rows + the dev plan
  //  - plan edits read back: observation rows, newest first (the route orders by
  //    updated_at DESC); the component keeps the ones carrying extra.plan_edit
  frontierQueue: (signal?: AbortSignal) =>
    statusGet("/api/bot/work/items?parent=FRONTIER-RESEARCH&limit=200&offset=0", signal),
  mlPlan: (signal?: AbortSignal) => statusGet("/api/bot/ml/plan", signal),
  planEditRows: (signal?: AbortSignal) =>
    statusGet("/api/bot/work/items?kind=observation&limit=1000&offset=0", signal),
  // Tier 2, operator session: file one add or suggested edit. 200 {accepted, status,
  // item, read_back}; 400 bad body; 401 no session; 404 unknown target row; 503 not persisted.
  planEdit: (
    body: { section: "frontier" | "ml_plan"; kind: "add" | "edit"; text: string; item_id?: string },
    signal?: AbortSignal,
  ) => post("/api/bot/work/plan-edits", body, signal),

  // Strategies & Models.
  gpuSpend: (signal?: AbortSignal) => get<any>("/api/bot/gpu/spend", signal),
  mlRegistry: (signal?: AbortSignal) => get<any>("/api/bot/ml/registry", signal),
  mlStatus: (signal?: AbortSignal) => get<any>("/api/bot/ml/status", signal),
  exitLadderSoak: (limit = 100, signal?: AbortSignal) =>
    get<any>(`/api/bot/exit-ladder/soak?limit=${limit}`, signal),
  backtestSweeps: (limit = 10, signal?: AbortSignal) =>
    get<any>(`/api/bot/backtests/sweeps?limit=${limit}`, signal),
  shadowStats: (signal?: AbortSignal) => get<any>("/api/bot/shadow/stats", signal),
};
