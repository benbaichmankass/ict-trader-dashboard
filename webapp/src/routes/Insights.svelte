<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso } from "../lib/format";

  interface Card {
    key: string;
    title: string;
    data: any | null;
  }
  let cards = $state<Card[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [summary, health] = await Promise.all([
        api.insight("summary").catch(() => null),
        api.insight("health").catch(() => null),
      ]);
      cards = [
        { key: "summary", title: "Book — Analyst read", data: summary },
        { key: "health", title: "Health — Analyst read", data: health },
      ];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
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
  <h2>Insights</h2>
  <p class="muted sub">AI-analyst narrative + grade (cache-only read; the bot's generator writes it).</p>
  {#if error}
    <div class="err panel">Couldn't load insights: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    {#each cards as c (c.key)}
      <div class="panel card">
        <div class="ch">
          <span class="ct">{c.title}</span>
          {#if c.data?.grade}<span class="grade {gradeClass(c.data.grade)}">{c.data.grade}</span>{/if}
          {#if c.data?.generated_at}<span class="when muted">{agoFromIso(c.data.generated_at)}</span>{/if}
        </div>
        {#if c.data?.cache_present === false}
          <div class="muted">No analyst read cached yet — the generator hasn't run.</div>
        {:else if c.data?.summary_md}
          <div class="md">{c.data.summary_md}</div>
        {:else}
          <div class="muted">—</div>
        {/if}
        {#if c.data?.signals?.length}
          <ul class="sig">
            {#each c.data.signals as s}<li>{typeof s === "string" ? s : (s.text ?? s.message ?? JSON.stringify(s))}</li>{/each}
          </ul>
        {/if}
      </div>
    {/each}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { margin: 0; font-size: 12px; }
  .card { padding: 14px; }
  .ch { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .ct { font-weight: 600; }
  .grade { font-size: 12px; }
  .grade.pos { color: var(--pos); }
  .grade.neg { color: var(--neg); }
  .grade.warn { color: #e0a800; }
  .when { margin-left: auto; font-size: 12px; }
  .md { white-space: pre-wrap; font-size: 13.5px; line-height: 1.5; }
  .sig { margin: 10px 0 0; padding-left: 18px; font-size: 13px; }
  .sig li { margin: 3px 0; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
