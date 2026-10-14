<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { DASH, num, agoFromIso } from "../lib/format";
  import {
    FACETS,
    catalogState,
    metricScalars,
    toggleFacet,
    readLastSeen,
    writeLastSeen,
    type CatalogResponse,
    type CatalogDetail,
    type CatalogItem,
    type FacetKey,
    type SortKey,
    type StayItem,
  } from "../lib/catalog";

  const PAGE = 50;
  const COLS: Array<{ key: SortKey; label: string }> = [
    { key: "id", label: "ID" },
    { key: "title", label: "Test" },
    { key: "theme", label: "Theme" },
    { key: "priority", label: "Pri" },
    { key: "status", label: "Status" },
    { key: "verdict", label: "Verdict" },
    { key: "lastActivity", label: "Last activity" },
  ];

  let q = $state("");
  let facets = $state<Partial<Record<FacetKey, string[]>>>({});
  let sort = $state<SortKey>("lastActivity");
  let order = $state<"asc" | "desc">("desc");
  let offset = $state(0);

  let resp = $state<CatalogResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  // Read once at mount: the "new since" baseline for this visit. Advanced only
  // when the operator clicks "Mark seen" — a reload must not erase what was new.
  let since = $state<string | null>(null);
  let acked = $state(false);

  let openId = $state<string | null>(null);
  let detail = $state<CatalogDetail | null>(null);
  let detailErr = $state<string | null>(null);
  let detailLoading = $state(false);

  let timer: ReturnType<typeof setTimeout> | undefined;
  let ctl: AbortController | undefined;

  async function load() {
    ctl?.abort();
    ctl = new AbortController();
    loading = true;
    error = null;
    try {
      resp = await api.researchCatalog({ q, facets, sort, order, limit: PAGE, offset, since }, ctl.signal);
    } catch (e) {
      if ((e as any)?.name === "AbortError") return;
      error = e instanceof Error ? e.message : String(e);
      resp = null;
    } finally {
      loading = false;
    }
  }

  function reload(resetPage = true) {
    if (resetPage) offset = 0;
    load();
  }
  function onSearch() {
    clearTimeout(timer);
    timer = setTimeout(() => reload(), 300);
  }
  function pickFacet(f: FacetKey, v: string) {
    facets = { ...facets, [f]: toggleFacet(facets[f], v) };
    reload();
  }
  function clearAll() {
    q = "";
    facets = {};
    reload();
  }
  function sortBy(k: SortKey) {
    if (sort === k) order = order === "asc" ? "desc" : "asc";
    else {
      sort = k;
      order = k === "lastActivity" || k === "priority" ? "desc" : "asc";
    }
    reload();
  }
  function jump(f: FacetKey, v: string) {
    facets = { [f]: [v] };
    q = "";
    reload();
  }
  async function open(id: string) {
    openId = id;
    detail = null;
    detailErr = null;
    detailLoading = true;
    try {
      detail = await api.researchUnit(id);
    } catch (e) {
      detailErr = e instanceof Error ? e.message : String(e);
    } finally {
      detailLoading = false;
    }
  }
  function markSeen() {
    const ok = writeLastSeen(resp?.generatedAt ?? new Date().toISOString());
    acked = ok;
    if (!ok) error = "Could not save the last-seen marker (browser storage is blocked).";
  }

  onMount(() => {
    since = readLastSeen();
    load();
    return () => {
      clearTimeout(timer);
      ctl?.abort();
    };
  });

  const cstate = $derived(catalogState(resp));
  const items = $derived(resp?.items ?? []);
  const matched = $derived(resp?.matched ?? resp?.total ?? null);
  const stay = $derived(resp?.stayOnTop ?? null);
  const nFacets = $derived(Object.values(facets).reduce((n, v) => n + (v?.length ?? 0), 0));
  // detail.unit is the authoritative full item; the list row supplies `links`
  // (the detail unit omits them) and is the fallback while detail is absent.
  const itemOpen = $derived.by(() => {
    const row = items.find((i) => i.id === openId);
    const u = detail?.unit as CatalogItem | undefined;
    return u ? ({ ...row, ...u, links: u.links ?? row?.links } as CatalogItem) : (row ?? null);
  });
  const hasPrev = $derived(offset > 0);
  const hasNext = $derived(matched != null && offset + PAGE < matched);

  const cls = (v: string | null | undefined) => (v ? `b ${String(v).replace(/[^a-z_]/gi, "")}` : "b");
  const ago = (iso?: string | null) => (iso ? agoFromIso(iso) : DASH);
  const scalar = (v: unknown) => (typeof v === "number" ? num(v, 4) : v == null ? DASH : String(v));
  const kv = (o?: Record<string, unknown> | null) => Object.entries(o ?? {});
</script>

