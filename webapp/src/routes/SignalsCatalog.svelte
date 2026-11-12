<script lang="ts">
  // Signals catalog (UI-REDESIGN-2026-11 S&M: "Signals catalog (exists on the
  // Claude console) hooked up here"). Source: GET /api/bot/signals/catalog
  // (bot #25199, ungated) — every input in docs/reference/signal-catalog.yaml
  // joined with the served + candidate model feature lists. Filtering and paging
  // are the ROUTE's (family / kind / q / consumer, limit+offset): this page never
  // downloads the whole catalog to filter it, and every count is the bot's.
  //
  // Health: "unmeasured" means no null-rate/staleness metric exists for that
  // input — it is shown grey and never read as healthy (the route's own
  // health_vocabulary is the legend).
  import { api } from "../lib/api";
  import { num, DASH } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  const PAGE = 50;
  const CONSUMERS = [
    { value: "any", label: "All" },
    { value: "strategy", label: "Used by a strategy" },
    { value: "model", label: "Used by a model" },
    { value: "none", label: "Unused" },
  ];

  let family = $state<string | null>(null);
  let kind = $state<string | null>(null);
  let consumer = $state("any");
  let qInput = $state("");
  let q = $state("");
  let offset = $state(0);

  let data = $state<any>(null);
  let err = $state<string | null>(null);
  let loading = $state(false);
  let groups = $state<any[]>([]); // the unfiltered roll-up, kept for the chips
  let openRow = $state<string | null>(null);

  async function load(f: string | null, k: string | null, c: string, query: string, off: number) {
    loading = true;
    err = null;
    try {
      const r = await api.signalsCatalog({ family: f, kind: k, consumer: c, q: query, limit: PAGE, offset: off });
      data = r;
      if (!f && !k && !query && c === "any") groups = r?.groups ?? [];
    } catch (e) {
      data = null;
      err = e instanceof Error ? e.message : String(e);
    }
    loading = false;
  }
  $effect(() => { load(family, kind, consumer, q, offset); });

  function pick(f: string | null, k: string | null) {
    const same = family === f && kind === k;
    family = same ? null : f;
    kind = same ? null : k;
    offset = 0;
  }
  function search() { q = qInput.trim(); offset = 0; }
  // A new consumer filter starts from the first page.
  let lastConsumer = "any";
  $effect(() => { if (consumer !== lastConsumer) { lastConsumer = consumer; offset = 0; } });

  const pop = $derived(data?.population ?? null);
  const cov = $derived(data?.coverage ?? null);
  const vocab = $derived<Record<string, string>>(data?.health_vocabulary ?? {});
  const familyTotals = $derived.by(() => {
    const m = new Map<string, { n: number; kinds: any[] }>();
    for (const g of groups) {
      const e = m.get(g.family) ?? { n: 0, kinds: [] };
      e.n += g.count ?? 0;
      e.kinds.push(g);
      m.set(g.family, e);
    }
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n);
  });
  const healthClass = (h: string | null | undefined) => (h === "measured" ? "ok" : "grey");
  const list = (xs: string[] | null | undefined) => (xs && xs.length ? xs.join(", ") : DASH);
</script>

