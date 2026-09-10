<script lang="ts">
  // The read-only work view — Phase B of the operating-layer build.
  //
  // Renders `docs/claude/work/` (intents → objects → steps) so the operator can
  // see what is in flight without opening the repo.
  //
  // ⚠️ THREE THINGS THIS VIEW MUST NOT SMOOTH OVER, because the API goes to
  // deliberate trouble to keep them apart and a renderer is where that care
  // usually gets thrown away:
  //
  //   1. `coverage.complete` is false. The store holds the operating-layer
  //      build's own phases and NOT the ~572 carried backlog rows (they migrate
  //      in Phase C). The banner below is not decoration — without it this page
  //      reads as "the system has 8 things to do", which is false.
  //   2. `wip.enforced` is false. The ceiling of 8 is DECLARED, not enforced, so
  //      "2 / 8" must not render like a limit that is being kept. It is a
  //      reading.
  //   3. `blockedOnState` distinguishes `declared_none` (the object CLAIMS
  //      nothing blocks it) from `unstated` (nobody has said). Rendering both as
  //      a blank cell is how a false "ready" appears.
  //
  // READ-ONLY BY DESIGN. Answering a decision from here is Phase H, together
  // with the read gate — that split is what keeps this half cheap.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num } from "../lib/format";

  let raw = $state<any | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let checklistError = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  const summary = $derived(raw?.summary ?? null);
  const coverage = $derived(raw?.coverage ?? null);
  const wip = $derived(raw?.wip ?? null);
  const lifecycle = $derived(raw?.lifecycle ?? null);
  const objects = $derived<any[]>(raw?.objects ?? []);
  const intents = $derived<any[]>(raw?.intents ?? []);
  const readErrors = $derived<any[]>(raw?.readErrors ?? []);

  // Declared order, never alphabetical — these are a progression, and sorting
  // them by name would scramble the one thing the vocabulary encodes.
  const STATES = ["in_flight", "ready", "waiting", "dormant", "done", "accepted", "unknown"];
  const STATE_LABEL: Record<string, string> = {
    in_flight: "in flight",
    ready: "ready",
    waiting: "waiting",
    dormant: "dormant",
    done: "done",
    accepted: "accepted",
    unknown: "ungradeable",
  };


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

  let checklist = $state<any | null>(null);
  let decisions = $state<any | null>(null);
  // `loading`, `error` and `open` are declared once, above, and shared: this
  // is ONE page over three registers, not three pages in a trench coat.
  let openDecision = $state<Record<string, boolean>>({});
  let showDone = $state(false);

  const fresh = $derived(checklist?.freshness ?? null);
  // Named for its SOURCE, not just "summary": the decision inbox has a
  // summary too, and one alias covering both is how a reader (and the
  // api-contract checker) ends up resolving a field against the wrong
  // payload.
  const chk = $derived(checklist?.summary ?? null);
  const dec = $derived(decisions?.summary ?? null);
  const sess = $derived(checklist?.sessions ?? null);
  const lanes = $derived<any[]>(sess?.lanes ?? []);
  // Named apart for the same reason `chk` and `dec` are: three payloads each
  // have a `summary`, and one alias covering several is how a reader (and the
  // api-contract checker) resolves a field against the wrong one.
  const ssum = $derived(sess?.summary ?? null);
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
  // ⚠️ `settled` COMES FROM THE BOT — do not re-derive it here. This filter
  // used to read `answerState !== "committed"`, which was a SECOND definition
  // of "answered" living in TypeScript. It missed every decision answered IN
  // CONVERSATION (recorded as `verdict`, not as an `answer` block), so three
  // questions the operator settled at 07:52Z on 2026-09-10 kept showing as
  // waiting on them. `work_decisions.SETTLED_STATES` is the one owner.
  //
  // ⚠️ THREE STATES, NEVER TWO. `settled` is ABSENT on a bot that predates
  // MI-254, and a strict `=== false` / `=== true` pair sends those rows to
  // NEITHER bucket — they disappear from the page with no trace. MEASURED
  // 2026-09-10 against the live API before the bot half deployed: all 26
  // decisions vanished, and because one unanswerable edge was present the
  // "Nothing is waiting" empty-state did not fire either, so the panel read
  // as populated while the inbox was silently empty. That is the exact
  // collapsed-state failure this page exists to prevent, committed by the
  // page itself. `ungraded` is "WE COULD NOT TELL", never "answered".
  const isSettled = (r: any) =>
    r?.settled === true ? "yes" : r?.settled === false ? "no" : "ungraded";
  // Ungraded rows ride WITH the waiting ones, deliberately: showing a
  // possibly-answered decision costs the operator a glance, hiding a
  // genuinely-waiting one is the defect MI-254 exists to fix. Fail toward
  // surfacing.
  const waiting = $derived<any[]>(
    (decisions?.requests ?? []).filter((r: any) => isSettled(r) !== "yes"),
  );
  const ungraded = $derived<any[]>(
    (decisions?.requests ?? []).filter((r: any) => isSettled(r) === "ungraded"),
  );
  // Answered rows are SHOWN, not hidden: the operator needs to see what they
  // decided and under what CONDITION, and this page is the one surface they
  // read. Hiding them would lose that record here.
  const answered = $derived<any[]>(
    (decisions?.requests ?? []).filter((r: any) => isSettled(r) === "yes"),
  );
  let showAnswered = $state(false);
  const edges = $derived<any[]>(decisions?.unanswerableOperatorEdges ?? []);


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

  async function load() {
    loading = true;
    error = null;
    // Settled INDEPENDENTLY, deliberately: the work store, the manager
    // checklist and the decision inbox are three different registers, and one
    // being unreadable is not evidence about the others. A single try/catch
    // would blank all three on any one failure.
    const [store, ck, dc] = await Promise.allSettled([
      api.work(), api.workChecklist(), api.workDecisions(),
    ]);
    if (store.status === "fulfilled") raw = store.value;
    else error = store.reason instanceof Error
      ? store.reason.message : String(store.reason);
    checklist = ck.status === "fulfilled" ? ck.value : null;
    checklistError = ck.status === "rejected"
      ? (ck.reason instanceof Error ? ck.reason.message : String(ck.reason))
      : null;
    decisions = dc.status === "fulfilled" ? dc.value : null;
    loading = false;
  }
  onMount(load);

  function blockedLabel(o: any): string {
    // Each state says a DIFFERENT thing. None of them is "blank".
    if (o?.blockedOnState === "declared") {
      return `${o.blockedOn?.length ?? 0} edge${(o.blockedOn?.length ?? 0) === 1 ? "" : "s"}`;
    }
    if (o?.blockedOnState === "declared_none") return "claims nothing blocks";
    if (o?.blockedOnState === "unstated") return "not stated";
    if (o?.blockedOnState === "malformed") return "malformed";
    return "—";
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
          <!--
            ⚠️ `synced` ON ITS OWN IS THE LINE THAT MISLED A READER (MI-262,
            2026-09-10). It compares the VM's HEAD against its LOCAL
            origin/main ref, and the VM's sync does `git fetch` then
            `git reset --hard origin/main` — so the equality holds BY
            CONSTRUCTION and carries no information about currency. Measured
            that day: this line read `synced` while the VM was genuinely one
            commit behind GitHub. All of the staleness is in WHEN IT LAST
            LOOKED, so that is now rendered beside the verdict rather than
            left in a `stamp` field nothing displays.
          -->
          {#if fresh.mainRefAgeHours != null}
            Level with <span class="mono">main</span> as of a fetch
            <strong>{age(fresh.mainRefAgeHours)}</strong> — it may have moved since.
          {:else}
            <span class="muted">When it last fetched is <strong>not known here</strong>, so
            "{fresh.treeState}" cannot say how current it is — this bot may predate the field.</span>
          {/if}
          <span class="muted">(These conditions were checked — this is not a claim the content is correct.)</span>
        </div>
      {/if}
    </div>
  {/if}

  {#if checklistError}
    <div class="panel err">
      Couldn't load the checklist: <span class="mono">{checklistError}</span>
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
      {#if ungraded.length}
        <p class="warnline">
          ⚠️ <strong>{ungraded.length} of {waiting.length}</strong> row(s) below are shown
          because this bot could not say whether they are settled — it predates the
          field, so an answer you gave in conversation would not be reflected here.
          They are surfaced rather than hidden: a decision that may be waiting must
          not disappear. This clears itself once the trader picks up the bot-side
          change (<span class="mono">git-sync</span>, ~5 min after it merges).
        </p>
      {/if}

      {#if waiting.length === 0 && edges.length === 0}
        <p class="muted">
          Nothing is waiting on you right now.
          <span class="mono">{dec?.decided ?? 0}</span> answered decision(s)
          are on record —
          <span class="mono">{dec?.decidedViaRoute ?? 0}</span> through this
          channel and
          <span class="mono">{dec?.decidedInConversation ?? 0}</span> in
          conversation.
        </p>
      {/if}

      {#each waiting as r (r.objectId + r.id)}
        <div class="drow" class:blocking={r.urgency === "blocking"}>
          <button class="dh" onclick={() => (openDecision = { ...openDecision, [r.id]: !openDecision[r.id] })}>
            <span class="pill ans-{r.answerState}">{(r.answerState ?? "").replace("_", " ")}</span>
            {#if r.urgency}<span class="pill urg">{r.urgency}</span>{/if}
            {#if r.settled == null}<span class="pill ungraded" title="This bot did not report whether the decision is settled — not a claim that it is open.">settled?</span>{/if}
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
                  {#each r.options as opt}
                    <li><strong>{opt.label ?? opt.key}</strong>
                      {#if opt.implication}<div class="muted">{opt.implication}</div>{/if}
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="warnline">
                  ⚠️ This request declares no options, so it cannot be answered with a
                  button — it needs a written answer in the repo.
                </p>
              {/if}
              {#if r.answerStateNote}
                <p class="statenote" class:warnline={r.settled === false}>{r.answerStateNote}</p>
              {:else if r.settled == null}
                <p class="statenote warnline">
                  This bot reported no settled/unsettled grade for this request, so
                  whether it is still waiting on you is <em>unknown here</em> — read the
                  work object to be sure.
                </p>
              {/if}
              {#if r.conversationalAnswer}
                {@const ca = r.conversationalAnswer}
                <h4>Your answer</h4>
                <p>
                  <span class="mono">{ca.verdict}</span>{#if ca.chosen} → <strong>{ca.chosen}</strong>{/if}
                  {#if ca.answeredAt}<span class="muted"> · {ca.answeredAt}</span>{/if}
                </p>
                {#if ca.condition}
                  <!-- ⚠️ NEVER DROPPED. A verdict recorded without its
                       condition reads as complete when it is not — OPEN-PRS's
                       own doctrine, and hiding it here would put that failure
                       on the operator's own screen. -->
                  <h4 class="cond">Condition you attached</h4>
                  <p class="warnline">{ca.condition}</p>
                {/if}
                {#if ca.text}<h4>What you said</h4><p>{ca.text}</p>{/if}
              {/if}
            </div>
          {/if}
        </div>
      {/each}

      {#if answered.length}
        <button class="toggle ansToggle" onclick={() => (showAnswered = !showAnswered)}>
          {showAnswered ? "Hide" : "Show"} {answered.length} answered decision(s)
        </button>
        {#if showAnswered}
          {#each answered as r (r.objectId + r.id)}
            <div class="drow ansrow">
              <button class="dh" onclick={() => (openDecision = { ...openDecision, [r.id]: !openDecision[r.id] })}>
                <span class="pill ans-{r.answerState}">{(r.answerState ?? "").replaceAll("_", " ")}</span>
                <span class="q">{r.question}</span>
                <span class="chev">{openDecision[r.id] ? "▾" : "▸"}</span>
              </button>
              {#if openDecision[r.id]}
                <div class="ddetail">
                  <div class="muted mono small">{r.objectId} · {r.id}</div>
                  {#if r.answerStateNote}<p class="statenote">{r.answerStateNote}</p>{/if}
                  {#if r.conversationalAnswer}
                    {@const ca = r.conversationalAnswer}
                    <h4>Your answer</h4>
                    <p>
                      <span class="mono">{ca.verdict}</span>{#if ca.chosen} → <strong>{ca.chosen}</strong>{/if}
                      {#if ca.answeredAt}<span class="muted"> · {ca.answeredAt}</span>{/if}
                    </p>
                    {#if ca.condition}
                      <h4 class="cond">Condition you attached</h4>
                      <p class="warnline">{ca.condition}</p>
                    {/if}
                  {:else if r.answer}
                    <h4>Your answer</h4>
                    <p><strong>{r.answer.chosen ?? "(free text)"}</strong>
                      {#if r.answer.submitted_at}<span class="muted"> · {r.answer.submitted_at}</span>{/if}
                    </p>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        {/if}
      {/if}

      {#if edges.length}
        <!-- Deliberately counted apart from the answerable requests: this is a
             question the operator is blocking on that they CANNOT answer from
             any UI, because nobody wrote it down as a request. Folding the two
             together would hide exactly that gap. -->
        <h4 class="gap">Blocking you, with no answerable request attached ({edges.length})</h4>
        <p class="sub muted">
          ⚠️ These are <strong>not answerable from this page</strong> — they are typed
          <span class="mono">blocked_on</span> edges with no request behind them, so
          clearing one needs a repo-side edit. An edge whose answer arrived in
          conversation will sit here looking live until someone removes it, so treat
          age here as a prompt to check rather than as a live ask.
        </p>
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

  <!-- ── LIVE WORK SESSIONS ─────────────────────────────────────────────────
       Operator, 2026-09-10: "part of that is making the work page on the UI
       clear so that I can keep track of the work sessions without needing to
       ask for ad hoc updates all the time."

       ⚠️ EVERY LANE'S STATE IS RENDERED BESIDE HOW STALE THAT READING IS, and
       that pairing is the whole point of this panel rather than a nicety.
       `state` in SESSIONS.json DECAYS and nothing decays it — measured
       2026-09-10, two lanes read `working` while both were idle and completed.
       A panel showing `state` alone would show dead lanes as running, which is
       WORSE than no panel: the operator would stop asking precisely because it
       looks live. The page must also never imply a live feed; `list_sessions`
       is an mcp__* tool no route holds. -->
  {#if sess}
    <div class="panel dec">
      <h3>Live work sessions ({ssum?.live ?? 0})</h3>
      {#if sess.present === false}
        <p class="warnline">
          ⚠️ The session registry could not be read ({sess.readState}). That is
          <em>not</em> a statement that no lanes are running.
        </p>
      {:else}
        {#if ssum?.byObservationState?.stale}
          <div class="warnline">
            ⚠️ {ssum.byObservationState.stale} of {ssum.live} lane(s)
            have not been looked at for over {sess.staleAfterMinutes} minutes. Their
            state below may simply be out of date — it is what someone last wrote,
            not what the session is doing now.
          </div>
        {/if}
        {#each lanes as l (l.sessionId ?? l.title)}
          <div class="lane" class:lstale={l.observation?.state !== "recent"}>
            <div class="lrow">
              <span class="pill st-{l.state}">{l.state}</span>
              <span class="id">{l.item ?? "(no item)"}</span>
              <span class="ttl2">{l.title ?? ""}</span>
            </div>
            <div class="lmeta muted">
              <!-- The age is NEVER shown without the state, and vice versa. -->
              <span class="obs obs-{l.observation?.state}">
                last observed
                {#if l.observation?.ageMinutes != null}
                  {l.observation.ageMinutes < 90
                    ? `${Math.round(l.observation.ageMinutes)}m ago`
                    : `${(l.observation.ageMinutes / 60).toFixed(1)}h ago`}
                {:else}
                  — never recorded
                {/if}
              </span>
              {#if l.observation?.fromField}
                <span class="mono small">via {l.observation.fromField}</span>
              {/if}
              {#if l.observation?.basis === "spawn_confirmation"}
                <span class="small">⚠️ spawn only — nobody has checked it since</span>
              {/if}
              {#if l.sessionId}<span class="mono small">…{String(l.sessionId).slice(-6)}</span>{/if}
            </div>
            {#if l.blockedOn}
              <div class="lmeta muted">
                blocked on: {typeof l.blockedOn === "string" ? l.blockedOn : JSON.stringify(l.blockedOn)}
              </div>
            {/if}
            {#if l.observation?.state !== "recent" && l.observation?.note}
              <div class="lmeta warnline">{l.observation.note}</div>
            {/if}
          </div>
        {/each}
        {#if lanes.length === 0}
          <p class="muted">No lane in the registry is in a working state.</p>
        {/if}
      {/if}
      <div class="sub muted">{sess.note}</div>
    </div>
  {/if}

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
          {#each rows as row (row.id ?? row.title)}
            <div class="ckrow" class:dis={row.status?.disagrees}>
              <button class="rh" onclick={() => (open = { ...open, [row.id]: !open[row.id] })}>
                <span class="pill st-{k}">{row.status?.value ?? "no status"}</span>
                <span class="id">{row.id ?? "(no id)"}</span>
                <span class="ttl2">{row.title ?? "(no title declared)"}</span>
                {#if row.lane}<span class="meta">{row.lane}</span>{/if}
                {#if row.tier != null}<span class="meta">T{row.tier}</span>{/if}
                <span class="meta own" title={row.ownerGrade}>{row.ownerRendered ?? "—"}</span>
                <span class="chev">{open[row.id] ? "▾" : "▸"}</span>
              </button>
              {#if open[row.id]}
                <div class="detail">
                  <!-- Provenance FIRST: how this row's status was arrived at is
                       not inferable from the value, and a contested row must
                       not read as a settled one. -->
                  <div class="basis" class:warn={row.status?.disagrees}>
                    <span class="mono">{row.status?.basis}</span> — {row.status?.note}
                    {#if row.status?.declaredState || row.status?.declaredStatus}
                      <div class="muted small">
                        declared <span class="mono">state</span>: {row.status.declaredState ?? "—"}
                        · <span class="mono">status</span>: {row.status.declaredStatus ?? "—"}
                      </div>
                    {/if}
                    {#if row.status?.inDeclaredVocabulary === false && row.status?.value}
                      <div class="muted small">
                        <span class="mono">{row.status.value}</span> is not in the checklist's own
                        <span class="mono">states</span> block — shown verbatim, never remapped.
                      </div>
                    {/if}
                    {#if row.sectioned === false}
                      <div class="muted small">
                        No <span class="mono">/status</span> section covers this status, so this row
                        does not appear in the Telegram readout's sections.
                      </div>
                    {/if}
                  </div>
                  {#if row.owner}
                    <h4>Owner</h4>
                    <p>{row.owner} <span class="muted">({row.ownerGrade})</span></p>
                  {/if}
                  {#each rest(row.fields) as [k2, v] (k2)}
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

  <h3 class="storeh">The work store</h3>

  {#if error}
    <div class="err panel">Couldn't load the work store: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if raw && raw.present === false}
    <!-- present:false is a DEGRADED read, not an empty store. Say which. -->
    <div class="err panel">
      The work store could not be read{raw.reason ? `: ${raw.reason}` : "."}
      <div class="sub">This is not the same as the store being empty.</div>
    </div>
  {:else}
    <!-- (1) The store is knowingly partial. This banner is load-bearing. -->
    {#if coverage && coverage.complete === false}
      <div class="panel warn">
        <strong>This is not the whole of the system's work.</strong>
        <div class="sub">
          The store covers the <span class="mono">{coverage.scope ?? "operating-layer build"}</span>
          only. About {num(coverage.carriedRowsApprox)} carried backlog rows migrate in
          {coverage.carriedRowsMigrateIn ?? "a later phase"}, together with the WIP ceiling.
          A bug to fix still goes to the review backlogs.
        </div>
      </div>
    {/if}

    <!-- (2) A read failure is REPORTED. It must never look like an empty store. -->
    {#if readErrors.length}
      <div class="panel warn">
        <strong>{readErrors.length} file(s) in the store could not be read.</strong>
        <div class="sub">
          They are counted as <span class="mono">ungradeable</span> below, not dropped —
          so the totals still describe every file on disk.
        </div>
        <ul class="errs">
          {#each readErrors as rerr (rerr.path)}
            <li><span class="mono">{rerr.path}</span> — {rerr.error}</li>
          {/each}
        </ul>
      </div>
    {/if}

    <div class="panel roll">
      <div class="chips">
        {#each STATES as s (s)}
          {#if lifecycle && lifecycle[s] !== undefined}
            <span class="chip" class:zero={lifecycle[s] === 0} class:hot={s === "in_flight" && lifecycle[s] > 0}>
              <b>{num(lifecycle[s])}</b> {STATE_LABEL[s]}
            </span>
          {/if}
        {/each}
      </div>
      <div class="stats muted">
        {num(summary?.objectCount)} work object(s) · {num(summary?.intentCount)} intent(s) ·
        {num(summary?.stepCount)} step(s)
        <!-- The buckets sum to the object count by construction; showing the
             denominator is what makes that checkable rather than asserted. -->
      </div>
    </div>

    <!-- (3) The ceiling is a READING, not a gate. -->
    {#if wip}
      <div class="panel wipbox" class:atceiling={wip.inFlight >= wip.ceiling}>
        <div class="wiprow">
          <span class="wipnum">{num(wip.inFlight)} / {num(wip.ceiling)}</span>
          <span class="muted">in flight vs the declared ceiling</span>
        </div>
        {#if wip.enforced === false}
          <div class="sub">
            ⚠️ <strong>Declared, not enforced.</strong> Nothing checks this yet — enforcement
            ships with the migration. Read it as a measurement, not as a limit being kept.
          </div>
        {/if}
      </div>
    {/if}

    {#if intents.length}
      <div class="list">
        {#each intents as it (it.id)}
          <div class="panel intent">
            <div class="ih"><span class="id">{it.id}</span><span class="st muted">{it.status ?? ""}</span></div>
            <div class="title">{it.title ?? ""}</div>
          </div>
        {/each}
      </div>
    {/if}

    <div class="list">
      {#each objects as o (o.id)}
        <div class="panel ob">
          <button class="obh" onclick={() => (open = { ...open, [o.id]: !open[o.id] })}>
            <span class="lc lc-{o.lifecycle}">{STATE_LABEL[o.lifecycle] ?? o.lifecycle}</span>
            <span class="id">{o.id}</span>
            <span class="focus">{o.title ?? ""}</span>
            <span class="blk muted">{blockedLabel(o)}</span>
            <span class="chev">{open[o.id] ? "▾" : "▸"}</span>
          </button>
          {#if open[o.id]}
            <div class="detail">
              {#if o.lifecycle === "unknown"}
                <p class="warnline">
                  ⚠️ This object's lifecycle could not be graded
                  {o.lifecycleDeclared ? ` (declared: "${o.lifecycleDeclared}")` : ""} —
                  it is not being reported as any of the six real states.
                </p>
              {/if}
              {#if o.doneCondition}
                <h4>Done when</h4><p>{o.doneCondition}</p>
              {/if}
              {#if o.blockedOnState === "declared" && o.blockedOn?.length}
                <h4>Blocked on</h4>
                <ul>
                  {#each o.blockedOn as edge}
                    <li>
                      <span class="mono">{edge.kind ?? "untyped"}</span> · {edge.ref}
                      {#if edge.since}<span class="muted"> (since {edge.since})</span>{/if}
                      {#if edge.refResolvedInStore === false}
                        <span class="dangling"> — not an object in this store</span>
                      {/if}
                      {#if edge.note}<div class="muted note">{edge.note}</div>{/if}
                    </li>
                  {/each}
                </ul>
              {:else if o.blockedOnState === "declared_none"}
                <p class="muted">Claims nothing blocks it. (An empty edge list is a claim, not an absence.)</p>
              {:else if o.blockedOnState === "unstated"}
                <p class="muted">No <span class="mono">blocked_on</span> key — nobody has stated whether anything blocks this.</p>
              {/if}
              {#if o.note}<h4>Note</h4><p>{o.note}</p>{/if}
              {#if o.verdict}<h4>Verdict</h4><p>{o.verdict}</p>{/if}
              {#each Object.entries(o.extra ?? {}) as [k, v]}
                <h4 class="xk">{k}</h4>
                <p>{typeof v === "string" ? v : JSON.stringify(v, null, 2)}</p>
              {/each}
              <div class="muted path mono">{o.path}</div>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>

  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  h4 { margin: 12px 0 4px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
  .warn { padding: 12px 14px; border-left: 3px solid var(--warn, #d19a2f); }
  .sub { font-size: 12.5px; color: var(--muted); margin-top: 6px; line-height: 1.5; }
  .errs { margin: 8px 0 0; padding-left: 18px; font-size: 12.5px; color: var(--muted); }
  .roll { padding: 14px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { background: var(--panel-2); border-radius: 5px; padding: 4px 9px; font-size: 12.5px; }
  .chip.zero { opacity: .45; }
  .chip.hot { background: var(--accent); color: #fff; }
  .stats { font-size: 12.5px; margin-top: 10px; }
  .wipbox { padding: 14px; }
  .wipbox.atceiling { border-left: 3px solid var(--warn, #d19a2f); }
  .wiprow { display: flex; align-items: baseline; gap: 10px; }
  .wipnum { font-size: 20px; font-weight: 600; }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .intent { padding: 12px 14px; }
  .ih { display: flex; gap: 10px; align-items: baseline; }
  .st { font-size: 12px; }
  .title { font-size: 13.5px; margin-top: 4px; }
  .ob { overflow: hidden; }
  .obh { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 12px 14px; cursor: pointer; font-size: 13.5px; }
  .lc { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 2px 7px; border-radius: 4px; background: var(--panel-2); color: var(--muted); white-space: nowrap; }
  .lc-in_flight { background: var(--accent); color: #fff; }
  .lc-unknown { background: var(--warn, #d19a2f); color: #fff; }
  .id { font-weight: 600; white-space: nowrap; }
  .focus { flex: 1; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .blk { font-size: 12px; white-space: nowrap; }
  .chev { color: var(--muted); }
  .detail { padding: 0 14px 14px; font-size: 13px; line-height: 1.55; }
  .detail p { margin: 0; white-space: pre-wrap; color: var(--muted); }
  .detail ul { margin: 0; padding-left: 18px; color: var(--muted); }
  .warnline { color: var(--warn, #d19a2f) !important; }
  .dangling { color: var(--warn, #d19a2f); }
  .note { font-size: 12px; margin-top: 2px; }
  .xk { color: var(--warn, #d19a2f); }
  .path { font-size: 11.5px; margin-top: 12px; }

  /* — MI-238 panels — */
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
  .ans-engaged_not_settled { background: var(--warn, #d19a2f); color: #fff; }
  .ans-verdict_unrecognised { background: var(--warn, #d19a2f); color: #fff; }
  .ans-answered_in_conversation { background: var(--panel-2); }
  .pill.ungraded { background: var(--warn, #d19a2f); color: #fff; }
  .ansrow { opacity: .9; }
  .ansToggle { margin-top: 10px; }
  .statenote { font-size: 12.5px; margin: 6px 0 0 !important; }
  .cond { color: var(--warn, #d19a2f); }
  .urg { background: var(--panel-2); }
  .ckrow { background: var(--panel); border-radius: 6px; overflow: hidden; }
  .ckrow.dis { box-shadow: inset 3px 0 0 var(--warn, #d19a2f); }
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
  .lane { border-top: 1px solid var(--panel-2); padding: 9px 0; }
  .lane.lstale { opacity: .82; }
  .lrow { display: flex; gap: 10px; align-items: baseline; font-size: 13px; }
  .lmeta { font-size: 11.5px; margin-top: 3px; display: flex; gap: 10px; flex-wrap: wrap; }
  .obs-stale, .obs-unknown { color: var(--warn, #d19a2f); }
  .st-working, .st-running { background: var(--accent); color: #fff; }
  .st-stalled_poked { background: var(--warn, #d19a2f); color: #fff; }
  .toggle { align-self: flex-start; background: var(--panel-2); border: none; color: var(--muted); border-radius: 6px; padding: 7px 12px; cursor: pointer; font-size: 12.5px; }
  .mono { font-family: ui-monospace, monospace; }
  .storeh { margin: 18px 0 0; font-size: 14px; }

</style>
