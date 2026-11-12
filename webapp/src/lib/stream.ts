// T2 (UI-TRADING-PUSH): the SPA on the bot's ONE push stream, GET /api/bot/stream
// (SSE, bot #25173). Frames {seq, ts, type, payload}; type ∈ hello | alert | package |
// trade | bracket | position | health. One EventSource per tab, shared by every view
// (refcounted acquire/release).
//
// Rules (from the server's contract):
// - Each (re)connect mints a FRESH single-use ?ticket= (POST /api/auth/ws-ticket) and
//   sends ?last_event_id=<last seq> so the server replays its 10-minute ring.
// - `hello` with gap:true, or the first hello of a page load → "resnapshot": REST
//   (/positions, /accounts/balances) stays the authority on membership.
// - `position` = the open-trade set changed → views re-read REST /positions.
// - Down / could not connect → `streamStatus` says so; views fall back to their old
//   poll and LABEL it. Never a frozen view that looks live.
import { writable, get } from "svelte/store";
import { getBotApiUrl } from "./config";
import { streamTicket } from "./session";

export type StreamFrame = { seq?: number; ts?: string; type: string; payload: any };
export type StreamStatus = "idle" | "connecting" | "live" | "down";

export const streamStatus = writable<StreamStatus>("idle");
/** Wall-clock ms of the last frame or keepalive-backed open; null before the first. */
export const streamLastFrameAt = writable<number | null>(null);

type Listener = (f: StreamFrame) => void;
const listeners = new Set<Listener>();
let refs = 0;
let es: EventSource | null = null;
let lastSeq: number | null = null;
let backoff = 1000;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
const TYPES = ["hello", "alert", "package", "trade", "bracket", "position", "health"];

function dispatch(f: StreamFrame) {
  streamLastFrameAt.set(Date.now());
  for (const l of listeners) { try { l(f); } catch { /* a view's handler must not kill the stream */ } }
}

async function connect() {
  if (es || refs === 0) return;
  streamStatus.set("connecting");
  const q = new URLSearchParams();
  const t = await streamTicket();
  if (refs === 0) { streamStatus.set("idle"); return; }
  if (t) q.set("ticket", t);
  if (lastSeq != null) q.set("last_event_id", String(lastSeq));
  let src: EventSource;
  try {
    src = new EventSource(`${getBotApiUrl()}/api/bot/stream${q.toString() ? `?${q}` : ""}`);
  } catch {
    scheduleRetry();
    return;
  }
  es = src;
  for (const type of TYPES) {
    src.addEventListener(type, (ev: MessageEvent) => {
      let f: StreamFrame;
      try { f = JSON.parse(String(ev.data)); } catch { return; }
      if (typeof f?.seq === "number" && type !== "hello") lastSeq = f.seq;
      if (type === "hello") {
        backoff = 1000;
        streamStatus.set("live");
        const gap = f?.payload?.gap === true;
        if (typeof f?.seq === "number" && lastSeq == null) lastSeq = f.seq;
        // First hello on this page load, or the ring no longer covers our last seq.
        if (gap || !sawEverHello) dispatch({ type: "resnapshot", payload: { reason: gap ? "gap" : "first_load" } });
        sawEverHello = true;
      }
      dispatch({ ...f, type });
    });
  }
  src.onerror = () => {
    // EventSource auto-retries with the SAME url (a spent ticket) — close and reconnect
    // ourselves with a fresh ticket and the last seq.
    try { src.close(); } catch { /* gone */ }
    if (es === src) es = null;
    streamStatus.set("down");
    scheduleRetry();
  };
}
let sawEverHello = false;

function scheduleRetry() {
  if (retryTimer || refs === 0) return;
  retryTimer = setTimeout(() => { retryTimer = null; connect(); }, backoff);
  backoff = Math.min(backoff * 2, 30000);
}

/** Start (or share) the stream; returns the release function. */
export function acquireStream(): () => void {
  refs++;
  connect();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    refs = Math.max(0, refs - 1);
    if (refs === 0) {
      if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
      if (es) { try { es.close(); } catch { /* gone */ } es = null; }
      streamStatus.set("idle");
    }
  };
}

/** Listen to every frame (plus the synthetic "resnapshot"); returns the unsubscribe. */
export function onStreamFrame(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function isStreamLive(): boolean {
  return get(streamStatus) === "live";
}
