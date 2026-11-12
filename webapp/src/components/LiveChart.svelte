<script lang="ts">
  import { onMount } from "svelte";
  import {
    createChart,
    ColorType,
    CrosshairMode,
    LineStyle,
    type IChartApi,
    type ISeriesApi,
    type IPriceLine,
    type SeriesMarker,
    type UTCTimestamp,
    type Time,
  } from "lightweight-charts";
  import type { Candle, Position, ClosedTrade, BracketHistory, TradeDecision } from "../lib/api";
  import { dispositionColor } from "../lib/chartTime";

  // Candles + trade context overlaid the way Streamlit's monitor does it:
  // live-position entry/SL/TP price-lines, buy/sell signal markers, and
  // closed-trade exit markers — all scoped to the charted symbol upstream.
  let {
    candles = [], positions = [], signals = [], closedTrades = [], brackets = null, decisions = [],
    height = 320,
  }: {
    candles?: Candle[]; positions?: Position[]; signals?: any[];
    closedTrades?: ClosedTrade[]; brackets?: BracketHistory | null;
    // UI-REDESIGN-2026-11 addendum 5: one marker per LTR review / Claude decision at
    // the bar it was made. Hook only — the per-trade read route is being built
    // bot-side (lane CLOSED-TRADE-SNAPSHOT); empty → nothing drawn, never invented.
    decisions?: TradeDecision[];
    height?: number;
  } = $props();

  let el: HTMLDivElement;
  let chart: IChartApi | null = null;
  let series: ISeriesApi<"Candlestick"> | null = null;
  let priceLines: IPriceLine[] = [];
  // UI-CHART-BRACKET-HISTORY: one faint line series per REPLACED level (from its
  // set time to its replacement), redrawn when the history or the bars change.
  let historyLines: ISeriesApi<"Line">[] = [];
  let seeded = false;

  function isDark(): boolean {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
  }

  function toSec(v: any): number | null {
    if (v == null || v === "") return null;
    if (typeof v === "number") return v > 1e12 ? Math.floor(v / 1000) : Math.floor(v);
    // The bot serialises some times as naive "YYYY-MM-DD HH:MM:SS" (UTC, no
    // zone) — normalise to an explicit UTC instant so markers don't shift by
    // the viewer's local offset.
    let s = String(v).trim().replace(" ", "T");
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
    const t = Date.parse(s);
    return Number.isNaN(t) ? null : Math.floor(t / 1000);
  }

  // Snap an event time to the nearest candle time so lightweight-charts renders
  // the marker on the grid (an off-grid time can be dropped).
  function snap(sec: number, times: number[]): number | null {
    if (!times.length) return null;
    let best = times[0], bestD = Math.abs(sec - times[0]);
    for (const t of times) {
      const d = Math.abs(sec - t);
      if (d < bestD) { best = t; bestD = d; }
    }
    return best;
  }

  function isSell(side: any): boolean {
    return String(side ?? "").toLowerCase().startsWith("s");
  }

  onMount(() => {
    const dark = isDark();
    chart = createChart(el, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: dark ? "#8b93a3" : "#5b6472",
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: dark ? "#1a1f2b" : "#eceef1" },
        horzLines: { color: dark ? "#1a1f2b" : "#eceef1" },
      },
      rightPriceScale: { borderColor: dark ? "#232a38" : "#e2e5ea" },
      timeScale: { borderColor: dark ? "#232a38" : "#e2e5ea", timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
      autoSize: true,
    });
    series = chart.addCandlestickSeries({
      upColor: "#26a17b",
      downColor: "#e5484d",
      borderVisible: false,
      wickUpColor: "#26a17b",
      wickDownColor: "#e5484d",
    });

    const ro = new ResizeObserver(() => chart?.timeScale().fitContent());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart?.remove();
      chart = null;
      series = null;
      priceLines = [];
      historyLines = [];
    };
  });

  // Re-seed candles whenever the array identity changes.
  $effect(() => {
    if (!series || candles.length === 0) return;
    series.setData(candles.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open, high: c.high, low: c.low, close: c.close,
    })));
    if (!seeded) {
      chart?.timeScale().fitContent();
      seeded = true;
    }
  });

  // Price lines: live-position entry / SL / TP (redrawn on any change).
  $effect(() => {
    if (!series) return;
    for (const pl of priceLines) { try { series.removePriceLine(pl); } catch { /* gone */ } }
    priceLines = [];
    for (const p of positions) {
      const sell = isSell(p.side);
      if (p.entryPrice != null) priceLines.push(series.createPriceLine({
        price: p.entryPrice, color: sell ? "#e5484d" : "#26a17b",
        lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true,
        title: `entry ${sell ? "SHORT" : "LONG"}`,
      }));
      if (p.stopLoss != null && p.stopLoss > 0) priceLines.push(series.createPriceLine({
        price: p.stopLoss, color: "#e5484d", lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "SL",
      }));
      if (p.takeProfit != null && p.takeProfit > 0) priceLines.push(series.createPriceLine({
        price: p.takeProfit, color: "#26a17b", lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "TP",
      }));
    }
    // Signals carry a price but (currently) no usable timestamp, so draw the
    // most recent few as thin dotted price levels (buy=green, sell=red) rather
    // than time-positioned markers.
    for (const g of signals.slice(0, 3)) {
      const price = Number(g?.price);
      if (!price || !Number.isFinite(price)) continue;
      const sell = isSell(g.side ?? g.action ?? g.direction);
      priceLines.push(series.createPriceLine({
        price, color: sell ? "#e5484d" : "#26a17b", lineWidth: 1,
        lineStyle: LineStyle.Dotted, axisLabelVisible: false,
        title: `signal ${sell ? "sell" : "buy"}${g.strategy ? " " + g.strategy : ""}`,
      }));
    }
  });

  // Earlier SL/TP levels: subtle dashed segments over the bars they were in
  // force. A level replaced inside one bar has no visible span — its marker
  // (below) still records the move. Never a fabricated continuous line.
  $effect(() => {
    if (!chart) return;
    for (const l of historyLines) { try { chart.removeSeries(l); } catch { /* gone */ } }
    historyLines = [];
    if (!brackets || candles.length === 0) return;
    const times = candles.map((c) => c.time);
    for (const lv of brackets.levels ?? []) {
      if (lv.to_ts == null || !Number.isFinite(lv.price)) continue; // the level in force is the SL/TP price line
      const a = toSec(lv.from_ts), b = toSec(lv.to_ts);
      if (a == null || b == null) continue;
      const t0 = snap(a, times), t1 = snap(b, times);
      if (t0 == null || t1 == null || t1 <= t0) continue;
      const ls = chart.addLineSeries({
        color: lv.kind === "tp" ? "rgba(38,161,123,0.45)" : "rgba(229,72,77,0.45)",
        lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      ls.setData([{ time: t0 as UTCTimestamp, value: lv.price }, { time: t1 as UTCTimestamp, value: lv.price }]);
      historyLines.push(ls);
    }
  });

  // Markers: buy/sell signals + open-position entries + closed-trade exits.
  $effect(() => {
    if (!series || candles.length === 0) return;
    const times = candles.map((c) => c.time);
    const marks: SeriesMarker<Time>[] = [];

    for (const s of signals) {
      const sec = toSec(s.timestamp ?? s.time ?? s.ts ?? s.detectedAt);
      if (sec == null) continue;
      const t = snap(sec, times);
      if (t == null) continue;
      const sell = isSell(s.side ?? s.action ?? s.direction);
      marks.push({
        time: t as UTCTimestamp,
        position: sell ? "aboveBar" : "belowBar",
        color: sell ? "#e5484d" : "#26a17b",
        shape: sell ? "arrowDown" : "arrowUp",
        text: s.pattern ?? s.strategy ?? (sell ? "sell" : "buy"),
      });
    }

    for (const p of positions) {
      const sec = toSec(p.openedAt);
      if (sec == null) continue;
      const t = snap(sec, times);
      if (t == null) continue;
      const sell = isSell(p.side);
      marks.push({
        time: t as UTCTimestamp,
        position: sell ? "aboveBar" : "belowBar",
        color: "#e0a800", shape: sell ? "arrowDown" : "arrowUp",
        text: "● open",
      });
    }

    for (const c of closedTrades) {
      const sec = toSec(c.closedAt ?? c.openedAt);
      if (sec == null) continue;
      const t = snap(sec, times);
      if (t == null) continue;
      // The endpoint serialises PnL as `realizedPnl` (legacy `pnl` fallback).
      const pnl = (c as any).realizedPnl ?? c.pnl;
      const win = (pnl ?? 0) >= 0;
      marks.push({
        time: t as UTCTimestamp, position: "inBar",
        color: win ? "#26a17b" : "#e5484d", shape: "circle",
        text: pnl != null ? (win ? "+" : "") + Number(pnl).toFixed(0) : "×",
      });
    }

    // One marker per bracket update, on the bar it happened in: ▲/▼ = the stop
    // moved up/down, ■ = a TP move. Label "SL from→to".
    for (const u of brackets?.updates ?? []) {
      const sec = toSec(u.bar_ts ?? u.ts);
      if (sec == null) continue;
      const t = snap(sec, times);
      if (t == null) continue;
      const up = (u.to ?? 0) > (u.from ?? 0);
      const fmt = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : String(+v.toPrecision(6)));
      marks.push({
        time: t as UTCTimestamp,
        position: u.kind === "tp" ? "aboveBar" : up ? "belowBar" : "aboveBar",
        color: "#d4a017",
        shape: u.kind === "tp" ? "square" : up ? "arrowUp" : "arrowDown",
        text: `${String(u.kind).toUpperCase()} ${fmt(u.from)}→${fmt(u.to)}`,
      });
    }

    // LTR / Claude decisions: ◆ at the bar; colour by disposition
    // (applied blue, advice-only amber, refused red, operator-ask orange, dry-run
    // purple, no-action / unknown grey — lib/chartTime::dispositionColor).
    for (const d of decisions) {
      const sec = toSec(d.reviewed_at ?? d.at);
      if (sec == null) continue;
      const t = snap(sec, times);
      if (t == null) continue;
      const disp = String(d.disposition ?? "").toLowerCase();
      const color = dispositionColor(disp);
      marks.push({
        time: t as UTCTimestamp, position: "aboveBar", color, shape: "square",
        text: `LTR ${d.action ?? "—"}${disp ? ` · ${disp.replace("_", "-")}` : ""}`,
      });
    }

    marks.sort((a, b) => (a.time as number) - (b.time as number));
    series.setMarkers(marks);
  });
</script>

<div class="chart" bind:this={el} style:height={`${height}px`}></div>

<style>
  .chart {
    width: 100%;
  }
</style>
