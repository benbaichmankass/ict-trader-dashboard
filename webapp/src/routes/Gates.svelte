<script lang="ts">
  // Admin → Gates — the live gate registry (operator ask 2026-11-12: "the Admin
  // tab in the UI needs to keep an actively-updated gate registry so we can
  // have visibilty and make changes more quickly").
  //
  // Reads GET /api/bot/gates (polled every 60 s while the page is visible) and
  // GET /api/bot/gates/{id} for an expanded row. The decision buttons are the
  // one write: POST /api/bot/gates/{id}/decision with the operator's session.
  //
  // ⚠️ NO CONFIRM DIALOGS, deliberately (operator's no-new-gates rule): one
  // press sends the POST, and the server's answer — `message` or `detail` — is
  // shown VERBATIM next to the row, then the row is re-read.
  //
  // ⚠️ "unreadable" is rendered as unreadable, with the error. It is never an
  // empty table, which would claim the registry holds zero gates.
  import { onMount, onDestroy } from "svelte";
  import { api, AuthRequiredError } from "../lib/api";
  import { agoFromIso } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";
  import {
    DECISIONS,
    STATE_FILTERS,
    sortGates,
    isFlagged,
    dash,
    realMoneyText,
    decisionLabel,
    ATTENTION_LABEL,
    prUrl,
    shortSha,
    hitsText,
    driftText,
    serverAnswer,
    categoryOptions,
    type GateRow,
    type GatesResponse,
    type GateDetailResponse,
  } from "../lib/gates";

  const POLL_MS = 60_000;

  const DECISION_OPTS = [{ value: "", label: "All" }, ...DECISIONS];
  const STATE_OPTS = [{ value: "", label: "All" }, ...STATE_FILTERS];
  const REAL_MONEY_OPTS = [
    { value: "", label: "All" },
    { value: "true", label: "Real money" },
    { value: "false", label: "Not real money" },
  ];

  let category = $state("");
  let decision = $state("");
  let gstate = $state("");
  let realMoney = $state("");

  let resp = $state<GatesResponse | null>(null);
  let loading = $state(true);
  let loadError = $state<string | null>(null);
  let authNeeded = $state(false);
  let lastFetched = $state<number | null>(null);
  let seenCategories = $state<string[]>([]);

  // Per-row UI state, keyed by gate id — survives the 60 s refresh.
  let expanded = $state<Record<string, boolean>>({});
  let details = $state<Record<string, { data: GateDetailResponse | null; error: string | null; loading: boolean }>>({});
  let notes = $state<Record<string, string>>({});
  let busy = $state<Record<string, boolean>>({});
  let answers = $state<Record<string, { ok: boolean; status: number | null; text: string; at: number }>>({});

  const rows = $derived(sortGates(Array.isArray(resp?.gates) ? (resp!.gates as GateRow[]) : []));
  const flaggedCount = $derived(rows.filter(isFlagged).length);
  const catOpts = $derived([{ value: "", label: "All" }, ...seenCategories.map((c) => ({ value: c, label: c }))]);
  const unreadable = $derived(resp != null && resp.readState !== "read");

  let seq = 0;
  async function load(quiet = false) {
    const mine = ++seq;
    if (!quiet) loading = true;
    try {
      const r = await api.gates({ category, decision, state: gstate, real_money: realMoney, sort: "attention" });
      if (mine !== seq) return; // a newer filter's request superseded this one
      resp = r;
      seenCategories = categoryOptions(seenCategories, r);
      loadError = null;
      authNeeded = false;
      lastFetched = Date.now();
    } catch (e) {
      if (mine !== seq) return;
      authNeeded = e instanceof AuthRequiredError;
      loadError = e instanceof Error ? e.message : String(e);
    } finally {
      if (mine === seq) loading = false;
    }
  }

  // Re-query when a filter changes (also the first load).
  $effect(() => {
    category; decision; gstate; realMoney;
    load();
  });

  let timer: ReturnType<typeof setInterval> | null = null;
  function onVisible() {
    if (!document.hidden) load(true);
  }
  onMount(() => {
    timer = setInterval(() => {
      if (!document.hidden) load(true);
    }, POLL_MS);
    document.addEventListener("visibilitychange", onVisible);
  });
  onDestroy(() => {
    if (timer) clearInterval(timer);
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
  });

  async function loadDetail(id: string) {
    details[id] = { data: details[id]?.data ?? null, error: null, loading: true };
    try {
      const d = await api.gate(id);
      details[id] = { data: d, error: null, loading: false };
      if (d?.gate && resp?.gates) {
        resp = { ...resp, gates: resp.gates.map((g) => (g.id === id ? { ...g, ...d.gate } : g)) };
      }
    } catch (e) {
      details[id] = { data: details[id]?.data ?? null, error: e instanceof Error ? e.message : String(e), loading: false };
    }
  }

  function toggle(id: string) {
    expanded[id] = !expanded[id];
    if (expanded[id]) loadDetail(id);
  }

  async function decide(g: GateRow, d: string) {
    busy[g.id] = true;
    try {
      const r = await api.gateDecision(g.id, d, notes[g.id] ?? "");
      answers[g.id] = { ok: r.ok, status: r.status, text: serverAnswer(r.status, r.body, r.text), at: Date.now() };
      const fresh = (r.body as any)?.gate as GateRow | undefined;
      if (r.ok && fresh && resp?.gates) {
        resp = { ...resp, gates: resp.gates.map((x) => (x.id === g.id ? { ...x, ...fresh } : x)) };
      }
      if (r.ok) notes[g.id] = "";
    } catch (e) {
      answers[g.id] = { ok: false, status: null, text: e instanceof Error ? e.message : String(e), at: Date.now() };
    } finally {
      busy[g.id] = false;
    }
    // Refresh the row from the server whatever the answer was.
    await loadDetail(g.id);
  }

  // Bulk: accept the audit's recommendation for every WAITING gate shown (design
  // § Tab 4). One press runs it — no confirm(). A waiting gate with no
  // recommendation (operator-preference row) is SKIPPED, never guessed. Each POST is
  // the same session-auth decision route as the per-row buttons; the tally below is
  // what the server answered, and the first failure messages are shown verbatim.
  const waitingShown = $derived(rows.filter((g) => g.operator_decision === "undecided" || g.operator_decision == null));
  const waitingWithRec = $derived(waitingShown.filter((g) => g.recommended_decision != null));
  let bulk = $state<{ running: boolean; done: number; total: number; set: number; skipped: number; failed: number; errors: string[] } | null>(null);
  async function acceptRecommendations() {
    const targets = [...waitingShown];
    bulk = { running: true, done: 0, total: targets.length, set: 0, skipped: 0, failed: 0, errors: [] };
    for (const g of targets) {
      const rec = g.recommended_decision;
      if (rec == null) { bulk.skipped++; bulk.done++; continue; }
      try {
        const r = await api.gateDecision(g.id, rec, "accepted the audit recommendation (bulk)");
        if (r.ok) bulk.set++;
        else { bulk.failed++; if (bulk.errors.length < 5) bulk.errors.push(`${g.id}: HTTP ${r.status} ${serverAnswer(r.status, r.body, r.text)}`); }
      } catch (e) {
        bulk.failed++;
        if (bulk.errors.length < 5) bulk.errors.push(`${g.id}: ${e instanceof Error ? e.message : String(e)}`);
      }
      bulk.done++;
    }
    bulk.running = false;
    await load(true);
  }

  function countList(m: Record<string, number | null> | null | undefined): [string, string][] {
    return Object.entries(m ?? {}).map(([k, v]) => [k.replace(/_/g, " "), dash(v)]);
  }
