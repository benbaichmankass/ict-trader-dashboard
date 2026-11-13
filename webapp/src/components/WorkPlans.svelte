<script lang="ts">
  // Work → Plans (bot PR #25554; design docs/design/ui-redesign-2026-11-reconciliation.md
  // § "Tab 5: Plans"). Three views:
  //   - Frontier queue: GET /api/bot/work/items?parent=FRONTIER-RESEARCH. The
  //     FRONTIER-Q-* rows; why / baseline / family / est_cost / consumer live in extra.frontier.
  //   - ML plan: GET /api/bot/ml/plan. Plan items by track, each joined bot-side to
  //     its carrying ref (ref_state, ref_read_state, flags), plus the dev plan's lines
  //     (stage, row + row_state, levers ahead, next weeks, exhaustion).
  //   - My adds & edits: observation rows that carry extra.plan_edit, newest first
  //     (the route orders by updated_at DESC). Status, reply and owner are shown as
  //     the store holds them.
  // Writes: POST /api/bot/work/plan-edits (Tier 2, operator session). One press sends,
  // with no confirm(). The server's answer is shown verbatim, and the server decides:
  // a missing session is its 401, not a client gate.
  // Every state, flag and count is the bot's. Nothing is graded or re-derived here.
  // null renders "—"; a 404 renders "not available yet".
  import { api } from "../lib/api";
  import { agoFromIso, num, DASH } from "../lib/format";
  import { serverAnswer } from "../lib/gates";

  const VIEWS = [
    { v: "frontier", label: "Frontier queue" },
    { v: "ml", label: "ML plan" },
    { v: "edits", label: "My adds & edits" },
  ];
  const CLOSED = new Set(["done", "dropped"]);

  let view = $state("frontier");

  type Read = { status: number | null; body: any; err: string | null };
  const blank = (): Read => ({ status: null, body: null, err: null });
  let fq = $state<Read>(blank());
  let mp = $state<Read>(blank());
  let ed = $state<Read>(blank());
  let showClosed = $state(false);
  let openLine = $state<Record<string, boolean>>({});

  async function read(fn: () => Promise<{ status: number; body: any }>): Promise<Read> {
    try {
      const r = await fn();
      return { status: r.status, body: r.body, err: null };
    } catch (e) {
      return { status: null, body: null, err: e instanceof Error ? e.message : String(e) };
    }
  }
  async function loadFrontier() { fq = await read(() => api.frontierQueue()); }
  async function loadPlan() { mp = await read(() => api.mlPlan()); }
  async function loadEdits() { ed = await read(() => api.planEditRows()); }
  $effect(() => {
    if (view === "frontier") loadFrontier();
    else if (view === "ml") loadPlan();
    else loadEdits();
  });

  // ---- write: one form per target, keyed `${section}|${kind}|${item_id ?? ""}` ----
  let openForm = $state<string | null>(null);
  let text = $state<Record<string, string>>({});
  let sending = $state<string | null>(null);
  let answers = $state<Record<string, { ok: boolean; msg: string }>>({});
  const fkey = (section: string, kind: string, itemId?: string | null) => `${section}|${kind}|${itemId ?? ""}`;

  async function send(section: "frontier" | "ml_plan", kind: "add" | "edit", itemId?: string | null) {
    const k = fkey(section, kind, itemId);
    const t = (text[k] ?? "").trim();
    if (!t || sending) return;
    sending = k;
    try {
      const r = await api.planEdit({ section, kind, text: t, ...(itemId ? { item_id: itemId } : {}) });
      const b = r.body as any;
      const msg = r.ok
        ? `Filed ${b?.item?.id ?? ""} · status ${b?.status ?? DASH} · the manager relays it to the owner`
        : `HTTP ${r.status}: ${serverAnswer(r.status, r.body, r.text)}`;
      answers = { ...answers, [k]: { ok: r.ok, msg } };
      if (r.ok) { text = { ...text, [k]: "" }; openForm = null; }
    } catch (e) {
      answers = { ...answers, [k]: { ok: false, msg: e instanceof Error ? e.message : String(e) } };
    }
    sending = null;
  }

  // ---- frontier ----
  const fItems = $derived<any[]>(fq.status === 200 && Array.isArray(fq.body?.items) ? fq.body.items : []);
  const fOpen = $derived(fItems.filter((i) => !CLOSED.has(i.state)));
  const fClosed = $derived(fItems.filter((i) => CLOSED.has(i.state)));

  // ---- ML plan ----
  const plan = $derived(mp.status === 200 ? mp.body : null);
  const pItems = $derived<any[]>(Array.isArray(plan?.items) ? plan.items : []);
  const lines = $derived<any[]>(Array.isArray(plan?.dev_plan?.lines) ? plan.dev_plan.lines : []);
  const weeks = $derived<Record<string, string>>(plan?.dev_plan?.weeks ?? {});
  // Grouping only (first-seen track order, rows in the server's order): no reordering, no counts made up.
  function byTrack(rows: any[]): [string, any[]][] {
    const m = new Map<string, any[]>();
    for (const r of rows) {
      const t = r?.track ?? DASH;
      if (!m.has(t)) m.set(t, []);
      m.get(t)!.push(r);
    }
    return [...m.entries()];
  }
  const itemGroups = $derived(byTrack(pItems));
  const lineGroups = $derived(byTrack(lines));

  // ---- my adds & edits ----
  const edRows = $derived<any[]>(ed.status === 200 && Array.isArray(ed.body?.items) ? ed.body.items : []);
  const edits = $derived(edRows.filter((r) => r?.extra?.plan_edit));
  const oldest = $derived(edRows.length ? edRows[edRows.length - 1]?.updated_at : null);

  const stCls = (s: string) =>
    s === "in_flight" ? "fl" : s === "blocked" ? "bl" : s === "done" || s === "production" ? "dn" : s === "dropped" || s === "failed" || s === "killed" ? "dr" : "ot";
  const t = (v: unknown) => (v === null || v === undefined || v === "" ? DASH : String(v));
