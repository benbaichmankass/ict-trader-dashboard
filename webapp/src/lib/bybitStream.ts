// T3a (UI-TWO-SURFACE-DESIGN-2026-11 § 4.3, operator U3): crypto prices come
// straight from Bybit's PUBLIC v5 WebSocket in the browser — no key, no
// account, no relay, and no tick traffic through the trader VM.
//
// ONE socket for the whole page (refcounted topics), mirroring cardStream's
// "no socket per card" rule. Each `kline.<iv>.<SYMBOL>` frame upserts the
// current bar into the caller's candle array. History is NOT on the socket:
// the caller seeds once from the bot's REST `/api/bot/candles` and this stream
// only moves the right edge.
//
// Scope: USDT linear perps (`*USDT`). Every other symbol keeps `/ws/market`
// until T3b/T3c move it.
//
// `tickers.<SYM>` feeds `bybitLast` (symbol → lastPrice) for the in-browser
// live uPnL on crypto rows (SPA handoff § 1). Bybit's linear tickers send a
// snapshot then deltas; a delta without `lastPrice` leaves the last value.

import { writable } from "svelte/store";
import type { Candle } from "./api";

/** symbol → Bybit lastPrice (from `tickers.*`); absent until a tick arrives → render "—". */
export const bybitLast = writable<Record<string, number>>({});

export const BYBIT_PUBLIC_WS = "wss://stream.bybit.com/v5/public/linear";

const IV: Record<string, string> = {
  "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
  "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720", "1d": "D",
};

/** True for a symbol this stream serves (Bybit USDT linear perp naming). */
export function isBybitLinear(symbol: string): boolean {
  return /^[A-Z0-9]{2,20}USDT$/.test(symbol);
}

export function bybitInterval(interval: string): string | null {
  return IV[interval] ?? null;
}

type Listener = (symbol: string, bar: Candle) => void;
export type BybitStatus = "idle" | "connecting" | "open" | "closed";

const topicRefs = new Map<string, number>();
const listeners = new Set<Listener>();
const statusListeners = new Set<(s: BybitStatus) => void>();
let ws: WebSocket | null = null;
let status: BybitStatus = "idle";
let backoff = 1000;
let pingTimer: ReturnType<typeof setInterval> | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

function setStatus(s: BybitStatus): void {
  status = s;
  for (const l of statusListeners) l(s);
}

