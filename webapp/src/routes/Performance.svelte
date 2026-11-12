<script lang="ts">
  import Trades from "./Trades.svelte";
  import CategoryPerformance from "../components/CategoryPerformance.svelte";
  import PerformanceRange from "../components/PerformanceRange.svelte";
</script>

<section>
  <div class="head">
    <h2>Performance</h2>
  </div>

  <!-- UI-REDESIGN-2026-11 PERFORMANCE: book selector + start/end date range (replaces
       the window buttons), richer summary stats, breakdowns by strategy, asset class
       AND account. -->
  <PerformanceRange />

  <!-- Performance reviews = the weekly /performance-review outputs (AM-UI 2026-11-12).
       No list/fetch route yet (lane UI-SPA-BACKEND-ROUTES) → could not look. -->
  <div class="panel revs">
    <div class="rh">Performance reviews</div>
    <div class="muted">could not look — the weekly performance-review list route is being built (lane UI-SPA-BACKEND-ROUTES).</div>
  </div>

  <!-- Per-category table + cumulative P&L (UI workplan §4/§5). Own 7d/30d/90d/All axis: the routes 400 on 24h. -->
  <CategoryPerformance />

  <!-- The closed-trade log lives at the bottom of Performance (operator 2026-11-09; Activity tab retired). -->
  <div class="tradelog"><Trades /></div>
</section>


<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .revs { padding: 10px 12px; font-size: 13px; }
  .rh { font-weight: 600; margin-bottom: 4px; }
  .muted { color: var(--muted); }
</style>
