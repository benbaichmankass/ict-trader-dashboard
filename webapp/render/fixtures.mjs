// Realistic mock API responses for headless render verification (no live API in
// the sandbox). Values mirror the live diag pull (ict-trading-bot#6639) so
// screenshots reflect real shapes: real-money ETH+XRP open on bybit_2, signals
// with EMPTY timestamps + a price, closed trades using `realizedPnl`, and
// multi-symbol accounts in /config. Keyed by URL substring → JSON body.

const positions = [
  // Real money (bybit_2) — the two that were invisible in the bug screenshot.
  { id: "3523", account: "bybit_2", accountClass: "real_money", assetClass: "crypto", symbol: "ETHUSDT", side: "buy", qty: 0.08, entryPrice: 1911.39, unrealizedPnl: -1.76, unrealizedPnlSource: "broker", openedAt: "2026-07-16 08:03:13", stopLoss: 1860.35, takeProfit: 2100.62, pattern: "eth_pullback_2h" },
  { id: "3507", account: "bybit_2", accountClass: "real_money", assetClass: "crypto", symbol: "XRPUSDT", side: "buy", qty: 167.2, entryPrice: 1.1102, unrealizedPnl: -0.4, unrealizedPnlSource: "broker", openedAt: "2026-07-15 20:04:47", stopLoss: 1.08279, takeProfit: 1.22011, pattern: "xrp_pullback_2h" },
  // Paper (bybit_1) sample.
  { id: "3508", account: "bybit_1", accountClass: "paper", assetClass: "crypto", symbol: "BTCUSDT", side: "buy", qty: 0.021, entryPrice: 65003.2, unrealizedPnl: -10.41, unrealizedPnlSource: "broker", openedAt: "2026-07-15 20:16:36", stopLoss: 63834.81, takeProfit: 71438.52, pattern: "htf_pullback_trend_2h" },
];

const signals = [
  { id: "a1", timestamp: "", symbol: "XRPUSDT", side: "buy", strategy: "xrp_pullback_2h", pattern: null, confidence: 0.6075, price: 1.1075, zones: [] },
  { id: "a2", timestamp: "", symbol: "BTCUSDT", side: "buy", strategy: "htf_pullback_trend_2h", pattern: null, confidence: 0.5851, price: 64217.0, zones: [] },
  { id: "a3", timestamp: "", symbol: "ETHUSDT", side: "buy", strategy: "eth_pullback_2h", pattern: null, confidence: 0.7671, price: 1888.81, zones: [] },
];

const closed = [
  { id: "3433", account: "bybit_2", accountClass: "real_money", symbol: "BTCUSDT", assetClass: "crypto", side: "buy", pattern: "trend_donchian", qty: 0.003, entryPrice: 63678.4, exitPrice: 63944.0, realizedPnl: 0.5023, realizedPnlPct: 0.2629, openedAt: "2026-07-14T12:49:06Z", closedAt: "2026-07-16T08:10:38Z", closeReason: "sl" },
  { id: "3168", account: "bybit_2", accountClass: "real_money", symbol: "ETHUSDT", assetClass: "crypto", side: "buy", pattern: "eth_pullback_2h", qty: 0.06, entryPrice: 1761.62, exitPrice: 1933.97, realizedPnl: 10.341, realizedPnlPct: 9.78, openedAt: "2026-07-05T04:05:19Z", closedAt: "2026-07-15T13:08:29Z", closeReason: "reconciler" },
];

const perfReal = {
  window: "7d", totalTrades: 13, wins: 4, losses: 9, winRate: 30.8, totalPnl: 4.5,
  expectancy: 0.35, profitFactor: 1.34, maxDrawdown: -9.99,
  perAssetClass: [{ assetClass: "crypto", trades: 12, winRate: 33.3, totalPnl: 4.5 }, { assetClass: "bond", trades: 1, winRate: 0, totalPnl: -0.44 }],
  perStrategy: [
    { name: "eth_pullback_2h", trades: 1, wins: 1, winRate: 100, totalPnl: 10.34, expectancy: 10.34 },
    { name: "ada_pullback_2h", trades: 3, wins: 0, winRate: 0, totalPnl: -12.05, expectancy: -4.02 },
  ],
  equity: [{ t: "2026-07-14", cum: 0 }, { t: "2026-07-15", cum: 10.3 }, { t: "2026-07-16", cum: 4.5 }],
  paper: { window: "7d", totalTrades: 23, wins: 8, winRate: 34.8, totalPnl: -8665.93, expectancy: -376.8, profitFactor: 0.17, maxDrawdown: -9200, perStrategy: [], perAssetClass: [], equity: [] },
};

// Symbol-aware synthetic candles so overlays (entry/SL/TP/signal lines) land on
// the chart for whichever symbol is charted. Base price per symbol ≈ live.
const SYM_BASE = { BTCUSDT: 64000, ETHUSDT: 1900, XRPUSDT: 1.11, SOLUSDT: 77, ADAUSDT: 0.165, AVAXUSDT: 6.6, SPY: 740, QQQ: 720 };
function candlesFor(url) {
  const m = /symbol=([A-Za-z0-9]+)/.exec(url);
  const sym = m ? m[1] : "BTCUSDT";
  const base = SYM_BASE[sym] ?? 100;
  const amp = base * 0.02;
  return {
    symbol: sym, interval: "15m", source: "bybit",
    candles: Array.from({ length: 96 }, (_, i) => {
      const b = base + Math.sin(i / 6) * amp;
      return { time: 1784000000 + i * 900, open: b, high: b + amp * 0.15, low: b - amp * 0.15, close: b + (i % 3 - 1) * amp * 0.08, volume: 100 };
    }),
    count: 96,
  };
}

