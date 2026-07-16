// Thin typed fetch client for the bot's Tier-1 read API. The interface here is
// the authoritative list of endpoints this app depends on — keep it in sync
// with ict-trading-bot/CLAUDE.md § "Dashboard REST API". Rename-resilient:
// unknown fields are ignored, a missing field stays undefined and renders as
// an em-dash downstream.

import { getBotApiUrl } from "./config";

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
  perAssetClass?: Array<{ assetClass: string; trades: number; winRate?: number | null; totalPnl?: number | null }>;
  perStrategy?: PerfStrategy[];
  equity?: Array<{ t: number | string; cum: number }>;
  paper?: Partial<Performance> | null;
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

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = `${getBotApiUrl()}${path}`;
  const res = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export const api = {
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
    q.set("limit", String(opts.limit ?? 200));
    return get<ClosedTrade[]>(`/api/bot/trades/closed?${q.toString()}`, signal).then((rows) =>
      // Normalise the bot's field names so every consumer reads pnl/strategy:
      // the endpoint returns `realizedPnl` (not `pnl`) and carries the strategy
      // in `pattern` (not `strategy`). Without this, Trades/Accounts show
      // Net P&L / Win rate / Strategy as "—" despite real closed trades.
      (Array.isArray(rows) ? rows : []).map((r) => ({
        ...r,
        pnl: r.pnl ?? r.realizedPnl ?? null,
        strategy: r.strategy ?? r.pattern ?? null,
      })),
    );
  },
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
  orderPackages: (opts: { since?: string; includePaper?: boolean; limit?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.since) q.set("since", opts.since);
    if (opts.includePaper) q.set("include_paper", "true");
    q.set("limit", String(opts.limit ?? 100));
    return get<any>(`/api/bot/order-packages?${q.toString()}`, signal);
  },
  insight: (endpoint: string, signal?: AbortSignal) => get<any>(`/api/bot/insights/${endpoint}`, signal),
  roadmap: (signal?: AbortSignal) => get<any>("/api/bot/roadmap", signal),

  // Prop (Breakout manual-bridge) — isolated journal, never blended into real/paper.
  propStatus: (accountId = "breakout_1", signal?: AbortSignal) =>
    get<any>(`/api/bot/prop/status?account_id=${encodeURIComponent(accountId)}`, signal),
  propFills: (limit = 50, signal?: AbortSignal) => get<any>(`/api/bot/prop/fills?limit=${limit}`, signal),
  propTickets: (limit = 50, signal?: AbortSignal) => get<any>(`/api/bot/prop/tickets?limit=${limit}`, signal),
  propReconcile: (accountId = "breakout_1", signal?: AbortSignal) =>
    get<any>(`/api/bot/prop/reconcile?account_id=${encodeURIComponent(accountId)}`, signal),

  // Admin — health / logs / data explorer.
  healthServices: (signal?: AbortSignal) => get<any>("/api/bot/health/services", signal),
  healthLatest: (signal?: AbortSignal) => get<any>("/api/bot/health/latest", signal),
  notifications: (signal?: AbortSignal) => get<any>("/api/bot/notifications", signal),
  logs: (opts: { limit?: number; level?: string } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    q.set("limit", String(opts.limit ?? 200));
    if (opts.level) q.set("level", opts.level);
    return get<any>(`/api/bot/logs?${q.toString()}`, signal);
  },
  dbTables: (signal?: AbortSignal) => get<any>("/api/bot/db/tables", signal),
  dbTable: (name: string, opts: { db?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams();
    if (opts.db) q.set("db", opts.db);
    q.set("limit", String(opts.limit ?? 50));
    if (opts.offset) q.set("offset", String(opts.offset));
    return get<any>(`/api/bot/db/table/${encodeURIComponent(name)}?${q.toString()}`, signal);
  },

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
