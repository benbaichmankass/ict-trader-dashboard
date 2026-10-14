<script lang="ts">
  import { DASH, num, money, agoFromIso } from "../lib/format";
  import {
    facetCounts,
    matchesFacets,
    matchesSearch,
    compareRows,
    type View,
    type Col,
  } from "../lib/explorerViews";

  // `loadedNote` is the honest denominator: these tabs filter a LOADED window
  // client-side, so "showing X of Y" must say Y is what is loaded, and `total`
  // (when the bot reports one) says how many exist beyond it.
  let {
    view,
    rows,
    loading,
    error,
    total = null,
    onRefresh,
    onLoadMore = null,
    note = null,
  }: {
    view: View;
    rows: any[];
    loading: boolean;
    error: string | null;
    total?: number | null;
    onRefresh: () => void;
    onLoadMore?: (() => void) | null;
    note?: string | null;
  } = $props();

  const PAGE = 50;
  let q = $state("");
  let sel = $state<Record<string, string[]>>({});
  let sortKey = $state<string | null>(null);
  let sortDir = $state<"asc" | "desc">("desc");
  let page = $state(0);
  let openRow = $state<any | null>(null);

  const key = $derived(sortKey ?? view.defaultSort);
  const counts = $derived(facetCounts(rows, view.facets, sel));
  const filtered = $derived(
    rows.filter((r) => matchesFacets(r, sel) && matchesSearch(r, view.search, q)).sort((a, b) => compareRows(a, b, key, sortDir)),
  );
  const shown = $derived(filtered.slice(page * PAGE, page * PAGE + PAGE));
  const nSel = $derived(Object.values(sel).reduce((n, v) => n + v.length, 0));

  function toggle(f: string, v: string) {
    const cur = sel[f] ?? [];
    sel = { ...sel, [f]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] };
    page = 0;
  }
  function clear() {
    q = "";
    sel = {};
    page = 0;
  }
  function sortBy(k: string) {
    if (key === k) sortDir = sortDir === "asc" ? "desc" : "asc";
    else {
      sortKey = k;
      sortDir = "desc";
    }
    page = 0;
  }

  function cell(r: any, c: Col): string {
    const v = r?.[c.key];
    if (v === null || v === undefined || v === "") return DASH;
    if (c.kind === "money") return typeof v === "number" ? money(v) : String(v);
    if (c.kind === "num") return typeof v === "number" ? num(v, 4) : String(v);
    if (c.kind === "time") return agoFromIso(String(v));
    return String(v);
  }
  function raw(v: unknown): string {
    if (v === null || v === undefined || v === "") return DASH;
    if (typeof v === "object") return JSON.stringify(v, null, 1);
    return String(v);
  }
  const signCls = (r: any, c: Col) => (c.kind === "money" && typeof r?.[c.key] === "number" ? (r[c.key] > 0 ? "pos" : r[c.key] < 0 ? "neg" : "") : "");
  // Provenance is shown verbatim beside P&L; "unverified"/"fabricated"/"estimated"
  // are flagged and never folded into "measured".
  const prov = (r: any) => (r?.pnlProvenance ? String(r.pnlProvenance) : null);
</script>

