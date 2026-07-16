<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, DASH } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  const LEVELS = [
    { value: "", label: "All" },
    { value: "info", label: "Info" },
    { value: "warn", label: "Warn" },
    { value: "error", label: "Error" },
    { value: "trade", label: "Trade" },
  ];
  let level = $state("");
  let rows = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.logs({ limit: 200, level: level || undefined });
      rows = Array.isArray(raw) ? raw : (raw?.logs ?? raw?.entries ?? []);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }
  $effect(() => { level; load(); });
  onMount(load);

  function lvlClass(l: string): string {
    const v = (l ?? "").toLowerCase();
    if (v === "error" || v === "critical") return "neg";
    if (v === "warn" || v === "warning") return "warn";
    if (v === "trade") return "pos";
    return "flat";
  }
</script>

<section>
  <div class="head">
    <h2>Logs</h2>
    <Segmented options={LEVELS} bind:value={level} />
  </div>
  {#if error}
    <div class="err panel">Couldn't load logs: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if rows.length === 0}
    <div class="muted pad">No log entries in this filter.</div>
  {:else}
    <div class="feed panel">
      {#each rows as r, i (r.id ?? i)}
        <div class="lr">
          <span class="lvl {lvlClass(r.level)}">{(r.level ?? DASH).toString().toUpperCase()}</span>
          <span class="msg">{r.message ?? r.msg ?? r.text ?? JSON.stringify(r)}</span>
          <span class="muted when">{agoFromIso(r.timestamp ?? r.ts ?? r.time)}</span>
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  h2 { margin: 0; font-size: 18px; }
  .feed { display: flex; flex-direction: column; }
  .lr { display: flex; align-items: baseline; gap: 10px; padding: 7px 12px; border-bottom: 1px solid var(--border); font-size: 12.5px; }
  .lr:last-child { border-bottom: none; }
  .lvl { font-size: 10.5px; font-weight: 600; width: 46px; flex-shrink: 0; }
  .lvl.neg { color: var(--neg); }
  .lvl.warn { color: #e0a800; }
  .lvl.pos { color: var(--pos); }
  .lvl.flat { color: var(--muted); }
  .msg { flex: 1; font-family: var(--mono, monospace); white-space: pre-wrap; word-break: break-word; }
  .when { font-size: 11px; flex-shrink: 0; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
