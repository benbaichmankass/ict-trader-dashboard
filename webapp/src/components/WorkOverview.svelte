<script lang="ts">
  // WORK = THE CONSOLE'S OVERVIEW (UI-REDESIGN-2026-11, "WORK: implement the JTA
  // console's overview page as the design spec, as is"). The console's Overview
  // has four cards: Inbox · This week · Roadmap · Health. This ports the three
  // whose data has a browser-readable route today; "This week" needs a paged,
  // sectioned rows route (the console's work_rows tool) that the bot does not
  // serve yet, so it names that gap instead of polling the ~5.8 MB checklist.
  //
  // Read-only. The console's writes (Mark done, replies, rank/lane moves, notes)
  // have no REST route and are not ported. Every section that could not be read
  // says so with the reason — never an empty list standing in for "nothing".
  import { onMount, onDestroy } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, num, DASH } from "../lib/format";
  import HealthBar from "./HealthBar.svelte";

  const POLL_MS = 60_000;
  const ALERT_WINDOW_H = 24;
  const ALERT_LIMIT = 200;
  const CARD_KEY = "ict.workOverview.cards";
  const CLOSED = new Set(["done", "dropped"]); // the console's inbox excludes these

  type Read<T> = { v: T | null; err: string | null };
  const empty = <T,>(): Read<T> => ({ v: null, err: null });

  let decisions = $state<Read<any>>(empty());
  let snapshot = $state<Read<any>>(empty());
  let alerts = $state<Read<any>>(empty());
  let topics = $state<Read<any>>(empty());
  let services = $state<Read<any>>(empty());
  let loadedAt = $state<string | null>(null);
  let alertsSince = $state<string>("");

  // Which cards are open — persisted like the console's CARD_KEY.
  function savedCards(): Record<string, boolean> {
    const dflt = { inbox: true, week: true, roadmap: true, health: true };
    try {
      const saved = JSON.parse(localStorage.getItem(CARD_KEY) ?? "null");
      return saved && typeof saved === "object" ? { ...dflt, ...saved } : dflt;
    } catch { return dflt; } // storage unavailable: defaults
  }
  let open = $state<Record<string, boolean>>(savedCards());
  function toggled(k: string, e: Event) {
    open[k] = (e.currentTarget as HTMLDetailsElement).open;
    try { localStorage.setItem(CARD_KEY, JSON.stringify(open)); } catch { /* ignore */ }
  }

  const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));
  async function settle<T>(p: Promise<T>): Promise<Read<T>> {
    try { return { v: await p, err: null }; } catch (e) { return { v: null, err: msg(e) }; }
  }

  async function load() {
    alertsSince = new Date(Date.now() - ALERT_WINDOW_H * 3600_000).toISOString().replace(/\.\d+Z$/, "Z");
    // Settled independently: one unreadable register is not evidence about the others.
    const [d, s, a, t, h] = await Promise.all([
      settle(api.workDecisions()),
      settle(api.workSnapshot()),
      settle(api.alerts({ since: alertsSince, limit: ALERT_LIMIT })),
      settle(api.workTopics()),
      settle(api.healthServices()),
    ]);
    decisions = d; snapshot = s; alerts = a; topics = t; services = h;
    loadedAt = new Date().toISOString();
  }
  let timer: ReturnType<typeof setInterval> | undefined;
  onMount(() => { load(); timer = setInterval(load, POLL_MS); });
  onDestroy(() => clearInterval(timer));

  // ---- Inbox ---------------------------------------------------------------
  type InboxRow = { id: string; chip: "decide" | "ask"; title: string; sub: string; when: string };
  const inbox = $derived.by(() => {
    const rows: InboxRow[] = [];
    const seen = new Set<string>();
    const dv = decisions.v;
    for (const r of dv?.requests ?? []) {
      const id = String(r.id ?? r.requestId ?? r.objectId ?? "");
      rows.push({ id, chip: "decide", title: r.title ?? r.question ?? r.objectTitle ?? DASH,
        sub: r.ref ?? r.note ?? "", when: r.dueBy ? `due ${r.dueBy}` : "" });
      if (id) seen.add(id);
    }
    for (const e of dv?.unanswerableOperatorEdges ?? []) {
      if (CLOSED.has(String(e.objectLifecycle ?? ""))) continue;
      const id = String(e.objectId ?? "");
      if (id && seen.has(id)) continue;
      rows.push({ id, chip: "decide", title: e.objectTitle ?? DASH,
        sub: [e.objectLifecycle, e.ref].filter(Boolean).join(" · "), when: e.since ? `since ${String(e.since).slice(0, 10)}` : "" });
      if (id) seen.add(id);
    }
    for (const w of snapshot.v?.waitingOnOperator ?? []) {
      const id = String(w.id ?? "");
      const what = (w.asks ?? []).map((a: any) => a.what).filter(Boolean).join(" · ");
      if (id && seen.has(id)) {
        // Same row already listed as a decision: add the ask text, don't list it twice.
        const r = rows.find((x) => x.id === id);
        if (r && what) r.sub = [r.sub, what].filter(Boolean).join(" — ");
        continue;
      }
      rows.push({ id, chip: "ask", title: w.title ?? DASH,
        sub: [w.state, what].filter(Boolean).join(" · "), when: w.updatedAt ? `upd ${agoFromIso(w.updatedAt)}` : "" });
      if (id) seen.add(id);
    }
    return rows;
  });
  const highAlerts = $derived(
    (alerts.v?.rows ?? []).filter((r: any) => r.priority === "high")
      .sort((a: any, b: any) => String(b.ts).localeCompare(String(a.ts))),
  );
  const alertsReadable = $derived(alerts.v != null && alerts.v.read_state === "read");
  let showAllAlerts = $state(false);
  let expanded = $state<Record<number, boolean>>({});

  // ---- Roadmap -------------------------------------------------------------
  const topicRows = $derived(
    [...(topics.v?.topics ?? [])].sort((a: any, b: any) => (b.n_open ?? 0) - (a.n_open ?? 0)),
  );
  const openTotal = $derived(topicRows.reduce((s: number, t: any) => s + (t.n_open ?? 0), 0));

  const svcLight = (s: any) => (s.state === "active" ? "ok" : s.state ? "bad" : "unknown");
