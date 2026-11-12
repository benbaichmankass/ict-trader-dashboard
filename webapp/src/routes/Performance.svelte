<script lang="ts">
  import Trades from "./Trades.svelte";
  import CategoryPerformance from "../components/CategoryPerformance.svelte";
  import PerformanceRange from "../components/PerformanceRange.svelte";
  import PerformanceReviews from "../components/PerformanceReviews.svelte";

  // One date range for the page: the range picker owns it, the category table follows it.
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  let start = $state(iso(new Date(Date.now() - 30 * 86_400_000)));
  let end = $state(iso(new Date()));
</script>

<section>
  <div class="head">
    <h2>Performance</h2>
  </div>

  <!-- UI-REDESIGN-2026-11 PERFORMANCE: book selector + start/end date range (replaces
       the window buttons), richer summary stats, breakdowns by strategy, asset class
       AND account. -->
  <PerformanceRange bind:start bind:end />

  <!-- Performance reviews = the weekly /performance-review outputs (AM-UI 2026-11-12). -->
  <PerformanceReviews />

  <!-- Per-category table (follows the page's start/end, bot #25241) + cumulative P&L
       (the series route takes a window, so the chart keeps its own 7d/30d/90d/All axis). -->
  <CategoryPerformance {start} {end} />

  <!-- The closed-trade log lives at the bottom of Performance (operator 2026-11-09; Activity tab retired). -->
  <div class="tradelog"><Trades /></div>
</section>


<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
</style>
