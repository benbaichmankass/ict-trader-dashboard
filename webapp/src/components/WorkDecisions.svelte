<script lang="ts">
  // Work → Decisions (bot PR #25354 § "Work queue tabs (SPA)", Tab 1). Design from
  // the operator's decisions page; DATA from GET /api/bot/work/decisions.
  //
  // - Waiting first, then answered; a waiting | answered | all filter whose COUNTS
  //   are the route's summary (awaitingOperator / decided / requestCount, with the
  //   byAnswerState breakdown beside them) — never counted in the browser.
  // - Row membership uses the bot's own settled / actionable grade (lib/decisions.ts,
  //   three states, never two).
  // - Each card: question, evidence/context, options with the recommended one first
  //   and marked (when the request declares one), and "Other" whenever the bot says
  //   allowsFreeText. The state chip is waiting / in transit / recorded from
  //   answerState — in transit is NOT recorded.
  // - Answering: the session write route (POST /work/decision/session) does not
  //   exist yet, so the card says so in one plain line. No disabled buttons, no
  //   confirm dialog.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, DASH } from "../lib/format";
  import { isSettled, isMoot, isWaiting } from "../lib/decisions";

  let d = $state<any>(null);
  let err = $state<string | null>(null);
  let view = $state<"waiting" | "answered" | "all">("waiting");
  let open = $state<Record<string, boolean>>({});

  onMount(async () => {
    try { d = await api.workDecisions(); }
    catch (e) { err = e instanceof Error ? e.message : String(e); }
  });

  const sum = $derived(d?.summary ?? null);
  const reqs = $derived<any[]>(Array.isArray(d?.requests) ? d.requests : []);
  const waitingRows = $derived(reqs.filter(isWaiting));
  const answeredRows = $derived(reqs.filter((r) => isSettled(r) === "yes"));
  const mootRows = $derived(reqs.filter(isMoot));
  const shown = $derived(
    view === "waiting" ? waitingRows : view === "answered" ? answeredRows : [...waitingRows, ...answeredRows, ...mootRows],
  );
  const edges = $derived<any[]>(Array.isArray(d?.unanswerableOperatorEdges) ? d.unanswerableOperatorEdges : []);

  // answerState → the design's three chips; anything else is shown raw.
  function chip(s: string | null | undefined): { cls: string; text: string } {
    if (s === "not_submitted") return { cls: "wait", text: "waiting" };
    if (s === "in_transit") return { cls: "transit", text: "in transit" };
    if (s === "committed" || s === "answered_in_conversation") return { cls: "rec", text: "recorded" };
    return { cls: "other", text: s ? s.replaceAll("_", " ") : DASH };
  }
  function orderedOptions(r: any): any[] {
    const opts: any[] = Array.isArray(r?.options) ? r.options : [];
    const rec = r?.recommended;
    const isRec = (o: any) => o?.recommended === true || (rec != null && (o?.key === rec || o?.label === rec));
    return [...opts.filter(isRec), ...opts.filter((o) => !isRec(o))].map((o) => ({ ...o, _rec: isRec(o) }));
  }
  const byAnswer = $derived(
    Object.entries((sum?.byAnswerState ?? {}) as Record<string, number>).filter(([, n]) => typeof n === "number"),
  );
</script>

