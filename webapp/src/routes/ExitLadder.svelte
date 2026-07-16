<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, money, agoFromIso, DASH } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  const VENUES = [
    { value: "", label: "All" },
    { value: "api", label: "API" },
    { value: "prop", label: "Prop" },
  ];
  let venue = $state("");
  let present = $state<boolean | null>(null);
  let summary = $state<any | null>(null);
  let records = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.exitLadderSoak(100);
      present = raw?.present ?? null;
      summary = raw?.summary ?? null;
      records = raw?.records ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  const shown = $derived(venue ? records.filter((r) => (r.venue ?? "") === venue) : records);
</script>

<section>
  <div class="head">
    <h2>Exit Ladder <span class="muted sub">· laddered-vs-single-target soak (observe-only)</span></h2>
    <Segmented options={VENUES} bind:value={venue} />
  </div>
  {#if error}
    <div class="err panel">Couldn't load exit-ladder soak: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if present === false || records.length === 0}
    <div class="panel pad muted">No exit-ladder soak rows yet — empty until the first live opening order writes one.</div>
  {:else}
    {#if summary}
      <div class="panel pad recap muted">
        {num(summary.total_scanned)} orders soaked ·
        {num(summary.differing)} differ from the single target ({num(summary.differing_pct, 1)}%)
        {#if summary.by_venue}· venues: {Object.entries(summary.by_venue).map(([k, v]) => `${k} ${v}`).join(" · ")}{/if}
      </div>
    {/if}
    <div class="panel scroll">
      <table>
        <thead><tr><th>Symbol</th><th>Venue</th><th class="r">Qty</th><th>Single SL/TP</th><th>Ladder rungs</th><th>Differs</th><th>When</th></tr></thead>
        <tbody>
          {#each shown as r, i (r.id ?? i)}
            <tr>
              <td class="sym">{r.symbol ?? DASH}</td>
              <td class="muted">{r.venue ?? DASH}</td>
              <td class="r mono">{r.qty == null ? DASH : num(r.qty, 4)}</td>
              <td class="mono">{money(r.single_sl ?? r.sl)} / {money(r.single_tp ?? r.tp)}</td>
              <td class="mono">{Array.isArray(r.ladder ?? r.rungs) ? (r.ladder ?? r.rungs).length : (r.rung_count ?? DASH)}</td>
              <td class={r.differs_from_single_target ? "neg" : "muted"}>{r.differs_from_single_target ? "yes" : "no"}</td>
              <td class="muted">{agoFromIso(r.timestamp ?? r.ts ?? r.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .recap { font-size: 13px; }
  .pad { padding: 14px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .neg { color: var(--neg); }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
