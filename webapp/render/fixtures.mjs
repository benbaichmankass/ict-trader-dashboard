// Realistic mock API responses for headless render verification (no live API in
// the sandbox). Values mirror tonight's live pulls so screenshots look real.
// Keyed by URL substring → JSON body.

const positions = [
  { id: "1", account: "bybit_2", accountClass: "real_money", assetClass: "crypto", symbol: "BTCUSDT", side: "buy", qty: 0.001, entryPrice: 63754.2, unrealizedPnl: 3.48, unrealizedPnlSource: "broker", openedAt: "2026-07-16T01:50:16Z", stopLoss: 62711.2, takeProfit: 70065.87, pattern: "trend_donchian" },
  { id: "2", account: "bybit_2", accountClass: "real_money", assetClass: "crypto", symbol: "XRPUSDT", side: "sell", qty: 5, entryPrice: 1.0717, unrealizedPnl: 0.87, unrealizedPnlSource: "broker", openedAt: "2026-07-13T03:12:48Z", stopLoss: 1.10025, takeProfit: 0.96560, pattern: "trend_donchian_xrp_4h" },
  { id: "3", account: "bybit_1", accountClass: "paper", assetClass: "crypto", symbol: "ETHUSDT", side: "buy", qty: 0.5, entryPrice: 1813.0, unrealizedPnl: 1384.2, unrealizedPnlSource: "broker", openedAt: "2026-07-11T14:39:18Z", stopLoss: 1795.18, takeProfit: 1992.49, pattern: "trend_donchian_eth" },
];

const perfReal = {
  window: "24h", totalTrades: 11, wins: 3, losses: 8, winRate: 27.3, totalPnl: 5.57,
  expectancy: 0.506, profitFactor: 1.34, maxDrawdown: -9.99,
  perAssetClass: [{ assetClass: "crypto", trades: 10, winRate: 30.0, totalPnl: 6.0 }, { assetClass: "bond", trades: 1, winRate: 0, totalPnl: -0.44 }],
  perStrategy: [
    { name: "eth_pullback_2h", trades: 1, wins: 1, winRate: 100, totalPnl: 10.34, expectancy: 10.34 },
    { name: "trend_donchian_eth_4h", trades: 2, wins: 1, winRate: 50, totalPnl: 9.65, expectancy: 4.83 },
    { name: "ada_pullback_2h", trades: 2, wins: 0, winRate: 0, totalPnl: -10.05, expectancy: -5.02 },
  ],
  equity: [{ t: "2026-07-15", cum: 0 }, { t: "2026-07-15T12:00", cum: 10.3 }, { t: "2026-07-16", cum: 5.57 }],
  paper: { window: "24h", totalTrades: 24, wins: 9, winRate: 37.5, totalPnl: -7551.97, expectancy: -314.7, profitFactor: 0.17, maxDrawdown: -8723.99, perStrategy: [], perAssetClass: [], equity: [] },
};

export const FIXTURES = [
  ["/api/bot/stats", { pnl24h: 2.90, totalPnL: -26.93, openTrades: 2, winRate: 27.2, status: "running", datasource: "live", vmHealth: { cpu: 32.1, memory: 48.5, disk: 21.0 }, paperOpenTrades: 1, paper: { pnl24h: 0, totalPnL: -15478, openTrades: 6, winRate: 37.5 } }],
  ["/api/bot/positions", positions],
  ["/api/bot/performance", perfReal],
  ["/api/bot/strategies", { runtime: { bot_running: true, last_tick_utc: "2026-07-16T08:06:43Z", tick_age_seconds: 92, loaded_strategies: 44 }, strategies: [] }],
  ["/api/bot/config", { accounts: [{ id: "bybit_2", account_class: "real_money", symbols: ["BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT"] }, { id: "bybit_1", account_class: "paper", symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"] }], strategies: {} }],
  ["/api/bot/accounts/balances", { present: true, source: "db", balances: { bybit_2: { balance: 307.13, delta_1h: -0.01, open_positions: 3, api_ok: true }, bybit_1: { balance: 167308.81, delta_1h: -61.1, open_positions: 6, api_ok: true } } }],
  ["/api/bot/trades/closed", []],
  ["/api/bot/signals", []],
  ["/api/bot/candles", { symbol: "BTCUSDT", interval: "15m", source: "bybit", candles: Array.from({ length: 96 }, (_, i) => { const base = 64000 + Math.sin(i / 6) * 900; return { time: 1784000000 + i * 900, open: base, high: base + 120, low: base - 120, close: base + (i % 3 - 1) * 60, volume: 100 }; }), count: 96 }],
  ["/api/pnl/history", Array.from({ length: 30 }, (_, i) => ({ date: `2026-06-${String(i + 1).padStart(2, "0")}`, pnl: (i % 5 - 2) * 3 }))],
  ["/api/bot/news/recent", { present: true, count: 2, records: [{ symbol: "BTCUSDT", decision: "neutral", adjustment: 0.0, top_items: [{ headline: "Bitcoin steadies near 64k", url: "https://example.com/a", score: 0.2 }] }] }],
  ["/api/bot/reports", { present: true, count: 1, reports: [{ id: "RPT-20260716-061200-weekly", window: "weekly", generated_at: "2026-07-16T06:12:00Z", roll_up_grade: "caution", headline: "Net-positive real-money week (+$5.57, PF 1.34) carried by the ETH book." }] }],
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
  ["/api/bot/db/tables", { present: true, tables: [{ name: "trades", rows: 3442, db: "trade_journal" }, { name: "order_packages", rows: 1200, db: "trade_journal" }] }],
  ["/api/bot/insights/summary", { cache_present: true, grade: "🟡", summary_md: "The book is net-positive on the week; ETH strategies carry it.", generated_at: "2026-07-16T06:00:00Z", signals: ["ETH book strong", "alt bleeders small"] }],
  ["/api/bot/insights/health", { cache_present: true, grade: "🟢", summary_md: "Core services healthy.", generated_at: "2026-07-16T06:00:00Z", signals: [] }],
  ["/api/bot/roadmap", { present: true, summary: { done: 8, active: 4, pending: 10, total: 22 }, milestones: [] }],
];

export function matchFixture(url) {
  for (const [frag, body] of FIXTURES) if (url.includes(frag)) return body;
  return null;
}
