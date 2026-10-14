<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { TRADES_VIEW } from "../lib/explorerViews";
  import FacetTable from "./FacetTable.svelte";

  const PAGE = 200; // the bot's own cap on /trades/closed
  let rows = $state<any[]>([]);
  let total = $state<number | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load(more = false) {
    loading = true;
    error = null;
    try {
      const r = await api.closedTradesPage({ includePaper: true, limit: PAGE, offset: more ? rows.length : 0 });
      rows = more ? [...rows, ...r.rows] : r.rows;
      total = r.total;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(() => load());
</script>

<FacetTable view={TRADES_VIEW} {rows} {loading} {error} {total} onRefresh={() => load()} onLoadMore={() => load(true)} note="all funding classes (real / paper / prop shown via Class)" />
