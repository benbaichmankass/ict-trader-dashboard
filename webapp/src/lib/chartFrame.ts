// Open-trade chart framing (UI-LIVE-CHART-FRAMING, operator rule 2026-11-15, verbatim):
//   "open until current bar +5% on each side, as well as top-to-bottom from SL (first one
//    if it's been moved) to TP (farthest if it has been moved), + 5% on each side".
//
// Pure functions — no chart library, no DOM — so tests/chart-frame.mjs can import this file
// directly (node 22 strips the types). LiveChart applies the result; the closed-trade
// SnapshotChart has its own framing (15% / 10%) and does not use this.

export type FrameLevel = { price: number; fromSec: number | null };

export interface FrameInput {
  /** When the trade opened (epoch s) — the left edge before padding. null → no x frame. */
  openSec: number | null;
  /** The newest bar's open time (epoch s) — the right edge before padding. null → no x frame. */
  lastBarSec: number | null;
  /** Bar length in seconds (900 for 15m). */
  barSec: number;
  side: "long" | "short" | null;
  entry: number | null;
  /** Every SL level the trade has had (bracket history); the FIRST by time is the frame's anchor. */
  sl: FrameLevel[];
  /** Every TP level the trade has had; the farthest in the profit direction anchors the frame. */
  tp: FrameLevel[];
  /** The SL / TP in force now — used when the history is absent (a prop row, an older bot). */
  currentSl: number | null;
  currentTp: number | null;
}

export interface Frame {
  /** Visible time range, epoch s, padded. null when the open time or the last bar is unknown. */
  x: { from: number; to: number } | null;
  /** Visible price range, padded. null when fewer than two anchors are known → let the chart autoscale. */
  y: { lo: number; hi: number } | null;
}

/** Operator's padding: 5% of the span on each side. */
export const PAD = 0.05;
/** A just-opened trade has almost no span; show at least this many bars so it is not two huge candles.
 *  Extra room is added to the LEFT (context before the open) — the right edge stays the current bar. */
export const MIN_BARS = 20;

const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;

/** The SL the trade OPENED with: the earliest-by-time history level, else the one in force. */
export function initialSl(i: FrameInput): number | null {
  const lv = i.sl.filter((l) => fin(l.price));
  if (lv.length) {
    // Levels without a time sort after those with one; among equals the first listed wins.
    const t = (l: FrameLevel) => (l.fromSec == null ? Infinity : l.fromSec);
    return lv.reduce((a, b) => (t(b) < t(a) ? b : a)).price;
  }
  return fin(i.currentSl) ? i.currentSl : null;
}

/** The TP farthest from the entry in the profit direction (highest for a long, lowest for a short). */
export function farthestTp(i: FrameInput): number | null {
  const all = [...i.tp.map((l) => l.price), i.currentTp].filter(fin);
  if (!all.length) return null;
  if (i.side === "long") return Math.max(...all);
  if (i.side === "short") return Math.min(...all);
  // Unknown side: the farthest from the entry by distance (entry unknown → the first).
  if (!fin(i.entry)) return all[0];
  return all.reduce((a, b) => (Math.abs(b - i.entry!) > Math.abs(a - i.entry!) ? b : a));
}

export function frameFor(i: FrameInput): Frame {
  let x: Frame["x"] = null;
  if (i.openSec != null && i.lastBarSec != null && Number.isFinite(i.openSec) && Number.isFinite(i.lastBarSec) && i.barSec > 0) {
    const right = Math.max(i.lastBarSec, i.openSec);
    let left = Math.min(i.openSec, right);
    if (right - left < MIN_BARS * i.barSec) left = right - MIN_BARS * i.barSec;
    const pad = (right - left) * PAD;
    x = { from: Math.round(left - pad), to: Math.round(right + pad) };
  }

  let y: Frame["y"] = null;
  const sl = initialSl(i);
  const tp = farthestTp(i);
  const anchors = [sl, tp].filter((v): v is number => v != null);
  // One anchor alone (e.g. TP known, SL not) is completed with the entry; with neither → autoscale.
  if (anchors.length === 1 && fin(i.entry)) anchors.push(i.entry);
  if (anchors.length >= 2) {
    const lo = Math.min(...anchors);
    const hi = Math.max(...anchors);
    if (hi > lo) {
      const pad = (hi - lo) * PAD;
      y = { lo: lo - pad, hi: hi + pad };
    }
  }
  return { x, y };
}

/** "15m" → 900, "1h" → 3600, "1d" → 86400; unknown → 900. */
export function intervalSec(interval: string): number {
  const m = /^(\d+)\s*([mhdw])$/i.exec(String(interval).trim());
  if (!m) return 900;
  const n = Number(m[1]);
  const unit = { m: 60, h: 3600, d: 86400, w: 604800 }[m[2].toLowerCase() as "m" | "h" | "d" | "w"];
  return n * unit;
}

/** How many bars to request so history reaches back to the open (+ padding room), within the API's cap. */
export function barsToLoad(openSec: number | null, nowSec: number, barSec: number, floor = 200, cap = 1000): number {
  if (openSec == null || !Number.isFinite(openSec) || barSec <= 0) return floor;
  const span = Math.max(0, nowSec - openSec) / barSec;
  const want = Math.ceil(span * (1 + 2 * PAD)) + 10;
  return Math.min(cap, Math.max(floor, want));
}
