<script lang="ts">
  // Operator decision u8 (2026-11-12): the features catalog gets "no check" —
  // just show "models missing from the catalog" as a number. Every figure here
  // is the bot's own (`/api/bot/catalog/features` → `coverage`); nothing is
  // recounted in the browser. A model missing from the catalog means the
  // CATALOG is behind (it lacks that model's features), not that the model is bad.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, DASH } from "../lib/format";

  let cat = $state<any>(null);
  let err = $state<string | null>(null);
  onMount(async () => {
    try { cat = await api.catalogFeatures(); }
    catch (e) { err = e instanceof Error ? e.message : String(e); }
  });
  const cov = $derived(cat?.coverage ?? null);
  const missing = $derived<string[]>(cov?.models_missing_from_catalog ?? []);
</script>

<div class="strip">
  <span class="lbl">Features catalog</span>
  {#if err}
    <span class="muted">not available (<span class="mono">{err}</span>)</span>
  {:else if !cat}
    <span class="muted">loading…</span>
  {:else if cat.read_state !== "read" || !cov}
    <span class="muted">not available ({cat.reason ?? cat.read_state ?? DASH})</span>
  {:else}
    <span class="kv" title="models whose features the catalog does not list (from the served + candidate model.json files)">
      Models missing from the catalog <b class="mono" class:warn={(cov.n_models_missing_from_catalog ?? 0) > 0}>{num(cov.n_models_missing_from_catalog)}</b>
    </span>
    <span class="kv" title="distinct model features the catalog does not list">Features missing <b class="mono">{num(cov.n_features_missing_from_catalog)}</b></span>
    <span class="kv muted">{num(cov.n_features)} catalogued · {num(cov.n_with_consumer)} in use · {num(cov.n_models_in_registry)} models on disk</span>
    {#if missing.length}<span class="muted small">missing: <span class="mono">{missing.join(", ")}</span></span>{/if}
  {/if}
</div>

<style>
  .strip { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: baseline; padding: 8px 12px; margin: 6px 0 10px;
    border: 1px solid var(--border); border-radius: 8px; font-size: 13px; }
  .lbl { font-weight: 600; }
  .kv b { margin-left: 4px; }
  .warn { color: #d4a017; }
  .small { font-size: 12px; }
</style>
