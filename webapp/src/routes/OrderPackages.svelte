<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { sinceFor, WINDOW_OPTIONS, FUNDING_OPTIONS } from "../lib/nav";
  import { money, signClass, agoFromIso, DASH } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  let funding = $state("real");
  let win = $state("7d");
  let rows = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  function classOf(r: any): string {
    const c = (r.accountClass ?? "").toLowerCase();
    if (c === "prop") return "prop";
    if (c === "paper") return "paper";
    return "real";
  }

  async function load() {
    loading = true;
    error = null;
    try {
      if (funding === "prop") {
        rows = [];
        return;
      }
      const raw = await api.orderPackages({ since: sinceFor(win), includePaper: funding === "paper", limit: 200 });
      rows = (raw?.rows ?? []).filter((r: any) => classOf(r) === funding);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }
  $effect(() => { funding; win; load(); });
  onMount(load);
</script>

<section>
  <div class="head">
    <h2>Order Packages</h2>
    <div class="controls">
      <Segmented options={FUNDING_OPTIONS} bind:value={funding} />
      <Segmented options={WINDOW_OPTIONS} bind:value={win} />
    </div>
  </div>

  {#if error}
    <div class="err panel">Couldn't load order packages: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if rows.length === 0}
    <div class="muted pad">{funding === "prop" ? "Prop decisions come from the prop journal (Prop tab)." : "No order packages in this window."}</div>
  {:else}
    <div class="panel scroll">
      <table>
        <thead>
          <tr><th>Strategy</th><th>Symbol</th><th>Dir</th><th class="r">Entry</th><th class="r">SL</th><th class="r">TP</th><th>Status</th><th class="r">P&L</th><th>Claude</th><th>When</th></tr>
        </thead>
        <tbody>
          {#each rows as r (r.orderPackageId)}
            <tr>
              <td class="muted">{r.strategy ?? DASH}</td>
              <td class="sym">{r.symbol ?? DASH}</td>
              <td class={String(r.direction).toLowerCase() === "sell" || String(r.direction).toLowerCase() === "short" ? "neg" : "pos"}>
                {(r.direction ?? DASH).toString().toUpperCase()}
              </td>
              <td class="r mono">{money(r.entry)}</td>
              <td class="r mono">{money(r.sl)}</td>
              <td class="r mono">{money(r.tp)}</td>
              <td class="muted">{r.status ?? DASH}</td>
              <td class="r mono {signClass(r.pnl)}">{r.pnl == null ? DASH : money(r.pnl, { sign: true })}</td>
              <td>{r.claudeScore?.grade ?? DASH}</td>
              <td class="muted">{agoFromIso(r.createdAt)}</td>
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
