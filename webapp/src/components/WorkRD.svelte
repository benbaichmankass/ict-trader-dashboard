<script lang="ts">
  // Work → R&D registry (bot PR #25354 § "Work queue tabs (SPA)", Tab 3). Backend:
  // bot #25561, GET /api/bot/research/registry?track=&stage=&q=&since=.
  // One card per idea with the REGISTRY's computed stage (+ reason), latest result,
  // test counts, next step. Views: ML ideas · strategy ideas · changed (the route's
  // server-side `changed` over a stated window). Filters (stage, search) are the
  // route's; every count is the route's. A count the registry could not read is null
  // with `counts_read_state` and renders "—" — never 0. The client never sets a stage.
  import { api } from "../lib/api";
  import { agoFromIso, num, DASH } from "../lib/format";

  const VIEWS = [
    { v: "ML", label: "ML ideas" },
    { v: "STRATEGY", label: "Strategy ideas" },
    { v: "changed", label: "Changed" },
  ];
  const WINDOWS = [
    { v: "1", label: "24h" },
    { v: "7", label: "7 days" },
    { v: "30", label: "30 days" },
  ];
  const SHOW = 60;

  let view = $state("ML");
  let stage = $state("");
  let qInput = $state("");
  let q = $state("");
  let win = $state("7");
  let shown = $state(SHOW);
  let open = $state<Record<string, boolean>>({});

  let status = $state<number | null>(null);
  let data = $state<any>(null);
  let err = $state<string | null>(null);
  let loading = $state(false);
  let seq = 0;

  function sinceFor(days: string): string {
    return new Date(Date.now() - Number(days) * 86_400_000).toISOString().slice(0, 16) + "Z";
  }
  async function load(v: string, st: string, qq: string, w: string) {
    const my = ++seq;
    loading = true;
    err = null;
    try {
      const r = await api.researchRegistry({
        track: v === "changed" ? undefined : v, stage: v === "changed" ? undefined : st || undefined,
        q: v === "changed" ? undefined : qq || undefined, since: v === "changed" ? sinceFor(w) : undefined,
      });
      if (my !== seq) return;
      status = r.status;
      data = r.status === 200 ? r.body : null;
    } catch (e) {
      if (my !== seq) return;
      status = null; data = null;
      err = e instanceof Error ? e.message : String(e);
    }
    loading = false;
  }
  $effect(() => { shown = SHOW; load(view, stage, q, win); });
  function search() { q = qInput.trim(); }

  const ideas = $derived<any[]>(Array.isArray(data?.ideas) ? data.ideas : []);
  const stages = $derived<any[]>(Array.isArray(data?.stages) ? data.stages : []);
  const stageLabel = (s: string) => stages.find((x) => x.stage === s)?.label ?? s;
  const perStage = $derived<Record<string, Record<string, number>>>(data?.summary?.per_stage_per_track ?? {});
  const changed = $derived(data?.changed ?? null);
  const stageCls = (s: string) =>
    s === "production" ? "prod" : s === "testing_book" || s === "shadow_advisory" ? "book" : s === "passed_waiting" ? "pass"
      : s === "failed" ? "fail" : s === "stuck" ? "stuck" : s === "retired" ? "ret" : "oth";
  const iso = (v: unknown) => (v ? String(v).slice(0, 10) : DASH);
</script>