<section class="wd">
  <h3>Decisions <span class="muted sub">· questions waiting on your answer, then answered ones</span></h3>

  {#if err}
    <div class="na">Decisions: not available (<span class="mono">{err}</span>)</div>
  {:else if !d}
    <div class="muted">Loading…</div>
  {:else if d.present === false}
    <div class="na">Decisions: not available ({d.reason ?? DASH})</div>
  {:else}
    <div class="filter" role="group" aria-label="Show">
      <button class:on={view === "waiting"} onclick={() => (view = "waiting")}>Waiting <b class="mono">{num(sum?.awaitingOperator)}</b></button>
      <button class:on={view === "answered"} onclick={() => (view = "answered")}>Answered <b class="mono">{num(sum?.decided)}</b></button>
      <button class:on={view === "all"} onclick={() => (view = "all")}>All <b class="mono">{num(sum?.requestCount)}</b></button>
    </div>
    <div class="muted small">
      By answer state (the route's count):
      {#if byAnswer.length}{byAnswer.map(([k, n]) => `${k.replaceAll("_", " ")} ${n}`).join(" · ")}{:else}{DASH}{/if}
      · transit log: {d.transit?.state ?? DASH}
    </div>

    {#if shown.length === 0}
      <div class="empty">
        {num(view === "waiting" ? sum?.awaitingOperator : view === "answered" ? sum?.decided : sum?.requestCount)} {view === "all" ? "requests" : view}
        · the route reads {num(sum?.requestCount)} answerable request(s) today.
        {#if (sum?.unanswerableOperatorEdgeCount ?? 0) > 0}
          {num(sum?.unanswerableOperatorEdgeCount)} item(s) are blocking on you with no answerable request attached (listed below).
        {/if}
      </div>
    {:else}
      {#each shown as r (String(r.objectId) + r.id)}
        {@const c = chip(r.answerState)}
        <div class="card" class:moot={isMoot(r)}>
          <button class="h" onclick={() => (open = { ...open, [r.id]: !open[r.id] })}>
            <span class="chip {c.cls}">{c.text}</span>
            {#if r.urgency === "blocking"}<span class="chip block">blocking</span>{/if}
            {#if isSettled(r) === "ungraded"}<span class="chip other" title="This bot did not report whether it is settled — not a claim that it is open.">settled?</span>{/if}
            {#if isMoot(r)}<span class="chip other">moot</span>{/if}
            <span class="q">{r.question ?? DASH}</span>
            <span class="muted">{open[r.id] ? "▾" : "▸"}</span>
          </button>
          {#if open[r.id]}
            <div class="body">
              <div class="muted mono small">{r.objectId ?? DASH} · {r.id}{r.askedOn ? ` · asked ${r.askedOn}` : ""}</div>
              {#if r.context}<h4>Evidence</h4><p>{r.context}</p>{/if}
              {#if Array.isArray(r.evidence) && r.evidence.length}
                <ul class="ev">{#each r.evidence as e, i (i)}<li>{typeof e === "string" ? e : JSON.stringify(e)}</li>{/each}</ul>
              {/if}
              <h4>Options</h4>
              <ul class="opts">
                {#each orderedOptions(r) as o, i (i)}
                  <li class:rec={o._rec}><strong>{o.label ?? o.key ?? DASH}</strong>{#if o._rec} <span class="chip rec">recommended</span>{/if}
                    {#if o.implication}<div class="muted small">{o.implication}</div>{/if}</li>
                {/each}
                {#if r.allowsFreeText !== false}
                  <li class="other"><strong>Other</strong> <span class="muted small">— your own answer, in your words</span></li>
                {/if}
              </ul>
              {#if r.answerStateNote}<p class="muted small">{r.answerStateNote}</p>{/if}
              {#if r.conversationalAnswer}
                {@const ca = r.conversationalAnswer}
                <h4>Your answer</h4>
                <p><span class="mono">{ca.verdict ?? DASH}</span>{#if ca.chosen} → <strong>{ca.chosen}</strong>{/if}{#if ca.answeredAt}<span class="muted"> · {ca.answeredAt}</span>{/if}</p>
                {#if ca.condition}<p class="cond">Condition you attached: {ca.condition}</p>{/if}
              {/if}
              <p class="line">Answering from the dashboard is not wired yet (route missing); answer on the decisions page.</p>
            </div>
          {/if}
        </div>
      {/each}
    {/if}

    {#if edges.length}
      <h4 class="gap">Blocking on you, with no answerable request attached ({num(sum?.unanswerableOperatorEdgeCount ?? edges.length)})</h4>
      <p class="muted small">Typed <span class="mono">blocked_on</span> edges with no question written down, so there is nothing to answer here; clearing one is a repo-side edit.</p>
      <ul class="edges">
        {#each edges as e, i (i)}
          <li><span class="mono small">{e.objectId ?? DASH}</span> <span class="muted small">({e.objectLifecycle ?? DASH} · {e.source ?? DASH})</span>
            {#if e.objectTitle}<div>{e.objectTitle}</div>{/if}
            {#if e.ref}<div class="muted small">{e.ref}</div>{/if}</li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .wd { display: flex; flex-direction: column; gap: 8px; }
  h3 { margin: 0; }
  .sub { font-size: 13px; font-weight: 400; }
  .small { font-size: 12px; }
  h4 { margin: 10px 0 4px; font-size: 13px; }
  .filter { display: flex; gap: 6px; flex-wrap: wrap; }
  .filter button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 14px; padding: 4px 12px; font-size: 13px; cursor: pointer; }
  .filter button.on { border-color: var(--accent, #4c8dff); background: #4c8dff22; }
  .empty, .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .card { border: 1px solid var(--border); border-radius: 8px; }
  .card.moot { opacity: 0.7; }
  .h { width: 100%; display: flex; gap: 8px; align-items: baseline; padding: 8px 10px; background: none; border: none; color: var(--text); cursor: pointer; text-align: left; }
  .q { flex: 1; font-weight: 500; }
  .body { padding: 0 12px 10px; font-size: 13px; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 8px; white-space: nowrap; }
  .chip.wait { background: #d4a01722; color: #d4a017; }
  .chip.transit { background: #4c8dff22; color: #4c8dff; }
  .chip.rec { background: #30a46c22; color: #30a46c; }
  .chip.block { background: #e5484d22; color: #e5484d; }
  .chip.other { background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); }
  .opts { padding-left: 18px; margin: 4px 0; }
  .opts li { margin: 3px 0; }
  .opts li.rec strong { color: #30a46c; }
  .cond { color: #d4a017; }
  .line { margin-top: 10px; padding: 6px 8px; background: var(--panel-2); border-radius: 6px; font-size: 12.5px; }
  .gap { margin-top: 14px; }
  .edges { padding-left: 18px; margin: 4px 0; font-size: 13px; }
  .edges li { margin: 5px 0; }
</style>
