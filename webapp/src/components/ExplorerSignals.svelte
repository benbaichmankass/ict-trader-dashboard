<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { SIGNALS_VIEW } from "../lib/explorerViews";
  import FacetTable from "./FacetTable.svelte";

  let rows = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.signals();
      const list: any[] = Array.isArray(raw) ? raw : (raw?.signals ?? raw?.records ?? []);
      rows = list.filter((s) => s?.symbol);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);
</script>

<FacetTable view={SIGNALS_VIEW} {rows} {loading} {error} onRefresh={load} note="the host's recent-signals window" />
