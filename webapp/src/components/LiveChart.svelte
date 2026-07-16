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
  import type { Candle, Position, ClosedTrade } from "../lib/api";

  // Candles + trade context overlaid the way Streamlit's monitor does it:
  // live-position entry/SL/TP price-lines, buy/sell signal markers, and
  // closed-trade exit markers — all scoped to the charted symbol upstream.
  let {
    candles = [], positions = [], signals = [], closedTrades = [],
    height = 320,
  }: {
    candles?: Candle[]; positions?: Position[]; signals?: any[];
    closedTrades?: ClosedTrade[]; height?: number;
  } = $props();

  let el: HTMLDivElement;
  let chart: IChartApi | null = null;
  let series: ISeriesApi<"Candlestick"> | null = null;
  let priceLines: IPriceLine[] = [];
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
