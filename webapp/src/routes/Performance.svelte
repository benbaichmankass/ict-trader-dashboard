<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Performance } from "../lib/api";
  import { WINDOW_OPTIONS } from "../lib/nav";
  import { money, pct, num, signClass, DASH } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";
  import EquityChart from "../components/EquityChart.svelte";

  let win = $state("30d");
  let perf = $state<Performance | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      perf = await api.performance(win);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      perf = null;
    } finally {
      loading = false;
    }
  }
  $effect(() => { win; load(); });
  onMount(load);
</script>

<section>
  <div class="head">
    <h2>Performance</h2>
    <Segmented options={WINDOW_OPTIONS} bind:value={win} />
  </div>

  {#if error}
    <div class="err panel">Couldn't load performance: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if perf}
    <div class="grid">
      <div class="metric panel"><div class="k">Trades</div><div class="v mono">{num(perf.totalTrades)}</div></div>
      <div class="metric panel"><div class="k">Win rate</div><div class="v mono">{pct(perf.winRate)}</div></div>
      <div class="metric panel"><div class="k">Net P&L</div><div class="v mono {signClass(perf.totalPnl)}">{money(perf.totalPnl, { sign: true })}</div></div>
      <div class="metric panel"><div class="k">Expectancy</div><div class="v mono {signClass(perf.expectancy)}">{money(perf.expectancy, { sign: true })}</div></div>
      <div class="metric panel"><div class="k">Profit factor</div><div class="v mono">{perf.profitFactor == null ? DASH : perf.profitFactor.toFixed(2)}</div></div>
      <div class="metric panel"><div class="k">Max drawdown</div><div class="v mono {signClass(perf.maxDrawdown)}">{money(perf.maxDrawdown)}</div></div>
    </div>

    {#if perf.equity && perf.equity.length > 1}
      <div class="panel card">
        <div class="ph">Equity curve — cumulative realised P&L</div>
        <EquityChart points={perf.equity} />
      </div>
    {/if}

    {#if perf.perStrategy && perf.perStrategy.length}
      <div class="panel card">
        <div class="ph">By strategy</div>
        <div class="scroll">
          <table>
            <thead><tr><th>Strategy</th><th class="r">Trades</th><th class="r">Win rate</th><th class="r">Net P&L</th><th class="r">Expectancy</th></tr></thead>
            <tbody>
              {#each [...perf.perStrategy].sort((a, b) => (b.totalPnl ?? 0) - (a.totalPnl ?? 0)) as s (s.name)}
                <tr>
                  <td class="sym">{s.name}</td>
                  <td class="r mono">{num(s.trades)}</td>
                  <td class="r mono">{pct(s.winRate)}</td>
                  <td class="r mono {signClass(s.totalPnl)}">{money(s.totalPnl, { sign: true })}</td>
                  <td class="r mono {signClass(s.expectancy)}">{money(s.expectancy, { sign: true })}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}

    {#if perf.perAssetClass && perf.perAssetClass.length}
      <div class="panel card">
        <div class="ph">By asset class</div>
        <div class="scroll">
          <table>
            <thead><tr><th>Asset class</th><th class="r">Trades</th><th class="r">Win rate</th><th class="r">Net P&L</th></tr></thead>
            <tbody>
              {#each perf.perAssetClass as a (a.assetClass)}
                <tr>
                  <td class="sym">{a.assetClass}</td>
                  <td class="r mono">{num(a.trades)}</td>
                  <td class="r mono">{pct(a.winRate)}</td>
                  <td class="r mono {signClass(a.totalPnl)}">{money(a.totalPnl, { sign: true })}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .metric { padding: 12px 14px; }
  .k { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
  .v { font-size: 20px; font-weight: 600; }
  .card { padding: 12px; }
  .ph { font-weight: 600; margin-bottom: 10px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
