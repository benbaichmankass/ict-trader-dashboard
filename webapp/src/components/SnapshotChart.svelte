<script lang="ts">
  // Closed-trade CHART SNAPSHOT (UI-REDESIGN-2026-11 addenda 2, 3, 5; wire shape
  // trade_chart_snapshot/v1, bot #25205/#25216). The snapshot is built ONCE at close
  // and stored with the trade; this component only draws it:
  //   frame          → the view box (15% time / 10% price padding, bot-computed)
  //   candles        → candlesticks; indicators pane "price" → overlay lines
  //                    (other panes, e.g. rsi/atr, are listed with their last value)
  //   entry / exit   → markers at bar_ts
  //   brackets       → each level as a line over [from_ts, to_ts] (the final level
  //                    solid, earlier levels faint) + a marker at each update's bar_ts
  //   entry_signal   → marker at its bar_ts
  //   decisions      → LTR / Claude markers at bar_ts, coloured by disposition
  import { onMount } from "svelte";
  import { createChart, ColorType, LineStyle, type IChartApi, type SeriesMarker, type Time, type UTCTimestamp } from "lightweight-charts";
  import { toSec, snapTo, dispositionColor } from "../lib/chartTime";
  import { DASH } from "../lib/format";

  let { snap, height = 300 }: { snap: any; height?: number } = $props();

  let el: HTMLDivElement;
  let chart: IChartApi | null = null;
  const LINE_COLORS = ["#4c8dff", "#a06cd5", "#26a17b", "#d4a017"];
  const fmt = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(+v.toPrecision(7)) : DASH);

  const otherPanes = $derived(((snap?.indicators?.series ?? []) as any[]).filter((s) => s?.pane && s.pane !== "price").map((s) => {
    const pts = (s.points ?? []) as any[];
    return { name: s.name, last: pts.length ? pts[pts.length - 1]?.value : null };
  }));
  const decisions = $derived(((snap?.decisions?.markers ?? []) as any[]));

  function isDark() { return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true; }

  onMount(() => {
    const dark = isDark();
    chart = createChart(el, {
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: dark ? "#c9d1d9" : "#333" },
      grid: { vertLines: { color: dark ? "#2a2f36" : "#eee" }, horzLines: { color: dark ? "#2a2f36" : "#eee" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderVisible: false },
      autoSize: true,
    });
    const rows = ((snap?.candles?.rows ?? []) as any[]).filter((c) => c?.time != null && [c.open, c.high, c.low, c.close].every((v) => v != null && Number.isFinite(Number(v))))
      .map((c) => ({ time: Number(c.time) as UTCTimestamp, open: +c.open, high: +c.high, low: +c.low, close: +c.close }))
      .sort((a, b) => (a.time as number) - (b.time as number));
    const series = chart.addCandlestickSeries({ upColor: "#26a17b", downColor: "#e5484d", wickUpColor: "#26a17b", wickDownColor: "#e5484d", borderVisible: false });
    series.setData(rows);
    const times = rows.map((r) => r.time as number);

    // Frame: the bot's padded view box. Price: an invisible series spanning the frame's
    // low/high pins the autoscale; time: the visible range is set to the frame.
    const f = snap?.frame ?? {};
    const t0 = toSec(f.time_from), t1 = toSec(f.time_to);
    if (t0 != null && t1 != null && Number.isFinite(f.price_low) && Number.isFinite(f.price_high) && times.length) {
      const pin = chart.addLineSeries({ color: "rgba(0,0,0,0)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      pin.setData([{ time: times[0] as UTCTimestamp, value: f.price_low }, { time: times[times.length - 1] as UTCTimestamp, value: f.price_high }]);
    }

    // Price-pane indicators.
    let ci = 0;
    for (const s of ((snap?.indicators?.series ?? []) as any[])) {
      if (s?.pane !== "price") continue;
      const pts = ((s.points ?? []) as any[]).filter((p) => p?.value != null && p?.time != null && Number.isFinite(Number(p.time)) && Number.isFinite(Number(p.value))) // null is "no value", never 0
        .map((p) => ({ time: Number(p.time) as UTCTimestamp, value: Number(p.value) })).sort((a, b) => (a.time as number) - (b.time as number));
      if (!pts.length) continue;
      chart.addLineSeries({ color: LINE_COLORS[ci++ % LINE_COLORS.length], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: s.name }).setData(pts);
    }

    // Brackets: each level over its in-force span; the final (open-ended) level solid.
    for (const lv of ((snap?.brackets?.levels ?? []) as any[])) {
      if (!Number.isFinite(lv?.price) || !times.length) continue;
      const a = snapTo(toSec(lv.from_ts) ?? times[0], times), b = lv.to_ts == null ? times[times.length - 1] : snapTo(toSec(lv.to_ts) ?? times[times.length - 1], times);
      if (a == null || b == null || b < a) continue;
      const final = lv.to_ts == null;
      const tp = lv.kind === "tp";
      const color = tp ? (final ? "#26a17b" : "rgba(38,161,123,0.45)") : (final ? "#e5484d" : "rgba(229,72,77,0.45)");
      const ls = chart.addLineSeries({ color, lineWidth: final ? 2 : 1, lineStyle: final ? LineStyle.Solid : LineStyle.Dashed, priceLineVisible: false, lastValueVisible: final, crosshairMarkerVisible: false, title: final ? lv.kind.toUpperCase() : "" });
      ls.setData(a === b ? [{ time: a as UTCTimestamp, value: lv.price }] : [{ time: a as UTCTimestamp, value: lv.price }, { time: b as UTCTimestamp, value: lv.price }]);
    }

    // Markers.
    const marks: SeriesMarker<Time>[] = [];
    const at = (ts: unknown) => { const s = toSec(ts); return s == null ? null : snapTo(s, times); };
    const long = String(snap?.trade?.direction ?? "").toLowerCase().startsWith("l");
    const sig = snap?.entry_signal; const ts = sig ? at(sig.bar_ts ?? sig.decision_bar) : null;
    if (ts != null) marks.push({ time: ts as UTCTimestamp, position: long ? "belowBar" : "aboveBar", color: "#4c8dff", shape: long ? "arrowUp" : "arrowDown", text: `signal${sig.model_id ? ` · ${sig.model_id}` : ""}` });
    const en = snap?.entry ? at(snap.entry.bar_ts ?? snap.entry.ts) : null;
    if (en != null) marks.push({ time: en as UTCTimestamp, position: long ? "belowBar" : "aboveBar", color: "#e0a800", shape: long ? "arrowUp" : "arrowDown", text: `entry ${fmt(snap.entry.price)}` });
    const ex = snap?.exit ? at(snap.exit.bar_ts ?? snap.exit.ts) : null;
    if (ex != null) marks.push({ time: ex as UTCTimestamp, position: "inBar", color: "#8b93a3", shape: "circle", text: `exit ${fmt(snap.exit.price)}${snap.exit.reason ? ` (${snap.exit.reason})` : ""}` });
    for (const u of ((snap?.brackets?.updates ?? []) as any[])) {
      const t = at(u.bar_ts ?? u.ts); if (t == null) continue;
      const up = (u.to ?? 0) > (u.from ?? 0);
      marks.push({ time: t as UTCTimestamp, position: u.kind === "tp" ? "aboveBar" : up ? "belowBar" : "aboveBar", color: "#d4a017", shape: u.kind === "tp" ? "square" : up ? "arrowUp" : "arrowDown", text: `${String(u.kind).toUpperCase()} ${fmt(u.from)}→${fmt(u.to)}` });
    }
    for (const d of decisions) {
      const t = at(d.bar_ts ?? d.ts); if (t == null) continue;
      marks.push({ time: t as UTCTimestamp, position: "aboveBar", color: dispositionColor(d.disposition), shape: "square", text: `LTR ${d.action ?? DASH}${d.disposition ? ` · ${String(d.disposition).replace("_", "-")}` : ""}` });
    }
    marks.sort((a, b) => (a.time as number) - (b.time as number));
    series.setMarkers(marks);

    if (t0 != null && t1 != null) chart.timeScale().setVisibleRange({ from: t0 as UTCTimestamp, to: t1 as UTCTimestamp });
    else chart.timeScale().fitContent();
    return () => { chart?.remove(); chart = null; };
  });
</script>

<div bind:this={el} class="snapchart" style:height={`${height}px`}></div>
<div class="legend">
  {#if otherPanes.length}<span>{#each otherPanes as p, i (p.name)}{i ? " · " : ""}{p.name} last <b class="mono">{fmt(p.last)}</b>{/each}</span>{/if}
  <span>candles: {snap?.candles?.state ?? DASH}{snap?.candles?.source ? ` (${snap.candles.source})` : ""}</span>
  <span>brackets: {snap?.brackets?.read_state ?? DASH}{snap?.brackets?.tp_history ? ` · TP history ${snap.brackets.tp_history}` : ""}</span>
  <span>decisions: {decisions.length}{snap?.decisions?.read_state ? ` (${snap.decisions.read_state})` : ""}</span>
  {#if (snap?.frame?.levels_outside_frame ?? []).length}<span>{snap.frame.levels_outside_frame.length} level(s) outside the frame</span>{/if}
</div>

<style>
  .snapchart { width: 100%; }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--muted); font-size: 11px; margin-top: 4px; }
  .mono { font-variant-numeric: tabular-nums; }
</style>
