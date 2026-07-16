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
    return get<ClosedTrade[]>(`/api/bot/trades/closed?${q.toString()}`, signal);
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
  signals: (signal?: AbortSignal) => get<any>("/api/bot/signals", signal),
};
