<script lang="ts">
  import { onMount } from "svelte";
  import {
    createChart,
    ColorType,
    CrosshairMode,
    type IChartApi,
    type ISeriesApi,
    type UTCTimestamp,
  } from "lightweight-charts";
  import type { Candle } from "../lib/api";

  let { candles = [], height = 320 }: { candles?: Candle[]; height?: number } = $props();

  let el: HTMLDivElement;
  let chart: IChartApi | null = null;
  let series: ISeriesApi<"Candlestick"> | null = null;
  let seeded = false;

  function isDark(): boolean {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
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
    };
  });

  // Re-seed the series whenever the candle array identity changes.
  $effect(() => {
    if (!series || candles.length === 0) return;
    const data = candles.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    series.setData(data);
    if (!seeded) {
      chart?.timeScale().fitContent();
      seeded = true;
    }
  });
</script>

<div class="chart" bind:this={el} style:height={`${height}px`}></div>

<style>
  .chart {
    width: 100%;
  }
</style>
