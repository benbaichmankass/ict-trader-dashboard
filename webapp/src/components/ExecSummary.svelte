<script lang="ts">
  import type { BotStats, Performance } from "../lib/api";
  import { money, pct, num, signClass } from "../lib/format";

  let { stats, perf }: { stats: BotStats | null; perf: Performance | null } = $props();
</script>

<div class="grid">
  <div class="metric panel">
    <div class="k">Net P&L · 24h</div>
    <div class="v mono {signClass(stats?.pnl24h)}">{money(stats?.pnl24h, { sign: true })}</div>
  </div>
  <div class="metric panel">
    <div class="k">Total P&L</div>
    <div class="v mono {signClass(stats?.totalPnL)}">{money(stats?.totalPnL, { sign: true })}</div>
  </div>
  <div class="metric panel">
    <div class="k">Open trades</div>
    <div class="v mono">{num(stats?.openTrades)}</div>
  </div>
  <div class="metric panel">
    <div class="k">Win rate</div>
    <div class="v mono">{pct(stats?.winRate)}</div>
  </div>
  <div class="metric panel">
    <div class="k">Profit factor · 7d</div>
    <div class="v mono">{perf?.profitFactor == null ? "—" : perf.profitFactor.toFixed(2)}</div>
  </div>
  <div class="metric panel">
    <div class="k">Max drawdown · 7d</div>
    <div class="v mono {signClass(perf?.maxDrawdown)}">{money(perf?.maxDrawdown)}</div>
  </div>
</div>

<style>
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
