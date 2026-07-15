<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type Position } from "../lib/api";
  import { money, signClass } from "../lib/format";
  import PositionsTable from "../components/PositionsTable.svelte";

  let positions = $state<Position[]>([]);
  let error = $state<string | null>(null);
  let timer: ReturnType<typeof setInterval> | null = null;

  async function load() {
    try {
      positions = await api.positions();
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }
  onMount(() => { load(); timer = setInterval(load, 30000); });
  onDestroy(() => { if (timer) clearInterval(timer); });

  // uPnL sum excludes legs with no measurement (null), never summed as 0.
  const upnl = $derived(
    positions.reduce((a, p) => a + (typeof p.unrealizedPnl === "number" ? p.unrealizedPnl : 0), 0),
  );
  const measured = $derived(positions.some((p) => typeof p.unrealizedPnl === "number"));
</script>

<section>
  <div class="head">
    <h2>Open positions</h2>
    <div class="upnl">
      <span class="muted">Total uPnL</span>
      <b class="mono {signClass(measured ? upnl : null)}">{measured ? money(upnl, { sign: true }) : "—"}</b>
    </div>
  </div>

  {#if error}
    <div class="err panel">Couldn't load positions: <span class="mono">{error}</span></div>
  {/if}

  <div class="panel">
    <PositionsTable {positions} />
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .upnl b { margin-left: 6px; font-size: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
