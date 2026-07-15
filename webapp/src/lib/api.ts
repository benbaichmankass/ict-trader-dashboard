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

export interface Performance {
  window?: string;
  totalTrades?: number | null;
  winRate?: number | null;
  totalPnl?: number | null;
  expectancy?: number | null;
  profitFactor?: number | null;
  maxDrawdown?: number | null;
  perAssetClass?: Array<{ assetClass: string; trades: number; winRate?: number | null; totalPnl?: number | null }>;
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
};
