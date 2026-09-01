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
  //   1. `coverage.complete` is false. ⚠️ CORRECTED 2026-09-01: this comment
  //      said the store holds the build's own phases and NOT the ~572 carried
  //      rows "(they migrate in Phase C)". Phase C MERGED; the store holds 584
  //      objects. `complete` is still false for a different reason — there are
  //      no steps and nobody has audited that every workstream has an object —
  //      and the banner is still not decoration. But the page must not render
  //      584 as 584 things to do: it reads the LIFECYCLE, where 577 are
  //      dormant. Every string here comes from the API's own values rather
  //      than being retyped, precisely so this cannot drift again.
  //   2. `wip.enforced` — the ceiling of 8 IS enforced in CI since Phase C, and
  //      this view told the operator "Declared, not enforced. Nothing checks
  //      this yet" on the day it was. The banner is now conditioned on the
  //      field rather than on a hardcoded belief, so it disappears by itself.
  //   3. `blockedOnState` distinguishes `declared_none` (the object CLAIMS
  //      nothing blocks it) from `unstated` (nobody has said). Rendering both as
  //      a blank cell is how a false "ready" appears.
  //
  // PHASE H added the DECISIONS panel at the top of this view. The design puts
  // "anything waiting on the operator, at the top" and requires decisions to be
  // answerable FROM THE UI, so the operator is not the bottleneck on their own
  // decisions.
  //
  // ⚠️ A FOURTH THING THIS VIEW MUST NOT SMOOTH OVER, and it is the sharpest:
  //   4. SUBMITTING AN ANSWER IS NOT DECIDING IT. The bot appends the answer to
  //      a transit log and returns `answerState: "in_transit"`; the repo is the
  //      source of truth, so it becomes a decision only when a committer writes
  //      it into the work object. This panel therefore NEVER paints a submitted
  //      answer as decided — it re-reads the server and renders `answerState`
  //      verbatim. Transit fails BACK: a question wrongly shown as answered is
  //      a decision nobody made.
  //
  // ⚠️ The READ GATE half of Phase H is NOT here and is not this file's to
  // ship. Its precondition (Streamlit + Android off the live feed) was unmet
  // when this landed — which is itself the first question in the panel below.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num } from "../lib/format";

  let raw = $state<any | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  // ── Phase H: the decision inbox ──────────────────────────────────────────
  let dec = $state<any | null>(null);
  let decError = $state<string | null>(null);
  let choice = $state<Record<string, string>>({});
  let freeText = $state<Record<string, string>>({});
  let busy = $state<Record<string, boolean>>({});
  let submitError = $state<Record<string, string>>({});

  // ⚠️ sessionStorage, NEVER localStorage, and never a component default.
  // A static site on GitHub Pages cannot hold a secret, so the operator supplies
  // the bearer per browser session and it dies with the tab. This is the
  // stop-gap, stated as one: the designed answer is a SHORT-LIVED session token
  // from /api/auth/login, which lands with the read gate. Until then the value
  // pasted here is DASHBOARD_API_TOKEN, which also authorises prop-journal
  // writes — the panel says so where it is asked for rather than in a comment
  // only a developer reads.
  const TOKEN_KEY = "metis.decisionToken";
  let token = $state<string>("");
  let tokenSaved = $state(false);

  const dsum = $derived(dec?.summary ?? null);
  const dtransit = $derived(dec?.transit ?? null);
  const dgate = $derived(dec?.writeGate ?? null);
  const requests = $derived<any[]>(dec?.requests ?? []);
  const bareEdges = $derived<any[]>(dec?.unanswerableOperatorEdges ?? []);

  const ANSWER_LABEL: Record<string, string> = {
    not_submitted: "waiting on you",
    in_transit: "submitted — not landed",
    committed: "decided",
    unreadable: "could not read the channel",
  };

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

  async function load() {
    loading = true;
    error = null;
    try {
      raw = await api.work();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function loadDecisions() {
    decError = null;
    try {
      dec = await api.workDecisions();
    } catch (e) {
      // ⚠️ A failed READ is NOT "no decisions are waiting". Say which.
      decError = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    try {
      token = sessionStorage.getItem(TOKEN_KEY) ?? "";
      tokenSaved = token.length > 0;
    } catch {
      // Private mode / storage disabled. Answering still works for this render;
      // the operator just re-pastes. Never a reason to fail the whole panel.
      token = "";
    }
    load();
    loadDecisions();
  });

  function rememberToken() {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable — the in-memory value still works for this tab */
    }
    tokenSaved = token.length > 0;
  }

  async function submit(req: any) {
    const key = `${req.objectId}/${req.id}`;
    submitError = { ...submitError, [key]: "" };
    const chosen = choice[key] ?? null;
    const text = (freeText[key] ?? "").trim() || null;
    if (!chosen && !text) {
      // Refused client-side for the same reason the API refuses it: a vacuous
      // answer that reads as compliance is worse than no answer. The server
      // refuses it too — this is the friendlier of two identical refusals, not
      // the only one.
      submitError = { ...submitError, [key]: "Pick an option or write something." };
      return;
    }
    busy = { ...busy, [key]: true };
    try {
      await api.postWorkDecision(token, {
        object_id: req.objectId,
        request_id: req.id,
        chosen,
        free_text: text,
      });
    } catch (e) {
      submitError = { ...submitError, [key]: e instanceof Error ? e.message : String(e) };
    } finally {
      busy = { ...busy, [key]: false };
      // Re-read rather than mutating local state from the POST's response. The
      // SERVER decides what state this question is in, and it will say
      // `in_transit` — not `committed`. Painting it optimistically here is
      // exactly how a question comes to look answered when it is not.
      await loadDecisions();
    }
  }

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
  <h2>Work</h2>

  <!-- ═══ PHASE H — DECISIONS, AT THE TOP ═══════════════════════════════════
       "Anything waiting on the operator, at the top." This block is first on
       the page deliberately: it is the one thing here that nobody else can do.
  -->
  <div class="decwrap">
    <h3>Waiting on you</h3>

    {#if decError}
      <!-- ⚠️ A failed READ is not "nothing is waiting". -->
      <div class="panel err">
        The decision inbox could not be read: <span class="mono">{decError}</span>
        <div class="sub">This is not the same as having no decisions waiting.</div>
      </div>
    {:else if dec && dec.present === false}
      <div class="panel err">
        The decision inbox is degraded{dec.reason ? `: ${dec.reason}` : "."}
        <div class="sub">Not the same as an empty inbox.</div>
      </div>
    {:else if dec}
      {#if dtransit?.state === "unreadable"}
        <!-- The channel could not be read, so a question showing "waiting on
             you" may already have an answer in flight. Say so ONCE, loudly,
             rather than letting each row imply a state nobody measured. -->
        <div class="panel warn">
          ⚠️ <strong>The submission channel could not be read.</strong>
          <div class="sub">
            A question below reading “could not read the channel” is
            <em>we did not look</em> — <strong>not</strong> “nobody has answered”.
            It may already have an answer in transit.
            {#if dtransit?.error}<span class="mono"> {dtransit.error}</span>{/if}
          </div>
        </div>
      {/if}

      {#if dsum && (dsum.staleOpenWindows ?? 0) > 0}
        <div class="panel warn">
          ⚠️ <strong>{dsum.staleOpenWindows} answer(s) submitted and not landed</strong>
          for more than {Math.round((dsum.staleAfterSeconds ?? 3600) / 60)} minutes.
          <div class="sub">
            An open window is a reportable condition, not a decision. Until the
            committer writes it into the repo the question is still unanswered.
          </div>
        </div>
      {/if}

      <div class="panel decroll">
        <div class="chips">
          <span class="chip" class:hot={(dsum?.awaitingOperator ?? 0) > 0} class:zero={(dsum?.awaitingOperator ?? 0) === 0}>
            <b>{num(dsum?.awaitingOperator)}</b> waiting on you
          </span>
          <!-- Deliberately a SEPARATE chip: an in-transit answer is unanswered,
               but it is waiting on a committer, not on the operator. -->
          <span class="chip" class:zero={(dsum?.awaitingCommit ?? 0) === 0}>
            <b>{num(dsum?.awaitingCommit)}</b> submitted, not landed
          </span>
          <span class="chip" class:zero={(dsum?.decided ?? 0) === 0}>
            <b>{num(dsum?.decided)}</b> decided
          </span>
        </div>
        {#if (dsum?.malformedRequestsDropped ?? 0) > 0}
          <div class="sub warnline">
            ⚠️ {dsum.malformedRequestsDropped} declared request(s) carry no id and are
            <strong>not answerable</strong> — a question you can see and cannot answer.
          </div>
        {/if}
      </div>

      {#if dgate && dgate.acceptsWrites !== true}
        <div class="panel warn">
          {#if dgate.state === "closed_no_token"}
            <strong>Answering is closed on the server.</strong>
            <div class="sub">
              The bot has no write token configured, so it refuses submissions
              (503). This is <strong>fail-closed and deliberate</strong>, not an
              outage — you can still read every question below.
            </div>
          {:else}
            <strong>The server could not say whether answering is open.</strong>
            <div class="sub">{dgate.note ?? ""}</div>
          {/if}
        </div>
      {:else if dgate}
        <div class="panel tokenbox">
          <label for="dectok"><strong>Bearer token</strong> — needed to submit an answer</label>
          <input id="dectok" type="password" bind:value={token} onchange={rememberToken}
                 placeholder="DASHBOARD_API_TOKEN" autocomplete="off" />
          <div class="sub">
            Kept for this browser tab only (<span class="mono">sessionStorage</span>), never
            stored to disk and never sent anywhere but the bot's own API.
            ⚠️ <strong>This token also authorises prop-journal writes.</strong> It is a
            stop-gap: the designed answer is a short-lived login token, which lands
            with the read gate — the first question below.
            {#if tokenSaved}<span class="ok"> · held for this tab</span>{/if}
          </div>
        </div>
      {/if}

      {#if requests.length === 0}
        <div class="panel muted pad">
          No decisions are waiting.
          <span class="sub">
            (The inbox was read successfully — this is a measured empty, not a failure.)
          </span>
        </div>
      {/if}

      {#each requests as req (req.objectId + "/" + req.id)}
        {@const key = req.objectId + "/" + req.id}
        <div class="panel dec dec-{req.answerState}">
          <div class="dech">
            <span class="astate as-{req.answerState}">{ANSWER_LABEL[req.answerState] ?? req.answerState}</span>
            {#if req.urgency === "blocking"}<span class="urg">blocking</span>{/if}
            <span class="id mono">{req.objectId}</span>
          </div>
          <div class="q">{req.question ?? req.id}</div>
          {#if req.context}<div class="ctx">{req.context}</div>{/if}

          {#if req.answerState === "committed" && req.answer}
            <div class="answered">
              <strong>Decided:</strong> {req.answer.chosen ?? "(free text)"}
              {#if req.answer.freeText}<div class="ctx">{req.answer.freeText}</div>{/if}
              <div class="sub">
                Recorded in the repo{req.answer.answeredAt ? ` at ${req.answer.answeredAt}` : ""}.
                To change it, edit the work object.
              </div>
            </div>
          {:else if req.answerState === "in_transit"}
            <!-- ⚠️ NOT rendered as decided. The answer is submitted and has not
                 reached the repo, so the question is still unanswered. -->
            <div class="intransit">
              <strong>Submitted — not landed yet.</strong>
              <div class="sub">
                This question is still <strong>unanswered</strong> until the committer
                writes the answer into the work object.
                {#if req.transit?.ageSeconds != null}
                  Open for {Math.round(req.transit.ageSeconds / 60)} min.
                {:else}
                  ⚠️ The submission could not be dated, so its age is unknown.
                {/if}
                {#if req.transit?.stale}<span class="warnline"> This window is overdue.</span>{/if}
              </div>
            </div>
          {:else}
            <div class="opts">
              {#each req.options as opt (opt.key)}
                <label class="opt" class:sel={choice[key] === opt.key}>
                  <input type="radio" name={key} value={opt.key}
                         checked={choice[key] === opt.key}
                         onchange={() => (choice = { ...choice, [key]: opt.key })} />
                  <span class="optlabel">{opt.label ?? opt.key}</span>
                  {#if opt.implication}<span class="impl">{opt.implication}</span>{/if}
                </label>
              {/each}
              {#if req.allowsFreeText}
                <textarea rows="2" placeholder="…or say something else"
                          value={freeText[key] ?? ""}
                          oninput={(e) => (freeText = { ...freeText, [key]: (e.currentTarget as HTMLTextAreaElement).value })}
                ></textarea>
              {/if}
              {#if dgate?.acceptsWrites === true}
                <div class="actions">
                  <button class="submit" disabled={busy[key] || !token} onclick={() => submit(req)}>
                    {busy[key] ? "Submitting…" : "Submit answer"}
                  </button>
                  {#if !token}<span class="sub">Paste the bearer above to submit.</span>{/if}
                </div>
              {/if}
              {#if submitError[key]}
                <div class="sub warnline">{submitError[key]}</div>
              {/if}
            </div>
          {/if}
          <div class="sub mono path">{req.objectId} · {req.id}</div>
        </div>
      {/each}

      {#if bareEdges.length}
        <!-- ⚠️ The gap worth reading: the operator is BLOCKING on these and
             cannot answer them here, because nobody wrote them down as a
             request. Folding them in with the answerable ones would hide it. -->
        <div class="panel warn">
          <strong>{bareEdges.length} object(s) are blocked on you with no answerable question.</strong>
          <div class="sub">
            They declare an <span class="mono">operator_decision</span> edge but no
            <span class="mono">decision_requests</span> entry, so there is nothing to
            answer here — someone has to write the question down first.
          </div>
          <ul class="errs">
            {#each bareEdges as e (e.objectId + "/" + e.ref)}
              <li><span class="mono">{e.objectId}</span> — {e.ref ?? "(unnamed)"}{e.since ? ` (since ${e.since})` : ""}</li>
            {/each}
          </ul>
        </div>
      {/if}
    {/if}
  </div>


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
          Scope: <span class="mono">{coverage.scope ?? "operating-layer build"}</span>.
          {num(coverage.carriedRowsApprox)} carried backlog rows —
          {coverage.carriedRowsMigrateIn ?? "migration status unstated"}.
          <strong>Read the lifecycle, not the count:</strong> they arrived
          <span class="mono">dormant</span> — carried, not started, and not queued.
          Carrying everything is not the same as everything being open.
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

  /* ── Phase H — decisions ─────────────────────────────────────────────── */
  .decwrap { display: flex; flex-direction: column; gap: 8px; }
  h3 { margin: 0; font-size: 15px; }
  .err { padding: 12px 14px; border-left: 3px solid var(--danger, #c0392b); }
  .pad { padding: 12px 14px; }
  .decroll { padding: 12px 14px; }
  .tokenbox { padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
  .tokenbox input { background: var(--panel-2); border: 1px solid var(--border, #333); color: var(--text); border-radius: 5px; padding: 7px 9px; font-size: 13px; }
  .ok { color: var(--good, #2e9e5b); }
  .dec { padding: 14px; border-left: 3px solid var(--panel-2); }
  .dec-not_submitted { border-left-color: var(--accent); }
  .dec-in_transit { border-left-color: var(--warn, #d19a2f); }
  .dec-unreadable { border-left-color: var(--warn, #d19a2f); }
  .dech { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .astate { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 2px 7px; border-radius: 4px; background: var(--panel-2); color: var(--muted); }
  .as-not_submitted { background: var(--accent); color: #fff; }
  .as-in_transit, .as-unreadable { background: var(--warn, #d19a2f); color: #fff; }
  .urg { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--danger, #c0392b); font-weight: 600; }
  .q { font-size: 14.5px; margin: 8px 0 4px; line-height: 1.5; }
  .ctx { font-size: 12.5px; color: var(--muted); line-height: 1.55; white-space: pre-wrap; }
  .opts { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
  .opt { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 6px; background: var(--panel-2); cursor: pointer; }
  .opt.sel { outline: 2px solid var(--accent); }
  .opt input { margin-right: 6px; }
  .optlabel { font-size: 13.5px; }
  .impl { font-size: 12px; color: var(--muted); line-height: 1.5; }
  .opts textarea { background: var(--panel-2); border: 1px solid var(--border, #333); color: var(--text); border-radius: 5px; padding: 7px 9px; font-size: 13px; font-family: inherit; }
  .actions { display: flex; gap: 10px; align-items: center; }
  .submit { background: var(--accent); color: #fff; border: none; border-radius: 5px; padding: 7px 14px; font-size: 13px; cursor: pointer; }
  .submit:disabled { opacity: .5; cursor: not-allowed; }
  .answered, .intransit { margin-top: 8px; font-size: 13px; }
  .intransit { color: var(--warn, #d19a2f); }
</style>
