<script lang="ts">
  import type { BotStats, Performance } from "../lib/api";
  import { money, pct, num, signClass } from "../lib/format";

  let { stats, perf, funding = "real" }: { stats: BotStats | null; perf: Performance | null; funding?: string } =
    $props();

  // Scope the metrics to the funding class — never blended. Real uses the
  // top-level (real-money) figures; paper uses the additive `paper` sub-block;
  // prop lives in its own journal (surfaced on the Prop tab), so it reads "—".
  const s = $derived(funding === "paper" ? (stats?.paper ?? null) : funding === "prop" ? null : stats);
  const p = $derived(funding === "paper" ? (perf?.paper ?? null) : funding === "prop" ? null : perf);
  const openTrades = $derived(
    funding === "paper" ? (stats?.paperOpenTrades ?? stats?.paper?.openTrades ?? null) : funding === "prop" ? null : stats?.openTrades,
  );
</script>

{#if funding === "prop"}
  <div class="propnote panel">Prop metrics live on the <b>Prop</b> tab (its own journal — never blended into real/paper).</div>
{/if}

<div class="grid">
  <div class="metric panel">
    <div class="k">Net P&L · 24h</div>
    <div class="v mono {signClass(s?.pnl24h)}">{money(s?.pnl24h, { sign: true })}</div>
  </div>
  <div class="metric panel">
    <div class="k">Total P&L</div>
    <div class="v mono {signClass(s?.totalPnL)}">{money(s?.totalPnL, { sign: true })}</div>
  </div>
  <div class="metric panel">
    <div class="k">Open trades</div>
    <div class="v mono">{num(openTrades)}</div>
  </div>
  <div class="metric panel">
    <div class="k">Win rate</div>
    <div class="v mono">{pct(s?.winRate)}</div>
  </div>
  <div class="metric panel">
    <div class="k">Profit factor</div>
    <div class="v mono">{p?.profitFactor == null ? "—" : p.profitFactor.toFixed(2)}</div>
  </div>
  <div class="metric panel">
    <div class="k">Max drawdown</div>
    <div class="v mono {signClass(p?.maxDrawdown)}">{money(p?.maxDrawdown)}</div>
  </div>
</div>

<style>
  .propnote {
    padding: 12px 14px;
    color: var(--muted);
    font-size: 13px;
    margin-bottom: 10px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px;
  }
  .metric {
    padding: 12px 14px;
  }
  .k {
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 6px;
  }
  .v {
    font-size: 22px;
    font-weight: 600;
  }
</style>
