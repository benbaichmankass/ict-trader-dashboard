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
  <h2>Work</h2>

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
</style>
