<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, num, agoFromIso, DASH } from "../lib/format";

  let data = $state<any | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      data = await api.gpuSpend();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  const budget = $derived(data?.budget_usd_per_month ?? null);
  const spent = $derived(data?.current_month_usd ?? null);
  const pct = $derived(
    budget && spent != null ? Math.min(100, Math.round((100 * spent) / budget)) : 0,
  );
  const runs = $derived(data?.runs ?? []);
  const overBudget = $derived(!!data?.over_budget);
</script>

<section>
  <h2>GPU Spend <span class="muted sub">· spot-GPU training cost vs the monthly cap</span></h2>
  {#if error}
    <div class="err panel">Couldn't load GPU spend: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if data?.present === false}
    <div class="panel pad muted">No GPU bursts recorded yet — free CPU work never appears here.</div>
  {:else}
    <div class="panel pad">
      <div class="row">
        <div class="metric">
          <span class="mlabel">This month ({data?.current_month ?? DASH})</span>
          <span class="mval {overBudget ? 'neg' : ''}">{spent == null ? DASH : money(spent)}</span>
        </div>
        <div class="metric"><span class="mlabel">Cap</span><span class="mval">{budget == null ? DASH : money(budget)}</span></div>
        <div class="metric"><span class="mlabel">Remaining</span><span class="mval">{data?.budget_remaining_usd == null ? DASH : money(data.budget_remaining_usd)}</span></div>
        <div class="metric"><span class="mlabel">Runs</span><span class="mval">{num(data?.current_month_runs)}</span></div>
      </div>
      <div class="bar"><div class="fill {overBudget ? 'over' : ''}" style:width={`${pct}%`}></div></div>
      {#if overBudget}<div class="alert neg">⚠ Over the monthly GPU budget.</div>{/if}
    </div>

    <div class="panel scroll">
      <div class="ph pad-h">Training-session burst costs</div>
      {#if runs.length === 0}
        <div class="muted pad">No burst runs.</div>
      {:else}
        <table>
          <thead><tr><th>Ended</th><th>Experiment</th><th>GPU</th><th class="r">GPU-hrs</th><th class="r">$/hr</th><th class="r">Cost</th><th class="r">Month cum.</th><th>Status</th></tr></thead>
          <tbody>
            {#each runs as r, i (r.run_id ?? i)}
              <tr>
                <td class="muted">{agoFromIso(r.ended_at)}</td>
                <td>{r.experiment ?? DASH}</td>
                <td class="muted">{r.gpu_type ?? DASH}</td>
                <td class="r mono">{r.gpu_hours == null ? DASH : num(r.gpu_hours, 2)}</td>
                <td class="r mono">{money(r.rate_usd_per_hour)}</td>
                <td class="r mono">{money(r.cost_usd)}</td>
                <td class="r mono">{money(r.cumulative_month_usd)}</td>
                <td class="muted">{r.status ?? DASH}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .pad { padding: 14px; }
  .pad-h { padding: 12px 14px 4px; }
  .ph { font-weight: 600; font-size: 13.5px; }
  .row { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 12px; }
  .metric { display: flex; flex-direction: column; gap: 3px; }
  .mlabel { font-size: 11.5px; color: var(--muted); }
  .mval { font-size: 18px; font-weight: 600; }
  .mval.neg { color: var(--neg); }
  .bar { height: 8px; background: var(--panel-2); border-radius: 5px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); }
  .fill.over { background: var(--neg); }
  .alert { margin-top: 10px; font-size: 13px; }
  .alert.neg { color: var(--neg); }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
