<script lang="ts">
  // The live WORKFLOW page — the manager checklist and the decisions waiting on
  // the operator, in one place.
  //
  // Operator, 2026-09-10: "that will be the live workflow page that all the
  // manager sessions are supposed to use so that we can stay organized about
  // how we're working, and I can track the progress of the sessions as you're
  // going" — and it must be "the same as the document in the repo that you're
  // working on".
  //
  // ⚠️ THE ONE RULE THAT DECIDES THIS FILE'S DESIGN: **this page does NOT merge
  // `state` and `status`.** `docs/claude/work/MANAGER-CHECKLIST.json` carries
  // two competing status fields — MEASURED 2026-09-10 over all 244 items: 179
  // carry `state`, 83 carry `status`, 18 carry both and 13 of those DISAGREE.
  // A merge written here would become a SECOND definition of an item's status,
  // free to drift from the one `scripts/ci/check_manager_scope.py` and
  // `scripts/ops/manager_view.py` read. The bot owns it
  // (`manager_status.effective_state`) and ships `status.value` beside
  // `status.basis`; this file RENDERS both and decides neither. If you find
  // yourself reaching for `fields.state` or `fields.status` here, stop.
  //
  // ⚠️ AND THE PAGE MUST SHOW ITS OWN AGE. It reads the VM's working tree,
  // which `ict-git-sync` pulls roughly every 5 minutes, so it is exactly as
  // fresh as the last PUSH plus that interval. A page serving a three-hour-old
  // checklist must not read identically to a live one — that is the failure the
  // coordination board hit on 2026-09-07, where a frozen board served reads
  // byte-identically to a working one for ~20h.
  //
  // Read-only. Answering a decision happens in Telegram or via the token-gated
  // POST route; nothing here writes.
  import { onMount } from "svelte";
  import { api } from "../lib/api";

  let checklist = $state<any | null>(null);
  let decisions = $state<any | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});
  let openDecision = $state<Record<string, boolean>>({});
  let showDone = $state(false);

  const fresh = $derived(checklist?.freshness ?? null);
  // Named for its SOURCE, not just "summary": the decision inbox has a
  // summary too, and one alias covering both is how a reader (and the
  // api-contract checker) ends up resolving a field against the wrong
  // payload.
  const chk = $derived(checklist?.summary ?? null);
  const dec = $derived(decisions?.summary ?? null);
  const items = $derived<any[]>(checklist?.items ?? []);
  const declared = $derived<Record<string, string>>(checklist?.declaredStates ?? {});

  // Declared order, never alphabetical — the vocabulary encodes a progression
  // and sorting by name would scramble the one thing it carries. Anything the
  // file uses but this list does not name sorts last under its own heading,
  // rather than being folded into a bucket nobody chose for it.
  const ORDER = [
    "in_flight", "blocked", "ready", "queued", "triage",
    "landed_unproven", "done", "dropped",
  ];
  // What is not day-to-day attention. Collapsed behind a toggle so the page
  // opens on what is moving, WITHOUT hiding that the rest exists — the count is
  // always on the toggle.
  const QUIET = new Set(["done", "dropped"]);

  const groups = $derived.by(() => {
    const by = new Map<string, any[]>();
    for (const it of items) {
      const key = it?.status?.value ?? "(no status declared)";
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(it);
    }
    return [...by.entries()].sort((a, b) => {
      const ia = ORDER.indexOf(a[0]);
      const ib = ORDER.indexOf(b[0]);
      return (ia < 0 ? ORDER.length : ia) - (ib < 0 ? ORDER.length : ib)
        || a[0].localeCompare(b[0]);
    });
  });

  const quietCount = $derived(
    groups.filter(([k]) => QUIET.has(k)).reduce((n, [, v]) => n + v.length, 0),
  );
  const openRequests = $derived<any[]>(
    (decisions?.requests ?? []).filter((r: any) => r.answerState !== "committed"),
  );
  const edges = $derived<any[]>(decisions?.unanswerableOperatorEdges ?? []);

  async function load() {
    loading = true;
    error = null;
    try {
      // Settled independently: a decision-inbox failure must not blank the
      // checklist, and vice versa. They are two different questions and one
      // being unreadable is not evidence about the other.
      const [c, d] = await Promise.allSettled([
        api.workChecklist(),
        api.workDecisions(),
      ]);
      if (c.status === "fulfilled") checklist = c.value;
      else error = c.reason instanceof Error ? c.reason.message : String(c.reason);
      decisions = d.status === "fulfilled" ? d.value : null;
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function age(h: number | null | undefined): string {
    if (h == null) return "age unknown";
    if (h < 1) return `${Math.round(h * 60)}m ago`;
    if (h < 48) return `${h.toFixed(1)}h ago`;
    return `${(h / 24).toFixed(1)}d ago`;
  }

  // The fields already shown on the summary line or handled explicitly. Every
  // OTHER key is rendered verbatim on expansion — the checklist's keys are
  // free-form prose and an allowlist would silently drop exactly the detail the
  // operator opened the row to read.
  const SHOWN = new Set(["id", "title", "owner", "lane", "tier", "priority",
                         "state", "status"]);
  function rest(f: Record<string, any>): [string, any][] {
    return Object.entries(f ?? {}).filter(([k]) => !SHOWN.has(k));
  }
  function text(v: any): string {
    return typeof v === "string" ? v : JSON.stringify(v, null, 2);
  }
</script>

<section>
  <div class="head">
    <h2>Workflow</h2>
    <button class="reload" onclick={load} disabled={loading}>
      {loading ? "Loading…" : "Refresh"}
    </button>
  </div>

  <!-- ── THE AS-OF STAMP. Never optional: a stale page must announce itself. ── -->
  {#if fresh}
    <div class="panel stamp" class:stale={fresh.warnings?.length}>
      <div class="stamprow">
        <span class="lbl">Checklist as of</span>
        <span class="val">{age(fresh.commitAgeHours)}</span>
        {#if fresh.committedAt}
          <span class="muted mono">{fresh.committedAt}</span>
        {/if}
        {#if fresh.commitSha}<span class="muted mono">· {fresh.commitSha}</span>{/if}
      </div>
      <div class="sub">
        This page reads the trader VM's working tree, which <span class="mono">ict-git-sync</span>
        pulls roughly every 5 minutes — so it is exactly as fresh as a manager's last
        <strong>push</strong>, plus that interval. There is no separate "update the page" step.
      </div>
      {#each fresh.warnings ?? [] as w}
        <div class="warnline">⚠️ {w}</div>
      {/each}
      {#if fresh.warnings && fresh.warnings.length === 0}
        <div class="okline">
          ✓ Tree <span class="mono">{fresh.treeState}</span>, working copy matches its last commit.
          <span class="muted">(These conditions were checked — this is not a claim the content is correct.)</span>
        </div>
      {/if}
    </div>
  {/if}

  {#if error}
    <div class="panel err">
      Couldn't load the checklist: <span class="mono">{error}</span>
    </div>
  {:else if loading && !checklist}
    <div class="muted pad">Loading…</div>
  {:else if checklist && checklist.present === false}
    <!-- present:false is a DEGRADED read, NOT an empty checklist. Say which. -->
    <div class="panel err">
      <strong>The checklist could not be read ({checklist.readState}).</strong>
      {#if checklist.reason}<div class="sub mono">{checklist.reason}</div>{/if}
      <div class="sub">
        This is <em>not</em> the same as there being no work in flight. Nothing below
        should be read as a statement about what managers are doing.
      </div>
    </div>
  {/if}

  <!-- ── DECISIONS WAITING ON THE OPERATOR — above the checklist, by request ── -->
  <div class="panel dec">
    <h3>Waiting on you</h3>
    {#if !decisions}
      <p class="muted">
        The decision inbox could not be read. That is <em>not</em> a statement that
        nothing is waiting.
      </p>
    {:else}
      {#if openRequests.length === 0 && edges.length === 0}
        <p class="muted">
          Nothing is waiting on you right now.
          <span class="mono">{dec?.decided ?? 0}</span> answered decision(s)
          are on record.
        </p>
      {/if}

      {#each openRequests as r (r.objectId + r.id)}
        <div class="drow" class:blocking={r.urgency === "blocking"}>
          <button class="dh" onclick={() => (openDecision = { ...openDecision, [r.id]: !openDecision[r.id] })}>
            <span class="pill ans-{r.answerState}">{(r.answerState ?? "").replace("_", " ")}</span>
            {#if r.urgency}<span class="pill urg">{r.urgency}</span>{/if}
            <span class="q">{r.question}</span>
            <span class="chev">{openDecision[r.id] ? "▾" : "▸"}</span>
          </button>
          {#if openDecision[r.id]}
            <div class="ddetail">
              <div class="muted mono small">{r.objectId} · {r.id}</div>
              {#if r.objectTitle}<p class="ttl">{r.objectTitle}</p>{/if}
              {#if r.context}<h4>Context</h4><p>{r.context}</p>{/if}
              {#if r.options?.length}
                <h4>Options</h4>
                <ul>
                  {#each r.options as o}
                    <li><strong>{o.label ?? o.key}</strong>
                      {#if o.implication}<div class="muted">{o.implication}</div>{/if}
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="warnline">
                  ⚠️ This request declares no options, so it cannot be answered with a
                  button — it needs a written answer in the repo.
                </p>
              {/if}
              {#if r.answerState === "in_transit"}
                <p class="warnline">
                  Submitted, <strong>not yet decided</strong> — the answer becomes a decision
                  only when it is committed into the work object.
                </p>
              {/if}
            </div>
          {/if}
        </div>
      {/each}

      {#if edges.length}
        <!-- Deliberately counted apart from the answerable requests: this is a
             question the operator is blocking on that they CANNOT answer from
             any UI, because nobody wrote it down as a request. Folding the two
             together would hide exactly that gap. -->
        <h4 class="gap">Blocking you, with no answerable request attached ({edges.length})</h4>
        <ul class="edges">
          {#each edges as e}
            <li>
              <span class="mono small">{e.objectId}</span>
              {#if e.objectTitle}<div class="ttl">{e.objectTitle}</div>{/if}
              <div class="muted">{e.ref}</div>
              {#if e.since}<div class="muted small">since {e.since}</div>{/if}
            </li>
          {/each}
        </ul>
      {/if}

      {#if decisions.writeGate && decisions.writeGate.acceptsWrites === false}
        <div class="sub muted">
          Answering from the UI is currently closed
          (<span class="mono">{decisions.writeGate.state}</span>). Decisions are answered
          in Telegram or committed in the repo.
        </div>
      {/if}
    {/if}
  </div>

  <!-- ── THE CHECKLIST ──────────────────────────────────────────────────── -->
  {#if checklist?.present}
    <div class="panel roll">
      <div class="chips">
        {#each groups as [k, v] (k)}
          <span class="chip" class:hot={k === "in_flight"} class:blk={k === "blocked"}>
            <b>{v.length}</b> {k}
          </span>
        {/each}
      </div>
      <div class="stats muted">
        {chk?.total ?? 0} item(s) · cycle <span class="mono">{checklist.cycle ?? "—"}</span>
        {#if checklist.managerSession}
          · manager <span class="mono">…{String(checklist.managerSession).slice(-6)}</span>
        {/if}
      </div>

      <!-- The two-fields finding, surfaced rather than smoothed over. -->
      {#if chk?.disagreeing}
        <div class="warnline">
          ⚠️ {chk.disagreeing} item(s) declare a <span class="mono">state</span> and a
          <span class="mono">status</span> that <strong>disagree</strong>. They are grouped by
          <span class="mono">state</span> — what every other consumer of this file reads — and
          flagged on the row. That is a rule for picking a value, <em>not</em> a finding that
          <span class="mono">status</span> is wrong; neither field was edited.
        </div>
      {/if}
      {#if chk?.statusOnly}
        <div class="sub muted">
          {chk.statusOnly} item(s) declare only <span class="mono">status</span> and no
          <span class="mono">status</span>-less <span class="mono">state</span>. Nothing else in
          the repo reads <span class="mono">status</span> on this file, so those rows are
          invisible to the Telegram <span class="mono">/status</span> sections — they appear here.
        </div>
      {/if}
    </div>

    {#each groups as [k, rows] (k)}
      {#if !QUIET.has(k) || showDone}
        <div class="grp">
          <h3 class="gh">
            <span class="pill st-{k}">{k}</span>
            <span class="n">{rows.length}</span>
            {#if declared[k]}<span class="muted def">{declared[k]}</span>{/if}
          </h3>
          {#each rows as it (it.id ?? it.title)}
            <div class="row" class:dis={it.status?.disagrees}>
              <button class="rh" onclick={() => (open = { ...open, [it.id]: !open[it.id] })}>
                <span class="pill st-{k}">{it.status?.value ?? "no status"}</span>
                <span class="id">{it.id ?? "(no id)"}</span>
                <span class="ttl2">{it.title ?? "(no title declared)"}</span>
                {#if it.lane}<span class="meta">{it.lane}</span>{/if}
                {#if it.tier != null}<span class="meta">T{it.tier}</span>{/if}
                <span class="meta own" title={it.ownerGrade}>{it.ownerRendered ?? "—"}</span>
                <span class="chev">{open[it.id] ? "▾" : "▸"}</span>
              </button>
              {#if open[it.id]}
                <div class="detail">
                  <!-- Provenance FIRST: how this row's status was arrived at is
                       not inferable from the value, and a contested row must
                       not read as a settled one. -->
                  <div class="basis" class:warn={it.status?.disagrees}>
                    <span class="mono">{it.status?.basis}</span> — {it.status?.note}
                    {#if it.status?.declaredState || it.status?.declaredStatus}
                      <div class="muted small">
                        declared <span class="mono">state</span>: {it.status.declaredState ?? "—"}
                        · <span class="mono">status</span>: {it.status.declaredStatus ?? "—"}
                      </div>
                    {/if}
                    {#if it.status?.inDeclaredVocabulary === false && it.status?.value}
                      <div class="muted small">
                        <span class="mono">{it.status.value}</span> is not in the checklist's own
                        <span class="mono">states</span> block — shown verbatim, never remapped.
                      </div>
                    {/if}
                    {#if it.sectioned === false}
                      <div class="muted small">
                        No <span class="mono">/status</span> section covers this status, so this row
                        does not appear in the Telegram readout's sections.
                      </div>
                    {/if}
                  </div>
                  {#if it.owner}
                    <h4>Owner</h4>
                    <p>{it.owner} <span class="muted">({it.ownerGrade})</span></p>
                  {/if}
                  {#each rest(it.fields) as [k2, v] (k2)}
                    <h4>{k2}</h4>
                    <p>{text(v)}</p>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    {/each}

    {#if quietCount}
      <button class="toggle" onclick={() => (showDone = !showDone)}>
        {showDone ? "Hide" : "Show"} {quietCount} done / dropped item(s)
      </button>
    {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  h3 { margin: 0 0 8px; font-size: 14px; }
  h4 { margin: 12px 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); word-break: break-word; }
  .reload { background: var(--panel-2); border: none; color: var(--text); border-radius: 6px; padding: 6px 12px; cursor: pointer; font-size: 12.5px; }
  .reload:disabled { opacity: .5; cursor: default; }
  .sub { font-size: 12.5px; color: var(--muted); margin-top: 6px; line-height: 1.5; }
  .small { font-size: 11.5px; }
  .pad { padding: 12px; }
  .err { padding: 12px 14px; border-left: 3px solid var(--err, #c0392b); }
  .stamp { padding: 12px 14px; border-left: 3px solid var(--ok, #2f9e44); }
  .stamp.stale { border-left-color: var(--warn, #d19a2f); }
  .stamprow { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; font-size: 13px; }
  .lbl { color: var(--muted); }
  .val { font-weight: 600; font-size: 15px; }
  .warnline { color: var(--warn, #d19a2f); font-size: 12.5px; margin-top: 6px; line-height: 1.5; }
  .okline { color: var(--muted); font-size: 12.5px; margin-top: 6px; }
  .dec { padding: 14px; }
  .drow { border-top: 1px solid var(--panel-2); }
  .drow.blocking .q { color: var(--text); font-weight: 600; }
  .dh { display: flex; gap: 10px; align-items: baseline; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 10px 0; cursor: pointer; font-size: 13px; }
  .q { flex: 1; line-height: 1.45; }
  .ddetail { padding: 0 0 12px; font-size: 13px; line-height: 1.55; }
  .ddetail p, .ddetail ul { margin: 0; color: var(--muted); }
  .ddetail ul { padding-left: 18px; }
  .ddetail li { margin-bottom: 6px; }
  .ttl { font-size: 13px; margin: 4px 0; }
  .edges { padding-left: 18px; font-size: 12.5px; }
  .edges li { margin-bottom: 8px; }
  .gap { margin-top: 14px; color: var(--warn, #d19a2f); }
  .roll { padding: 14px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { background: var(--panel-2); border-radius: 5px; padding: 4px 9px; font-size: 12.5px; }
  .chip.hot { background: var(--accent); color: #fff; }
  .chip.blk { background: var(--warn, #d19a2f); color: #fff; }
  .stats { font-size: 12.5px; margin-top: 10px; }
  .grp { display: flex; flex-direction: column; gap: 4px; }
  .gh { display: flex; gap: 10px; align-items: baseline; margin: 10px 0 2px; }
  .gh .n { color: var(--muted); font-size: 12.5px; }
  .def { font-size: 12px; font-weight: 400; }
  .pill { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 2px 7px; border-radius: 4px; background: var(--panel-2); color: var(--muted); white-space: nowrap; }
  .st-in_flight { background: var(--accent); color: #fff; }
  .st-blocked { background: var(--warn, #d19a2f); color: #fff; }
  .ans-not_submitted { background: var(--warn, #d19a2f); color: #fff; }
  .urg { background: var(--panel-2); }
  .row { background: var(--panel); border-radius: 6px; overflow: hidden; }
  .row.dis { box-shadow: inset 3px 0 0 var(--warn, #d19a2f); }
  .rh { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 9px 12px; cursor: pointer; font-size: 13px; }
  .id { font-weight: 600; white-space: nowrap; max-width: 190px; overflow: hidden; text-overflow: ellipsis; }
  .ttl2 { flex: 1; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta { font-size: 11.5px; color: var(--muted); white-space: nowrap; }
  .own { font-family: ui-monospace, monospace; }
  .chev { color: var(--muted); }
  .detail { padding: 0 12px 14px; font-size: 13px; line-height: 1.55; }
  .detail p { margin: 0; white-space: pre-wrap; color: var(--muted); word-break: break-word; }
  .basis { background: var(--panel-2); border-radius: 5px; padding: 8px 10px; font-size: 12.5px; color: var(--muted); margin-bottom: 10px; }
  .basis.warn { color: var(--warn, #d19a2f); }
  .toggle { align-self: flex-start; background: var(--panel-2); border: none; color: var(--muted); border-radius: 6px; padding: 7px 12px; cursor: pointer; font-size: 12.5px; }
  .mono { font-family: ui-monospace, monospace; }
</style>
