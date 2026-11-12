// ONE shared live feed for every open trade card (operator decision on #233:
// no socket per card). Cards acquire(symbol) on mount and release on destroy.
//
// T3a (2026-11-12): `*USDT` symbols tick from Bybit's PUBLIC WebSocket in the
// browser (lib/bybitStream — one socket, refcounted topics); the VM never
// carries their ticks. Every other symbol stays on the bot's `/ws/market`
// MarketStream, subscribed to the union of acquired non-crypto symbols and
// re-created when that set changes (the protocol's `hello` is server-sent, so a
// new subscription = a new socket), closed when none are open.
//
// History is seeded once over REST (`seedCandles`, the card's /api/bot/candles
// call); the Bybit stream only upserts the live right-edge bar.

import { writable } from "svelte/store";
import { MarketStream } from "./ws";
import { acquireKline, isBybitLinear, onKline, upsertBar } from "./bybitStream";
import type { Candle } from "./api";

export const cardCandles = writable<Record<string, Candle[]>>({});
/** Which feed is moving each symbol's chart: "bybit" (browser-direct) or "ws_market" (via the bot). */
export const cardFeed = writable<Record<string, "bybit" | "ws_market">>({});

const INTERVAL = "15m";
const refs = new Map<string, number>();
const bybitRelease = new Map<string, () => void>();
let stream: MarketStream | null = null;
let streamKey = "";
let timer: ReturnType<typeof setTimeout> | null = null;
let klineUnsub: (() => void) | null = null;

function ensureKlineListener(): void {
  if (klineUnsub) return;
  klineUnsub = onKline((sym, bar) => {
    if (!refs.has(sym)) return;
    cardCandles.update((m) => ({ ...m, [sym]: upsertBar(m[sym] ?? [], bar) }));
  });
}

function sync(): void {
  timer = null;
  const syms = [...refs.keys()].sort();
  // Crypto → Bybit public WS.
  for (const s of syms) {
    if (isBybitLinear(s) && !bybitRelease.has(s)) {
      const rel = acquireKline(s, INTERVAL);
      if (rel) {
        ensureKlineListener();
        bybitRelease.set(s, rel);
        cardFeed.update((m) => ({ ...m, [s]: "bybit" }));
      }
    }
  }
  for (const [s, rel] of [...bybitRelease]) {
    if (!refs.has(s)) { rel(); bybitRelease.delete(s); }
  }
  // Everything else → /ws/market.
  const rest = syms.filter((s) => !bybitRelease.has(s));
  const key = rest.join(",");
  if (key === streamKey) return;
  stream?.stop();
  stream = null;
  streamKey = key;
  if (!rest.length) return;
  cardFeed.update((m) => ({ ...m, ...Object.fromEntries(rest.map((s) => [s, "ws_market" as const])) }));
  stream = new MarketStream(rest, INTERVAL, {
    onCandles: (sym, _iv, cs) => cardCandles.update((m) => ({ ...m, [sym]: cs })),
  });
  stream.start();
}

/** Seed a symbol's history from REST; a live array already held is kept (it is newer). */
export function seedCandles(symbol: string, candles: Candle[]): void {
  if (!candles.length) return;
  cardCandles.update((m) => {
    const cur = m[symbol];
    if (!cur || !cur.length) return { ...m, [symbol]: candles };
    // Live bars arrived first: put history in front of them.
    const first = cur[0].time;
    return { ...m, [symbol]: [...candles.filter((c) => c.time < first), ...cur].slice(-500) };
  });
}

/** Subscribe `symbol` for one card; returns the release function. */
export function acquireSymbol(symbol: string): () => void {
  refs.set(symbol, (refs.get(symbol) ?? 0) + 1);
  if (!timer) timer = setTimeout(sync, 30); // coalesce several cards opening at once
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const n = (refs.get(symbol) ?? 1) - 1;
    if (n <= 0) refs.delete(symbol); else refs.set(symbol, n);
    if (!timer) timer = setTimeout(sync, 30);
  };
}
