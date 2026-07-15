<script lang="ts">
  import { onMount } from "svelte";
  import { api, type ClosedTrade } from "../lib/api";
  import { sinceFor, WINDOW_OPTIONS, FUNDING_OPTIONS } from "../lib/nav";
  import { money, num, pct, signClass, DASH, agoFromIso } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  let funding = $state("real");
  let win = $state("7d");
  let rows = $state<ClosedTrade[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  function isPaper(t: ClosedTrade): boolean {
    return (t.accountClass ?? "").toLowerCase() === "paper";
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.closedTrades({ since: sinceFor(win), includePaper: funding === "paper", limit: 300 });
      rows = (raw ?? []).filter((t) => (funding === "paper" ? isPaper(t) : !isPaper(t)));
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }

  // Re-load whenever funding or window changes.
  $effect(() => {
    funding;
    win;
    load();
  });
  onMount(load);

  const stats = $derived.by(() => {
    const resolved = rows.filter((r) => r.pnl != null);
    const wins = resolved.filter((r) => (r.pnl ?? 0) > 0).length;
    const total = resolved.reduce((a, r) => a + (r.pnl ?? 0), 0);
    return {
      count: rows.length,
      resolved: resolved.length,
      winRate: resolved.length ? (wins / resolved.length) * 100 : null,
      total: resolved.length ? total : null,
    };
  });

  function dirLabel(t: ClosedTrade): string {
    const d = (t.direction ?? t.side ?? "").toLowerCase();
    if (d === "sell" || d === "short") return "SHORT";
    if (d === "buy" || d === "long") return "LONG";
    return DASH;
  }
</script>

<section>
  <div class="head">
    <h2>Trades</h2>
    <div class="controls">
      <Segmented options={FUNDING_OPTIONS} bind:value={funding} />
      <Segmented options={WINDOW_OPTIONS} bind:value={win} />
    </div>
  </div>

  <div class="summary">
    <div class="s"><span class="muted">Closed</span> <b class="mono">{num(stats.count)}</b></div>
    <div class="s"><span class="muted">Win rate</span> <b class="mono">{pct(stats.winRate)}</b></div>
    <div class="s"><span class="muted">Net P&L</span> <b class="mono {signClass(stats.total)}">{money(stats.total, { sign: true })}</b></div>
  </div>

  {#if error}
    <div class="err panel">Couldn't load trades: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if rows.length === 0}
    <div class="muted pad">No closed trades in this window.</div>
  {:else}
    <div class="panel scroll">
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Dir</th><th>Strategy</th><th class="r">Entry</th><th class="r">Exit</th><th class="r">P&L</th><th>Closed</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as t (t.id ?? `${t.symbol}-${t.closedAt}`)}
            <tr>
              <td class="sym">{t.symbol}</td>
              <td class={dirLabel(t) === "SHORT" ? "neg" : "pos"}>{dirLabel(t)}</td>
              <td class="muted">{t.strategy ?? DASH}</td>
              <td class="r mono">{money(t.entryPrice)}</td>
              <td class="r mono">{money(t.exitPrice)}</td>
              <td class="r mono {signClass(t.pnl)}">{money(t.pnl, { sign: true })}</td>
              <td class="muted">{agoFromIso(t.closedAt)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  h2 { margin: 0; font-size: 18px; }
  .controls { display: flex; gap: 8px; flex-wrap: wrap; }
  .summary { display: flex; gap: 20px; flex-wrap: wrap; }
  .s { font-size: 13px; }
  .s b { font-size: 16px; margin-left: 4px; }
  .scroll { overflow-x: auto; padding: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
