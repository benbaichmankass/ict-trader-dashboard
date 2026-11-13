<script lang="ts">
  // Work → This week (bot PR #25354 § "Work queue tabs (SPA)", Tab 2) — lane cards +
  // filtered task rows. Backend: bot #25542.
  //   GET /api/bot/work/lanes?next_n=5 → one card per assistant manager: moved today ·
  //       working now · stuck · next (each {read_state, count, items}), headline (prose,
  //       null until the AM writes one), plus week_lanes totals. 404 until #25542 deploys.
  //   GET /api/bot/work/items?state=&owner_prefix=&week_lane=&q=&counts=1&latest_note=1
  //       → rows, `matched` (the filtered count), counts.by_owner_state, latest_note.
  // Every count is the route's; filtering is the route's. An older bot ignores the new
  // params and answers no `matched` — the view then says the filters were NOT applied
  // instead of presenting an unfiltered list as filtered.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, num, DASH } from "../lib/format";

  const PAGE = 50;
  const STATES = ["", "open", "in_flight", "blocked", "queued", "landed_unproven", "done", "dropped"];
  const SINCE = [
    { v: "", label: "Any time" },
    { v: "24h", label: "Changed in 24h" },
    { v: "7d", label: "Changed in 7d" },
  ];
  const LISTS: Array<{ key: string; label: string }> = [
    { key: "moved_today", label: "Moved today" },
    { key: "working_now", label: "Working now" },
    { key: "stuck", label: "Stuck" },
    { key: "next", label: "Next" },
  ];

  // ---- lane cards --------------------------------------------------------
  let lanes = $state<any>(null);
  let lanesStatus = $state<number | null>(null);
  let lanesErr = $state<string | null>(null);
  onMount(async () => {
    try {
      const r = await api.workLanes(5);
      lanesStatus = r.status;
      lanes = r.status === 200 ? r.body : null;
    } catch (e) { lanesErr = e instanceof Error ? e.message : String(e); }
  });
  const laneList = $derived<any[]>(Array.isArray(lanes?.lanes) ? lanes.lanes : []);
  const weekLanes = $derived<Record<string, any>>(lanes?.week_lanes ?? {});

  // ---- rows ----------------------------------------------------------------
  let stateF = $state(""); // "open" needs bot #25542 — an older bot reads it as a literal state (0 rows)
  let owner = $state("");
  let weekLane = $state("");
  let qInput = $state("");
  let q = $state("");
  let since = $state("");
  let due = $state(false);
  let offset = $state(0);
  let data = $state<any>(null);
  let err = $state<string | null>(null);
  let loading = $state(false);
  let open = $state<Record<string, boolean>>({});
  let seq = 0;

  function sinceIso(v: string): string | undefined {
    const h = v === "24h" ? 24 : v === "7d" ? 168 : 0;
    return h ? new Date(Date.now() - h * 3600_000).toISOString().replace(/\.\d+Z$/, "Z") : undefined;
  }
  async function load(st: string, ow: string, wl: string, qq: string, si: string, du: boolean, off: number) {
    const my = ++seq;
    loading = true;
    err = null;
    try {
      const r = await api.workItems({ state: st || undefined, ownerPrefix: ow || undefined, weekLane: wl || undefined,
        q: qq || undefined, since: sinceIso(si), due: du, counts: true, latestNote: true, limit: PAGE, offset: off });
      if (my !== seq) return;
      data = r;
    } catch (e) {
      if (my !== seq) return;
      data = null;
      err = e instanceof Error ? e.message : String(e);
    }
    loading = false;
  }
  let lastKey = "";
  $effect(() => {
    const k = `${stateF}|${owner}|${weekLane}|${q}|${since}|${due}`;
    if (k !== lastKey) {
      lastKey = k;
      if (offset !== 0) { offset = 0; return; }
    }
    load(stateF, owner, weekLane, q, since, due, offset);
  });
  function search() { q = qInput.trim(); }

  const items = $derived<any[]>(Array.isArray(data?.items) ? data.items : []);
  // The route answers `matched` on any extended read (state=open, owner/lane/text,
  // counts). Missing → this bot predates #25542 and did not apply those filters.
  const filtersApplied = $derived(data != null && typeof data.matched === "number");
  const hasMore = $derived(filtersApplied ? offset + items.length < data.matched : items.length === PAGE);
  const byOwnerState = $derived<Record<string, Record<string, number>>>(data?.counts?.by_owner_state ?? {});
  const countStates = $derived.by(() => {
    const s: string[] = [];
    for (const row of Object.values(byOwnerState)) for (const k of Object.keys(row)) if (!s.includes(k)) s.push(k);
    return s;
  });
  const amOptions = $derived(laneList.map((l) => l.am).filter((a: string) => a && a !== "other"));
  const noteOf = (it: any): { text: string; meta: string; isEvent: boolean } | null => {
    const ln = it?.latest_note;
    if (ln && typeof ln.note === "string" && ln.note.trim()) return { text: ln.note, meta: `${ln.by ?? DASH} · ${ln.at ? agoFromIso(ln.at) : DASH}`, isEvent: true };
    const n = it?.extra?.note;
    return typeof n === "string" && n.trim() ? { text: n, meta: "the row's own note", isEvent: false } : null;
  };
  const stateCls = (s: string) =>
    s === "in_flight" ? "fl" : s === "blocked" ? "bl" : s === "queued" ? "qu" : s === "landed_unproven" ? "lu" : s === "done" ? "dn" : "ot";