const config = {
  accounts: [
    { id: "bybit_2", account_class: "real_money", symbols: ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT"] },
    { id: "bybit_1", account_class: "paper", symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT"] },
    { id: "alpaca_paper", account_class: "paper", symbols: ["SPY", "QQQ", "GLD", "IWM", "TLT"] },
    { id: "breakout_1", account_class: "prop", symbols: ["SOLUSDT", "ETHUSDT"] },
  ],
  strategies: {},
};

export const FIXTURES = [
  ["/api/bot/stats", { pnl24h: 0.5, totalPnL: -26.93, openTrades: 2, winRate: 30.8, status: "running", datasource: "live", vmHealth: { cpu: 32.1, memory: 48.5, disk: 21.0 }, paperOpenTrades: 1, paper: { pnl24h: 0, totalPnL: -15478, openTrades: 18, winRate: 34.8 } }],
  ["/api/bot/positions", positions],
  ["/api/bot/performance", perfReal],
  ["/api/bot/signals", signals],
  ["/api/bot/strategies", { runtime: { bot_running: true, last_tick_utc: "2026-07-16T10:29:31Z", tick_age_seconds: 45, loaded_strategies: 44 }, strategies: [] }],
  ["/api/bot/config", config],
  ["/api/bot/accounts/balances", { present: true, source: "db", balances: { bybit_2: { balance: 307.13, delta_1h: -0.01, open_positions: 2, api_ok: true }, bybit_1: { balance: 167308.81, delta_1h: -61.1, open_positions: 12, api_ok: true } } }],
  ["/api/bot/trades/closed", closed],
  ["/api/bot/candles", (url) => candlesFor(url)],
  ["/api/pnl/history", Array.from({ length: 30 }, (_, i) => ({ date: `2026-06-${String(i + 1).padStart(2, "0")}`, pnl: (i % 5 - 2) * 3 }))],
  ["/api/bot/news/recent", { present: true, count: 2, records: [{ symbol: "BTCUSDT", decision: "neutral", adjustment: 0.0, top_items: [{ headline: "Bitcoin steadies near 64k", url: "https://example.com/a", score: 0.2 }] }] }],
  ["/api/bot/reports", { present: true, count: 1, reports: [{ id: "RPT-20260716-061200-weekly", window: "weekly", generated_at: "2026-07-16T06:12:00Z", roll_up_grade: "caution", headline: "Net-positive real-money week (+$4.50, PF 1.34) carried by the ETH book." }] }],
  ["/api/bot/order-packages", { rows: [], count: 0 }],
  ["/api/bot/shadow/stats", { records: [{ model_id: "btc-regime-5m-lgbm-v2", stage: "shadow", count: 2487, score_mean: 0.984, score_min: 0.509, score_max: 0.9999, first_seen: "2026-07-07T13:00:52Z", last_seen: "2026-07-16T06:05:30Z" }] }],
  ["/api/bot/gpu/spend", { present: false }],
  ["/api/bot/ml/registry", []],
  ["/api/bot/exit-ladder/soak", { present: false, records: [], summary: {} }],
  ["/api/bot/backtests/sweeps", { present: false, sweeps: [] }],
  ["/api/bot/prop/status", { present: false }],
  ["/api/bot/prop/reconcile", { present: false }],
  ["/api/bot/prop/tickets", { present: true, count: 0, tickets: [] }],
  ["/api/bot/prop/fills", { present: true, count: 0, fills: [] }],
  ["/api/bot/health/services", { systemctl_available: true, services: [{ unit: "ict-trader-live.service", state: "active", sub_state: "running", active_enter_iso: "Thu 2026-07-16 05:55:33 UTC" }, { unit: "ict-web-api.service", state: "active", sub_state: "running" }] }],
  ["/api/bot/health/latest", { present: false }],
  ["/api/bot/notifications", { banners: [] }],
  ["/api/bot/logs", []],
  ["/api/bot/db/tables", { present: true, tables: [{ name: "trades", rows: 3527, db: "trade_journal" }, { name: "order_packages", rows: 1200, db: "trade_journal" }] }],
  ["/api/bot/insights/summary", { cache_present: true, grade: "🟡", summary_md: "The book is net-positive on the week; ETH strategies carry it.", generated_at: "2026-07-16T06:00:00Z", signals: ["ETH book strong", "alt bleeders small"] }],
  ["/api/bot/insights/health", { cache_present: true, grade: "🟢", summary_md: "Core services healthy.", generated_at: "2026-07-16T06:00:00Z", signals: [] }],
  ["/api/bot/roadmap", { present: true, summary: { done: 8, active: 4, pending: 10, total: 22 }, milestones: [] }],
];

export function matchFixture(url) {
  for (const [frag, body] of FIXTURES) {
    if (url.includes(frag)) return typeof body === "function" ? body(url) : body;
  }
  return null;
}