<section>
  <div class="panel pad ctrl">
    <input class="search" type="search" placeholder={`Search ${view.title.toLowerCase()}…`} bind:value={q} oninput={() => (page = 0)} aria-label={`Search ${view.title}`} />
    <div class="facets">
      {#each view.facets as f (f)}
        {#if (counts[f] ?? []).length > 1 || (sel[f] ?? []).length}
          <div class="fg">
            <span class="fl">{f}</span>
            {#each counts[f] ?? [] as [val, n] (val)}
              <button class="chip" class:on={sel[f]?.includes(val)} onclick={() => toggle(f, val)}>{val} <span class="muted">{num(n)}</span></button>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
    {#if q || nSel}<button class="lnk" onclick={clear}>Clear search &amp; filters</button>{/if}
  </div>

  {#if error}
    <div class="err panel">
      Could not load {view.title.toLowerCase()} — a failed request, not an empty list. <span class="mono">{error}</span>
      <button class="lnk" onclick={onRefresh}>Retry</button>
    </div>
  {:else if loading && rows.length === 0}
    <div class="muted pad">Loading…</div>
  {:else}
    <div class="meta muted">
      Showing {filtered.length ? `${num(page * PAGE + 1)}–${num(page * PAGE + shown.length)}` : "0"} of {num(filtered.length)} matching
      · {num(rows.length)} loaded{#if total != null && total > rows.length}&nbsp;of {num(total)} total{/if}
      {#if note}· {note}{/if}
      {#if loading}· refreshing…{/if}
    </div>
    {#if rows.length === 0}
      <div class="muted pad panel">No {view.title.toLowerCase()} returned by the host.</div>
    {:else if filtered.length === 0}
      <div class="muted pad panel">Nothing matches these filters. <button class="lnk" onclick={clear}>Clear filters</button></div>
    {:else}
      <div class="panel scroll">
        <table>
          <thead>
            <tr>
              {#each view.cols as c (c.key)}
                <th class:r={c.kind === "num" || c.kind === "money"}>
                  <button class="th" onclick={() => sortBy(c.key)} aria-label={`Sort by ${c.label}`}>{c.label}{key === c.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}</button>
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each shown as r, i (r?.[view.idKey] ?? i)}
              <tr class:sel={openRow === r} onclick={() => (openRow = r)}>
                {#each view.cols as c (c.key)}
                  <td class:r={c.kind === "num" || c.kind === "money"} class="nw {signCls(r, c)}" title={c.kind === "time" ? String(r?.[c.key] ?? "") : undefined}>
                    {cell(r, c)}{#if c.provenance && r?.[c.key] != null}<span class="pv" class:warnpv={prov(r) !== "measured"}>{prov(r) ?? "no provenance"}</span>{/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="pager">
        <button onclick={() => (page = Math.max(0, page - 1))} disabled={page === 0}>‹ Prev</button>
        <button onclick={() => (page += 1)} disabled={(page + 1) * PAGE >= filtered.length}>Next ›</button>
        {#if onLoadMore && total != null && rows.length < total}
          <button onclick={onLoadMore} disabled={loading}>Load more ({num(total - rows.length)} not loaded)</button>
        {/if}
        <button onclick={onRefresh} disabled={loading}>Refresh</button>
      </div>
    {/if}
  {/if}

  {#if openRow}
    <aside class="drawer panel" aria-label="Row detail">
      <div class="dh">
        <span class="mono">{raw(openRow[view.idKey])}</span>
        <button class="lnk" onclick={() => (openRow = null)}>Close ✕</button>
      </div>
      <div class="db">
        {#each Object.entries(openRow) as [k, v] (k)}
          <div class="kvr"><span class="muted">{k}</span><span class="mono">{raw(v)}</span></div>
        {/each}
      </div>
    </aside>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .pad { padding: 12px; }
  .ctrl { display: flex; flex-direction: column; gap: 10px; }
  .search { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 8px 10px; width: 100%; box-sizing: border-box; }
  .facets { display: flex; flex-direction: column; gap: 6px; }
  .fg { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
  .fl { font-size: 11px; color: var(--muted); width: 84px; text-transform: uppercase; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 999px; padding: 2px 9px; font-size: 12px; cursor: pointer; }
  .chip.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 22%, var(--panel-2)); }
  .lnk { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0; align-self: flex-start; }
  .meta { font-size: 12px; }
  .err { padding: 10px 12px; color: var(--neg); display: flex; flex-direction: column; gap: 4px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 6px 9px; text-align: left; border-bottom: 1px solid var(--border); }
  td.r, th.r { text-align: right; }
  .nw { white-space: nowrap; }
  tbody tr { cursor: pointer; }
  tbody tr:hover, tr.sel { background: var(--panel-2); }
  .th { background: none; border: none; color: var(--muted); font-weight: 500; cursor: pointer; padding: 0; font-size: 12px; white-space: nowrap; }
  .pv { margin-left: 6px; font-size: 10px; color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; }
  .pv.warnpv { color: #d9a441; border-color: #d9a441; }
  .pager { display: flex; gap: 8px; flex-wrap: wrap; }
  .pager button { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 4px 12px; cursor: pointer; }
  .pager button:disabled { opacity: .4; cursor: default; }
  .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(520px, 100vw); z-index: 40; overflow-y: auto; border-radius: 0; box-shadow: -4px 0 18px rgba(0,0,0,.4); }
  .dh { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--panel); }
  .db { padding: 6px 14px 24px; }
  .kvr { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
  .kvr .mono { text-align: right; overflow-wrap: anywhere; white-space: pre-wrap; max-width: 70%; }
  @media (max-width: 640px) { .fl { width: 100%; } }
</style>