<section>
  <!-- Stay-on-top strip -->
  {#if stay}
    <div class="strip">
      <div class="card">
        <div class="k">New since last visit</div>
        {#if stay.new == null}
          <div class="v">First visit</div>
          <div class="muted s">No baseline yet — nothing is counted as new.</div>
        {:else}
          <div class="v">{num(stay.new.count)}</div>
          <div class="muted s">since {since ? ago(since) + " ago" : DASH}</div>
        {/if}
        <button class="lnk" onclick={markSeen} disabled={acked}>{acked ? "Marked seen" : "Mark seen"}</button>
      </div>
      <button class="card click" onclick={() => jump("stuck", "yes")}>
        <div class="k">Stuck</div>
        <div class="v neg">{num(stay.stuck?.count)}</div>
        <div class="muted s">blocked, or dispatched &gt;6h with no result</div>
      </button>
      <button class="card click" onclick={() => jump("status", "due")}>
        <div class="k">Due</div>
        <div class="v">{num(stay.due?.count)}</div>
        <div class="muted s">ready to dispatch</div>
      </button>
      <div class="card wide">
        <div class="k">Recent verdicts</div>
        {#each (stay.recentVerdicts ?? []).slice(0, 5) as r (r.id)}
          <button class="rv" onclick={() => open(r.id)}>
            <span class={cls(r.verdict)}>{r.verdict ?? DASH}</span>
            <span class="ellip">{r.title ?? r.id}</span>
            <span class="muted">{ago(r.lastActivity)}</span>
          </button>
        {:else}
          <div class="muted s">None.</div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Search + facets -->
  <div class="panel pad ctrl">
    <input
      class="search"
      type="search"
      placeholder="Search id, title, summary…"
      bind:value={q}
      oninput={onSearch}
      aria-label="Search research tests"
    />
    <div class="facets">
      {#each FACETS as f (f)}
        {@const counts = resp?.facets?.[f] ?? {}}
        <div class="fg">
          <span class="fl">{f}</span>
          {#each Object.entries(counts) as [val, n] (val)}
            <button class="chip" class:on={facets[f]?.includes(val)} onclick={() => pickFacet(f, val)}>
              {val} <span class="muted">{num(n)}</span>
            </button>
          {/each}
        </div>
      {/each}
    </div>
    {#if q || nFacets}
      <button class="lnk" onclick={clearAll}>Clear search &amp; filters</button>
    {/if}
  </div>

  <!-- Results -->
  {#if error}
    <div class="err panel">
      Could not load the research catalog — this is a failed request, not an empty catalog.
      <span class="mono">{error}</span>
      <button class="lnk" onclick={() => load()}>Retry</button>
    </div>
  {:else if cstate === "unreadable"}
    <div class="err panel">
      The catalog store is unreadable on the host — this is NOT zero tests.
      {#each resp?.readErrors ?? [] as e}<div class="mono s">{e}</div>{/each}
    </div>
  {:else if cstate === "absent"}
    <div class="muted pad panel">The host reports no research catalog (<span class="mono">present: false</span>).</div>
  {:else}
    {#if cstate === "partial"}
      <div class="warn panel pad">
        Partial read — some queue files could not be parsed, so counts may be low.
        {#each resp?.readErrors ?? [] as e}<div class="mono s">{e}</div>{/each}
      </div>
    {/if}
    <div class="meta muted">
      {#if loading && !resp}Loading…{:else}
        Showing {items.length ? `${num(offset + 1)}–${num(offset + items.length)}` : "0"} of {num(matched)}
        matched{#if resp?.total != null && resp.total !== matched}&nbsp;(catalog total {num(resp.total)}){/if}
        · generated {ago(resp?.generatedAt)} ago{#if loading}&nbsp;· refreshing…{/if}
      {/if}
    </div>
    {#if cstate === "empty"}
      <div class="muted pad panel">
        {q || nFacets ? "No tests match these filters." : "The catalog is empty."}
        {#if q || nFacets}<button class="lnk" onclick={clearAll}>Clear filters</button>{/if}
      </div>
    {:else}
      <div class="panel scroll">
        <table>
          <thead>
            <tr>
              {#each COLS as c (c.key)}
                <th>
                  <button class="th" onclick={() => sortBy(c.key)} aria-label={`Sort by ${c.label}`}>
                    {c.label}{sort === c.key ? (order === "asc" ? " ▲" : " ▼") : ""}
                  </button>
                </th>
              {/each}
              <th>Roadmap</th>
              <th class="r">n</th>
            </tr>
          </thead>
          <tbody>
            {#each items as it (it.id)}
              <tr class:sel={openId === it.id} onclick={() => open(it.id)}>
                <td class="mono nw">{it.id}</td>
                <td class="title">{it.title ?? DASH}{#if it.stuck}<span class="b stuck" title={it.stuckReason ?? ""}>stuck</span>{/if}</td>
                <td>{it.theme ?? DASH}</td>
                <td class="r">{it.priority ?? DASH}</td>
                <td><span class={cls(it.status)}>{it.status ?? DASH}</span></td>
                <td><span class={cls(it.verdict)}>{it.verdict ?? DASH}</span></td>
                <td class="nw muted">{ago(it.lastActivity)}</td>
                <td class="nw">{it.roadmap?.length ? it.roadmap.map((r) => r.goal ? `${r.goal}·${r.id ?? ""}` : (r.id ?? "")).join(", ") : DASH}</td>
                <td class="r">{num(it.dataUsed?.n)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="pager">
        <button onclick={() => { offset = Math.max(0, offset - PAGE); load(); }} disabled={!hasPrev || loading}>‹ Prev</button>
        <button onclick={() => { offset += PAGE; load(); }} disabled={!hasNext || loading}>Next ›</button>
      </div>
    {/if}
  {/if}

  <!-- Detail drawer -->
  {#if openId}
    <aside class="drawer panel" aria-label="Test detail">
      <div class="dh">
        <span class="mono">{openId}</span>
        <button class="lnk" onclick={() => (openId = null)}>Close ✕</button>
      </div>
      {#if detailLoading}
        <div class="muted pad">Loading…</div>
      {:else if detailErr}
        <div class="err pad">Could not load this test: <span class="mono">{detailErr}</span></div>
      {:else if detail && detail.present === false}
        <div class="muted pad">The host has no unit with this id.</div>
      {:else if itemOpen}
        {@const it = itemOpen as CatalogItem}
        <div class="db">
          <h3>{it.title ?? DASH}</h3>
          <div class="tags">
            <span class={cls(it.status)}>{it.status ?? DASH}</span>
            <span class={cls(it.verdict)}>{it.verdict ?? "no verdict"}</span>
            {#if it.stuck}<span class="b stuck">stuck</span>{/if}
            <span class="muted">{it.kind ?? DASH} · {it.cadence ?? DASH} · {it.theme ?? DASH} · pri {it.priority ?? DASH}</span>
          </div>
          {#if it.stuckReason || it.blockedReason}
            <p class="neg s">{it.stuckReason ?? it.blockedReason}</p>
          {/if}
          <h4>Question / summary</h4>
          <p>{it.summary ?? DASH}</p>
          <h4>Why it matters</h4>
          <p>{it.whyItMatters ?? DASH}</p>
          <h4>Roadmap</h4>
          {#each it.roadmap ?? [] as r}
            <p class="s">{r.goal ?? DASH} {r.goalName ?? ""} → {r.id ?? DASH} {r.name ?? ""} <span class="muted">({r.status ?? DASH})</span></p>
          {:else}<p class="muted s">{DASH}</p>{/each}
          <h4>Pre-registered rule</h4>
          {#if it.rule}
            <p class="s mono">{it.rule.id ?? DASH} · registered {it.rule.registeredAt ?? DASH}{it.rule.registeredBeforeRun === false ? " · ⚠ AFTER the run" : ""}</p>
            <p class="s">{it.rule.text ?? DASH}</p>
            <p class="s muted">Statistic: {it.rule.statistic ?? DASH}</p>
          {:else}<p class="muted s">{DASH}</p>{/if}
          {#if it.power}
            <p class="s muted">Power: {it.power.state ?? DASH} · expected n {num(it.power.expectedN)} · MDE {it.power.minDetectableEffect ?? DASH}</p>
          {/if}
          <h4>Result</h4>
          <p>{it.resultNote ?? DASH}</p>
          {#each metricScalars(it.metrics) as [k, v]}
            <div class="kvr"><span class="muted">{k}</span><span class="mono">{scalar(v)}</span></div>
          {/each}
          <h4>Data used</h4>
          <div class="kvr"><span class="muted">workflow</span><span class="mono">{it.dataUsed?.workflow ?? DASH}</span></div>
          <div class="kvr"><span class="muted">harness</span><span class="mono">{it.dataUsed?.harness ?? DASH}</span></div>
          <div class="kvr"><span class="muted">population / n</span><span class="mono">{it.dataUsed?.population ?? DASH} / {num(it.dataUsed?.n)}</span></div>
          <div class="kvr"><span class="muted">store</span><span class="mono">{it.dataUsed?.store ?? DASH}</span></div>
          {#each kv(it.dataUsed?.dataInputs) as [k, v]}
            <div class="kvr"><span class="muted">{k}</span><span class="mono">{scalar(v)}</span></div>
          {/each}
          <div class="kvr"><span class="muted">backend · est.</span><span class="mono">{it.backend ?? DASH} · {it.estMinutes != null ? it.estMinutes + " min" : DASH}</span></div>
          <h4>Timestamps</h4>
          <div class="kvr"><span class="muted">created</span><span class="mono">{it.createdAt ?? DASH}</span></div>
          <div class="kvr"><span class="muted">last dispatched</span><span class="mono">{it.lastDispatchedAt ?? DASH}</span></div>
          <div class="kvr"><span class="muted">latest result</span><span class="mono">{it.latestResultAt ?? DASH}</span></div>
          <h4>Result rows</h4>
          {#if detail?.resultRows?.length}
            {#each detail.resultRows as row}
              <details><summary class="mono s">{(row as any).run_id ?? (row as any).id ?? (row as any).ts ?? "row"}</summary>
                <pre class="s">{JSON.stringify(row, null, 1)}</pre></details>
            {/each}
            {#if detail.resultRowsTruncated}<p class="muted s">Showing the newest 20 only.</p>{/if}
          {:else}<p class="muted s">No result rows landed.</p>{/if}
          <h4>Links</h4>
          <p class="s">
            {#if it.links?.unit}<a href={it.links.unit} target="_blank" rel="noopener noreferrer">Unit file</a>{/if}
            {#each it.links?.results ?? [] as l, i}· <a href={l} target="_blank" rel="noopener noreferrer">Result {i + 1}</a>{/each}
            {#if it.links?.run}· <a href={it.links.run} target="_blank" rel="noopener noreferrer">Run</a>{/if}
            {#if !it.links?.unit && !it.links?.run}{DASH}{/if}
          </p>
        </div>
      {/if}
    </aside>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; position: relative; }
  .pad { padding: 12px; }
  .s { font-size: 12px; margin: 4px 0; }
  .strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; text-align: left; color: var(--text); display: flex; flex-direction: column; gap: 3px; }
  .card.click { cursor: pointer; font: inherit; }
  .card.click:hover { border-color: var(--accent); }
  .card.wide { grid-column: span 2; }
  .k { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .v { font-size: 22px; font-weight: 700; }
  .rv { display: flex; gap: 8px; align-items: center; background: none; border: none; color: var(--text); cursor: pointer; text-align: left; padding: 2px 0; font-size: 12px; min-width: 0; }
  .ellip { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
  .ctrl { display: flex; flex-direction: column; gap: 10px; }
  .search { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 8px 10px; width: 100%; box-sizing: border-box; }
  .facets { display: flex; flex-direction: column; gap: 6px; }
  .fg { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
  .fl { font-size: 11px; color: var(--muted); width: 56px; text-transform: uppercase; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 999px; padding: 2px 9px; font-size: 12px; cursor: pointer; }
  .chip.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 22%, var(--panel-2)); }
  .lnk { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0; align-self: flex-start; }
  .lnk:disabled { color: var(--muted); cursor: default; }
  .meta { font-size: 12px; }
  .err { padding: 10px 12px; color: var(--neg); display: flex; flex-direction: column; gap: 4px; }
  .warn { color: #d9a441; border: 1px solid #d9a441; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 6px 9px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  td.r, th.r { text-align: right; }
  .nw { white-space: nowrap; }
  .title { min-width: 260px; max-width: 460px; }
  tbody tr { cursor: pointer; }
  tbody tr:hover, tr.sel { background: var(--panel-2); }
  .th { background: none; border: none; color: var(--muted); font-weight: 500; cursor: pointer; padding: 0; font-size: 12px; white-space: nowrap; }
  .b { display: inline-block; border-radius: 4px; padding: 1px 6px; font-size: 11px; background: var(--panel-2); border: 1px solid var(--border); margin-right: 4px; }
  .b.pass, .b.result { color: var(--pos); }
  .b.fail, .b.blocked, .b.stuck { color: var(--neg); }
  .b.indeterminate, .b.due, .b.dispatched, .b.running { color: #d9a441; }
  .pager { display: flex; gap: 8px; }
  .pager button { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 4px 12px; cursor: pointer; }
  .pager button:disabled { opacity: .4; cursor: default; }
  .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(560px, 100vw); z-index: 40; overflow-y: auto; border-radius: 0; box-shadow: -4px 0 18px rgba(0,0,0,.4); }
  .dh { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--panel); }
  .db { padding: 0 14px 24px; }
  .db h3 { font-size: 15px; margin: 12px 0 6px; }
  .db h4 { font-size: 11px; text-transform: uppercase; color: var(--muted); margin: 14px 0 4px; letter-spacing: .04em; }
  .db p { margin: 4px 0; font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .kvr { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; padding: 2px 0; }
  .kvr .mono { text-align: right; overflow-wrap: anywhere; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--panel-2); padding: 8px; border-radius: 6px; }
  a { color: var(--accent); }
  @media (max-width: 640px) { .card.wide { grid-column: span 1; } .fl { width: 100%; } }
</style>
