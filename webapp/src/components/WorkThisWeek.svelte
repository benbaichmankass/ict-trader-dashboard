<script lang="ts">
  // Work → This week, task rows (bot PR #25354 § "Work queue tabs (SPA)", Tab 2).
  // Rows from GET /api/bot/work/items with the route's OWN filters only (state,
  // due, since, limit/offset). One row per task: state, id, title, updated, PRs,
  // owner, and the row's note behind a disclosure.
  //
  // Not built here, because they need routes (and are never faked client-side):
  //   - AM / week_lane / text filters  → new /work/items params (owner_prefix, week_lane, q)
  //   - per-lane status cards (moved today / working now / stuck / next) → GET /work/lanes
  //   - the newest note EVENT per row (`latest_note`) → /work/items field; until then
  //     the row's own note (`extra.note`) is shown, labelled as such
  //
  // ⚠️ The route's `total` is the WHOLE store's count, not this filter's, and there
  // is no next_offset: "Next" is offered only when a full page came back.
  import { api } from "../lib/api";
  import { agoFromIso, num, DASH } from "../lib/format";

  const PAGE = 50;
  const STATES = ["", "in_flight", "blocked", "queued", "landed_unproven", "done", "dropped"];
  const SINCE = [
    { v: "", label: "Any time" },
    { v: "24h", label: "Changed in 24h" },
    { v: "7d", label: "Changed in 7d" },
  ];

  let stateF = $state("");
  let due = $state(false);
  let since = $state("");
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
  async function load(st: string, du: boolean, si: string, off: number) {
    const my = ++seq;
    loading = true;
    err = null;
    try {
      const r = await api.workItems({ state: st || undefined, due: du, since: sinceIso(si), limit: PAGE, offset: off });
      if (my !== seq) return;
      data = r;
    } catch (e) {
      if (my !== seq) return;
      data = null;
      err = e instanceof Error ? e.message : String(e);
    }
    loading = false;
  }
  // One request per change: a filter change first resets to page 1 (which re-runs
  // this effect), so the old offset is never sent with the new filter.
  let lastKey = "";
  $effect(() => {
    const k = `${stateF}|${due}|${since}`;
    if (k !== lastKey) {
      lastKey = k;
      if (offset !== 0) { offset = 0; return; }
    }
    load(stateF, due, since, offset);
  });

  const items = $derived<any[]>(Array.isArray(data?.items) ? data.items : []);
  const fullPage = $derived(items.length === PAGE);
  const note = (it: any): string | null => {
    const n = it?.extra?.note;
    return typeof n === "string" && n.trim() ? n : null;
  };
  const stateCls = (s: string) =>
    s === "in_flight" ? "fl" : s === "blocked" ? "bl" : s === "queued" ? "qu" : s === "landed_unproven" ? "lu" : s === "done" ? "dn" : "ot";
</script>

<section class="tw">
  <h3>This week <span class="muted sub">· task rows from the work store</span></h3>
  <div class="gaps muted small">
    Not here yet (they need bot routes, so they are not faked in the browser): the per-lane status cards
    (moved today · working now · stuck · next → <span class="mono">GET /work/lanes</span>), and the AM, week-lane and
    text filters (new <span class="mono">/work/items</span> params).
  </div>

  <div class="bar">
    <select bind:value={stateF} aria-label="State">
      {#each STATES as s (s)}<option value={s}>{s ? s.replaceAll("_", " ") : "Any state"}</option>{/each}
    </select>
    <select bind:value={since} aria-label="Changed">
      {#each SINCE as o (o.v)}<option value={o.v}>{o.label}</option>{/each}
    </select>
    <label class="tog"><input type="checkbox" bind:checked={due} /> Due now</label>
    {#if loading}<span class="muted small">loading…</span>{/if}
  </div>

  {#if err}
    <div class="na">Work items: not available (<span class="mono">{err}</span>)</div>
  {:else if !data}
    <div class="muted">Loading…</div>
  {:else if data.readState !== "read"}
    <div class="na">Work items: not available ({data.readState ?? DASH}{data.error ? `: ${data.error}` : ""})</div>
  {:else}
    <div class="muted small">
      {items.length ? `Rows ${offset + 1}–${offset + items.length}` : "No rows"} for this filter · {num(data.total)} items in the whole store
      (the route's total is not this filter's count)
      {#if data.canonical === false} · {data.note ?? "not canonical yet"}{/if}
    </div>
    {#if items.length}
      <div class="scroll">
        <table>
          <thead><tr><th>State</th><th>Task</th><th>Updated</th><th>PRs</th><th>Owner</th><th>Note</th></tr></thead>
          <tbody>
            {#each items as it (it.id)}
              <tr>
                <td><span class="st {stateCls(it.state)}">{(it.state ?? DASH).replaceAll("_", " ")}</span></td>
                <td><span class="mono id">{it.id}</span><div>{it.title ?? DASH}</div>
                  {#if (it.blocked_on ?? []).length}<div class="muted small">blocked on: {it.blocked_on.join("; ")}</div>{/if}
                  {#if it.due_at}<div class="muted small">due {String(it.due_at).slice(0, 10)}</div>{/if}</td>
                <td class="muted" title={it.updated_at ?? ""}>{it.updated_at ? agoFromIso(it.updated_at) : DASH}{#if it.updated_by}<div class="small">{it.updated_by}</div>{/if}</td>
                <td class="mono small">{(it.prs ?? []).length ? it.prs.map((p: any) => `#${p}`).join(" ") : DASH}</td>
                <td class="small">{it.owner ?? DASH}</td>
                <td class="small">
                  {#if note(it)}
                    <button class="link" onclick={() => (open = { ...open, [it.id]: !open[it.id] })}>{open[it.id] ? "▾ hide" : "▸ row note"}</button>
                  {:else}{DASH}{/if}
                </td>
              </tr>
              {#if open[it.id] && note(it)}
                <tr class="noterow"><td colspan="6"><div class="muted small">The row's own note (newest-note events need a route field):</div><div class="nt">{note(it)}</div></td></tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    <div class="pager">
      <button disabled={!offset || loading} onclick={() => (offset = Math.max(0, offset - PAGE))}>← Prev</button>
      <button disabled={!fullPage || loading} onclick={() => (offset += PAGE)} title={fullPage ? "" : "the last page came back short"}>Next →</button>
    </div>
  {/if}
</section>

<style>
  .tw { display: flex; flex-direction: column; gap: 8px; }
  h3 { margin: 0; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  .gaps { border-left: 3px solid var(--border); padding: 4px 8px; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  select, button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  button { cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: default; }
  .tog { display: inline-flex; gap: 4px; align-items: center; font-size: 13px; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px; white-space: nowrap; }
  .id { color: var(--muted); font-size: 12px; }
  .st { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; background: var(--panel-2); border: 1px solid var(--border); }
  .st.fl { color: #4c8dff; border-color: #4c8dff55; }
  .st.bl { color: #e5484d; border-color: #e5484d55; }
  .st.qu { color: var(--muted); }
  .st.lu { color: #d4a017; border-color: #d4a01755; }
  .st.dn { color: #30a46c; border-color: #30a46c55; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); padding: 0; font-size: 12px; }
  .noterow td { background: var(--panel-2); }
  .nt { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12.5px; margin-top: 4px; }
  .pager { display: flex; gap: 8px; }
</style>