<section class="rd">
  <h3>R&amp;D registry <span class="muted sub">· one card per idea, with the registry's own stage and why</span></h3>

  <div class="bar">
    {#each VIEWS as o (o.v)}<button class="tab" class:on={view === o.v} onclick={() => (view = o.v)}>{o.label}</button>{/each}
    {#if view === "changed"}
      <span class="muted small">in the last</span>
      {#each WINDOWS as w (w.v)}<button class="tab sm" class:on={win === w.v} onclick={() => (win = w.v)}>{w.label}</button>{/each}
    {:else}
      <select bind:value={stage} aria-label="Stage">
        <option value="">Any stage</option>
        {#each stages as s (s.stage)}<option value={s.stage}>{s.label}</option>{/each}
      </select>
      <input placeholder="Search id, name, reason…" bind:value={qInput} onkeydown={(e) => e.key === "Enter" && search()} />
      <button onclick={search}>Search</button>
      {#if q}<button class="link" onclick={() => { qInput = ""; q = ""; }}>clear "{q}"</button>{/if}
    {/if}
    {#if loading}<span class="muted small">loading…</span>{/if}
  </div>

  {#if err}
    <div class="na">R&amp;D registry: could not look (<span class="mono">{err}</span>)</div>
  {:else if status == null}
    <div class="muted">Loading…</div>
  {:else if status === 404}
    <div class="na">R&amp;D registry: not available yet — <span class="mono">GET /api/bot/research/registry</span> is not deployed (bot #25561).</div>
  {:else if status !== 200}
    <div class="na">R&amp;D registry: could not look (HTTP {status})</div>
  {:else if data?.present === false || (data?.readState && data.readState !== "read")}
    <div class="na">R&amp;D registry: not available ({data?.reason ?? data?.readState ?? DASH})</div>
  {:else}
    <div class="muted small">
      {num(data.summary?.ideas)} ideas · generated {data.generated_at ? agoFromIso(data.generated_at) : DASH}
      {#if data.servedFrom} · served from {data.servedFrom}{/if}{#if data.cache} · cache {data.cache}{/if}
    </div>
    {#if Object.keys(perStage).length}
      <div class="scroll">
        <table class="ps">
          <thead><tr><th>Stage (the registry's)</th>{#each Object.keys(perStage) as t (t)}<th class="r">{t}</th>{/each}</tr></thead>
          <tbody>
            {#each stages as s (s.stage)}
              <tr class:sel={stage === s.stage}><td>{s.label}</td>{#each Object.keys(perStage) as t (t)}<td class="r mono">{perStage[t]?.[s.stage] == null ? DASH : num(perStage[t][s.stage])}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}

    {#if view === "changed"}
      {#if !changed}
        <div class="na">No "changed" block in this answer.</div>
      {:else}
        <div class="muted small">{num(changed.count)} idea(s) changed since {changed.since ?? DASH} · {changed.basis ?? DASH}</div>
        <div class="scroll">
          <table>
            <thead><tr><th>Idea</th><th>Track</th><th>Stage</th><th>Latest verdict</th><th>Last activity</th></tr></thead>
            <tbody>
              {#each changed.items ?? [] as c (c.id)}
                <tr><td>{c.name ?? DASH} <span class="mono muted small">{c.id}</span></td><td>{c.track ?? DASH}</td>
                  <td><span class="st {stageCls(c.stage)}">{stageLabel(c.stage)}</span></td><td>{c.verdict ?? DASH}</td>
                  <td class="muted">{c.last_activity ? agoFromIso(c.last_activity) : DASH}</td></tr>
              {:else}<tr><td colspan="5" class="muted">Nothing changed in this window.</td></tr>{/each}
            </tbody>
          </table>
        </div>
      {/if}
    {:else}
      <div class="muted small">{num(data.matched)} matching</div>
      <div class="cards">
        {#each ideas.slice(0, shown) as i (i.id)}
          {@const lr = i.latest_result}
          <div class="card">
            <div class="ch">
              <span class="st {stageCls(i.stage)}">{i.stage_label ?? stageLabel(i.stage)}</span>
              <b class="nm">{i.name ?? DASH}</b>
            </div>
            <div class="muted small mono">{i.id}{i.programme ? ` · ${i.programme}` : ""}</div>
            {#if i.stage_reason}<div class="why small">Why: {i.stage_reason}</div>{/if}
            <div class="kv small">
              <span>Latest: {#if lr}<b>{lr.verdict ?? DASH}</b> · <span class="mono">{lr.unit ?? DASH}</span> · {iso(lr.date)} · n {lr.n == null ? DASH : num(lr.n)}{:else}{DASH}{/if}</span>
            </div>
            <div class="kv small">
              {#if i.counts}
                <span>Tests: {num(i.counts.units)} run · {num(i.counts.passed)} passed · {num(i.counts.failed)} failed · {num(i.counts.indeterminate)} indeterminate · {num(i.counts.open)} open{#if i.counts.blocked != null} · {num(i.counts.blocked)} blocked{/if}</span>
              {:else}
                <span>Tests: — <span class="muted">({i.counts_read_state ?? "not read"})</span></span>
              {/if}
            </div>
            <div class="kv small"><span>Next: {i.next_step ?? DASH}</span></div>
            <div class="muted small">Last activity: {i.last_activity ? agoFromIso(i.last_activity) : DASH}</div>
            {#if (i.open_units ?? []).length || lr?.note}
              <button class="link" onclick={() => (open = { ...open, [i.id]: !open[i.id] })}>{open[i.id] ? "▾ less" : "▸ more"}</button>
              {#if open[i.id]}
                {#if (i.open_units ?? []).length}<div class="small">Open units: <span class="mono">{i.open_units.join(", ")}</span></div>{/if}
                {#if lr?.note}<div class="small nt">{lr.note}</div>{/if}
                {#if lr?.population}<div class="muted small nt">{lr.population}</div>{/if}
              {/if}
            {/if}
          </div>
        {:else}
          <div class="muted">No ideas match.</div>
        {/each}
      </div>
      {#if ideas.length > shown}<button onclick={() => (shown += SHOW)}>Show more ({num(ideas.length - shown)} more)</button>{/if}
    {/if}
  {/if}
</section>

<style>
  .rd { display: flex; flex-direction: column; gap: 8px; }
  h3 { margin: 0; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  .bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  select, button, input { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  button { cursor: pointer; }
  .tab.on { border-color: var(--accent, #4c8dff); background: #4c8dff22; }
  .tab.sm { padding: 3px 8px; font-size: 12px; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); padding: 0; font-size: 12px; align-self: flex-start; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .ps { width: auto; }
  th, td { padding: 5px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px; }
  .r { text-align: right; }
  tr.sel td { background: var(--panel-2); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 8px; }
  .card { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 3px; }
  .ch { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .nm { overflow-wrap: anywhere; }
  .why { color: var(--text); }
  .nt { white-space: pre-wrap; overflow-wrap: anywhere; }
  .st { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; border: 1px solid var(--border); }
  .st.prod { color: #30a46c; border-color: #30a46c66; }
  .st.book { color: #4c8dff; border-color: #4c8dff66; }
  .st.pass { color: #2f9e8f; border-color: #2f9e8f66; }
  .st.fail { color: #e5484d; border-color: #e5484d66; }
  .st.stuck { color: #d4a017; border-color: #d4a01766; }
  .st.ret, .st.oth { color: var(--muted); }
</style>