</script>

<section>
  <div class="head">
    <h2>Gates <span class="muted sub">· live gate registry</span></h2>
    <div class="meta muted">
      {#if resp}
        <span title={resp.as_of ?? ""}>as of {dash(resp.as_of)}{#if resp.as_of} ({agoFromIso(resp.as_of)}){/if}</span>
        · <span>read state <b class:neg={unreadable}>{dash(resp.readState)}</b></span>
      {/if}
      · <span>refreshes every 60 s while visible</span>
      <button class="refresh" onclick={() => load()} disabled={loading}>Refresh</button>
    </div>
  </div>

  <div class="filters panel">
    <div class="fl">
      <span class="lab">Category</span>
      {#if seenCategories.length > 6}
        <select bind:value={category} aria-label="Category">
          {#each catOpts as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
        </select>
      {:else}
        <Segmented options={catOpts} bind:value={category} />
      {/if}
    </div>
    <div class="fl"><span class="lab">Decision</span><Segmented options={DECISION_OPTS} bind:value={decision} /></div>
    <div class="fl"><span class="lab">State</span><Segmented options={STATE_OPTS} bind:value={gstate} /></div>
    <div class="fl"><span class="lab">Real money</span><Segmented options={REAL_MONEY_OPTS} bind:value={realMoney} /></div>
  </div>

  {#if loadError && !resp}
    <div class="err panel">
      Could not look: the gate registry did not answer (no gate count is known, not zero). <span class="mono">{loadError}</span>
      {#if authNeeded}<div class="muted">Sign in from ⚙ Settings, then refresh.</div>{/if}
    </div>
  {:else if loading && !resp}
    <div class="muted pad">Loading…</div>
  {:else if resp}
    {#if loadError}
      <div class="err panel">Could not look on the last refresh (showing the previous read): <span class="mono">{loadError}</span></div>
    {/if}

    {#if unreadable}
      <div class="err panel">
        <b>Registry unreadable</b> (readState: <span class="mono">{dash(resp.readState)}</span>). The bot could not read the
        gate registry, so no gate count is known — this is not "zero gates".
      </div>
    {:else}
      <div class="counts">
        <div class="stat panel" class:alert={(resp.counts?.drift ?? 0) > 0}>
          <span class="k">Drift</span><span class="v">{dash(resp.counts?.drift)}</span>
        </div>
        <div class="stat panel" class:alert={(resp.counts?.unregistered ?? 0) > 0}>
          <span class="k">Unregistered</span><span class="v">{dash(resp.counts?.unregistered)}</span>
        </div>
        <div class="stat panel"><span class="k">Real money</span><span class="v">{dash(resp.counts?.real_money)}</span></div>
        <div class="stat panel">
          <span class="k">Population</span>
          <span class="v">{dash(resp.population?.returned)} / {dash(resp.population?.total)}</span>
          <span class="muted small">{dash(resp.population?.description)}</span>
        </div>
        <div class="stat panel wide">
          <span class="k">By attention (the route's rank)</span>
          <span class="chips">{#each Object.entries(resp.counts?.by_attention_rank ?? {}) as [k, v] (k)}<span class="chip" title={ATTENTION_LABEL[k] ?? ""}>{k} · {ATTENTION_LABEL[k] ?? k} <b>{dash(v)}</b></span>{:else}<span class="muted">—</span>{/each}</span>
        </div>
        <div class="stat panel"><span class="k">With a recommendation</span><span class="v">{dash(resp.counts?.recommendation_acceptable)}</span><span class="muted small">of {dash(resp.population?.total)}</span></div>
        <div class="stat panel wide">
          <span class="k">By decision</span>
          <span class="chips">{#each countList(resp.counts?.by_decision) as [k, v] (k)}<span class="chip">{k} <b>{v}</b></span>{:else}<span class="muted">—</span>{/each}</span>
        </div>
        <div class="stat panel wide">
          <span class="k">By state</span>
          <span class="chips">{#each countList(resp.counts?.by_state) as [k, v] (k)}<span class="chip">{k} <b>{v}</b></span>{:else}<span class="muted">—</span>{/each}</span>
        </div>
        <div class="stat panel wide">
          <span class="k">By mode in code</span>
          <span class="chips">{#each countList(resp.counts?.by_mode) as [k, v] (k)}<span class="chip">{k} <b>{v}</b></span>{:else}<span class="muted">—</span>{/each}</span>
        </div>
        <div class="stat panel wide">
          <span class="k">By category</span>
          <span class="chips">{#each countList(resp.counts?.by_category) as [k, v] (k)}<span class="chip">{k} <b>{v}</b></span>{:else}<span class="muted">—</span>{/each}</span>
        </div>
      </div>

      <div class="muted small refreshline">
        Registry refresh: {dash(resp.refresh?.at)}{#if resp.refresh?.at} ({agoFromIso(resp.refresh.at)}){/if}
        · head <span class="mono">{shortSha(resp.refresh?.head_sha)}</span>
        · read state <span class:neg={resp.refresh?.read_state != null && resp.refresh?.read_state !== "read"}>{dash(resp.refresh?.read_state)}</span>
        {#if resp.refresh?.error}<span class="neg"> · error: {resp.refresh.error}</span>{/if}
        {#if flaggedCount > 0}<span class="neg"> · {flaggedCount} flagged row{flaggedCount === 1 ? "" : "s"} pinned on top</span>{/if}
      </div>

      <div class="bulk panel">
        <button class="dbtn bulkbtn" disabled={!!bulk?.running || waitingShown.length === 0} onclick={acceptRecommendations}>
          Accept the recommendation for every waiting gate shown ({waitingShown.length})
        </button>
        <span class="muted small">{waitingWithRec.length} have a recommendation · {waitingShown.length - waitingWithRec.length} would be skipped (no recommendation — operator preference)</span>
        {#if bulk}
          <div class="small" class:neg={bulk.failed > 0}>
            {bulk.running ? `Sending… ${bulk.done}/${bulk.total}` : "Done"} · set <b>{bulk.set}</b> · skipped <b>{bulk.skipped}</b> · failed <b>{bulk.failed}</b>
            {#each bulk.errors as e, i (i)}<div class="mono">{e}</div>{/each}
          </div>
        {/if}
      </div>

      {#if rows.length === 0}
        <div class="muted pad panel">
          No gates match these filters (readState "read"; {dash(resp.population?.total)} in the population:
          {dash(resp.population?.description)}).
        </div>
      {:else}
        <div class="tablewrap panel">
          <table>
            <thead>
              <tr>
                <th></th><th>Gate</th><th>Category</th><th>Where</th><th>Blocks</th><th>Real money</th>
                <th>Authorization</th><th>Decision</th><th>Implementation</th><th>Mode in code</th>
                <th class="r">Hits 14d</th><th>Updated</th>
              </tr>
            </thead>
            {#each rows as g (g.id)}
              {@const flag = driftText(g)}
              {@const pr = prUrl(g.implementation_pr)}
              {@const ans = answers[g.id]}
              <tbody class:flagged={isFlagged(g)}>
                <tr class="main">
                  <td data-label="">
                    <button class="exp" aria-expanded={!!expanded[g.id]} onclick={() => toggle(g.id)} title="Full detail + history">
                      {expanded[g.id] ? "▾" : "▸"}
                    </button>
                  </td>
                  <td data-label="Gate" class="id">
                    <span class="mono">{g.id}</span>
                    {#if g.attention_rank != null}<span class="att att{g.attention_rank}" title={ATTENTION_LABEL[String(g.attention_rank)] ?? ""}>rank {g.attention_rank}</span>{/if}
                    {#if flag}<span class="flag" title={g.drift_detail ?? ""}>⚠ {flag}</span>{/if}
                  </td>
                  <td data-label="Category">{dash(g.category)}</td>
                  <td data-label="Where" class="mono wrap">{dash(g.where)}</td>
                  <td data-label="Blocks" class="wrap">{dash(g.blocks)}{#if g.effect}<span class="tag">{g.effect}</span>{/if}</td>
                  <td data-label="Real money" class:neg={g.real_money === true}>{realMoneyText(g.real_money)}</td>
                  <td data-label="Authorization" class="wrap">
                    {dash(g.authorization)}{#if g.authorization_class}<span class="tag">{g.authorization_class}</span>{/if}
                  </td>
                  <td data-label="Decision"><span class="dec dec-{g.operator_decision ?? 'none'}">{decisionLabel(g.operator_decision)}</span></td>
                  <td data-label="Implementation">
                    {dash(g.implementation_state)}
                    {#if pr}<a href={pr} target="_blank" rel="noopener noreferrer">#{g.implementation_pr}</a>{/if}
                    {#if g.implementation_sha}<span class="mono muted">{shortSha(g.implementation_sha)}</span>{/if}
                  </td>
                  <td data-label="Mode in code">{dash(g.mode_in_code)}</td>
                  <td data-label="Hits 14d" class="r mono" title={g.hits_note ?? (g.hits_read_state === "not_measurable" ? "not measurable" : "")}>
                    {hitsText(g)}{#if g.hits_read_state === "not_measurable"}<span class="muted small"> n/m</span>{/if}
                  </td>
                  <td data-label="Updated" title={g.updated_at ?? ""}>{agoFromIso(g.updated_at)}</td>
                </tr>
                <tr class="actions">
                  <td colspan="12">
                    <div class="act">
                      <span class="lab">Decide:</span>
                      {#each DECISIONS as d (d.value)}
                        <button
                          class="dbtn"
                          class:current={g.operator_decision === d.value}
                          class:rec={g.recommended_decision === d.value}
                          title={g.recommended_decision === d.value ? `audit recommendation: ${g.recommendation ?? d.label}` : ""}
                          disabled={!!busy[g.id]}
                          onclick={() => decide(g, d.value)}
                        >{d.label}{#if g.recommended_decision === d.value}<span class="recmark"> · rec.</span>{/if}</button>
                      {/each}
                      <input
                        class="note"
                        type="text"
                        placeholder="Optional note"
                        aria-label={`Note for ${g.id}`}
                        bind:value={notes[g.id]}
                        disabled={!!busy[g.id]}
                      />
                      {#if busy[g.id]}<span class="muted small">sending…</span>{/if}
                      {#if ans}
                        <span class="answer" class:neg={!ans.ok} class:pos={ans.ok}>
                          {#if ans.status != null}<span class="muted small">HTTP {ans.status}:</span>{/if}
                          <span class="mono">{ans.text}</span>
                        </span>
                      {/if}
                    </div>
                  </td>
                </tr>
                {#if expanded[g.id]}
                  {@const det = details[g.id]}
                  {@const full = { ...g, ...(det?.data?.gate ?? {}) }}
                  <tr class="detail">
                    <td colspan="12">
                      {#if det?.loading && !det?.data}<div class="muted">Loading detail…</div>{/if}
                      {#if det?.error}<div class="neg">Couldn't load detail: <span class="mono">{det.error}</span></div>{/if}
                      {#if det?.data && det.data.readState != null && det.data.readState !== "read"}
                        <div class="neg">Detail readState: {det.data.readState}{#if det.data.error} — {det.data.error}{/if}</div>
                      {/if}
                      <dl>
                        <dt>Where (more)</dt>
                        <dd class="mono">
                          {#if full.where_more && full.where_more.length}
                            {#each full.where_more as w, i (i)}<div>{w}</div>{/each}
                          {:else}—{/if}
                        </dd>
                        <dt>Authorization</dt><dd>{dash(full.authorization)} <span class="muted">({dash(full.authorization_class)})</span></dd>
                        <dt>Decision note</dt><dd>{dash(full.decision_note)}</dd>
                        <dt>Decided</dt><dd>{dash(full.decided_at)} · by {dash(full.decided_by)} · source {dash(full.decision_source)}</dd>
                        <dt>Implementation</dt>
                        <dd>
                          {dash(full.implementation_state)} · PR
                          {#if prUrl(full.implementation_pr)}<a href={prUrl(full.implementation_pr)} target="_blank" rel="noopener noreferrer">#{full.implementation_pr}</a>{:else}—{/if}
                          · sha <span class="mono">{dash(full.implementation_sha)}</span>
                        </dd>
                        <dt>Registry state</dt><dd>{dash(full.registry_state)}</dd>
                        <dt>Drift</dt><dd>{dash(full.drift)}{#if full.drift_detail} — {full.drift_detail}{/if}</dd>
                        <dt>Hits</dt>
                        <dd>14d {hitsText(full)} · last fired {dash(full.hits_last_fired)} · read state {dash(full.hits_read_state)}{#if full.hits_note} · {full.hits_note}{/if}</dd>
                        <dt>Effect</dt><dd>{dash(full.effect)}</dd>
                        <dt>Recommendation</dt><dd>{dash(full.recommendation)}</dd>
                        <dt>Added</dt><dd>{dash(full.added_at)} · by {dash(full.added_by)}</dd>
                        <dt>Updated</dt><dd>{dash(full.updated_at)}</dd>
                      </dl>
                      <h4>Decision history</h4>
                      {#if det?.data && Array.isArray(det.data.history)}
                        {#if det.data.history.length === 0}
                          <div class="muted">No recorded decisions.</div>
                        {:else}
                          <ul class="hist">
                            {#each det.data.history as h, i (i)}
                              <li>
                                <b>{decisionLabel(h.decision)}</b>
                                <span class="muted">{dash(h.decided_at)} · {dash(h.decided_by)} · {dash(h.source)}</span>
                                <div>{dash(h.note)}</div>
                              </li>
                            {/each}
                          </ul>
                        {/if}
                      {:else if !det?.loading}
                        <div class="muted">—</div>
                      {/if}
                    </td>
                  </tr>
                {/if}
              </tbody>
            {/each}
          </table>
        </div>
      {/if}
    {/if}
  {/if}
  {#if lastFetched}<div class="muted small">Last fetched {new Date(lastFetched).toLocaleTimeString()}</div>{/if}
</section>

<style>
  .bulk { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; padding: 8px 10px; margin: 6px 0; }
  .bulkbtn { font-weight: 600; }
  .dbtn.rec { outline: 1px dashed var(--accent, #4c8dff); outline-offset: 1px; }
  .recmark { font-size: 11px; color: var(--accent, #4c8dff); }
  .att { font-size: 10.5px; padding: 0 6px; border-radius: 6px; margin-left: 6px; border: 1px solid var(--border); white-space: nowrap; }
  .att1 { color: #e5484d; border-color: #e5484d66; }
  .att2 { color: #d4a017; border-color: #d4a01766; }
  .att3 { color: var(--muted); }
  section { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  h2 { margin: 0; font-size: 18px; }
  h4 { margin: 10px 0 4px; font-size: 13px; }
  .sub { font-size: 12px; font-weight: 400; }
  .meta { font-size: 12px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .small { font-size: 11.5px; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
  .err .muted { margin-top: 4px; }
  button { font: inherit; }
  .refresh, .dbtn, .exp {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12.5px;
  }
  .refresh:disabled, .dbtn:disabled { opacity: 0.5; cursor: default; }
  .exp { padding: 2px 8px; }

  .filters { display: flex; flex-wrap: wrap; gap: 10px 18px; padding: 10px 12px; }
  .fl { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .lab { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  select { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; max-width: 100%; }

  .counts { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .stat { padding: 8px 12px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .stat.wide { grid-column: span 2; }
  .stat .k { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .stat .v { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .stat.alert { border-color: var(--neg); }
  .stat.alert .v { color: var(--neg); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; font-size: 12px; }
  .refreshline { overflow-wrap: anywhere; }

  .tablewrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 7px 9px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; white-space: nowrap; }
  tbody { border-bottom: 1px solid var(--border); }
  tbody.flagged { background: color-mix(in srgb, var(--neg) 8%, transparent); }
  tbody.flagged tr.main td:first-child { box-shadow: inset 3px 0 0 var(--neg); }
  .r { text-align: right; }
  .wrap { overflow-wrap: anywhere; max-width: 260px; }
  .id { font-weight: 600; }
  .flag { display: inline-block; margin-left: 6px; color: var(--neg); font-size: 11.5px; font-weight: 600; text-transform: uppercase; }
  .tag { margin-left: 6px; font-size: 10.5px; color: var(--muted); border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; }
  .dec { font-weight: 600; }
  .dec-keep { color: var(--pos); }
  .dec-remove { color: var(--neg); }
  .dec-report_only { color: #e0a800; }
  .dec-undecided, .dec-none { color: var(--muted); }

  tr.actions td { padding-top: 0; }
  .act { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .dbtn.current { border-color: var(--accent); color: var(--accent); }
  .note { flex: 1 1 160px; min-width: 0; background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; font: inherit; font-size: 12.5px; }
  .answer { flex-basis: 100%; overflow-wrap: anywhere; white-space: pre-wrap; font-size: 12.5px; }

  tr.detail td { background: var(--panel-2); }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0; font-size: 12.5px; }
  dt { color: var(--muted); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .hist { margin: 0; padding-left: 18px; font-size: 12.5px; }
  .hist li { margin-bottom: 6px; }

  /* Phone width: each gate becomes a stacked card; no horizontal page scroll. */
  @media (max-width: 760px) {
    .stat.wide { grid-column: span 1; }
    .tablewrap { overflow-x: visible; background: none; border: none; }
    table, thead, tbody, tr, td { display: block; width: 100%; }
    thead { display: none; }
    tbody { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; overflow: hidden; }
    tbody.flagged { border-color: var(--neg); }
    tbody.flagged tr.main td:first-child { box-shadow: none; }
    tr.main td { display: flex; gap: 10px; padding: 4px 12px; }
    tr.main td::before { content: attr(data-label); color: var(--muted); font-size: 11.5px; flex: 0 0 96px; }
    tr.main td[data-label=""]::before { content: none; }
    .wrap { max-width: none; }
    .r { text-align: left; }
    tr.actions td, tr.detail td { padding: 8px 12px; }
    dl { grid-template-columns: 1fr; }
    dt { margin-top: 4px; }
  }
</style>