<section class="sc">
  <h2>Signals catalog <span class="muted sub">· every input the system computes, who uses it, and whether its health is measured</span></h2>

  {#if cov}
    <div class="kpis">
      <div><b class="mono">{num(cov.n_features)}</b><span class="muted small">inputs</span></div>
      <div><b class="mono">{num(cov.n_with_consumer)}</b><span class="muted small">in use</span></div>
      <div><b class="mono">{num(pop?.without_consumer)}</b><span class="muted small">unused</span></div>
      <div><b class="mono">{num(cov.n_models_in_registry)}</b><span class="muted small">models on disk</span></div>
      <div title="models whose features the catalog does not list"><b class="mono" class:warn={(cov.n_models_missing_from_catalog ?? 0) > 0}>{num(cov.n_models_missing_from_catalog)}</b><span class="muted small">models missing from the catalog</span></div>
    </div>
  {/if}

  {#if familyTotals.length}
    <div class="chips">
      <button class="chip" class:on={!family && !kind} onclick={() => pick(null, null)}>All</button>
      {#each familyTotals as [fam, e] (fam)}
        <span class="fam">
          <button class="chip famchip" class:on={family === fam && !kind} onclick={() => pick(fam, null)}>{fam} <span class="muted">{num(e.n)}</span></button>
          {#if e.kinds.length > 1}
            {#each e.kinds as g (g.family + g.kind)}
              <button class="chip sub" class:on={family === g.family && kind === g.kind} onclick={() => pick(g.family, g.kind)}>{g.kind} <span class="muted">{num(g.count)}</span></button>
            {/each}
          {/if}
        </span>
      {/each}
    </div>
  {/if}

  <div class="bar">
    <Segmented options={CONSUMERS} bind:value={consumer} />
    <input placeholder="Search id, name, definition…" bind:value={qInput} onkeydown={(e) => e.key === "Enter" && search()} />
    <button onclick={search}>Search</button>
    {#if q}<button class="link" onclick={() => { qInput = ""; search(); }}>clear "{q}"</button>{/if}
  </div>

  {#if err}
    <div class="na">Signals catalog: not available (<span class="mono">{err}</span>)</div>
  {:else if !data}
    <div class="muted">Loading…</div>
  {:else if data.read_state !== "read"}
    <div class="na">Signals catalog: not available ({data.reason ?? data.read_state ?? DASH})</div>
  {:else}
    <div class="muted small">
      {num(pop?.matched)} matching of {num(pop?.inputs)}{(pop?.returned ?? 0) > 0 ? ` · showing ${(pop?.offset ?? 0) + 1}–${(pop?.offset ?? 0) + pop.returned}` : ""}
      · catalog generated {data.catalog_generated ?? DASH}{loading ? " · loading…" : ""}
      {#if (pop?.read_errors ?? []).length} · <span class="warn">read errors: {pop.read_errors.join("; ")}</span>{/if}
    </div>
    <div class="scroll">
      <table>
        <thead><tr><th>Input</th><th>Kind</th><th>Timeframe</th><th>Strategies</th><th>Models</th><th>Health</th></tr></thead>
        <tbody>
          {#each data.items ?? [] as it (it.id)}
            <tr class="row" class:open={openRow === it.id} onclick={() => (openRow = openRow === it.id ? null : it.id)}>
              <td><span class="mono">{it.id}</span><div class="muted small def">{it.definition ?? DASH}</div></td>
              <td class="small">{it.family ?? DASH} · {it.kind ?? DASH}</td>
              <td class="small">{it.timeframe ?? DASH}</td>
              <td class="small">{num((it.used_by_strategies ?? []).length)}</td>
              <td class="small">{num((it.used_by_models ?? []).length)}</td>
              <td><span class="hs {healthClass(it.health_state)}" title={vocab[it.health_state] ?? ""}>{it.health_state ?? DASH}</span></td>
            </tr>
            {#if openRow === it.id}
              <tr class="detail"><td colspan="6">
                <dl>
                  <dt>Definition</dt><dd>{it.definition ?? DASH}</dd>
                  <dt>Source</dt><dd class="mono">{it.source_code ?? DASH}</dd>
                  <dt>Used by strategies</dt><dd>{list(it.used_by_strategies)}</dd>
                  <dt>Used by models</dt><dd>{list(it.used_by_models)}</dd>
                  <dt>Health</dt><dd>{it.health_state ?? DASH}{vocab[it.health_state] ? ` — ${vocab[it.health_state]}` : ""}</dd>
                  <dt>Freshness</dt><dd>{it.freshness?.state ?? DASH} · last value {it.freshness?.last_value_at ?? DASH}</dd>
                </dl>
              </td></tr>
            {/if}
          {:else}
            <tr><td colspan="6" class="muted">No inputs match these filters.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="pager">
      <button disabled={!offset || loading} onclick={() => (offset = Math.max(0, offset - PAGE))}>← Prev</button>
      <button disabled={pop?.next_offset == null || loading} onclick={() => (offset = pop.next_offset)}>Next →</button>
    </div>
    <div class="muted small foot">
      Source: {(data.provenance?.source ?? []).join(" + ") || DASH} ({data.provenance?.measure ?? DASH}).
      Per-input value distributions: the <b>Feature Impact</b> page.
    </div>
  {/if}
</section>

<style>
  .sc { display: flex; flex-direction: column; gap: 10px; }
  h2 { margin: 0; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  .kpis { display: flex; flex-wrap: wrap; gap: 8px 22px; }
  .kpis div { display: flex; flex-direction: column; }
  .kpis b { font-size: 18px; }
  .warn { color: #d4a017; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 12px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
  .chip.sub { font-size: 11px; padding: 2px 8px; opacity: 0.85; }
  .fam { display: inline-flex; flex-wrap: wrap; gap: 4px; align-items: center; padding: 2px 6px 2px 0; border-right: 1px solid var(--border); margin-right: 2px; }
  .famchip { font-weight: 600; }
  .chip.on { border-color: var(--accent, #4c8dff); background: #4c8dff22; }
  .bar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .bar input { flex: 1; min-width: 160px; }
  input, button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  button { cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: default; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 8px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; white-space: nowrap; }
  tr.row { border-bottom: 1px solid var(--border); cursor: pointer; }
  tr.row:hover, tr.row.open { background: var(--panel-2); }
  .def { max-width: 520px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  tr.detail td { background: var(--panel-2); border-bottom: 1px solid var(--border); }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 4px 0; font-size: 13px; }
  dt { color: var(--muted); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .hs { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; }
  .hs.ok { background: #30a46c22; color: #30a46c; }
  .hs.grey { background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); }
  .pager { display: flex; gap: 8px; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 4px 8px; font-size: 13px; }
  .foot { line-height: 1.5; }
</style>
