<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, agoFromIso, DASH } from "../lib/format";

  let models = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  function normalize(raw: any): any[] {
    if (Array.isArray(raw)) return raw;
    return raw?.models ?? raw?.registry ?? raw?.records ?? raw?.rows ?? [];
  }
  function mid(m: any): string { return m.model_id ?? m.manifest?.model_id ?? m.id ?? "?"; }
  function stage(m: any): string { return m.stage ?? m.current_stage ?? m.status ?? m.manifest?.target_deployment_stage ?? "—"; }
  function desc(m: any): string { return m.description ?? m.manifest?.description ?? m.manifest?.notes ?? ""; }

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.mlRegistry();
      models = normalize(raw);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function stageClass(s: string): string {
    const v = (s ?? "").toLowerCase();
    if (v === "advisory") return "pos";
    if (v === "shadow") return "info";
    if (v === "candidate") return "warn";
    return "flat";
  }
</script>

<section>
  <h2>Models <span class="muted sub">· ML registry (candidate → shadow → advisory)</span></h2>
  {#if error}
    <div class="err panel">Couldn't load models: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if models.length === 0}
    <div class="panel pad muted">No models in the registry.</div>
  {:else}
    <div class="list">
      {#each models as m, i (mid(m) + i)}
        {@const id = mid(m) + i}
        <div class="panel model">
          <button class="mh" onclick={() => (open = { ...open, [id]: !open[id] })}>
            <span class="dot {stageClass(stage(m))}"></span>
            <span class="mname mono">{mid(m)}</span>
            <span class="stage {stageClass(stage(m))}">{stage(m)}</span>
            <span class="chev muted">{open[id] ? "▾" : "▸"}</span>
          </button>
          {#if open[id]}
            <div class="mbody">
              {#if desc(m)}<div class="desc">{desc(m)}</div>{/if}
              {#if m.metrics}
                <div class="metrics">
                  {#each Object.entries(m.metrics) as [k, v]}
                    <span class="met"><span class="muted">{k}</span> {typeof v === "number" ? num(v as number, 3) : String(v)}</span>
                  {/each}
                </div>
              {/if}
              {#if m.manifest?.dataset}
                <div class="muted small">dataset: {m.manifest.dataset.family ?? DASH} · {m.manifest.dataset.symbol_scope ?? DASH} · {m.manifest.dataset.timeframe ?? DASH}</div>
              {/if}
              {#if m.created_at}<div class="muted small">registered {agoFromIso(m.created_at)}</div>{/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .model { overflow: hidden; }
  .mh { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 11px 14px; cursor: pointer; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; background: var(--muted); }
  .dot.pos { background: var(--pos); }
  .dot.info { background: var(--accent); }
  .dot.warn { background: #e0a800; }
  .mname { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; }
  .stage { font-size: 11px; text-transform: uppercase; }
  .stage.pos { color: var(--pos); }
  .stage.info { color: var(--accent); }
  .stage.warn { color: #e0a800; }
  .chev { font-size: 12px; }
  .mbody { padding: 0 14px 14px; display: flex; flex-direction: column; gap: 8px; }
  .desc { font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
  .metrics { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12.5px; }
  .met .muted { margin-right: 4px; }
  .small { font-size: 12px; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
