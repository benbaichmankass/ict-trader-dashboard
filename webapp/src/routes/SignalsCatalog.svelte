<script lang="ts">
  // Signals Catalog (UI-UPGRADE-1 item 8) — every input the system reads,
  // from GET /api/bot/signals/catalog (bot #25199). Read surface only: no
  // dialogs, no gates. Filters (family/kind/q/consumer) and paging
  // (offset/next_offset) go to the server; the table sort reorders only the
  // page on screen. Nothing is computed that the route does not publish —
  // every count in the header is the route's own `population` block.
  //
  // read_state "could_not_look" or a non-200 renders "could not look — …",
  // never an empty table that would read as zero inputs.
  import { onDestroy } from "svelte";
  import { api } from "../lib/api";
  import Segmented from "../components/Segmented.svelte";
  import { SC_DASH, SC_PAGE_SIZE, CONSUMER_OPTIONS, cell, listCell, listShort, freshnessCell, truncate, type Consumer } from "../lib/signalsCatalog";

  let family = $state<string | null>(null);
  let kind = $state<string | null>(null);
  let qInput = $state("");
  let q = $state("");
  let consumer = $state<Consumer>("any");
  let offset = $state(0);

  let resp = $state<any>(null);
  let loading = $state(true);
  let failure = $state<string | null>(null);
  let ctl: AbortController | null = null;

  async function load(o: { family: string | null; kind: string | null; q: string; consumer: Consumer; offset: number }) {
    ctl?.abort();
    const c = new AbortController();
    ctl = c;
    loading = true;
    failure = null;
    try {
      const res = await api.signalsCatalog({ limit: SC_PAGE_SIZE, ...o }, c.signal);
      if (c.signal.aborted) return;
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const d = body && typeof body.detail === "string" ? body.detail : res.statusText;
        failure = `HTTP ${res.status}${d ? ` ${d}` : ""}`;
        resp = null;
      } else if (!body || typeof body !== "object") {
        failure = "response was not JSON";
        resp = null;
      } else {
        resp = body;
      }
    } catch (e) {
      if (c.signal.aborted) return;
      failure = e instanceof Error ? e.message : String(e);
      resp = null;
    } finally {
      if (ctl === c) loading = false;
    }
  }
  $effect(() => { load({ family, kind, q, consumer, offset }); });
  onDestroy(() => ctl?.abort());

  let qTimer: ReturnType<typeof setTimeout> | undefined;
  function onSearch() {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { offset = 0; q = qInput.trim(); }, 350);
  }
  function pickGroup(g: any) {
    offset = 0;
    if (family === (g?.family ?? null) && kind === (g?.kind ?? null)) { family = null; kind = null; }
    else { family = g?.family ?? null; kind = g?.kind ?? null; }
  }
  function clearGroup() { offset = 0; family = null; kind = null; }
  let consumerSel = $state<string>("any");
  $effect(() => { const v = consumerSel as Consumer; if (v !== consumer) { offset = 0; consumer = v; } });

  const couldNotLook = $derived(failure != null || (resp != null && resp.read_state === "could_not_look"));
  const pop = $derived(resp?.population ?? null);
  const items = $derived<any[]>(Array.isArray(resp?.items) ? resp.items : []);
  const groups = $derived<any[]>(Array.isArray(resp?.groups) ? resp.groups : []);
  const readErrors = $derived<any[]>(Array.isArray(pop?.read_errors) ? pop.read_errors : []);
  const provTitle = $derived.by(() => {
    const p = resp?.provenance;
    if (!p) return "provenance: —";
    const src = Array.isArray(p.source) ? p.source.join(", ") : cell(p.source);
    return `source: ${src}\nmeasure: ${cell(p.measure)}\njoin: ${cell(p.join)}`;
  });
  const healthTip = (h: unknown): string => {
    const v = resp?.health_vocabulary;
    const k = typeof h === "string" ? h : "";
    return v && k && typeof v[k] === "string" ? `${k}: ${v[k]}` : cell(h);
  };

  // --- sort (current page only) ---
  type Key = "name" | "family" | "kind" | "timeframe" | "strategies" | "models" | "health" | "freshness";
  let key = $state<Key | null>(null);
  let asc = $state(true);
  function val(it: any, k: Key): string | number | null {
    switch (k) {
      case "name": return it?.name ?? it?.id ?? null;
      case "family": return it?.family ?? null;
      case "kind": return it?.kind ?? null;
      case "timeframe": return it?.timeframe ?? null;
      case "strategies": return Array.isArray(it?.used_by_strategies) ? it.used_by_strategies.length : null;
      case "models": return Array.isArray(it?.used_by_models) ? it.used_by_models.length : null;
      case "health": return it?.health_state ?? null;
      case "freshness": return typeof it?.freshness?.age_s === "number" ? it.freshness.age_s : it?.freshness?.state ?? null;
    }
  }
  const rows = $derived.by(() => {
    if (!key) return items;
    const k = key;
    return [...items].sort((a, b) => {
      const x = val(a, k), y = val(b, k);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return asc ? c : -c;
    });
  });
  function sortBy(k: Key) { if (key === k) asc = !asc; else { key = k; asc = true; } }
  const ar = (k: Key) => (key === k ? (asc ? " ▲" : " ▼") : "");

  const n = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("en-US") : SC_DASH);
  const prevOffset = $derived(Math.max(0, offset - (typeof pop?.limit === "number" ? pop.limit : SC_PAGE_SIZE)));
</script>

