<script lang="ts">
  // Performance reviews (UI-REDESIGN-2026-11, PERFORMANCE: "list of performance
  // reviews, openable"; AM-UI: the weekly /performance-review outputs). Source:
  // GET /api/bot/performance/reviews (list) + /performance/reviews/{id} (content),
  // bot #25231. While the route 404s → "could not look". An empty list with
  // read_state "read" means "we looked and there are none".
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { DASH, agoFromIso } from "../lib/format";

  let idx = $state<any>(null);
  let rstate = $state("loading");
  let open = $state<string | null>(null);
  let content = $state<Record<string, { text: string | null; json: any; err: string | null } | undefined>>({});
  let showAll = $state(false);

  onMount(async () => {
    try {
      const r = await api.performanceReviews(100);
      if (r.status === 200 && r.body) { idx = r.body; rstate = r.body.read_state ?? "read"; }
      else rstate = r.status === 404 ? "missing" : `error ${r.status}`;
    } catch (e) { rstate = `error ${e instanceof Error ? e.message : String(e)}`; }
  });

  async function toggle(id: string) {
    open = open === id ? null : id;
    if (!open || content[id]) return;
    try {
      const r = await api.performanceReview(id);
      content = { ...content, [id]: r.status === 200
        ? { text: r.body?.content_text ?? null, json: r.body?.content_json ?? null, err: null }
        : { text: null, json: null, err: `${r.status} ${r.body?.detail?.error ?? r.body?.detail ?? ""}`.trim() } };
    } catch (e) {
      content = { ...content, [id]: { text: null, json: null, err: e instanceof Error ? e.message : String(e) } };
    }
  }
  const reviews = $derived(((idx?.reviews ?? []) as any[]));
  const shown = $derived(showAll ? reviews : reviews.slice(0, 10));
</script>

<div class="panel revs">
  <div class="rh">Performance reviews {#if idx}<span class="muted">· {idx.count ?? DASH} of {idx.total ?? DASH} · read_state {idx.read_state ?? DASH}</span>{/if}</div>
  {#if rstate === "loading"}
    <div class="muted">Loading…</div>
  {:else if rstate === "missing"}
    <div class="muted">could not look — the performance-review route is not deployed on the bot yet.</div>
  {:else if rstate.startsWith("error")}
    <div class="err">could not look: <span class="mono">{rstate}</span></div>
  {:else if idx?.read_state === "could_not_look"}
    <div class="muted">could not look — {(idx.sources ?? []).map((x: any) => `${x.source}: ${x.read_state}`).join(", ") || "no source readable"}</div>
  {:else if !reviews.length}
    <div class="muted">No performance reviews yet{idx?.read_state === "partial" ? " (some sources unreadable)" : ""}.</div>
  {:else}
    {#each shown as rv (rv.id)}
      <button class="row" class:on={open === rv.id} onclick={() => toggle(rv.id)} aria-expanded={open === rv.id}>
        <span>{open === rv.id ? "▾" : "▸"} <b>{rv.title ?? rv.id}</b></span>
        <span class="muted">{rv.kind ?? DASH}{rv.window_start || rv.window_end ? ` · ${rv.window_start ?? DASH} → ${rv.window_end ?? DASH}` : ""}{rv.stamp ? ` · ${agoFromIso(rv.stamp)}` : ""}</span>
      </button>
      {#if open === rv.id}
        <div class="body">
          {#if rv.summary}<div class="sum">{rv.summary}</div>{/if}
          {#if !content[rv.id]}
            <div class="muted small">Loading…</div>
          {:else if content[rv.id]?.err}
            <div class="err small">could not look: <span class="mono">{content[rv.id]?.err}</span></div>
          {:else if content[rv.id]?.text != null}
            <pre class="md">{content[rv.id]?.text}</pre>
          {:else}
            <pre class="md">{JSON.stringify(content[rv.id]?.json, null, 2)}</pre>
          {/if}
          <div class="muted small">{rv.path ?? ""}</div>
        </div>
      {/if}
    {/each}
    {#if reviews.length > 10}<button class="more" onclick={() => (showAll = !showAll)}>{showAll ? "Show fewer" : `Show all ${reviews.length}`}</button>{/if}
  {/if}
</div>

<style>
  .revs { padding: 8px 4px 8px; font-size: 13px; }
  .rh { font-weight: 600; padding: 4px 10px 6px; }
  .revs > .muted, .revs > .err { padding: 4px 10px; }
  .row { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; width: 100%; text-align: left; background: none; border: none; border-top: 1px solid var(--border); color: var(--text); padding: 8px 10px; cursor: pointer; font-size: 13px; }
  .row.on, .row:hover { background: var(--panel-2); }
  .body { padding: 6px 10px 10px; }
  .sum { margin-bottom: 6px; }
  .md { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; max-height: 480px; overflow: auto; background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; padding: 8px; margin: 0 0 4px; }
  .more { display: block; width: 100%; text-align: left; background: none; border: none; border-top: 1px solid var(--border); color: var(--accent); cursor: pointer; font-size: 12.5px; padding: 8px 10px; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .err { color: var(--neg); }
  .mono { font-variant-numeric: tabular-nums; }
</style>
