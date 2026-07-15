<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, num, pct, signClass, DASH } from "../lib/format";
  import StatusDot from "../components/StatusDot.svelte";

  interface Row {
    name: string;
    running: boolean;
    loaded: boolean;
    execution: string;
    trades: number | null;
    winRate: number | null;
    totalPnl: number | null;
    short: string | null;
    accounts: string[];
  }

  let rows = $state<Row[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let botRunning = $state<boolean | null>(null);

  function normalize(raw: any): Row[] {
    const list: any[] = Array.isArray(raw) ? raw : (raw?.strategies ?? []);
    return list.map((s) => ({
      name: s.name ?? s.id ?? "—",
      running: !!(s.running ?? s.runtime?.running),
      loaded: !!(s.loaded ?? s.runtime?.loaded),
      execution: s.execution ?? s.mode ?? "live",
      trades: s.trades ?? s.stats?.trades ?? null,
      winRate: s.winRate ?? s.stats?.winRate ?? null,
      totalPnl: s.totalPnl ?? s.stats?.totalPnl ?? null,
      short: s.description?.short ?? s.short ?? null,
      accounts: (s.accounts ?? []).map((a: any) => (typeof a === "string" ? a : a.id)).filter(Boolean),
    }));
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.strategies();
      botRunning = raw?.runtime?.bot_running ?? null;
      rows = normalize(raw).sort((a, b) => (b.totalPnl ?? 0) - (a.totalPnl ?? 0));
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function dot(r: Row): "pos" | "neg" | "warn" | "flat" {
    if (r.execution === "shadow") return "warn";
    if (r.running) return "pos";
    if (r.loaded) return "warn";
    return "flat";
  }
</script>

<section>
  <div class="head">
    <h2>Strategies</h2>
    {#if botRunning != null}
      <div class="run"><StatusDot status={botRunning ? "pos" : "neg"} label={botRunning ? "pipeline running" : "pipeline stopped"} /></div>
    {/if}
  </div>

  {#if error}
    <div class="err panel">Couldn't load strategies: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    <div class="panel scroll">
      <table>
        <thead><tr><th></th><th>Strategy</th><th>Exec</th><th class="r">Trades</th><th class="r">Win rate</th><th class="r">Net P&L</th></tr></thead>
        <tbody>
          {#each rows as r (r.name)}
            <tr>
              <td><StatusDot status={dot(r)} /></td>
              <td>
                <div class="sym">{r.name}</div>
                {#if r.short}<div class="sub muted">{r.short}</div>{/if}
              </td>
              <td class="muted">{r.execution}</td>
              <td class="r mono">{num(r.trades)}</td>
              <td class="r mono">{pct(r.winRate)}</td>
              <td class="r mono {signClass(r.totalPnl)}">{money(r.totalPnl, { sign: true })}</td>
            </tr>
          {/each}
          {#if rows.length === 0}
            <tr><td colspan="6" class="muted pad">No strategies reported.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .scroll { overflow-x: auto; padding: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; white-space: nowrap; }
  .sym { font-weight: 600; }
  .sub { font-size: 12px; max-width: 360px; white-space: normal; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