</script>

<div class="wo">
  <div class="meta muted small">
    Console overview · read-only · refreshes every {POLL_MS / 1000}s{loadedAt ? ` · read ${agoFromIso(loadedAt)}` : ""}
  </div>

  <!-- 1. Inbox -->
  <details class="card" open={open.inbox} ontoggle={(e) => toggled("inbox", e)}>
    <summary>
      <span class="ct">Inbox</span>
      <span class="muted small">{decisions.v || snapshot.v ? `${inbox.length} open` : DASH}{alertsReadable ? ` · ${highAlerts.length} high alerts` : ""}</span>
    </summary>
    {#if !decisions.v && !snapshot.v && !decisions.err && !snapshot.err}
      <div class="muted">Loading…</div>
    {:else}
      {#if decisions.err}<div class="na">Decisions: not available (<span class="mono">{decisions.err}</span>)</div>{/if}
      {#if snapshot.err}<div class="na">Pipeline asks: not available (<span class="mono">{snapshot.err}</span>)</div>{:else if snapshot.v && snapshot.v.present === false}<div class="na">Pipeline asks: not available ({snapshot.v.reason ?? DASH})</div>{/if}
      {#if inbox.length}
        <ul class="rows">
          {#each inbox as r (r.chip + r.id + r.title)}
            <li>
              <span class="chip {r.chip}">{r.chip}</span>
              <div class="body">
                <div><span class="mono id">{r.id || DASH}</span> {r.title}</div>
                {#if r.sub}<div class="muted small sub">{r.sub}</div>{/if}
              </div>
              <span class="muted small when">{r.when}</span>
            </li>
          {/each}
        </ul>
      {:else if !decisions.err && !snapshot.err}
        <div class="muted">Nothing waiting on you.</div>
      {/if}

      <div class="subhead">Alerts · high priority · last {ALERT_WINDOW_H}h</div>
      {#if alerts.err}
        <div class="na">Alerts: not available (<span class="mono">{alerts.err}</span>)</div>
      {:else if !alerts.v}
        <div class="muted">Loading…</div>
      {:else if !alertsReadable}
        <div class="na">Alerts: not available ({alerts.v.read_state ?? DASH})</div>
      {:else}
        {#if highAlerts.length}
          <ul class="rows">
            {#each showAllAlerts ? highAlerts : highAlerts.slice(0, 8) as a, i (i + String(a.ts))}
              <li>
                <span class="chip alert">alert</span>
                <div class="body">
                  <button class="abody" class:clamp={!expanded[i]} onclick={() => (expanded[i] = !expanded[i])} title={expanded[i] ? "collapse" : "expand"}>{a.body ?? DASH}</button>
                  <div class="muted small sub">{a.kind ?? DASH} · {a.channel ?? DASH} · delivered: {a.delivered ?? DASH}</div>
                </div>
                <span class="muted small when">{agoFromIso(a.ts)}</span>
              </li>
            {/each}
          </ul>
          {#if highAlerts.length > 8}
            <button class="link" onclick={() => (showAllAlerts = !showAllAlerts)}>{showAllAlerts ? "Show fewer" : `Show all ${highAlerts.length}`}</button>
          {/if}
        {:else}
          <div class="muted">No high-priority alerts in this window.</div>
        {/if}
        <div class="muted small foot">
          Read the newest {num(alerts.v.rows?.length)} of {num(alerts.v.total_matching)} alerts since {alertsSince.slice(11, 16)}Z
          {#if alerts.v.rows_truncated_to_limit} (older ones in the window not read){/if}.
        </div>
      {/if}
    {/if}
  </details>

  <!-- 2. This week -->
  <details class="card" open={open.week} ontoggle={(e) => toggled("week", e)}>
    <summary><span class="ct">This week</span><span class="muted small">{DASH}</span></summary>
    <div class="na">
      Not available yet: this card needs a paged, sectioned work-rows route (the console's
      <span class="mono">work_rows</span>: due / in flight / blocked / queued, week lanes, closed this week).
      The bot does not serve one yet (<span class="mono">/api/bot/work/rows</span> → 404), and this page will not
      poll the full ~5.8 MB checklist to build it. The full register is on the <b>Work</b> view.
    </div>
  </details>

  <!-- 3. Roadmap -->
  <details class="card" open={open.roadmap} ontoggle={(e) => toggled("roadmap", e)}>
    <summary>
      <span class="ct">Roadmap</span>
      <span class="muted small">{topics.v?.read_state === "measured" ? `${num(openTotal)} open rows · ${num(topics.v?.unmapped?.n_rows)} unmapped` : DASH}</span>
    </summary>
    {#if topics.err}
      <div class="na">Roadmap: not available (<span class="mono">{topics.err}</span>)</div>
    {:else if !topics.v}
      <div class="muted">Loading…</div>
    {:else if topics.v.read_state !== "measured"}
      <div class="na">Roadmap: not available ({topics.v.read_state ?? DASH})</div>
    {:else}
      <table>
        <thead><tr><th>Topic</th><th class="r">Open</th><th class="r">Total</th><th></th></tr></thead>
        <tbody>
          {#each topicRows as t (t.topic)}
            <tr>
              <td class="sym">{t.topic}</td>
              <td class="r mono">{num(t.n_open)}</td>
              <td class="r mono muted">{num(t.n_total)}</td>
              <td class="bar"><span style="width:{t.n_total ? Math.round((100 * (t.n_open ?? 0)) / t.n_total) : 0}%"></span></td>
            </tr>
            {#if (t.subtopics ?? []).length > 1}
              {#each t.subtopics as st (st.subtopic)}
                <tr class="subt"><td>↳ {st.subtopic || DASH}</td><td class="r mono">{num(st.n_open)}</td><td class="r mono muted">{num(st.n_total)}</td><td></td></tr>
              {/each}
            {/if}
          {/each}
        </tbody>
      </table>
      <div class="muted small foot">
        Every work row, grouped by roadmap topic ({num(topics.v.n_rows)} rows,
        {num(topics.v.coverage?.n_mapped)} of {num(topics.v.coverage?.n_milestones)} milestones mapped).
        Unlike the console's card, this count includes rows already in this week's plan; that split needs the rows route above.
        {#if topics.v.unmapped?.refs} Unmapped refs: {Object.entries(topics.v.unmapped.refs).map(([k, v]) => `${k} ${v}`).join(" · ")}.{/if}
        Drill-down: the <b>Topics &amp; insights</b> and <b>Roadmap</b> views.
      </div>
    {/if}
  </details>

  <!-- 4. Health -->
  <details class="card" open={open.health} ontoggle={(e) => toggled("health", e)}>
    <summary><span class="ct">Health</span><span class="muted small">{services.v ? "live" : DASH}</span></summary>
    <HealthBar />
    <div class="subhead">Trader VM services</div>
    {#if services.err}
      <div class="na">Services: not available (<span class="mono">{services.err}</span>)</div>
    {:else if !services.v}
      <div class="muted">Loading…</div>
    {:else if services.v.systemctl_available === false}
      <div class="na">Services: not available (systemctl not readable on the VM)</div>
    {:else}
      <ul class="svcs">
        {#each services.v.services ?? [] as s (s.unit)}
          <li><span class="dot {svcLight(s)}"></span><span class="mono">{s.unit}</span>
            <span class="muted small">{s.state ?? DASH}/{s.sub_state ?? DASH}{s.active_enter_iso ? ` · since ${s.active_enter_iso}` : ""}</span></li>
        {/each}
      </ul>
    {/if}
    <div class="muted small foot">
      Timers, restarts today, tick cost and per-VM CPU/memory/disk are on the console only: they come from the diag
      routes, whose token cannot go into a browser.
    </div>
  </details>
</div>

<style>
  .wo { display: flex; flex-direction: column; gap: 10px; }
  .card { padding: 10px 12px; }
  summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "▸"; color: var(--muted); }
  details[open] > summary::before { content: "▾"; }
  .ct { font-weight: 600; }
  .small { font-size: 12px; }
  .subhead { font-weight: 600; font-size: 13px; margin: 12px 0 4px; }
  .rows { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; }
  .rows li { display: flex; gap: 10px; align-items: flex-start; padding: 7px 0; border-bottom: 1px solid var(--border); }
  .body { flex: 1; min-width: 0; }
  .sub, .abody { overflow-wrap: anywhere; }
  .abody { white-space: pre-wrap; font-size: 13px; background: none; border: none; color: inherit; text-align: left; padding: 0; cursor: pointer; font-family: inherit; width: 100%; }
  .abody.clamp { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .id { color: var(--muted); font-size: 12px; }
  .when { white-space: nowrap; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 8px; text-transform: uppercase; letter-spacing: 0.03em; flex: none; margin-top: 2px; }
  .chip.decide { background: #e5484d22; color: #e5484d; }
  .chip.ask { background: #d4a01722; color: #d4a017; }
  .chip.alert { background: #c2410c22; color: #c2410c; }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 4px 8px; margin: 6px 0; font-size: 13px; }
  .foot { margin-top: 8px; line-height: 1.5; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); cursor: pointer; padding: 4px 0; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
  th, td { padding: 5px 8px; text-align: left; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .subt td { color: var(--muted); font-size: 12px; padding-top: 2px; padding-bottom: 2px; }
  .bar { width: 30%; }
  .bar span { display: block; height: 6px; border-radius: 3px; background: var(--accent, #4c8dff); opacity: 0.6; }
  .svcs { list-style: none; padding: 0; margin: 4px 0; display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .svcs li { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: var(--muted); flex: none; }
  .dot.ok { background: #30a46c; }
  .dot.bad { background: #e5484d; }
</style>
