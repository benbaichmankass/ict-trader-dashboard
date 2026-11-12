// Client-side performance roll-ups for the Performance page's book + date-range
// view (UI-REDESIGN-2026-11, PERFORMANCE: date-range picker, book selector,
// breakdowns by strategy, asset class AND account). The bot's /performance only
// serves fixed windows (24h|7d|30d|all), so an arbitrary start..end is computed
// here from the closed-trade rows — labelled as such on the page.
//
// Rules: a row with no numeric P&L is COUNTED as a trade but left out of every
// P&L figure (never summed as 0); `unpriced` reports how many. Ratios with an
// empty denominator are null → "—".

export interface PerfRow {
  pnl: number | null;
  closedAt: string | null;
  strategy: string | null;
  assetClass: string | null;
  account: string | null;
  provenance: string | null; // broker | measured | fabricated | unverified | … (null = not graded)
}

export interface PerfStats {
  trades: number;
  priced: number;
  unpriced: number;
  wins: number;
  losses: number;
  winRate: number | null; // 0..1 over priced
  net: number | null;
  avgWin: number | null;
  avgLoss: number | null;
  expectancy: number | null;
  profitFactor: number | null;
  maxDrawdown: number | null; // ≤ 0, on the cumulative curve
  best: number | null;
  worst: number | null;
  estimated: number; // priced rows whose provenance is fabricated/unverified/estimated
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const EST = new Set(["fabricated", "unverified", "estimated", "estimate"]);

export function stats(rows: PerfRow[]): PerfStats {
  const priced = rows.filter((r) => isNum(r.pnl)) as Array<PerfRow & { pnl: number }>;
  const wins = priced.filter((r) => r.pnl > 0);
  const losses = priced.filter((r) => r.pnl < 0);
  const sum = (xs: Array<{ pnl: number }>) => xs.reduce((a, r) => a + r.pnl, 0);
  const grossWin = sum(wins), grossLoss = -sum(losses);
  const net = priced.length ? sum(priced) : null;
  let cum = 0, peak = 0, dd = 0;
  for (const r of [...priced].sort((a, b) => Date.parse(a.closedAt ?? "") - Date.parse(b.closedAt ?? ""))) {
    cum += r.pnl; peak = Math.max(peak, cum); dd = Math.min(dd, cum - peak);
  }
  return {
    trades: rows.length,
    priced: priced.length,
    unpriced: rows.length - priced.length,
    wins: wins.length,
    losses: losses.length,
    winRate: priced.length ? wins.length / priced.length : null,
    net,
    avgWin: wins.length ? grossWin / wins.length : null,
    avgLoss: losses.length ? -grossLoss / losses.length : null,
    expectancy: priced.length ? (net as number) / priced.length : null,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : null,
    maxDrawdown: priced.length ? dd : null,
    best: priced.length ? Math.max(...priced.map((r) => r.pnl)) : null,
    worst: priced.length ? Math.min(...priced.map((r) => r.pnl)) : null,
    estimated: priced.filter((r) => EST.has(String(r.provenance ?? "").toLowerCase())).length,
  };
}

/** Cumulative realised P&L points, time-ascending (priced rows only). */
export function equity(rows: PerfRow[]): Array<{ t: string; cum: number }> {
  let cum = 0;
  return rows
    .filter((r) => isNum(r.pnl) && r.closedAt)
    .sort((a, b) => Date.parse(a.closedAt as string) - Date.parse(b.closedAt as string))
    .map((r) => ({ t: r.closedAt as string, cum: (cum += r.pnl as number) }));
}

/** Group → stats, sorted by net P&L (unpriced groups last). Missing key → "—". */
export function breakdown(rows: PerfRow[], key: (r: PerfRow) => string | null): Array<{ name: string; s: PerfStats }> {
  const m = new Map<string, PerfRow[]>();
  for (const r of rows) {
    const k = key(r) || "—";
    (m.get(k) ?? m.set(k, []).get(k)!).push(r);
  }
  return [...m.entries()]
    .map(([name, rs]) => ({ name, s: stats(rs) }))
    .sort((a, b) => (b.s.net ?? -Infinity) - (a.s.net ?? -Infinity));
}

/** ISO date (YYYY-MM-DD, UTC) n days before today. */
export function isoDaysAgo(n: number, now = Date.now()): string {
  return new Date(now - n * 86_400_000).toISOString().slice(0, 10);
}

/** True when `closedAt` falls inside [start 00:00Z, end 24:00Z). */
export function inRange(closedAt: string | null, start: string, end: string): boolean {
  const t = closedAt ? Date.parse(closedAt) : NaN;
  if (Number.isNaN(t)) return false;
  return t >= Date.parse(`${start}T00:00:00Z`) && t < Date.parse(`${end}T00:00:00Z`) + 86_400_000;
}