</script>

{#snippet editor(section: "frontier" | "ml_plan", kind: "add" | "edit", itemId: string | null, label: string)}
  {@const k = fkey(section, kind, itemId)}
  {#if openForm === k}
    <div class="form">
      <textarea rows="3" maxlength="4000" placeholder={kind === "add" ? "The item you want added, and why" : "What should change, and why"} bind:value={text[k]}></textarea>
      <div class="bar">
        <button class="pri" disabled={!(text[k] ?? "").trim() || sending !== null} onclick={() => send(section, kind, itemId)}>{sending === k ? "Sending…" : "Send"}</button>
        <button onclick={() => (openForm = null)}>Cancel</button>
        <span class="muted small">Filed as a work-store observation; the manager relays it to the owner.</span>
      </div>
    </div>
  {:else}
    <button class="link" onclick={() => (openForm = k)}>{label}</button>
  {/if}
  {#if answers[k]}<div class="ans" class:bad={!answers[k].ok}>{answers[k].msg}</div>{/if}
{/snippet}

{#snippet notAvail(r: Read, what: string)}
  {#if r.err}
    <div class="na">{what}: could not look (<span class="mono">{r.err}</span>)</div>
  {:else if r.status === null}
    <div class="muted">Loading…</div>
  {:else if r.status === 404}
    <div class="na">{what}: not available yet (the route is not deployed on the bot).</div>
  {:else}
    <div class="na">{what}: could not look (HTTP {r.status}{r.body?.error ? `: ${r.body.error}` : r.body?.detail ? `: ${r.body.detail}` : ""})</div>
  {/if}
{/snippet}

<section class="pl">
  <h3>Plans <span class="muted sub">· the frontier sub-queue and the ML development plan</span></h3>
  <div class="bar">
    {#each VIEWS as o (o.v)}<button class="tab" class:on={view === o.v} onclick={() => (view = o.v)}>{o.label}</button>{/each}
  </div>

  {#if view === "frontier"}
    {#if fq.status !== 200 || fq.body?.readState !== "read"}
      {#if fq.status === 200}
        <div class="na">Frontier queue: could not look ({fq.body?.readState ?? DASH}{fq.body?.error ? `: ${fq.body.error}` : ""})</div>
      {:else}{@render notAvail(fq, "Frontier queue")}{/if}
    {:else}
      <div class="muted small">{num(fOpen.length)} open · {num(fClosed.length)} closed (dropped / done) · children of <span class="mono">FRONTIER-RESEARCH</span>, in the route's order</div>
      {@render editor("frontier", "add", null, "+ Add an item to the frontier queue")}
      {#snippet fcard(it: any)}
        {@const f = it.extra?.frontier ?? {}}
        <div class="card">
          <div class="ch"><span class="st {stCls(it.state)}">{t(it.state).replaceAll("_", " ")}</span><span class="mono id">{it.id}</span>
            {#if it.priority_rank != null}<span class="muted small">rank {it.priority_rank}</span>{/if}</div>
          <div class="nm">{t(it.title)}</div>
          <div class="kv"><span class="k">Why it might beat what we have</span><span>{t(f.why)}</span></div>
          <div class="kv"><span class="k">Baseline it must beat</span><span>{t(f.baseline)}</span></div>
          <div class="kv"><span class="k">Consumer</span><span>{t(f.consumer)}</span></div>
          <div class="kv"><span class="k">Family · est. cost · p(pass)</span><span>{t(f.family)} · {t(f.est_cost)} · {t(f.p_pass)}</span></div>
          {#if f.next_step}<div class="kv"><span class="k">Next step</span><span>{f.next_step}</span></div>{/if}
          {#if f.blocking_lever}<div class="kv"><span class="k">Blocking lever</span><span>{f.blocking_lever}</span></div>{/if}
          <div class="muted small">unit {t(f.unit)} · unit state {t(f.state)} · {it.owner ?? DASH} · updated {it.updated_at ? agoFromIso(it.updated_at) : DASH}{#if (it.prs ?? []).length} · {it.prs.map((p: any) => `#${p}`).join(" ")}{/if}</div>
          {#if it.terminal_reason}<div class="muted small">closed: {it.terminal_reason}</div>{/if}
          {@render editor("frontier", "edit", it.id, "Suggest an edit")}
        </div>
      {/snippet}
      <div class="cards">{#each fOpen as it (it.id)}{@render fcard(it)}{/each}</div>
      {#if fClosed.length}
        <button class="link" onclick={() => (showClosed = !showClosed)}>{showClosed ? "▾ hide" : "▸ show"} {fClosed.length} closed</button>
        {#if showClosed}<div class="cards">{#each fClosed as it (it.id)}{@render fcard(it)}{/each}</div>{/if}
      {/if}
    {/if}

  {:else if view === "ml"}
    {#if !plan}
      {@render notAvail(mp, "ML plan")}
    {:else}
      <div class="muted small">
        read state {t(plan.read_state)} · work rows {t(plan.rows_read_state)}{plan.rows_error ? ` (${plan.rows_error})` : ""} ·
        {num(plan.population?.items)} plan items · {num(plan.population?.dev_plan_lines)} dev-plan lines · as of {plan.as_of ? agoFromIso(plan.as_of) : DASH}
      </div>
      {#if plan.rows_read_state !== "read"}
        <div class="na">The work rows were not read ({t(plan.rows_read_state)}), so each ref's state and the line flags are withheld (—), not guessed.</div>
      {/if}
      {@render editor("ml_plan", "add", null, "+ Add an item to the ML plan")}

      <h4>Plan items by track</h4>
      {#each itemGroups as [track, rows] (track)}
        <div class="grp">
          <div class="gh">Track {track} <span class="muted small">· {plan.population?.items_by_track?.[track] ?? DASH} items</span></div>
          <div class="scroll"><table>
            <thead><tr><th>Plan state</th><th>Item</th><th>Carried by</th><th>Closes when</th><th></th></tr></thead>
            <tbody>
              {#each rows as it (it.id)}
                <tr>
                  <td><span class="st {stCls(it.plan_state)}">{t(it.plan_state)}</span></td>
                  <td><span class="mono id">{it.id}</span><div>{t(it.title)}</div>
                    {#if it.family || it.tier != null}<div class="muted small">{t(it.family)} · tier {t(it.tier)}</div>{/if}</td>
                  <td class="small"><span class="mono">{t(it.ref)}</span> <span class="muted">({t(it.ref_kind)})</span>
                    <div>{it.ref_state ?? `— (${t(it.ref_read_state)})`}</div>
                    {#each it.flags ?? [] as f (f)}<span class="flag">{f}</span>{/each}</td>
                  <td class="small cw">{t(it.closes_when)}</td>
                  <td class="small">
                    {#if it.ref_kind === "row" && it.ref}
                      {@render editor("ml_plan", "edit", it.ref, "Suggest an edit")}
                    {:else}
                      <span class="muted" title="Edits attach to a work-store row; this item is carried by a {t(it.ref_kind)}">edit via its line below, or Add</span>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table></div>
        </div>
      {/each}

      <h4>Development plan lines <span class="muted sub">· {t(plan.dev_plan?.source)}, updated {t(plan.dev_plan?.updated)}</span></h4>
      {#if !lines.length}<div class="na">No dev-plan lines in the payload.</div>{/if}
      {#each lineGroups as [track, rows] (track)}
        <div class="grp">
          <div class="gh">Track {track}</div>
          {#each rows as ln (ln.id)}
            <div class="line">
              <div class="ch">
                <span class="st {stCls(ln.stage)}">{t(ln.stage).replaceAll("_", " ")}</span>
                <span class="mono id">{ln.id}</span>
                {#if ln.slot}<span class="muted small">slot {ln.slot}</span>{/if}
                <span class="muted small">{t(ln.kind).replaceAll("_", " ")} · {t(ln.owner)}</span>
                {#if ln.flags === null}<span class="muted small">flags — (rows not read)</span>
                {:else}{#each ln.flags ?? [] as f (f)}<span class="flag">{f}</span>{/each}{/if}
                {#each ln.info ?? [] as f (f)}<span class="flag info">{f}</span>{/each}
              </div>
              {#if ln.subject}<div class="nm">{ln.subject}</div>{/if}
              <div class="small">{t(ln.summary)}</div>
              <div class="muted small">row <span class="mono">{t(ln.row)}</span> · {ln.row_state ?? "row state —"}{#if ln.row_updated_at} · moved {agoFromIso(ln.row_updated_at)}{/if}</div>
              <button class="link" onclick={() => (openLine = { ...openLine, [ln.id]: !openLine[ln.id] })}>{openLine[ln.id] ? "▾ less" : "▸ levers, next weeks, exhaustion"}</button>
              {#if openLine[ln.id]}
                {#if (ln.levers_ahead ?? []).length}
                  <div class="k">Levers ahead</div>
                  {#each ln.levers_ahead as lv, i (i)}
                    <div class="lever small">
                      <div><b>{t(lv.lever)}</b> <span class="muted mono">{t(lv.ref)}</span></div>
                      <div><span class="k">baseline</span> {t(lv.baseline)}</div>
                      <div><span class="k">pass</span> {t(lv.pass)} · <span class="k">fail</span> {t(lv.fail)}</div>
                    </div>
                  {/each}
                {/if}
                {#if (ln.levers_tried ?? []).length}
                  <div class="k">Levers tried</div>
                  {#each ln.levers_tried as lv, i (i)}<div class="lever small">{typeof lv === "string" ? lv : JSON.stringify(lv)}</div>{/each}
                {/if}
                {#if ln.next_weeks && Object.keys(ln.next_weeks).length}
                  <div class="k">Next weeks</div>
                  <table class="wk"><tbody>
                    {#each Object.entries(ln.next_weeks) as [w, v] (w)}<tr><td class="mono small">{w}{weeks[w] ? ` · ${weeks[w]}` : ""}</td><td class="small">{t(v)}</td></tr>{/each}
                  </tbody></table>
                {/if}
                <div class="small"><span class="k">Exhausted when</span> {t(ln.exhaustion)}</div>
                {#if ln.proposed_disposition}<div class="small"><span class="k">Proposed disposition</span> {typeof ln.proposed_disposition === "string" ? ln.proposed_disposition : JSON.stringify(ln.proposed_disposition)}</div>{/if}
              {/if}
              {#if ln.row}{@render editor("ml_plan", "edit", ln.row, "Suggest an edit")}{/if}
            </div>
          {/each}
        </div>
      {/each}

      {#if (plan.dev_plan?.graded_today ?? []).length}
        <h4>Graded today</h4>
        <ul class="small">
          {#each plan.dev_plan.graded_today as g, i (i)}<li><span class="mono">{t(g.unit)}</span> · {t(g.verdict)}{g.pr ? ` · #${g.pr}` : ""}{g.note ? ` · ${g.note}` : ""}</li>{/each}
        </ul>
      {/if}
      {#if (plan.dev_plan?.labelled_gates_not_planned ?? []).length}
        <h4>Labelled gates, not planned</h4>
        <ul class="small">
          {#each plan.dev_plan.labelled_gates_not_planned as g, i (i)}<li><span class="mono">{t(g.id)}</span> {t(g.text)} · <span class="muted">{t(g.status)}</span></li>{/each}
        </ul>
      {/if}
    {/if}

  {:else}
    {#if ed.status !== 200 || ed.body?.readState !== "read"}
      {#if ed.status === 200}
        <div class="na">Adds & edits: could not look ({ed.body?.readState ?? DASH}{ed.body?.error ? `: ${ed.body.error}` : ""})</div>
      {:else}{@render notAvail(ed, "Adds & edits")}{/if}
    {:else}
      <div class="muted small">
        {num(edits.length)} plan adds/edits among the newest {num(edRows.length)} observation rows
        {oldest ? `(back to ${String(oldest).slice(0, 16).replace("T", " ")}Z)` : ""}
      </div>
      {#if !edits.length}
        <div class="na">No plan adds or edits in that window.</div>
      {:else}
        <div class="scroll"><table>
          <thead><tr><th>Status</th><th>Your add / edit</th><th>Owner</th><th>Reply</th><th>Filed</th></tr></thead>
          <tbody>
            {#each edits as r (r.id)}
              {@const pe = r.extra.plan_edit}
              <tr>
                <td><span class="st {stCls(r.state)}">{t(pe.status)}</span><div class="muted small">row {t(r.state).replaceAll("_", " ")}</div></td>
                <td><div class="muted small">{t(pe.kind)} · {t(pe.section)}{pe.item_id ? ` · on ${pe.item_id}` : ""}</div><div class="nt">{t(pe.text)}</div><div class="mono id">{r.id}</div></td>
                <td class="small">{t(r.owner)}</td>
                <td class="small nt">{t(pe.reply)}{#if r.terminal_reason}<div class="muted">closed: {r.terminal_reason}</div>{/if}</td>
                <td class="muted small" title={r.created_at ?? ""}>{r.created_at ? agoFromIso(r.created_at) : DASH}</td>
              </tr>
            {/each}
          </tbody>
        </table></div>
      {/if}
    {/if}
  {/if}
</section>

<style>
  .pl { display: flex; flex-direction: column; gap: 8px; }
  h3, h4 { margin: 0; }
  h4 { margin-top: 8px; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  .bar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  button, textarea { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  button { cursor: pointer; }
  button:disabled { opacity: 0.4; cursor: default; }
  .pri { border-color: var(--accent, #4c8dff); }
  .tab.on { border-color: var(--accent, #4c8dff); background: #4c8dff22; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); padding: 0; font-size: 12px; align-self: flex-start; text-align: left; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .form { display: flex; flex-direction: column; gap: 6px; }
  textarea { width: 100%; box-sizing: border-box; font-family: inherit; }
  .ans { font-size: 12px; border-left: 3px solid #30a46c; padding: 3px 8px; overflow-wrap: anywhere; }
  .ans.bad { border-left-color: #e5484d; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 5px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 12px; }
  .cw { max-width: 360px; overflow-wrap: anywhere; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 8px; }
  .card, .line { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 3px; }
  .line { margin-bottom: 6px; }
  .grp { display: flex; flex-direction: column; gap: 4px; }
  .gh { font-weight: 600; font-size: 13px; }
  .ch { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .nm { overflow-wrap: anywhere; }
  .id { color: var(--muted); font-size: 12px; }
  .kv { display: flex; flex-direction: column; font-size: 12.5px; }
  .k { color: var(--muted); font-size: 11.5px; }
  .lever { border-left: 2px solid var(--border); padding-left: 8px; margin: 2px 0; }
  .wk { width: auto; }
  .nt { white-space: pre-wrap; overflow-wrap: anywhere; }
  .flag { font-size: 10.5px; padding: 0 6px; border-radius: 6px; border: 1px solid #d4a01766; color: #d4a017; margin-right: 4px; }
  .flag.info { border-color: var(--border); color: var(--muted); }
  .st { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; border: 1px solid var(--border); }
  .st.fl { color: #4c8dff; border-color: #4c8dff66; }
  .st.bl { color: #e5484d; border-color: #e5484d66; }
  .st.dn { color: #30a46c; border-color: #30a46c66; }
  .st.dr, .st.ot { color: var(--muted); }
</style>
