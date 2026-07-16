<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, DASH } from "../lib/format";

  let present = $state<boolean | null>(null);
  let sweeps = $state<any[]>([]);
  let mirrorAge = $state<number | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<Record<number, boolean>>({});

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.backtestSweeps(10);
      present = raw?.present ?? null;
      sweeps = raw?.sweeps ?? [];
      mirrorAge = raw?.mirror_age_seconds ?? null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  const mirrorDays = $derived(mirrorAge != null ? Math.floor(mirrorAge / 86400) : null);
</script>

<section>
  <h2>Backtesting <span class="muted sub">· trainer-VM strategy sweeps</span></h2>
  {#if error}
    <div class="err panel">Couldn't load sweeps: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if present === false || sweeps.length === 0}
    <div class="panel pad muted">No backtest sweeps mirrored yet.</div>
  {:else}
    {#if mirrorDays != null && mirrorDays > 7}
      <div class="panel pad warn">⚠ Sweep mirror is {mirrorDays} days old — the newest sweep may be stale (sweeps are operator-run on demand).</div>
    {/if}
    <div class="list">
      {#each sweeps as s, i (s.date ?? i)}
        <div class="panel sweep">
          <button class="sh" onclick={() => (open = { ...open, [i]: !open[i] })}>
            <span class="date mono">{s.date ?? DASH}</span>
            <span class="gen muted">generated {agoFromIso(s.generated_at)}</span>
            <span class="chev muted">{open[i] ? "▾" : "▸"}</span>
          </button>
          {#if open[i]}
            <div class="body">
              {#if s.summary_md}
                <pre class="md">{s.summary_md}</pre>
              {:else}
                <div class="muted">No SUMMARY.md for this run.</div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .pad { padding: 14px; }
  .warn { color: #e0a800; font-size: 13px; }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .sweep { overflow: hidden; }
  .sh { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 11px 14px; cursor: pointer; }
  .date { font-weight: 600; font-size: 13.5px; }
  .gen { flex: 1; font-size: 12px; }
  .chev { font-size: 12px; }
  .body { padding: 0 14px 14px; }
  .md { overflow-x: auto; font-size: 12px; margin: 0; white-space: pre; line-height: 1.45; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
