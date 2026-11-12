<script lang="ts">
  // One cumulative-P&L line per category (PERF-PAGE-PNL-CHART, bot #24893).
  // unit "pct": y = % of the category's capital at window start (`cum_pct`,
  //   already percent units); a category with no capital record is omitted —
  //   never drawn as 0% — and the parent names it.
  // unit "usd": y = cumulative $.
  // `showAllRows`: a dotted twin per category for the all-rows curve, so the
  //   measured vs not-measured gap is visible.
  // Hover legend shows $ and % and the trade count for the crosshair point.
  import { onMount } from "svelte";
  import { createChart, ColorType, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp, type MouseEventParams } from "lightweight-charts";
  import type { PnlSeries, PnlPoint } from "../lib/api";
  import { money, DASH } from "../lib/format";

  let { data, unit = "pct", labels = {}, showAllRows = true, height = 260 }:
    { data: PnlSeries; unit?: "pct" | "usd"; labels?: Record<string, string>; showAllRows?: boolean; height?: number } = $props();

  const COLORS: Record<string, string> = { live: "#26a17b", prop: "#d4a017", paper_portfolio: "#4c8dff", paper_testing: "#a06cd5" };

  let el: HTMLDivElement;
  let chart: IChartApi | null = null;
  let lines: ISeriesApi<"Line">[] = [];
  let legend = $state<Array<{ label: string; color: string; text: string }>>([]);
  let hoverTime = $state<string | null>(null);
  // time (sec) → per category point, for the hover legend
  let byTime = new Map<number, Map<string, PnlPoint>>();

  function toSec(d: string): number {
    const ms = Date.parse(d.length === 10 ? `${d}T00:00:00Z` : d);
    return Number.isNaN(ms) ? 0 : Math.floor(ms / 1000);
  }

  function isDark() {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true;
  }

  function fmtPct(v: number | null | undefined) {
    return v == null || Number.isNaN(v) ? DASH : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  }

  function render() {
    if (!chart) return;
    for (const l of lines) chart.removeSeries(l);
    lines = [];
    byTime = new Map();
    for (const s of data.series ?? []) {
      if (unit === "pct" && s.start_capital_usd == null) continue;
      const color = COLORS[s.category] ?? "#8b93a3";
      const main: Array<{ time: UTCTimestamp; value: number }> = [];
      const all: Array<{ time: UTCTimestamp; value: number }> = [];
      let last = 0;
      for (const p of s.points ?? []) {
        let t = toSec(p.date);
        if (!t) continue;
        if (t <= last) t = last + 1; // per-trade points can share a second; the chart needs strictly increasing time
        last = t;
        const v = unit === "pct" ? p.cum_pct : p.cum_pnl_usd;
        const va = unit === "pct" ? p.cum_pct_all_rows : p.cum_pnl_all_rows_usd;
        if (v != null) main.push({ time: t as UTCTimestamp, value: v });
        if (va != null) all.push({ time: t as UTCTimestamp, value: va });
        if (!byTime.has(t)) byTime.set(t, new Map());
        byTime.get(t)!.set(s.category, p);
      }
      const line = chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: labels[s.category] ?? s.category });
      line.setData(main);
      lines.push(line);
      const differs = all.some((a, i) => main[i] && Math.abs(a.value - main[i].value) > 1e-9);
      if (showAllRows && differs) {
        const dotted = chart.addLineSeries({ color, lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false });
        dotted.setData(all);
        lines.push(dotted);
      }
    }
    chart.applyOptions({ localization: { priceFormatter: (v: number) => (unit === "pct" ? `${v.toFixed(2)}%` : money(v)) } });
    chart.timeScale().fitContent();
    setLegend(null);
  }

  function setLegend(t: number | null) {
    const out: Array<{ label: string; color: string; text: string }> = [];
    for (const s of data.series ?? []) {
      const pts = s.points ?? [];
      const p = t == null ? pts[pts.length - 1] : byTime.get(t)?.get(s.category);
      const label = labels[s.category] ?? s.category;
      const color = COLORS[s.category] ?? "#8b93a3";
      if (!p) { out.push({ label, color, text: DASH }); continue; }
      out.push({ label, color, text: `${money(p.cum_pnl_usd, { sign: true })} · ${fmtPct(p.cum_pct)} · ${p.n ?? DASH} trade(s) that ${data.bucket === "trade" ? "point" : "day"}` });
    }
    legend = out;
    hoverTime = t == null ? null : new Date(t * 1000).toISOString().slice(0, data.bucket === "trade" ? 16 : 10).replace("T", " ");
  }

  onMount(() => {
    const dark = isDark();
    chart = createChart(el, {
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: dark ? "#8b93a3" : "#5b6472" },
      grid: { vertLines: { visible: false }, horzLines: { color: dark ? "#1a1f2b" : "#eceef1" } },
      rightPriceScale: { borderColor: dark ? "#232a38" : "#e2e5ea" },
      timeScale: { borderColor: dark ? "#232a38" : "#e2e5ea", timeVisible: true },
      autoSize: true,
    });
    chart.subscribeCrosshairMove((p: MouseEventParams) => setLegend(typeof p.time === "number" ? p.time : null));
    render();
    return () => { chart?.remove(); chart = null; lines = []; };
  });

  $effect(() => {
    data; unit; showAllRows;
    render();
  });
</script>

<div class="legend small">
  <span class="muted">{hoverTime ?? "Latest"}</span>
  {#each legend as l (l.label)}<span><i style:background={l.color}></i>{l.label}: <span class="mono">{l.text}</span></span>{/each}
</div>
<div bind:this={el} style:height={`${height}px`} style:width="100%"></div>

<style>
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; }
  i { display: inline-block; width: 10px; height: 3px; margin-right: 4px; vertical-align: middle; }
</style>
