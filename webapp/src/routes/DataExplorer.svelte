<script lang="ts">
  import ExplorerOverview from "../components/ExplorerOverview.svelte";
  import ResearchCatalog from "../components/ResearchCatalog.svelte";
  import ExplorerTrades from "../components/ExplorerTrades.svelte";
  import ExplorerSignals from "../components/ExplorerSignals.svelte";
  import ExplorerPackages from "../components/ExplorerPackages.svelte";
  import RawTables from "../components/RawTables.svelte";

  // Importance order, per the operator: structured data leads, ALL tables last
  // but always reachable. Only the active tab is mounted, so a tab fetches
  // nothing until it is opened.
  const TABS = [
    { id: "overview", label: "Overview" },
    { id: "research", label: "Research catalog" },
    { id: "trades", label: "Trades" },
    { id: "signals", label: "Signals" },
    { id: "packages", label: "Order packages" },
    { id: "tables", label: "All tables" },
  ] as const;
  type TabId = (typeof TABS)[number]["id"];

  const LS = "ict.explorer.tab";
  function initial(): TabId {
    try {
      const v = localStorage.getItem(LS);
      if (TABS.some((t) => t.id === v)) return v as TabId;
    } catch {
      /* storage blocked — default tab */
    }
    return "overview";
  }
  let tab = $state<TabId>(initial());
  // Deep link from the Overview's table rows into the raw browser.
  let target = $state<{ db: string; name: string } | null>(null);
  function openTable(db: string, name: string) {
    target = { db, name };
    pick("tables");
  }
  function pick(t: TabId) {
    tab = t;
    try {
      localStorage.setItem(LS, t);
    } catch {
      /* per-viewer convenience only */
    }
  }
</script>

<section>
  <h2>Data Explorer</h2>
  <div class="tabs" role="tablist">
    {#each TABS as t (t.id)}
      <button role="tab" aria-selected={tab === t.id} class:on={tab === t.id} onclick={() => pick(t.id)}>{t.label}</button>
    {/each}
  </div>
  {#if tab === "overview"}<ExplorerOverview onOpenTable={openTable} />
  {:else if tab === "research"}<ResearchCatalog />
  {:else if tab === "trades"}<ExplorerTrades />
  {:else if tab === "signals"}<ExplorerSignals />
  {:else if tab === "packages"}<ExplorerPackages />
  {:else}<RawTables initial={target} />{/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .tabs { display: flex; gap: 4px; overflow-x: auto; border-bottom: 1px solid var(--border); }
  .tabs button { background: none; border: none; border-bottom: 2px solid transparent; color: var(--muted); padding: 8px 12px; cursor: pointer; font-size: 13px; white-space: nowrap; }
  .tabs button.on { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
</style>