<section>
  <div class="head">
    <h2>Signals catalog</h2>
  </div>

  {#if resp && !failure}
    <div class="panel card small" title={provTitle}>
      <div>
        read_state <b>{cell(resp.read_state)}</b> · as of <span class="mono">{cell(resp.as_of)}</span>
        · catalog v{cell(resp.catalog_version)} generated <span class="mono">{cell(resp.catalog_generated)}</span>
      </div>
      {#if pop}
        <div>
          <b>{n(pop.matched)}</b> of {n(pop.inputs)} inputs · {n(pop.with_consumer)} with a consumer · {n(pop.without_consumer)} without
        </div>
      {/if}
      {#if resp.filters}
        <div class="muted">server applied: family {cell(resp.filters.family)} · kind {cell(resp.filters.kind)} · q {cell(resp.filters.q)} · consumer {cell(resp.filters.consumer)}</div>
      {/if}
      {#if readErrors.length}
        <div class="warn">read errors ({readErrors.length}): <span class="mono">{readErrors.map((e) => (typeof e === "string" ? e : JSON.stringify(e))).join(" · ")}</span></div>
      {/if}
    </div>
  {/if}

  <div class="controls">
    <input class="search" type="search" placeholder="Search id / name / definition…" bind:value={qInput} oninput={onSearch} />
    <Segmented options={[...CONSUMER_OPTIONS]} bind:value={consumerSel} />
  </div>

  {#if groups.length}
    <div class="chips">
      <button class="chip" class:on={!family && !kind} onclick={clearGroup}>All</button>
      {#each groups as g (`${g.family}\u0000${g.kind}`)}
        <button class="chip" class:on={family === (g.family ?? null) && kind === (g.kind ?? null)} onclick={() => pickGroup(g)}>
          {cell(g.family)} / {cell(g.kind)} <span class="muted">{n(g.count)}</span>
        </button>
      {/each}
    </div>
  {/if}

  {#if couldNotLook}
    <div class="err panel">
      could not look — <span class="mono">{failure ?? `read_state ${cell(resp?.read_state)}${readErrors.length ? `: ${readErrors.map((e) => (typeof e === "string" ? e : JSON.stringify(e))).join(" · ")}` : ""}`}</span>
    </div>
  {:else if loading && !resp}
    <div class="muted pad">Loading the catalog… (uncached reads take a few seconds)</div>
  {:else if resp}
    {#if !items.length}
      <div class="muted pad">No inputs match these filters ({n(pop?.matched)} matched of {n(pop?.inputs)}).</div>
    {:else}
      <div class="panel scroll" class:stale={loading}>
        <table>
          <thead>
            <tr>
              <th class="s" onclick={() => sortBy("name")}>Name / id{ar("name")}</th>
              <th class="s" onclick={() => sortBy("family")}>Family{ar("family")}</th>
              <th class="s" onclick={() => sortBy("kind")}>Kind{ar("kind")}</th>
              <th class="s" onclick={() => sortBy("timeframe")}>Timeframe{ar("timeframe")}</th>
              <th class="s" onclick={() => sortBy("strategies")}>Used by strategies{ar("strategies")}</th>
              <th class="s" onclick={() => sortBy("models")}>Used by models{ar("models")}</th>
              <th class="s" onclick={() => sortBy("health")}>Health{ar("health")}</th>
              <th class="s" onclick={() => sortBy("freshness")}>Freshness{ar("freshness")}</th>
              <th>Definition</th>
            </tr>
          </thead>
          <tbody>
            {#each rows as it, i (it.id ?? i)}
              <tr>
                <td title={cell(it.source_code)}><div class="nm">{cell(it.name)}</div><div class="muted mono small">{cell(it.id)}</div></td>
                <td class="mono">{cell(it.family)}</td>
                <td class="mono">{cell(it.kind)}</td>
                <td class="muted">{cell(it.timeframe)}</td>
                <td class="small list" title={listCell(it.used_by_strategies)}>{listShort(it.used_by_strategies)}</td>
                <td class="small list" title={listCell(it.used_by_models)}>{listShort(it.used_by_models)}</td>
                <td class="mono small" title={healthTip(it.health_state)}>{cell(it.health_state)}</td>
                <td class="mono small" title={`last value at ${cell(it.freshness?.last_value_at)}`}>{freshnessCell(it.freshness)}</td>
                <td class="small def" title={cell(it.definition)}>{truncate(it.definition)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="pager small">
        <button disabled={offset <= 0 || loading} onclick={() => (offset = prevOffset)}>← Prev</button>
        <span class="muted">rows {n(pop?.offset != null ? pop.offset + 1 : null)}–{n(pop?.offset != null && pop?.returned != null ? pop.offset + pop.returned : null)} of {n(pop?.matched)}</span>
        <button disabled={pop?.next_offset == null || loading} onclick={() => (offset = pop.next_offset)}>Next →</button>
        {#if loading}<span class="muted">loading…</span>{/if}
      </div>
    {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head h2 { margin: 0; font-size: 18px; }
  .card { padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
  .pad { padding: 18px; }
  .err { padding: 12px; }
  .warn { color: var(--warn, #d9a400); }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .search { flex: 1 1 220px; min-width: 0; padding: 7px 9px; border-radius: 6px; border: 1px solid var(--border); background: transparent; color: inherit; font: inherit; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { padding: 4px 9px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: inherit; font-size: 12px; cursor: pointer; }
  .chip.on { border-color: var(--accent, #4c8dff); background: rgba(76, 141, 255, 0.15); }
  .scroll { overflow-x: auto; padding: 4px; }
  .stale { opacity: 0.6; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 7px 9px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; white-space: nowrap; }
  th.s { cursor: pointer; user-select: none; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .nm { font-weight: 600; }
  .small { font-size: 11px; }
  .list { max-width: 220px; }
  .def { max-width: 320px; }
  .pager { display: flex; gap: 10px; align-items: center; }
</style>
