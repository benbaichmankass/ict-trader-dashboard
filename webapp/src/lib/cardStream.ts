// ONE shared MarketStream for every open trade card (operator decision on #233:
// no socket per card). Cards acquire(symbol) on mount and release on destroy; the
// stream is subscribed to the union of acquired symbols, re-created when that set
// changes (the protocol's `hello` is server-sent, so a new subscription = a new
// socket), and closed when no card is open.

import { writable } from "svelte/store";
import { MarketStream } from "./ws";
import type { Candle } from "./api";

export const cardCandles = writable<Record<string, Candle[]>>({});

const INTERVAL = "15m";
const refs = new Map<string, number>();
let stream: MarketStream | null = null;
let streamKey = "";
let timer: ReturnType<typeof setTimeout> | null = null;

function sync(): void {
  timer = null;
  const syms = [...refs.keys()].sort();
  const key = syms.join(",");
  if (key === streamKey) return;
  stream?.stop();
  stream = null;
  streamKey = key;
  if (!syms.length) return; // no card open → no socket
  stream = new MarketStream(syms, INTERVAL, {
    onCandles: (sym, _iv, cs) => cardCandles.update((m) => ({ ...m, [sym]: cs })),
  });
  stream.start();
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
