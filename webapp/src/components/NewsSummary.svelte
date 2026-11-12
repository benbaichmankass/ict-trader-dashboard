<script lang="ts">
  // News-layer sentiment summary (UI-REDESIGN-2026-11, STRATEGIES & MODELS: "News
  // layer stays, plus a summary: current model sentiment, its average over the past
  // week and month, and what decisions/impact it had").
  //
  // Source: /api/bot/news/recent (capped at 500 records bot-side). Sentiment = each
  // decision's `adjustment`. A window the records do not fully cover is NOT averaged
  // over what happens to be there: it says how far back the data reaches instead.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { DASH, agoFromIso } from "../lib/format";

  let recs = $state<any[]>([]);
  let error = $state<string | null>(null);
  let loaded = $state(false);

  onMount(async () => {
    try {
      const r = await api.news(500);
      recs = ((r?.records ?? []) as any[]).filter((x) => x?.ts && Number.isFinite(Date.parse(x.ts)));
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { loaded = true; }
  });

  const DAY = 86_400_000;
  const oldest = $derived(recs.length ? Math.min(...recs.map((x) => Date.parse(x.ts))) : null);
  const latest = $derived(recs.length ? recs.reduce((a, b) => (Date.parse(b.ts) > Date.parse(a.ts) ? b : a)) : null);
  const coverDays = $derived(oldest == null ? 0 : (Date.now() - oldest) / DAY);

  function windowStats(days: number) {
    if (oldest == null) return null;
    const covered = coverDays >= days * 0.98;
    const since = Date.now() - days * DAY;
    const rows = recs.filter((x) => Date.parse(x.ts) >= since);
    const adj = rows.map((x) => x.adjustment).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    const count = (k: string) => rows.filter((x) => String(x.decision ?? "").toLowerCase() === k).length;
    return {
      covered,
      n: rows.length,
      avg: covered && adj.length ? adj.reduce((a, b) => a + b, 0) / adj.length : null,
      boost: count("boost"), reduce: count("reduce"), neutral: count("neutral"),
      veto: rows.filter((x) => x.veto === true).length,
    };
  }
  const windows = $derived([
    { label: "24h", w: windowStats(1) },
    { label: "7d", w: windowStats(7) },
    { label: "30d", w: windowStats(30) },
  ]);
  const fx = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? DASH : `${v >= 0 ? "+" : ""}${v.toFixed(3)}`);
</script>

<div class="panel ns">
  <div class="ph">News sentiment summary <span class="muted">· from the last {recs.length} news-layer decisions{oldest != null ? ` (back to ${agoFromIso(new Date(oldest).toISOString())})` : ""}</span></div>
  {#if error}
    <div class="err pad">could not look: <span class="mono">{error}</span></div>
  {:else if !loaded}
    <div class="muted pad">Loading…</div>
  {:else if !latest}
    <div class="muted pad">No news-layer decisions recorded.</div>
  {:else}
    <div class="now">
      <span class="k">Current</span>
      <b class="mono">{fx(latest.adjustment)}</b>
      <span>{latest.veto ? "veto" : (latest.decision ?? DASH)}</span>
      <span class="muted">{latest.symbol ?? DASH} · {agoFromIso(latest.ts)}</span>
    </div>
    <table>
      <thead><tr><th>Window</th><th class="r">Avg sentiment</th><th class="r">Decisions</th><th class="r">Boost</th><th class="r">Reduce</th><th class="r">Veto</th><th class="r">Neutral</th></tr></thead>
      <tbody>
        {#each windows as { label, w } (label)}
          <tr>
            <td><b>{label}</b></td>
            {#if w && w.covered}
              <td class="r mono">{fx(w.avg)}</td><td class="r mono">{w.n}</td><td class="r mono pos">{w.boost}</td><td class="r mono neg">{w.reduce}</td><td class="r mono neg">{w.veto}</td><td class="r mono muted">{w.neutral}</td>
            {:else}
              <td colspan="6" class="muted small">could not look — the route returns at most 500 decisions, which reach back only {coverDays.toFixed(1)} days</td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="muted small">Impact = the boost / reduce / veto decisions the layer made on actionable signals. A per-signal size change applied ("influence downsize") is not in this feed.</div>
  {/if}
</div>

<style>
  .ns { padding: 4px 12px 12px; }
  .ph { padding: 10px 0 6px; font-weight: 600; }
  .now { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; margin-bottom: 8px; font-size: 14px; }
  .k { color: var(--muted); font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-bottom: 6px; }
  th, td { padding: 5px 8px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); }
  tbody tr { border-bottom: 1px solid var(--border); }
  td.small { white-space: normal; }
  .r { text-align: right; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .pad { padding: 12px 0; }
  .err { color: var(--neg); }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
