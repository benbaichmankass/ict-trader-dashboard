<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { PACKAGES_VIEW } from "../lib/explorerViews";
  import FacetTable from "./FacetTable.svelte";

  let rows = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.orderPackages({ includePaper: true, limit: 200 });
      rows = raw?.rows ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);
</script>

<FacetTable view={PACKAGES_VIEW} {rows} {loading} {error} onRefresh={load} note="most recent 200, all funding classes" />
