<script lang="ts">
  // Work → Gates (bot PR #25354 § "Work queue tabs (SPA)", Tab 4): "The Work page's
  // Gates tab is a link to the Admin panel, not a second copy." So this is a
  // summary card of the route's OWN counts (GET /api/bot/gates?sort=attention,
  // bot #25551) and a link; deciding happens on Admin → Gates.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { gotoDetail } from "../lib/nav";
  import { ATTENTION_LABEL, dash, type GatesResponse } from "../lib/gates";

  let resp = $state<GatesResponse | null>(null);
  let err = $state<string | null>(null);
  onMount(async () => {
    try { resp = await api.gates({ sort: "attention" }); }
    catch (e) { err = e instanceof Error ? e.message : String(e); }
  });
  const c = $derived(resp?.counts ?? null);
</script>

<section class="wg">
  <h3>Gates <span class="muted sub">· every guard that can block a trade or a change, and your keep / remove / report-only call on it</span></h3>
  {#if err}
    <div class="na">Gates: not available (<span class="mono">{err}</span>)</div>
  {:else if !resp}
    <div class="muted">Loading…</div>
  {:else if resp.readState !== "read"}
    <div class="na">Gates: not available ({dash(resp.readState)}{resp.error ? `: ${resp.error}` : ""})</div>
  {:else}
    <div class="grid">
      <div class="stat"><span class="k">Waiting on you</span><b>{dash(c?.by_decision?.undecided)}</b><span class="muted small">of {dash(resp.population?.total)} gates</span></div>
      <div class="stat"><span class="k">With an audit recommendation</span><b>{dash(c?.recommendation_acceptable)}</b></div>
      <div class="stat" class:alert={(c?.drift ?? 0) > 0}><span class="k">Drift</span><b>{dash(c?.drift)}</b></div>
      <div class="stat" class:alert={(c?.unregistered ?? 0) > 0}><span class="k">Unregistered</span><b>{dash(c?.unregistered)}</b></div>
    </div>
    <div class="ranks">
      {#each Object.entries(c?.by_attention_rank ?? {}) as [k, v] (k)}
        <span class="chip">rank {k} · {ATTENTION_LABEL[k] ?? k} <b>{dash(v)}</b></span>
      {:else}<span class="muted small">attention ranks: —</span>{/each}
    </div>
  {/if}
  <button class="go" onclick={() => gotoDetail("Admin", "Gates")}>Open Admin → Gates to decide →</button>
  <div class="muted small">Deciding — one gate at a time, or "accept the recommendation for every waiting gate shown" — happens on the Admin panel, in the route's attention order (real money with no authorization on record first).</div>
</section>

<style>
  .wg { display: flex; flex-direction: column; gap: 10px; }
  h3 { margin: 0; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  .grid { display: flex; flex-wrap: wrap; gap: 10px; }
  .stat { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; min-width: 140px; }
  .stat b { font-size: 20px; }
  .stat .k { color: var(--muted); font-size: 12px; }
  .stat.alert b { color: #e5484d; }
  .ranks { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border); }
  .go { align-self: flex-start; background: var(--panel-2); color: var(--text); border: 1px solid var(--accent, #4c8dff); border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 13px; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
</style>