</script>

<section class="tw">
  <h3>This week <span class="muted sub">· one card per assistant manager, then the task rows</span></h3>

  <!-- Lane cards -->
  {#if lanesErr}
    <div class="na">Lane cards: could not look (<span class="mono">{lanesErr}</span>)</div>
  {:else if lanesStatus == null}
    <div class="muted">Loading lane cards…</div>
  {:else if lanesStatus === 404}
    <div class="na">Lane cards: not available yet — <span class="mono">GET /api/bot/work/lanes</span> is not deployed (bot #25542).</div>
  {:else if lanesStatus !== 200}
    <div class="na">Lane cards: could not look (HTTP {lanesStatus})</div>
  {:else if lanes?.read_state !== "read"}
    <div class="na">Lane cards: could not look ({lanes?.read_state ?? DASH}{lanes?.error ? `: ${lanes.error}` : ""})</div>
  {:else}
    <div class="muted small">Moved = a state change since {lanes.moved_since ?? DASH} · {num(lanes.population?.items)} items · {num(lanes.population?.lanes)} lanes · as of {lanes.as_of ? agoFromIso(lanes.as_of) : DASH}</div>
    {#if Object.keys(weekLanes).length}
      <div class="wl">
        {#each Object.entries(weekLanes) as [lane, t] (lane)}
          <span class="chip" title={Object.entries(t?.by_state ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}>{lane} <b>{num(t?.total)}</b>
            <span class="muted">({Object.entries(t?.by_state ?? {}).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(" · ")})</span></span>
        {/each}
      </div>
    {/if}
    <div class="cards">
      {#each laneList as l (l.am)}
        <div class="card">
          <div class="ch"><b>{l.am}</b> <span class="muted small">{num(l.open)} open</span>
            <button class="link" onclick={() => { owner = l.am === "other" ? "" : l.am; }} title="Filter the rows below to this AM">rows ↓</button></div>
          <div class="hl small">{#if l.headline}{l.headline}{:else}<span class="muted">— no headline written ({l.headline_read_state ?? DASH})</span>{/if}</div>
          {#each LISTS as L (L.key)}
            {@const b = l[L.key]}
            <div class="li">
              <div class="lt small">{L.label} <b>{b?.read_state === "read" ? num(b?.count) : DASH}</b>{#if b && b.read_state !== "read"} <span class="muted">({b?.read_state ?? DASH})</span>{/if}</div>
              {#each (b?.items ?? []).slice(0, 4) as it (it.id)}
                <div class="lrow small"><span class="st {stateCls(it.state)}">{(it.state ?? DASH).replaceAll("_", " ")}</span> <span class="mono id">{it.id}</span> {it.title ?? DASH}</div>
              {/each}
              {#if (b?.count ?? 0) > 4}<div class="muted small">+{num((b?.count ?? 0) - Math.min(4, (b?.items ?? []).length))} more</div>{/if}
            </div>
          {/each}
        </div>
      {/each}
    </div>
  {/if}

  <!-- Filters -->
  <div class="bar">
    <select bind:value={stateF} aria-label="State">
      {#each STATES as s (s)}<option value={s}>{s === "open" ? "Open (any non-terminal)" : s ? s.replaceAll("_", " ") : "Any state"}</option>{/each}
    </select>
    {#if amOptions.length}
      <select bind:value={owner} aria-label="Assistant manager">
        <option value="">Any AM</option>
        {#each amOptions as a (a)}<option value={a}>{a}</option>{/each}
      </select>
    {:else}
      <input class="sm" placeholder="AM prefix (e.g. AM-UI)" bind:value={owner} aria-label="AM prefix" />
    {/if}
    <select bind:value={weekLane} aria-label="Week lane">
      <option value="">Any week lane</option>
      {#each Object.keys(weekLanes).length ? Object.keys(weekLanes) : ["surge", "throttle", "standing"] as w (w)}<option value={w}>{w}</option>{/each}
    </select>
    <select bind:value={since} aria-label="Changed">
      {#each SINCE as o (o.v)}<option value={o.v}>{o.label}</option>{/each}
    </select>
    <label class="tog"><input type="checkbox" bind:checked={due} /> Due now</label>
    <input placeholder="Search id, title, note…" bind:value={qInput} onkeydown={(e) => e.key === "Enter" && search()} />
    <button onclick={search}>Search</button>
    {#if q}<button class="link" onclick={() => { qInput = ""; q = ""; }}>clear "{q}"</button>{/if}
    {#if loading}<span class="muted small">loading…</span>{/if}
  </div>

  {#if err}
    <div class="na">Work items: could not look (<span class="mono">{err}</span>)</div>
  {:else if !data}
    <div class="muted">Loading…</div>
  {:else if data.readState !== "read"}
    <div class="na">Work items: could not look ({data.readState ?? DASH}{data.error ? `: ${data.error}` : ""})</div>
  {:else}
    {#if !filtersApplied}
      <div class="warn small">
        This bot did not apply the state "open" / AM / week-lane / text filters (its <span class="mono">/work/items</span> predates
        bot #25542, so it answered no <span class="mono">matched</span>). The rows below are NOT filtered by them.
      </div>
    {/if}
    <div class="muted small">
      {#if filtersApplied}{num(data.matched)} matching · {/if}{items.length ? `rows ${offset + 1}–${offset + items.length}` : "no rows"}
      · {num(data.total)} items in the whole store{#if data.canonical === false} · {data.note ?? "not canonical yet"}{/if}
    </div>
    {#if Object.keys(byOwnerState).length}
      <div class="scroll">
        <table class="ct">
          <thead><tr><th>AM (the route's grouping)</th>{#each countStates as s (s)}<th class="r">{s.replaceAll("_", " ")}</th>{/each}</tr></thead>
          <tbody>
            {#each Object.entries(byOwnerState) as [am, row] (am)}
              <tr><td>{am}</td>{#each countStates as s (s)}<td class="r mono">{row[s] == null ? DASH : num(row[s])}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    {#if items.length}
      <div class="scroll">
        <table>
          <thead><tr><th>State</th><th>Task</th><th>Updated</th><th>PRs</th><th>Owner</th><th>Latest note</th></tr></thead>
          <tbody>
            {#each items as it (it.id)}
              {@const n = noteOf(it)}
              <tr>
                <td><span class="st {stateCls(it.state)}">{(it.state ?? DASH).replaceAll("_", " ")}</span></td>
                <td><span class="mono id">{it.id}</span><div>{it.title ?? DASH}</div>
                  {#if (it.blocked_on ?? []).length}<div class="muted small">blocked on: {it.blocked_on.join("; ")}</div>{/if}
                  {#if it.due_at}<div class="muted small">due {String(it.due_at).slice(0, 10)}</div>{/if}</td>
                <td class="muted" title={it.updated_at ?? ""}>{it.updated_at ? agoFromIso(it.updated_at) : DASH}{#if it.updated_by}<div class="small">{it.updated_by}</div>{/if}</td>
                <td class="mono small">{(it.prs ?? []).length ? it.prs.map((p: any) => `#${p}`).join(" ") : DASH}</td>
                <td class="small">{it.owner ?? DASH}</td>
                <td class="small">
                  {#if n}<button class="link" onclick={() => (open = { ...open, [it.id]: !open[it.id] })}>{open[it.id] ? "▾ hide" : "▸ show"}</button> <span class="muted">{n.meta}</span>{:else}{DASH}{/if}
                </td>
              </tr>
              {#if open[it.id] && n}
                <tr class="noterow"><td colspan="6">{#if !n.isEvent}<div class="muted small">No note event returned; this is the row's own note.</div>{/if}<div class="nt">{n.text}</div></td></tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    <div class="pager">
      <button disabled={!offset || loading} onclick={() => (offset = Math.max(0, offset - PAGE))}>← Prev</button>
      <button disabled={!hasMore || loading} onclick={() => (offset += PAGE)}>Next →</button>
    </div>
  {/if}
</section>

<style>
  .tw { display: flex; flex-direction: column; gap: 8px; }
  h3 { margin: 0; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .warn { color: #d4a017; border-left: 3px solid #d4a017; padding: 4px 8px; }
  .wl { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }
  .card { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
  .ch { display: flex; gap: 8px; align-items: baseline; }
  .ch .link { margin-left: auto; }
  .li { border-top: 1px solid var(--border); padding-top: 4px; }
  .lrow { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  select, button, input:not([type="checkbox"]) { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  input.sm { width: 150px; }
  button { cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: default; }
  .tog { display: inline-flex; gap: 4px; align-items: center; font-size: 13px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px; white-space: nowrap; }
  .ct { width: auto; }
  .r { text-align: right; }
  .id { color: var(--muted); font-size: 12px; }
  .st { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; background: var(--panel-2); border: 1px solid var(--border); }
  .st.fl { color: #4c8dff; border-color: #4c8dff55; }
  .st.bl { color: #e5484d; border-color: #e5484d55; }
  .st.qu { color: var(--muted); }
  .st.lu { color: #d4a017; border-color: #d4a01755; }
  .st.dn { color: #30a46c; border-color: #30a46c55; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); padding: 0; font-size: 12px; cursor: pointer; }
  .noterow td { background: var(--panel-2); }
  .nt { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; margin-top: 4px; }
  .pager { display: flex; gap: 8px; }
</style>