function send(obj: unknown): void {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

/** Parse one Bybit kline frame into (symbol, bar) pairs. Exported for tests. */
export function parseKlineFrame(msg: any): Array<{ symbol: string; bar: Candle }> {
  const topic = typeof msg?.topic === "string" ? msg.topic : "";
  if (!topic.startsWith("kline.") || !Array.isArray(msg.data)) return [];
  const symbol = topic.split(".")[2];
  if (!symbol) return [];
  const out: Array<{ symbol: string; bar: Candle }> = [];
  for (const k of msg.data) {
    const time = Math.floor(Number(k?.start) / 1000);
    const o = Number(k?.open), h = Number(k?.high), l = Number(k?.low), c = Number(k?.close);
    if (!Number.isFinite(time) || ![o, h, l, c].every(Number.isFinite)) continue;
    const v = Number(k?.volume);
    out.push({ symbol, bar: { time, open: o, high: h, low: l, close: c, volume: Number.isFinite(v) ? v : null } });
  }
  return out;
}

/** Parse one Bybit `tickers.<SYM>` frame → {symbol, last} or null (no lastPrice in a delta). Exported for tests. */
export function parseTickerFrame(msg: any): { symbol: string; last: number } | null {
  const topic = typeof msg?.topic === "string" ? msg.topic : "";
  if (!topic.startsWith("tickers.")) return null;
  const symbol = topic.slice("tickers.".length);
  const raw = msg?.data?.lastPrice;
  const last = raw == null || raw === "" ? NaN : Number(raw);
  return symbol && Number.isFinite(last) ? { symbol, last } : null;
}

function connect(): void {
  if (ws || topicRefs.size === 0) return;
  setStatus("connecting");
  let sock: WebSocket;
  try {
    sock = new WebSocket(BYBIT_PUBLIC_WS);
  } catch {
    scheduleRetry();
    return;
  }
  ws = sock;
  sock.onopen = () => {
    backoff = 1000;
    setStatus("open");
    const args = [...topicRefs.keys()];
    // Bybit caps args per request; chunk to stay well under it.
    for (let i = 0; i < args.length; i += 10) send({ op: "subscribe", args: args.slice(i, i + 10) });
    pingTimer = setInterval(() => send({ op: "ping" }), 20000); // Bybit drops idle sockets after ~30 s
  };
  sock.onmessage = (ev) => {
    let msg: any;
    try { msg = JSON.parse(String(ev.data)); } catch { return; }
    const tk = parseTickerFrame(msg);
    if (tk) { bybitLast.update((m) => ({ ...m, [tk.symbol]: tk.last })); return; }
    for (const { symbol, bar } of parseKlineFrame(msg)) for (const l of listeners) l(symbol, bar);
  };
  sock.onclose = () => {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = null;
    ws = null;
    setStatus("closed");
    scheduleRetry();
  };
  sock.onerror = () => { try { sock.close(); } catch { /* closing */ } };
}

function scheduleRetry(): void {
  if (retryTimer || topicRefs.size === 0) return;
  retryTimer = setTimeout(() => { retryTimer = null; connect(); }, backoff);
  backoff = Math.min(backoff * 2, 15000);
}

function teardownIfIdle(): void {
  if (topicRefs.size > 0) return;
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  if (ws) { const s = ws; ws = null; s.onclose = null; try { s.close(); } catch { /* gone */ } }
  if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  setStatus("idle");
}

/** Subscribe to one symbol's kline stream; returns the release function (null if not servable). */
export function acquireKline(symbol: string, interval: string): (() => void) | null {
  const iv = bybitInterval(interval);
  if (!iv || !isBybitLinear(symbol)) return null;
  return acquireTopic(`kline.${iv}.${symbol}`);
}

/** Subscribe to one symbol's `tickers.*` stream (feeds `bybitLast`); release fn, or null if not servable. */
export function acquireTicker(symbol: string): (() => void) | null {
  if (!isBybitLinear(symbol)) return null;
  return acquireTopic(`tickers.${symbol}`);
}

function acquireTopic(topic: string): () => void {
  const n = topicRefs.get(topic) ?? 0;
  topicRefs.set(topic, n + 1);
  if (n === 0) send({ op: "subscribe", args: [topic] });
  connect();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const m = (topicRefs.get(topic) ?? 1) - 1;
    if (m <= 0) {
      topicRefs.delete(topic);
      send({ op: "unsubscribe", args: [topic] });
    } else topicRefs.set(topic, m);
    teardownIfIdle();
  };
}

export function onKline(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function onBybitStatus(l: (s: BybitStatus) => void): () => void {
  statusListeners.add(l);
  l(status);
  return () => statusListeners.delete(l);
}

/** Upsert one live bar into a time-ascending candle array (returns a new array; caps length). */
export function upsertBar(arr: Candle[], bar: Candle, cap = 500): Candle[] {
  if (!arr.length) return [bar];
  const last = arr[arr.length - 1];
  if (bar.time === last.time) return [...arr.slice(0, -1), bar];
  if (bar.time > last.time) return [...arr, bar].slice(-cap);
  return arr; // an older bar than we hold: ignore (history is REST's job)
}

/**
 * In-browser live uPnL for a crypto row (SPA handoff § 1):
 * (last − entry) × qty × (long ? 1 : −1). Null — rendered "—", never 0 — when
 * no tick has arrived or entry/qty is missing. Assumes linear USDT perps
 * (1 contract = 1 unit of the base coin).
 */
export function liveUpnl(
  row: { side?: string | null; entryPrice?: number | null; qty?: number | null },
  last: number | null | undefined,
): number | null {
  const e = row.entryPrice, q = row.qty;
  if (last == null || !Number.isFinite(last) || e == null || !Number.isFinite(e) || q == null || !Number.isFinite(q) || !e) return null;
  const short = /^(s|short)/i.test(String(row.side ?? ""));
  return (last - e) * Math.abs(q) * (short ? -1 : 1);
}
