// Reconnecting client for the bot's /ws/market push (live candles + positions).
// Frames (per ict-trading-bot/CLAUDE.md § WS /ws/market):
//   {type:"hello", symbols, interval}
//   {type:"candles", symbol, interval, candles:[…]}
//   {type:"positions", positions:[…]}
//
// The socket degrades gracefully: on close/error it retries with capped
// backoff, so a VM bounce or a dropped connection self-heals without a reload.

import { getBotWsUrl } from "./config";
import type { Candle, Position } from "./api";

export type MarketStatus = "connecting" | "open" | "closed";

export interface MarketHandlers {
  onCandles?: (symbol: string, interval: string, candles: Candle[]) => void;
  /**
   * Live positions frame.
   *
   * ⚠️ **THIS FRAME IS SYMBOL-SCOPED, NOT THE WHOLE BOOK.** The server filters
   * it to the symbols this stream subscribed to (`market_ws.py`: `if symbols:
   * positions = [p for p in positions if p["symbol"] in symbols]`). The type is
   * `Position[]` either way, so nothing here distinguishes "these are the open
   * positions" from "these are the open positions IN THE SUBSCRIBED SYMBOLS" —
   * and a consumer that assigns it straight onto its positions state silently
   * drops every position in every other symbol.
   *
   * That is not hypothetical: `Overview.svelte` did exactly that until
   * 2026-08-25, subscribing to one charted symbol and then replacing the
   * REST-populated array with this frame ~2s after every load. Measured that
   * day, `/api/bot/positions` returned 3 real-money rows and the SPA rendered
   * "Open trades 2".
   *
   * **Use it to REFRESH uPnL on rows you already have. Never to decide which
   * rows exist** — REST (`/api/bot/positions`) is the authority on membership.
   */
  onPositions?: (positions: Position[]) => void;
  onStatus?: (status: MarketStatus) => void;
}

export class MarketStream {
  private ws: WebSocket | null = null;
  private closed = false;
  private backoff = 1000;
  private readonly maxBackoff = 15000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly symbols: string[],
    private readonly interval: string,
    private readonly handlers: MarketHandlers,
    private readonly limit = 200,
  ) {}

  start(): void {
    this.closed = false;
    this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.ws?.close();
    this.ws = null;
  }

  private connect(): void {
    const q = new URLSearchParams({
      symbols: this.symbols.join(","),
      interval: this.interval,
      limit: String(this.limit),
      include_paper: "true",
    });
    const url = `${getBotWsUrl()}/ws/market?${q.toString()}`;
    this.handlers.onStatus?.("connecting");
    try {
      this.ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.backoff = 1000;
      this.handlers.onStatus?.("open");
    };
    this.ws.onmessage = (ev) => {
      let msg: any;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      if (msg?.type === "candles" && Array.isArray(msg.candles)) {
        this.handlers.onCandles?.(msg.symbol, msg.interval, msg.candles as Candle[]);
      } else if (msg?.type === "positions" && Array.isArray(msg.positions)) {
        this.handlers.onPositions?.(msg.positions as Position[]);
      }
    };
    this.ws.onclose = () => {
      this.handlers.onStatus?.("closed");
      this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.closed) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), this.backoff);
    this.backoff = Math.min(this.maxBackoff, this.backoff * 2);
  }
}
