<script lang="ts">
  // Performance reviews list (UI-REDESIGN-2026-11, PERFORMANCE: "list of performance
  // reviews, openable"). Source: the committed daily strategy-review record
  // (/api/bot/strategy-reviews — one review per UTC date, every leg graded). Each
  // date is a row; open it to see that day's verdicts. The denominator (graded) is
  // always shown, so a filtered view is never read as the whole fleet.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { DASH, agoFromIso } from "../lib/format";

  let index = $state<any>(null);
  let error = $state<string | null>(null);
  let open = $state<string | null>(null);
  let detail = $state<Record<string, any>>({});
  let actionableOnly = $state(true);
  let showAll = $state(false);

  onMount(async () => {
    try { index = await api.strategyReviews(); open = index?.utc_date ?? null; if (open) detail = { [open]: index }; }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
  });

  async function toggle(d: string) {
    open = open === d ? null : d;
    if (open && !detail[d]) {
      try { const r = await api.strategyReviews(d); detail = { ...detail, [d]: r }; }
      catch (e) { detail = { ...detail, [d]: { error: e instanceof Error ? e.message : String(e) } }; }
    }
  }
  const dates = $derived<string[]>((index?.available_dates ?? []) as string[]);
  const shown = $derived(showAll ? dates : dates.slice(0, 10));
  const rowsOf = (r: any) => ((r?.rows ?? []) as any[]).filter((x) => !actionableOnly || x?.actionable);
</script>

<div class="panel rv">
  <div class="ph">Performance reviews <span class="muted">· daily strategy-review record</span>
    <label class="tog"><input type="checkbox" bind:checked={actionableOnly} /> actionable only</label>
  </div>
  {#if error}
    <div class="err pad">Couldn't load reviews: <span class="mono">{error}</span></div>
  {:else if !index}
    <div class="muted pad">Loading…</div>
  {:else if !dates.length}
    <div class="muted pad">No committed reviews.</div>
  {:else}
    {#each shown as d (d)}
      {@const r = detail[d]}
      <button class="row" class:on={open === d} onclick={() => toggle(d)} aria-expanded={open === d}>
        <span>{open === d ? "▾" : "▸"} <b class="mono">{d}</b></span>
        {#if r && !r.error}
          <span class="muted">{r.graded ?? DASH} graded · <b class:hot={(r.actionable ?? 0) > 0}>{r.actionable ?? DASH} actionable</b> · {r.freshness ?? DASH}{r.generated_at ? ` · ${agoFromIso(r.generated_at)}` : ""}</span>
        {/if}
      </button>
      {#if open === d}
        <div class="body">
          {#if !r}
            <div class="muted small">Loading…</div>
          {:else if r.error}
            <div class="err small">could not look: <span class="mono">{r.error}</span></div>
          {:else}
            <div class="chips">{#each Object.entries(r.by_action ?? {}) as [k, n] (k)}<span class="chip">{k} <b>{n}</b></span>{/each}</div>
            {#if rowsOf(r).length}
              <div class="scroll">
                <table>
                  <thead><tr><th>Stage</th><th>Account</th><th>Strategy</th><th>Proposed</th><th>Disposition</th><th>Reason</th></tr></thead>
                  <tbody>
                    {#each rowsOf(r) as x, i (i)}
                      <tr class:act={x.actionable}>
                        <td class="mono">{x.stage ?? DASH}</td>
                        <td>{x.account ?? DASH}</td>
                        <td class="sym">{x.strategy ?? DASH}</td>
                        <td class="mono">{x.proposed_action ?? DASH}</td>
                        <td>{x.disposition ?? DASH}</td>
                        <td class="reason" title={x.reason ?? ""}>{x.reason ?? DASH}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <div class="muted small">{actionableOnly ? `No actionable rows (of ${r.graded ?? DASH} graded).` : "No rows."}</div>
            {/if}
          {/if}
        </div>
      {/if}
    {/each}
    {#if dates.length > 10}
      <button class="more" onclick={() => (showAll = !showAll)}>{showAll ? "Show fewer" : `Show all ${dates.length} reviews`}</button>
    {/if}
  {/if}
</div>

<style>
  .rv { padding: 4px 4px 8px; }
  .ph { padding: 10px 10px 6px; font-weight: 600; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .tog { margin-left: auto; font-weight: 400; font-size: 12px; display: inline-flex; gap: 4px; align-items: center; }
  .row { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; width: 100%; text-align: left; background: none; border: none; border-top: 1px solid var(--border); color: var(--text); padding: 8px 10px; cursor: pointer; font-size: 13px; }
  .row.on, .row:hover { background: var(--panel-2); }
  .hot { color: var(--neg); }
  .body { padding: 6px 10px 10px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
  .chip { border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px; font-size: 11px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 4px 8px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); }
  tr.act td { color: var(--text); font-weight: 600; }
  .reason { max-width: 420px; overflow: hidden; text-overflow: ellipsis; }
  .sym { font-weight: 600; }
  .more { display: block; width: 100%; text-align: left; background: none; border: none; border-top: 1px solid var(--border); color: var(--accent); cursor: pointer; font-size: 12.5px; padding: 8px 10px; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .pad { padding: 12px 10px; }
  .err { color: var(--neg); }
  .mono { font-variant-numeric: tabular-nums; }
</style>
