<script lang="ts">
  // Topics & insights (UI workplan §10 WORK-TOPIC-TAXONOMY + §6 INSIGHTS-LEDGER,
  // bot #24927 / #24919). A view of the Work tab.
  // - Topics: /api/bot/work/topics → each topic's open/total work rows, its
  //   subtopics, and (on expand) the row ids filed under it. Rows whose roadmap
  //   ref maps to no topic are shown as "Unmapped" with their refs — the gap is
  //   a to-do, not hidden.
  // - Insights: /api/bot/work/ledger → pipeline items with kind:"insight",
  //   grouped by topic, each with its links' live state. An empty ledger says
  //   how many insights exist in total (0 is a measured count here, read_state
  //   says whether the store was read).
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, DASH } from "../lib/format";

  let topics = $state<any>(null);
  let topicsErr = $state<string | null>(null);
  let ledger = $state<any>(null);
  let ledgerErr = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  onMount(async () => {
    api.workTopics().then((r) => (topics = r)).catch((e) => (topicsErr = e instanceof Error ? e.message : String(e)));
    api.workLedger().then((r) => (ledger = r)).catch((e) => (ledgerErr = e instanceof Error ? e.message : String(e)));
  });

  // row id → {topic, subtopic}; inverted for the expand lists
  const rowsBy = $derived.by(() => {
    const m = new Map<string, string[]>();
    for (const [id, r] of Object.entries<any>(topics?.rows ?? {})) {
      const k = `${r?.topic ?? ""}\u0000${r?.subtopic ?? ""}`;
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(id);
    }
    return m;
  });
  const insightsByTopic = $derived.by(() => {
    const m = new Map<string, any[]>();
    for (const it of ledger?.insights ?? []) {
      const t = it?.topic ?? "Unmapped";
      if (!m.has(t)) m.set(t, []);
      m.get(t)!.push(it);
    }
    return m;
  });
</script>

<section>
  <div class="panel card">
    <div class="ph">Topics</div>
    {#if topicsErr}
      <div class="err">Couldn't load topics: <span class="mono">{topicsErr}</span></div>
    {:else if !topics}
      <div class="muted">Loading…</div>
    {:else if topics.read_state && topics.read_state !== "measured"}
      <div class="err">Topic map unavailable: <span class="mono">{topics.read_state}</span></div>
    {:else}
      <div class="muted small">
        {num(topics.n_rows)} work rows · {num(topics.coverage?.n_mapped)} of {num(topics.coverage?.n_milestones)} milestones mapped to a topic
        {#if (topics.coverage?.milestones_without_topic ?? []).length} · without a topic: {topics.coverage.milestones_without_topic.join(", ")}{/if}
      </div>
      <table>
        <thead><tr><th>Topic / subtopic</th><th class="r">Open</th><th class="r">Total</th><th class="bar"></th></tr></thead>
        <tbody>
          {#each topics.topics ?? [] as t (t.topic)}
            <tr class="t" onclick={() => (open = { ...open, [t.topic]: !open[t.topic] })}>
              <td><span class="caret">{open[t.topic] ? "▾" : "▸"}</span> <b>{t.topic}</b></td>
              <td class="r mono">{num(t.n_open)}</td>
              <td class="r mono">{num(t.n_total)}</td>
              <td class="bar"><div class="track"><div class="fill" style:width={t.n_total ? `${(100 * (t.n_total - t.n_open)) / t.n_total}%` : "0"}></div></div></td>
            </tr>
            {#if open[t.topic]}
              {#each t.subtopics?.length ? t.subtopics : [{ subtopic: "", n_open: t.n_open, n_total: t.n_total }] as s (s.subtopic)}
                {@const ids = rowsBy.get(`${t.topic}\u0000${s.subtopic}`) ?? []}
                <tr class="s">
                  <td class="ind">{s.subtopic || (t.topic === "Unmapped" ? "no roadmap ref maps to a topic" : DASH)}
                    <div class="ids mono">{ids.slice(0, 40).join(" · ")}{ids.length > 40 ? ` · +${ids.length - 40} more` : ""}</div></td>
                  <td class="r mono">{num(s.n_open)}</td>
                  <td class="r mono">{num(s.n_total)}</td>
                  <td></td>
                </tr>
              {/each}
              {#if t.topic === "Unmapped" && topics.unmapped?.refs}
                <tr class="s"><td colspan="4" class="ind muted small">Unmapped refs: {Object.entries(topics.unmapped.refs).map(([k, v]) => `${k} ${v}`).join(" · ")}</td></tr>
              {/if}
            {/if}
          {/each}
        </tbody>
      </table>
      <div class="muted small">Bar = closed share (total − open) ÷ total.</div>
    {/if}
  </div>

  <div class="panel card">
    <div class="ph">Insights ledger</div>
    {#if ledgerErr}
      <div class="err">Couldn't load the ledger: <span class="mono">{ledgerErr}</span></div>
    {:else if !ledger}
      <div class="muted">Loading…</div>
    {:else if ledger.read_state === "store_unreadable"}
      <div class="err">The pipeline store could not be read — this is not "no insights".</div>
    {:else}
      <div class="muted small">
        {num(ledger.population?.n_shown)} of {num(ledger.population?.n_insights_total)} insight(s) · read_state {ledger.read_state ?? DASH}
        {#if ledger.n_unreadable_records} · {num(ledger.n_unreadable_records)} unreadable record(s){/if}
      </div>
      {#if !(ledger.insights ?? []).length}
        <div class="muted">No insights are filed yet. Lanes file one with <span class="mono">pipeline.py</span> and <span class="mono">kind: "insight"</span> plus a claim, population, provenance and links to the rows or units that came of it.</div>
      {:else}
        {#each [...insightsByTopic.entries()] as [topic, items] (topic)}
          <div class="grp"><b>{topic}</b> <span class="muted small">· {items.length}</span></div>
          {#each items as it (it.id)}
            <div class="ins">
              <div><span class="mono small muted">{it.id}</span> {it.claim ?? it.what ?? DASH}</div>
              <div class="muted small">
                population: {it.population ?? DASH} · provenance: {it.provenance ?? DASH} · outcome: {it.outcome ?? DASH}{it.subtopic ? ` · ${it.subtopic}` : ""}
              </div>
              {#if (it.links ?? []).length}
                <div class="small">{#each it.links as l, i (i)}<span class="link">{l.type}:{l.id} <span class="muted">({l.state ?? l.read_state ?? DASH})</span></span>{/each}</div>
              {/if}
            </div>
          {/each}
        {/each}
      {/if}
    {/if}
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .card { padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .ph { font-weight: 600; }
  .small { font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 8px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tr.t { cursor: pointer; border-top: 1px solid var(--border); }
  .r { text-align: right; white-space: nowrap; }
  .ind { padding-left: 26px; }
  .ids { font-size: 11px; color: var(--muted); overflow-wrap: anywhere; margin-top: 2px; }
  .caret { color: var(--muted); }
  .bar { width: 28%; }
  .track { height: 6px; background: var(--panel-2); border-radius: 3px; overflow: hidden; margin-top: 6px; }
  .fill { height: 100%; background: var(--pos); }
  .grp { margin-top: 6px; }
  .ins { padding: 6px 0 6px 12px; border-left: 2px solid var(--border); }
  .link { margin-right: 10px; }
  .err { color: var(--neg); }
</style>
