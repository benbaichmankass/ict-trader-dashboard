<script lang="ts">
  // "Why we entered" — the order package a trade was opened from (UI-REDESIGN-2026-11
  // (3) and addendum 2): strategy, model, decision bar, probabilities, confidence,
  // Claude score, contributing strategies, setup, TP intent, the indicators at
  // decision time, and the models that saw it. Shared by the open- and closed-trade
  // cards. Missing values render "—", never 0.
  import { DASH } from "../lib/format";

  let { pkg = null, pkgState = "—", modelScores = null }: { pkg?: any; pkgState?: string; modelScores?: any } = $props();

  const logic = $derived((pkg?.signalLogic ?? null) as any);
  const meta = $derived((pkg?.meta ?? {}) as any);
  const models = $derived.by(() => {
    const ms = modelScores ?? pkg?.modelScores;
    if (!ms || typeof ms !== "object") return [] as Array<{ id: string; stage: string; score: string }>;
    return Object.entries<any>(ms).map(([id, v]) => ({
      id, stage: v?.stage ?? DASH, score: v?.score != null && Number.isFinite(Number(v.score)) ? Number(v.score).toFixed(3) : DASH,
    }));
  });
  const features = $derived.by(() => {
    const f = logic?.features;
    if (!f || typeof f !== "object") return [] as Array<[string, string]>;
    return Object.entries<any>(f).map(([k, v]) => [k, typeof v === "number" && Number.isFinite(v) ? String(+v.toPrecision(4)) : v == null ? DASH : String(v)] as [string, string]);
  });
  const contributing = $derived(((logic?.contributing_strategies ?? logic?.aggregation?.contributing_strategies ?? []) as string[]).join(", "));
  const fx = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? String(+v.toFixed(d)) : v == null || v === "" ? DASH : String(v));
</script>

<div class="why">
  <div class="wt">Why we entered <span class="muted">· {pkgState}{pkg?.orderPackageId ? ` · ${pkg.orderPackageId}` : ""}</span></div>
  {#if pkg}
    <div class="kv">
      <span>Strategy <b>{logic?.strategy_name ?? pkg.strategy ?? DASH}</b></span>
      <span>Model <b class="mono">{logic?.model_id ?? DASH}</b></span>
      <span>Decision bar <b class="mono">{logic?.decision_bar ? String(logic.decision_bar).slice(0, 16).replace("T", " ") + "Z" : DASH}</b></span>
      <span>p(long) <b class="mono">{fx(logic?.p_long)}</b> · p(short) <b class="mono">{fx(logic?.p_short)}</b> · τ <b class="mono">{fx(logic?.tau)}</b></span>
      <span>Confidence <b class="mono">{fx(pkg.confidence ?? logic?.confidence, 2)}</b></span>
      <span>Claude score <b class="mono">{fx(pkg.claudeScore, 2)}</b></span>
      <span>Contributing <b>{contributing || DASH}</b>{logic?.aggregation?.resolution ? ` (${logic.aggregation.resolution})` : ""}</span>
      {#if meta.setup_type || meta.killzone || meta.bias}<span>Setup <b>{meta.setup_type ?? DASH}</b> · killzone <b>{meta.killzone ?? DASH}</b> · bias <b>{meta.bias ?? DASH}</b></span>{/if}
      {#if logic?.tp_intent || logic?.tp_basis}<span class="wide" title={logic?.tp_basis ?? ""}>TP intent <b>{logic?.tp_intent ?? DASH}</b>{logic?.tp_basis ? ` — ${logic.tp_basis}` : ""}</span>{/if}
    </div>
    {#if features.length}
      <div class="wsub">Indicators at decision time</div>
      <div class="chips">{#each features as [k, v] (k)}<span class="chip"><span class="muted">{k}</span> <span class="mono">{v}</span></span>{/each}</div>
    {/if}
  {/if}
  <div class="wsub">Models that saw it</div>
  {#if models.length}
    <div class="chips">{#each models as m (m.id)}<span class="chip"><span class="mono">{m.id}</span> <span class="muted">{m.stage}</span> <b class="mono">{m.score}</b></span>{/each}</div>
  {:else}
    <div class="muted small">{DASH}</div>
  {/if}
</div>

<style>
  .why { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; font-size: 12px; }
  .wt { font-weight: 600; margin-bottom: 4px; }
  .kv { display: flex; flex-wrap: wrap; gap: 4px 16px; }
  .kv .wide { flex-basis: 100%; overflow-wrap: anywhere; }
  .wsub { color: var(--muted); font-size: 11px; margin: 8px 0 3px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px; font-size: 11px; white-space: nowrap; }
  .muted { color: var(--muted); }
  .small { font-size: 11px; }
  .mono { font-variant-numeric: tabular-nums; }
</style>
