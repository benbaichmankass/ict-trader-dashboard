<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, DASH } from "../lib/format";

  let present = $state<boolean | null>(null);
  let records = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.news(50);
      present = raw?.present ?? null;
      records = raw?.records ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function decisionClass(d: string): string {
    const s = (d ?? "").toLowerCase();
    if (s.includes("veto")) return "neg";
    if (s.includes("boost")) return "pos";
    if (s.includes("reduce")) return "warn";
    return "flat";
  }
</script>

<section>
  <h2>News</h2>
  {#if error}
    <div class="err panel">Couldn't load news: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if present === false || records.length === 0}
    <div class="panel pad muted">
      The news layer isn't active yet (source-driven: <span class="mono">NEWS_SOURCE=rss</span>, or
      <span class="mono">newsapi</span> + a key). No decisions logged.
    </div>
  {:else}
    <div class="feed">
      {#each records as r, i (r.id ?? i)}
        <div class="panel item">
          <div class="row1">
            <span class="sym">{r.symbol ?? DASH}</span>
            <span class="badge {decisionClass(r.decision ?? r.action)}">{(r.decision ?? r.action ?? DASH).toString()}</span>
            {#if r.adjustment != null}<span class="adj muted">adj {Number(r.adjustment).toFixed(2)}</span>{/if}
            <span class="when muted">{agoFromIso(r.timestamp ?? r.ts)}</span>
          </div>
          {#if r.top_items && r.top_items.length}
            <div class="items">
              {#each r.top_items as it (it.url ?? it.headline)}
                <a class="hl" href={it.url} target="_blank" rel="noopener noreferrer">{it.headline}</a>
              {/each}
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
  .feed { display: flex; flex-direction: column; gap: 8px; }
  .item { padding: 12px 14px; }
  .row1 { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .sym { font-weight: 600; }
  .badge { font-size: 11px; border-radius: 6px; padding: 1px 8px; border: 1px solid var(--border); text-transform: uppercase; }
  .badge.pos { color: var(--pos); border-color: var(--pos); }
  .badge.neg { color: var(--neg); border-color: var(--neg); }
  .badge.warn { color: #e0a800; border-color: #e0a800; }
  .adj { font-size: 12px; }
  .when { margin-left: auto; font-size: 12px; }
  .items { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
  .hl { font-size: 13px; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
