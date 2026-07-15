<script lang="ts">
  import { onMount } from "svelte";
  import { createChart, ColorType, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";

  let { points = [], height = 240 }: { points?: Array<{ t: number | string; cum: number }>; height?: number } = $props();

  let el: HTMLDivElement;
  let chart: IChartApi | null = null;
  let series: ISeriesApi<"Area"> | null = null;

  function isDark() {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
  }

  function toSec(t: number | string): number {
    if (typeof t === "number") return t > 1e11 ? Math.floor(t / 1000) : t;
    const ms = Date.parse(t);
    return Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
  }

  onMount(() => {
    const dark = isDark();
    chart = createChart(el, {
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: dark ? "#8b93a3" : "#5b6472" },
      grid: { vertLines: { visible: false }, horzLines: { color: dark ? "#1a1f2b" : "#eceef1" } },
      rightPriceScale: { borderColor: dark ? "#232a38" : "#e2e5ea" },
      timeScale: { borderColor: dark ? "#232a38" : "#e2e5ea", timeVisible: false },
      autoSize: true,
    });
    series = chart.addAreaSeries({
      lineColor: "#4c8dff",
      topColor: "rgba(76,141,255,0.35)",
      bottomColor: "rgba(76,141,255,0.02)",
      lineWidth: 2,
      priceLineStyle: LineStyle.Dotted,
    });
    const ro = new ResizeObserver(() => chart?.timeScale().fitContent());
    ro.observe(el);
    return () => { ro.disconnect(); chart?.remove(); chart = null; series = null; };
  });

  $effect(() => {
    if (!series) return;
    const data = points
      .map((p) => ({ time: toSec(p.t) as UTCTimestamp, value: p.cum }))
      .filter((d) => d.time > 0)
      .sort((a, b) => (a.time as number) - (b.time as number));
    series.setData(data);
    chart?.timeScale().fitContent();
  });
</script>

<div bind:this={el} style:height={`${height}px`} style:width="100%"></div>
