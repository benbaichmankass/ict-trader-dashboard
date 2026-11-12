<script lang="ts">
  import ModelGoodCalls from "../components/ModelGoodCalls.svelte";
  import ModelHistory from "../components/ModelHistory.svelte";
  import CatalogCoverage from "../components/CatalogCoverage.svelte";
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, agoFromIso, DASH } from "../lib/format";
  import ModelsTable from "../components/ModelsTable.svelte";
  import Segmented from "../components/Segmented.svelte";
  let view = $state("cards");

  let models = $state<any[]>([]);
  // 2026-11-09 ML-REGISTRY-CONSOLIDATE: slot (D1..D10) -> breed -> lineage card -> variants, from /api/bot/ml/registry `by_slot`.
  // null when the API predates the field: the flat list below is then the whole page.
  let bySlot = $state<Record<string, any> | null>(null);
  let showFlat = $state(false);
  const SLOT_TITLES: Record<string, string> = {
    D1: "Universe & book", D2: "Regime gate", D3: "Entry generation", D4: "Signal filter", D5: "Position aggregation",
    D6: "Bracket at entry", D7: "In-trade management", D8: "Exit now", D9: "Execution", D10: "Review & grading",
  };
  function slotKeys(bs: Record<string, any>): string[] {
    const known = Object.keys(SLOT_TITLES).filter((k) => k in bs);
    return [...known, ...Object.keys(bs).filter((k) => !(k in SLOT_TITLES))];
  }
  function chipClass(st: string): string {
    return st === "live" ? "pos" : st === "testing" || st === "shadow" ? "info" : "flat";
  }
  function byId(id: string): any { return models.find((m) => mid(m) === id); }
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  function normalize(raw: any): any[] {
    if (Array.isArray(raw)) return raw;
    return raw?.models ?? raw?.registry ?? raw?.records ?? raw?.rows ?? [];
  }
  // `m.id` dropped 2026-08-20: measured across all 95 live registry rows,
  // `model_id` is present on 95 and non-falsy on 95, `manifest.model_id` on 95,
  // and `id` on ZERO. It was an unreachable fallback — surfaced by
  // webapp/tests/api-contract.mjs on its first row-scoped run, which is the
  // checker doing its job on a read nobody had questioned.
  function mid(m: any): string { return m.model_id ?? m.manifest?.model_id ?? "?"; }
  // BL-20260820-SPA-MODELS-STAGE-READS-POISONED-STATUS (F-111).
  //
  // This chain used to read `m.stage ?? m.current_stage ?? m.status ??
  // m.manifest?.target_deployment_stage`. Measured against ALL 95 rows of the
  // live /api/bot/ml/registry on 2026-08-20: `stage` present on 0,
  // `current_stage` on 0, `status` on 95, `target_deployment_stage` on 95 — so
  // the chain ALWAYS short-circuited at `status`, which `experiments-runner`
  // rewrites `candidate -> candidate` on every nightly re-train (F-105) and
  // which reads `candidate` for 95 of 95 models. The SPA therefore labelled
  // all three LIVE advisory heads — btc-regime-15m-lgbm-fc-pcv-v2,
  // mes-regime-5m-lgbm-v2, sol-regime-15m-lgbm-fc-pcv-v2 — as `candidate`,
  // i.e. it displayed the fleet's most consequential distinction backwards.
  //
  // `status` is deliberately NOT in the chain any more, not merely demoted:
  // a fallback to a field known to be uniformly wrong is a fallback to a lie,
  // and it would silently take over again the moment the field above it went
  // missing. An absent stage renders "—", which is the honest value.
  //
  // Legacy 7-stage names alias onto the canonical 3-stage ladder
  // (candidate -> shadow -> advisory), matching ml.manifest.canonical_stage;
  // an unrecognised value passes through unchanged rather than being coerced.
  const STAGE_ALIASES: Record<string, string> = {
    research_only: "candidate",
    backtest_approved: "candidate",
    limited_live: "advisory",
    live_approved: "advisory",
  };
  function stage(m: any): string {
    const raw = m.target_deployment_stage ?? m.manifest?.target_deployment_stage ?? null;
    if (!raw) return "—";
    return STAGE_ALIASES[raw] ?? raw;
  }
  // `deployment_bucket` (LIVE / SHADOW / OFFLINE) is deliberately NOT shown
  // beside the stage. It looks like it would add "is this model actually
  // influencing orders?", but measured across all 95 live rows it is a pure
  // function of the canonical stage — advisory->LIVE 3, shadow->SHADOW 28,
  // candidate->OFFLINE 64, with ZERO disagreements. Rendering it would be a
  // second column carrying no information, and a helper written and never
  // read. Revisit only if a row ever disagrees (e.g. an advisory model with
  // `linked_strategies: []`), which is the case that would make it earn a
  // column.
  // ⚠️ REVISITED 2026-11-12 (UI-SPA lane): measured over all 106 live rows, 8 now
  // carry NO stage ("—") yet a deployment bucket — 5 LIVE, 3 SHADOW (overlays such
  // as overlay-td-v1, deployment_bucket LIVE via stage_from_config). The bucket
  // is no longer a function of the stage, so the Table view shows it as
  // "Deployed". The card view is unchanged.
  function desc(m: any): string { return m.description ?? m.manifest?.description ?? m.manifest?.notes ?? ""; }

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.mlRegistry();
      models = normalize(raw);
      bySlot = raw && !Array.isArray(raw) && raw.by_slot ? raw.by_slot : null;
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
  <h2>Models <span class="muted sub">· by decision slot · registry (candidate → shadow → advisory)</span></h2>
  <ModelGoodCalls />
  <CatalogCoverage />
  {#if error}
    <div class="err panel">Couldn't load models: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if models.length === 0}
    <div class="panel pad muted">No models in the registry.</div>
  {:else}
    <div class="viewtog"><Segmented options={[{ value: "cards", label: "Cards" }, { value: "table", label: "Table" }]} bind:value={view} /></div>
    {#if view === "table"}
      <ModelsTable {models} stageOf={stage} />
    {:else}
    {#if bySlot}
      {#each slotKeys(bySlot) as sk (sk)}
        {@const sl = bySlot[sk]}
        <div class="slot">
          <h3>{sk} <span class="muted sub">· {SLOT_TITLES[sk] ?? "Unassigned"}</span></h3>
          {#if sl.empty}
            <div class="panel pad muted small">no model yet</div>
          {:else}
            {#each Object.entries(sl.breeds as Record<string, any[]>) as [breed, cards] (breed)}
              <div class="breed muted">{breed}</div>
              {#each cards as card (card.lineage)}
                <div class="panel model">
                  <div class="mh static">
                    <span class="dot {chipClass(card.status)}"></span>
                    <span class="mname mono">{card.lineage}</span>
                    <span class="stage {chipClass(card.status)}">{card.status}</span>
                  </div>
                  <div class="mbody">
                    {#each card.variants as v (v.model_id)}
                      {@const row = byId(v.model_id)}
                      <div class="variant">
                        <span class="dot {chipClass(v.status)}"></span>
                        <span>{v.display_name}</span>
                        <span class="mono muted small">{v.model_id}</span>
                        <span class="stage {chipClass(v.status)}">{v.status}</span>
                        {#if v.consuming_accounts?.length}<span class="muted small">{v.consuming_accounts.join(", ")}</span>{/if}
                      </div>
                      {#if row && desc(row)}<div class="desc small muted">{desc(row)}</div>{/if}
                      {#if row}<ModelHistory {row} />{/if}
                    {/each}
                  </div>
                </div>
              {/each}
            {/each}
          {/if}
        </div>
      {/each}
      <button class="mh" onclick={() => (showFlat = !showFlat)}>
        <span class="mname">All registry rows ({models.length})</span><span class="chev muted">{showFlat ? "▾" : "▸"}</span>
      </button>
    {/if}
    {#if !bySlot || showFlat}
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
              <ModelHistory row={m} />
            </div>
          {/if}
        </div>
      {/each}
    </div>
    {/if}
  {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  h3 { margin: 6px 0 4px; font-size: 15px; }
  .slot { display: flex; flex-direction: column; gap: 6px; }
  .breed { font-size: 12px; text-transform: uppercase; margin-top: 4px; }
  .static { cursor: default; }
  .variant { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 13px; }
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
