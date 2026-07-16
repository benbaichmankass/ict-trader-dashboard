<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, DASH } from "../lib/format";

  let reports = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let selectedId = $state<string | null>(null);
  let html = $state<string | null>(null);
  let loadingBody = $state(false);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.reports();
      reports = raw?.reports ?? [];
      if (reports.length) open(reports[0].id);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function open(id: string) {
    selectedId = id;
    loadingBody = true;
    html = null;
    try {
      const raw = await api.report(id);
      html = raw?.html ?? null;
    } catch (e) {
      html = null;
    } finally {
      loadingBody = false;
    }
  }
  onMount(load);

  function gradeClass(g: string): string {
    const s = (g ?? "").toLowerCase();
    if (s.includes("good") || s === "🟢") return "pos";
    if (s.includes("concern") || s === "🔴") return "neg";
    return "warn";
  }
</script>

<section>
  <h2>Reports</h2>
  {#if error}
    <div class="err panel">Couldn't load reports: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if reports.length === 0}
    <div class="muted pad">No system reports yet.</div>
  {:else}
    <div class="split">
      <div class="list panel">
        {#each reports as r (r.id)}
          <button class="rowbtn" class:active={r.id === selectedId} onclick={() => open(r.id)}>
            <div class="r1">
              <span class="dot {gradeClass(r.roll_up_grade)}"></span>
              <span class="w">{r.window ?? DASH}</span>
              <span class="when muted">{agoFromIso(r.generated_at)}</span>
            </div>
            <div class="hl">{r.headline ?? DASH}</div>
          </button>
        {/each}
      </div>
      <div class="viewer panel">
        {#if loadingBody}
          <div class="muted pad">Loading report…</div>
        {:else if html}
          <iframe title="system report" srcdoc={html}></iframe>
        {:else}
          <div class="muted pad">Select a report.</div>
        {/if}
      </div>
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .split { display: grid; grid-template-columns: 300px 1fr; gap: 12px; }
  @media (max-width: 720px) { .split { grid-template-columns: 1fr; } }
  .list { padding: 6px; max-height: 70vh; overflow-y: auto; }
  .rowbtn { display: block; width: 100%; text-align: left; background: none; border: none; border-bottom: 1px solid var(--border); color: var(--text); padding: 10px; cursor: pointer; }
  .rowbtn.active { background: var(--panel-2); }
  .r1 { display: flex; align-items: center; gap: 8px; font-size: 12px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
  .dot.pos { background: var(--pos); }
  .dot.neg { background: var(--neg); }
  .dot.warn { background: #e0a800; }
  .w { font-weight: 600; }
  .when { margin-left: auto; }
  .hl { font-size: 13px; margin-top: 4px; }
  .viewer { padding: 0; overflow: hidden; }
  iframe { width: 100%; height: 70vh; border: 0; background: #fff; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
