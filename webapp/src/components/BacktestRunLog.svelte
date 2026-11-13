<script lang="ts">
  // Backtesting → run log (operator spec 2026-11-09 S&M: "a log of every test run, its
  // result and what we did with it"). Backend: bot #25562,
  // GET /api/bot/research/runs?verdict=&what=&q=&since=&limit=&offset=.
  // "What we did" is COMPUTED BY THE BOT from links the units carry (follow-up units,
  // grading.disposition, retired_reason); `none_recorded` means "no link on the record",
  // NOT "nobody acted" — the route's own basis text is shown. Filters, counts and paging
  // are the route's.
  import { api } from "../lib/api";
  import { agoFromIso, num, DASH } from "../lib/format";

  const PAGE = 50;
  const WHAT = [
    { v: "", label: "Any" },
    { v: "acted", label: "Acted on" },
    { v: "recorded", label: "Recorded only" },
    { v: "none_recorded", label: "Nothing recorded" },
  ];
  const SINCE = [
    { v: "", label: "All time" },
    { v: "7", label: "7 days" },
    { v: "30", label: "30 days" },
  ];

  let verdict = $state("");
  let what = $state("");
  let since = $state("");
  let qInput = $state("");
  let q = $state("");
  let offset = $state(0);
  let open = $state<Record<string, boolean>>({});
  let status = $state<number | null>(null);
  let data = $state<any>(null);
  let err = $state<string | null>(null);
  let loading = $state(false);
  let seq = 0;

  async function load(v: string, w: string, si: string, qq: string, off: number) {
    const my = ++seq;
    loading = true;
    err = null;
    try {
      const r = await api.researchRuns({ verdict: v || undefined, what: w || undefined, q: qq || undefined,
        since: si ? new Date(Date.now() - Number(si) * 86_400_000).toISOString().slice(0, 10) : undefined, limit: PAGE, offset: off });
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
  let lastKey = "";
  $effect(() => {
    const k = `${verdict}|${what}|${since}|${q}`;
    if (k !== lastKey) { lastKey = k; if (offset !== 0) { offset = 0; return; } }
    load(verdict, what, since, q, offset);
  });
  function search() { q = qInput.trim(); }

  const runs = $derived<any[]>(Array.isArray(data?.runs) ? data.runs : []);
  const byVerdict = $derived<Record<string, number>>(data?.counts?.by_verdict ?? {});
  const byWhat = $derived<Record<string, number>>(data?.counts?.by_what_we_did ?? {});
  const hasMore = $derived(typeof data?.matched === "number" && offset + runs.length < data.matched);
  const whatCls = (s: string) => (s === "acted" ? "acted" : s === "recorded" ? "rec" : "none");
  const whatText = (s: string) => (s === "acted" ? "acted on" : s === "recorded" ? "recorded only" : s === "none_recorded" ? "nothing recorded" : s ?? DASH);
  const verdictCls = (v: string) => (v === "pass" ? "pass" : v === "fail" ? "fail" : "ind");
  const iso = (v: unknown) => (v ? String(v).slice(0, 10) : DASH);
</script>

<div class="rl panel">
  <div class="ph">Run log <span class="muted sub">· every test run that produced a verdict, newest first, and what was done with it</span></div>

  {#if err}
    <div class="na">Run log: could not look (<span class="mono">{err}</span>)</div>
  {:else if status == null}
    <div class="muted">Loading…</div>
  {:else if status === 404}
    <div class="na">Run log: not available yet — <span class="mono">GET /api/bot/research/runs</span> is not deployed (bot #25562). The trainer sweeps below are the older, on-demand record.</div>
  {:else if status !== 200}
    <div class="na">Run log: could not look (HTTP {status})</div>
  {:else if data?.present === false || data?.readState === "unreadable"}
    <div class="na">Run log: could not look ({data?.reason ?? data?.readState ?? DASH})</div>
  {:else}
    <div class="bar">
      <select bind:value={verdict} aria-label="Verdict">
        <option value="">Any verdict</option>
        {#each Object.entries(byVerdict) as [v, n] (v)}<option value={v}>{v} ({n})</option>{/each}
      </select>
      {#each WHAT as o (o.v)}
        <button class="tab" class:on={what === o.v} onclick={() => (what = o.v)}>{o.label}{#if o.v} <b>{byWhat[o.v] == null ? DASH : num(byWhat[o.v])}</b>{/if}</button>
      {/each}
      <select bind:value={since} aria-label="Since">{#each SINCE as o (o.v)}<option value={o.v}>{o.label}</option>{/each}</select>
      <input placeholder="Search id, title, theme, note…" bind:value={qInput} onkeydown={(e) => e.key === "Enter" && search()} />
      <button onclick={search}>Search</button>
      {#if q}<button class="link" onclick={() => { qInput = ""; q = ""; }}>clear "{q}"</button>{/if}
      {#if loading}<span class="muted small">loading…</span>{/if}
    </div>
    <div class="muted small">
      {num(data.matched)} matching of {num(data.total)} runs{runs.length ? ` · rows ${offset + 1}–${offset + runs.length}` : ""}
      {#if data.readState === "partial"} · <span class="warn">partial: {num((data.readErrors ?? []).length)} unit file(s) unreadable</span>{/if}
      · generated {data.generatedAt ? agoFromIso(data.generatedAt) : DASH}
    </div>
    {#if data.what_we_did_basis}<div class="muted small basis">What we did: {data.what_we_did_basis}</div>{/if}

    <div class="scroll">
      <table>
        <thead><tr><th>Run</th><th>Verdict</th><th>Graded</th><th>What we did</th></tr></thead>
        <tbody>
          {#each runs as r (r.id)}
            {@const w = r.what_we_did ?? {}}
            <tr class="row" onclick={() => (open = { ...open, [r.id]: !open[r.id] })}>
              <td><span class="mono id">{r.id}</span> <span class="muted small">{r.theme ?? ""}</span><div>{r.title ?? DASH}</div></td>
              <td><span class="v {verdictCls(r.verdict)}">{r.verdict ?? DASH}</span></td>
              <td class="muted small" title={`graded ${r.graded_at ?? "—"} · last activity ${r.last_activity ?? "—"}`}>{iso(r.graded_at ?? r.last_activity)}</td>
              <td><span class="w {whatCls(w.state)}">{whatText(w.state)}</span>
                {#if (w.follow_ups ?? []).length}<span class="muted small"> · {w.follow_ups.length} follow-up{w.follow_ups.length === 1 ? "" : "s"}</span>{/if}</td>
            </tr>
            {#if open[r.id]}
              <tr class="detail"><td colspan="4">
                {#if (w.follow_ups ?? []).length}
                  <div class="small"><b>Follow-up units</b></div>
                  <ul>{#each w.follow_ups as f, i (i)}<li class="small"><span class="mono">{f.id}</span> · {String(f.relation ?? DASH).replaceAll("_", " ")} · {f.status ?? DASH}{f.verdict ? ` · ${f.verdict}` : ""}{#if f.title}<div class="muted">{f.title}</div>{/if}</li>{/each}</ul>
                {/if}
                {#if w.disposition}<div class="small"><b>Disposition</b> <span class="muted">(prose)</span>: {w.disposition}</div>{/if}
                {#if w.retired_reason}<div class="small"><b>Retired</b> <span class="muted">(prose)</span>: {w.retired_reason}</div>{/if}
                {#if w.state === "none_recorded"}<div class="muted small">No follow-up, disposition or retirement is linked on the record. This does not mean nobody acted: an action outside the queue leaves no link.</div>{/if}
                {#if r.result_note}<div class="small nt"><b>Result</b>: {r.result_note}</div>{/if}
                {#if r.rule_id}<div class="muted small">Rule <span class="mono">{r.rule_id}</span> · status {r.status ?? DASH}</div>{/if}
              </td></tr>
            {/if}
          {:else}
            <tr><td colspan="4" class="muted">No runs match.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="pager">
      <button disabled={!offset || loading} onclick={() => (offset = Math.max(0, offset - PAGE))}>← Prev</button>
      <button disabled={!hasMore || loading} onclick={() => (offset += PAGE)}>Next →</button>
    </div>
    {#if data.trainer_sweeps}
      <div class="muted small">Trainer sweep mirror: {data.trainer_sweeps.read_state ?? DASH} · {data.trainer_sweeps.mirror_age_days == null ? DASH : `${data.trainer_sweeps.mirror_age_days} days old`} — {data.trainer_sweeps.note ?? ""}</div>
    {/if}
  {/if}
</div>

<style>
  .rl { padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .ph { font-weight: 600; }
  .sub { font-size: 12px; font-weight: 400; }
  .small { font-size: 12px; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .warn { color: #d4a017; }
  .basis { line-height: 1.4; }
  .bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  select, button, input { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  button { cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: default; }
  .tab.on { border-color: var(--accent, #4c8dff); background: #4c8dff22; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); padding: 0; font-size: 12px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px; }
  tr.row { cursor: pointer; }
  tr.row:hover { background: var(--panel-2); }
  tr.detail td { background: var(--panel-2); }
  .id { color: var(--muted); font-size: 12px; }
  .nt { white-space: pre-wrap; overflow-wrap: anywhere; }
  ul { margin: 4px 0; padding-left: 18px; }
  .v, .w { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; border: 1px solid var(--border); }
  .v.pass { color: #30a46c; border-color: #30a46c66; }
  .v.fail { color: #e5484d; border-color: #e5484d66; }
  .v.ind { color: #d4a017; border-color: #d4a01766; }
  .w.acted { color: #4c8dff; border-color: #4c8dff66; }
  .w.rec { color: var(--text); }
  .w.none { color: var(--muted); }
  .pager { display: flex; gap: 8px; }
</style>
