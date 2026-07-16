<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, signClass, agoFromIso, num, DASH } from "../lib/format";

  let status = $state<any | null>(null);
  let reconcile = $state<any | null>(null);
  let tickets = $state<any[]>([]);
  let fills = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [st, rc, tk, fl] = await Promise.all([
        api.propStatus().catch(() => null),
        api.propReconcile().catch(() => null),
        api.propTickets(50).catch(() => null),
        api.propFills(50).catch(() => null),
      ]);
      status = st;
      reconcile = rc;
      tickets = tk?.tickets ?? [];
      fills = fl?.fills ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  const rd = $derived(status?.rule_distance ?? null);
  const dailyLeft = $derived(rd?.daily_loss_remaining ?? null);
  const ddLeft = $derived(rd?.static_dd_remaining ?? null);
  // Cushion severity: loud when a killer limit is close.
  function cushionClass(v: number | null): string {
    if (v == null) return "flat";
    if (v <= 25) return "neg";
    if (v <= 75) return "warn";
    return "pos";
  }
</script>

<section>
  <h2>Prop <span class="muted sub">· Breakout manual-bridge (isolated journal — never blended into real/paper)</span></h2>
  {#if error}
    <div class="err panel">Couldn't load prop journal: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    <!-- Rule-distance cushion -->
    <div class="panel pad">
      <div class="ph">Rule-distance cushion (account-killer limits)</div>
      {#if status?.present === false || rd == null}
        <div class="muted">No account-status snapshot yet — report a <span class="mono">bal</span> to compute the cushion.</div>
      {:else}
        <div class="grid2">
          <div class="metric {cushionClass(dailyLeft)}">
            <span class="mlabel">Daily-loss remaining</span>
            <span class="mval">{dailyLeft == null ? DASH : money(dailyLeft)}</span>
          </div>
          <div class="metric {cushionClass(ddLeft)}">
            <span class="mlabel">Static-DD cushion</span>
            <span class="mval">{ddLeft == null ? DASH : money(ddLeft)}</span>
          </div>
        </div>
        {#if (dailyLeft != null && dailyLeft <= 25) || (ddLeft != null && ddLeft <= 25)}
          <div class="alert neg">⚠ A killer limit is very close — the cushion is thin.</div>
        {/if}
      {/if}
    </div>

    <!-- Reconciliation -->
    {#if reconcile?.summary}
      <div class="panel pad">
        <div class="ph">Reconciliation</div>
        <div class="recon muted">
          {num(reconcile.summary.tickets_total)} tickets emitted ·
          {num(reconcile.summary.fills_total)} fills reported ·
          <span class={reconcile.summary.unacted_count > 0 ? "neg" : "pos"}>{num(reconcile.summary.unacted_count)} un-acted</span>
        </div>
        {#if reconcile.unacted_tickets?.length}
          <div class="unacted">
            {#each reconcile.unacted_tickets as t, i (t.ticket_id ?? i)}
              <div class="urow">
                <span class="sym">{t.symbol ?? DASH}</span>
                <span class={String(t.direction).toLowerCase() === "sell" ? "neg" : "pos"}>{(t.direction ?? DASH).toString().toUpperCase()}</span>
                <span class="muted">emitted {agoFromIso(t.created_at ?? t.emitted_at)}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Tickets -->
    <div class="panel scroll">
      <div class="ph pad-h">Outbound tickets</div>
      {#if tickets.length === 0}
        <div class="muted pad">No prop tickets emitted.</div>
      {:else}
        <table>
          <thead><tr><th>Symbol</th><th>Dir</th><th class="r">Entry</th><th class="r">SL</th><th class="r">TP</th><th>Status</th><th>When</th></tr></thead>
          <tbody>
            {#each tickets as t, i (t.ticket_id ?? i)}
              <tr>
                <td class="sym">{t.symbol ?? DASH}</td>
                <td class={String(t.direction).toLowerCase() === "sell" ? "neg" : "pos"}>{(t.direction ?? DASH).toString().toUpperCase()}</td>
                <td class="r mono">{money(t.entry_price ?? t.entry)}</td>
                <td class="r mono">{money(t.stop_loss ?? t.sl)}</td>
                <td class="r mono">{money(t.take_profit ?? t.tp)}</td>
                <td class="muted">{t.status ?? DASH}</td>
                <td class="muted">{agoFromIso(t.created_at ?? t.emitted_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <!-- Fills -->
    <div class="panel scroll">
      <div class="ph pad-h">Inbound fills / closes</div>
      {#if fills.length === 0}
        <div class="muted pad">No fills reported yet.</div>
      {:else}
        <table>
          <thead><tr><th>Symbol</th><th>Dir</th><th>Status</th><th class="r">Entry</th><th class="r">Exit</th><th class="r">P&L</th><th>When</th></tr></thead>
          <tbody>
            {#each fills as f, i (f.id ?? i)}
              <tr>
                <td class="sym">{f.symbol ?? DASH}</td>
                <td class={String(f.direction).toLowerCase() === "sell" ? "neg" : "pos"}>{(f.direction ?? DASH).toString().toUpperCase()}</td>
                <td class="muted">{f.status ?? DASH}</td>
                <td class="r mono">{money(f.entry_price)}</td>
                <td class="r mono">{money(f.exit_price)}</td>
                <td class="r mono {signClass(f.pnl)}">{f.pnl == null ? DASH : money(f.pnl, { sign: true })}</td>
                <td class="muted">{agoFromIso(f.created_at ?? f.reported_at)}</td>
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
  .ph { font-weight: 600; margin-bottom: 10px; font-size: 13.5px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .metric { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; }
  .mlabel { font-size: 11.5px; color: var(--muted); }
  .mval { font-size: 18px; font-weight: 600; }
  .metric.pos .mval { color: var(--pos); }
  .metric.neg .mval { color: var(--neg); }
  .metric.warn .mval { color: #e0a800; }
  .alert { margin-top: 10px; font-size: 13px; }
  .alert.neg { color: var(--neg); }
  .recon { font-size: 13px; }
  .unacted { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
  .urow { display: flex; gap: 10px; font-size: 13px; align-items: center; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pos { color: var(--pos); }
  .neg { color: var(--neg); }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
