<script lang="ts">
  // Trade approvals — the SPA's Approve / Reject button for a live-review
  // recommendation (bot TRADE-ACTION-DIRECT-PATH phase 1b, #25046).
  //
  // Operator, 2026-11-12: "there needs to be a button that I press to accept a
  // recommendation, and that directly executes that action." Approve calls
  // `POST /api/bot/trade-approvals/{token}` → `trade_approvals.decide(...,
  // source="spa")`, the SAME state machine as the Telegram buttons: whichever
  // surface decides first wins, the other reads `already_<state>`. Execution is
  // the bot's directed-action spool (each account's own RiskManager, read back
  // from the venue); this panel decides nothing about the trade itself.
  //
  // One press executes, exactly like the Telegram button — no confirm dialog and
  // no client-side refusal (operator 2026-11-12: "no more gates that I don't
  // explicitly give you permission for"). The countdown is display only: an
  // expired ask is still pressable and the bot's own 410 answer is shown verbatim
  // (a browser clock can be wrong; the bot decides). Every kind of pending ask
  // gets the buttons — the bot's decide route takes any ask token.
  //
  // Polls every 15 s while the tab is visible. ⚠️ When T2 lands (the SPA on
  // /api/bot/stream) this poll should move onto a stream frame if the
  // broadcaster carries approval events; until then a 15-minute ask needs a
  // poll to appear at all.
  import { onMount, onDestroy } from "svelte";
  import { api, AuthRequiredError, type TradeApprovalAsk } from "../lib/api";
  import { hasAnyToken, requestLogin, session } from "../lib/auth";
  import { DASH } from "../lib/format";

  // `embedded`: rendered inside the Overview "Waiting on me" card (UI-REDESIGN-2026-11
  // addendum 1) — no panel chrome, and trade asks are RED so a real-money decision is
  // never confused with a housekeeping ask. `pendingCount` is bound out for the card title.
  let { embedded = false, pendingCount = $bindable(0) }: { embedded?: boolean; pendingCount?: number } = $props();

  let asks = $state<TradeApprovalAsk[] | null>(null);
  let error = $state<string | null>(null);
  let signedIn = $state(hasAnyToken());
  let busy = $state<Record<string, boolean>>({});
  let results = $state<Record<string, { ok: boolean; text: string }>>({});
  let now = $state(Date.now());
  let showDecided = $state(false);

  const isTradeAsk = (a: TradeApprovalAsk) => !a.kind || a.kind === "trade";
  const expired = (a: TradeApprovalAsk) => !!a.expires_at && Date.parse(a.expires_at) <= now;
  const pending = $derived((asks ?? []).filter((a) => a.state === "pending"));
  const decided = $derived((asks ?? []).filter((a) => a.state !== "pending").slice(0, 10));
  $effect(() => { pendingCount = pending.length; });

  function fmtLevel(v: number | null | undefined): string {
    return v == null || Number.isNaN(v) ? DASH : String(v);
  }

  // Mirrors trade_approvals._action_text (bot) so both surfaces say the same thing.
  function actionText(a: TradeApprovalAsk): string {
    const d = a.directed ?? {};
    switch (d.action) {
      case "close":
        return "CLOSE the position";
      case "partial_close":
        return d.fraction == null ? `CLOSE ${DASH} of the position` : `CLOSE ${Math.round(d.fraction * 100)}% of the position`;
      case "move_tp":
        return `Move TP to ${fmtLevel(d.level)}`;
      case "tighten_sl":
        return `Tighten SL to ${fmtLevel(d.level)}`;
      case "move_sl":
        return `Move SL to ${fmtLevel(d.level)} (looser: a widen)`;
      default:
        return d.action ?? a.row_action ?? DASH;
    }
  }

  function countdown(iso: string | null | undefined): string {
    if (!iso) return DASH;
    const ms = Date.parse(iso) - now;
    if (Number.isNaN(ms)) return DASH;
    if (ms <= 0) return "expired";
    const m = Math.floor(ms / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${m}:${String(s).padStart(2, "0")} left`;
  }

  function hhmm(iso: string | null | undefined): string {
    return iso && iso.length >= 16 ? `${iso.slice(11, 16)}Z` : DASH;
  }

  async function load(): Promise<void> {
    signedIn = hasAnyToken();
    if (!signedIn) {
      asks = null;
      return;
    }
    try {
      const r = await api.tradeApprovals();
      asks = Array.isArray(r?.asks) ? r.asks : [];
      error = null;
    } catch (e) {
      if (e instanceof AuthRequiredError) {
        signedIn = false;
        asks = null;
      } else {
        error = e instanceof Error ? e.message : String(e);
      }
    }
  }

  async function decide(a: TradeApprovalAsk, choice: "approve" | "reject"): Promise<void> {
    if (busy[a.token]) return;
    busy = { ...busy, [a.token]: true };
    try {
      const r = await api.decideTradeApproval(a.token, choice);
      const ok = r.outcome === "approved" || r.outcome === "rejected";
      results = { ...results, [a.token]: { ok, text: r.reply ?? r.outcome ?? `HTTP ${r.status}` } };
    } catch (e) {
      const text = e instanceof AuthRequiredError ? "Session expired — sign in again; nothing was done." : e instanceof Error ? e.message : String(e);
      results = { ...results, [a.token]: { ok: false, text } };
    } finally {
      busy = { ...busy, [a.token]: false };
      await load();
    }
  }

  let poll: ReturnType<typeof setInterval> | null = null;
  let clock: ReturnType<typeof setInterval> | null = null;
  const unsub = session.subscribe(() => load());

  onMount(() => {
    poll = setInterval(() => { if (!document.hidden) load(); }, 15000);
    clock = setInterval(() => (now = Date.now()), 1000);
  });
  onDestroy(() => {
    if (poll) clearInterval(poll);
    if (clock) clearInterval(clock);
    unsub();
  });
</script>

<div class="ta" class:panel={!embedded} class:embedded class:hot={pending.length > 0}>
  {#if !embedded}
    <div class="ph">
      <span>🔔 Trade approvals{asks ? ` · ${pending.length} waiting` : ""}</span>
    </div>
  {/if}

  {#if !signedIn}
    <div class="pad muted small">
      Approvals need a signed-in session.
      <button class="btn" onclick={() => requestLogin("Trade approvals need a signed-in session.")}>Sign in</button>
    </div>
  {:else if error && !asks}
    <div class="pad err">Couldn't load approvals: <span class="mono">{error}</span></div>
  {:else if !asks}
    <div class="pad muted small">Loading…</div>
  {:else}
    {#if error}<div class="pad err small">Last refresh failed: <span class="mono">{error}</span></div>{/if}
    {#each pending as a (a.token)}
      {#if isTradeAsk(a)}
        <div class="ask money">
          <div class="top">
            <span class="tag">💰 TRADE DECISION</span>
            <b>{a.symbol ?? DASH}</b>
            <span class="muted">{a.leg ?? DASH}</span>
            <span class="cd mono" class:late={expired(a)}>{countdown(a.expires_at)}</span>
          </div>
          <div class="act">➡️ {actionText(a)}</div>
          <div class="meta small">
            <span>Accounts: {(a.accounts ?? []).join(", ") || DASH}</span>
            <span>EV vs hold: {a.ev_delta_r == null ? DASH : `${a.ev_delta_r >= 0 ? "+" : ""}${a.ev_delta_r.toFixed(3)}R`}</span>
            <span>basis: {a.basis ?? DASH} · confidence: {a.confidence ?? DASH}</span>
          </div>
          {#if a.reason}<div class="reason small">{a.reason}</div>{/if}
          {#if a.mechanics && a.mechanics !== "match"}
            <div class="warn small">⚠️ mechanics: {a.mechanics} (the venue read did not complete at review time)</div>
          {/if}
          <div class="btns">
            <button class="approve" disabled={busy[a.token]} onclick={() => decide(a, "approve")}>
              {busy[a.token] ? "Sending…" : "✅ Approve"}
            </button>
            <button class="reject" disabled={busy[a.token]} onclick={() => decide(a, "reject")}>✖ Reject</button>
            <span class="muted small mono">{a.review_id ?? DASH}</span>
          </div>
          <div class="muted small">Approve executes now on every account carrying the package, through each account's own risk checks.</div>
          {#if results[a.token]}
            <div class="small" class:okmsg={results[a.token].ok} class:err={!results[a.token].ok}>{results[a.token].text}</div>
          {/if}
        </div>
      {:else}
        <!-- Non-trade ask (e.g. kind ops_job): same buttons, same route — the bot
             decides whether it accepts the token and its answer is shown verbatim. -->
        <div class="ask other">
          <div class="top"><b>{a.title ?? a.kind}</b> <span class="muted">{a.kind}</span>
            <span class="cd mono" class:late={expired(a)}>{countdown(a.expires_at)}</span></div>
          {#if a.summary ?? a.reason}<div class="reason small">{a.summary ?? a.reason}</div>{/if}
          <div class="btns">
            <button class="approve" disabled={busy[a.token]} onclick={() => decide(a, "approve")}>{busy[a.token] ? "Sending…" : "✅ Approve"}</button>
            <button class="reject" disabled={busy[a.token]} onclick={() => decide(a, "reject")}>✖ Reject</button>
          </div>
          {#if results[a.token]}
            <div class="small" class:okmsg={results[a.token].ok} class:err={!results[a.token].ok}>{results[a.token].text}</div>
          {/if}
        </div>
      {/if}
    {:else}
      <div class="pad muted small">No trade decisions waiting on you.</div>
    {/each}

    {#each Object.entries(results).filter(([t]) => !pending.some((a) => a.token === t)) as [t, r] (t)}
      <div class="pad small" class:okmsg={r.ok} class:err={!r.ok}>{r.text}</div>
    {/each}

    {#if decided.length}
      <button class="link small" onclick={() => (showDecided = !showDecided)}>
        {showDecided ? "Hide" : "Show"} recent decisions ({decided.length})
      </button>
      {#if showDecided}
        <table class="small">
          <thead><tr><th>Asked</th><th>Symbol</th><th>Action</th><th>State</th><th>Decided</th><th>Record</th></tr></thead>
          <tbody>
            {#each decided as a (a.token)}
              <tr>
                <td class="mono">{hhmm(a.created_at)}</td>
                <td>{a.symbol ?? a.title ?? DASH}</td>
                <td>{isTradeAsk(a) ? actionText(a) : (a.kind ?? DASH)}</td>
                <td>{a.state ?? DASH}</td>
                <td class="mono">{hhmm(a.decided_at)}</td>
                <td class="mono">{a.record_id ?? DASH}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .ta { margin: 12px 0; }
  .ta.hot { border-color: #d4a017; }
  .ph { padding: 10px 12px; font-weight: 600; border-bottom: 1px solid var(--border); }
  .pad { padding: 10px 12px; }
  .small { font-size: 12px; }
  .err { color: var(--neg); }
  .okmsg { color: var(--pos); }
  .warn { color: #d4a017; }
  .ask { padding: 10px 12px; border-bottom: 1px solid var(--border); display: grid; gap: 6px; }
  .ask.other { opacity: 0.85; }
  /* Real-money decisions are RED (addendum 1): never mistaken for a housekeeping ask. */
  .ask.money { border: 2px solid var(--neg); border-radius: 8px; background: color-mix(in srgb, var(--neg) 8%, transparent); margin: 6px 0; }
  .tag { background: var(--neg); color: #fff; font-size: 10.5px; font-weight: 700; padding: 1px 6px; border-radius: 4px; letter-spacing: 0.03em; }
  .embedded .pad { padding: 4px 0; }
  .embedded .link { padding: 6px 0; }
  .top { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .cd { margin-left: auto; color: var(--muted); }
  .cd.late { color: var(--neg); }
  .act { font-size: 15px; font-weight: 600; }
  .meta { display: flex; gap: 12px; flex-wrap: wrap; color: var(--muted); }
  .reason { color: var(--text); overflow-wrap: anywhere; }
  .btns { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .btns button { padding: 10px 18px; border-radius: 8px; border: 1px solid var(--border); font-weight: 600; cursor: pointer; font-size: 14px; }
  .approve { background: var(--pos); color: #fff; border-color: var(--pos); }
  .reject { background: var(--panel-2); color: var(--text); }
  .btns button:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn { margin-left: 8px; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--panel-2); color: var(--text); cursor: pointer; }
  .link { background: none; border: none; color: var(--accent); cursor: pointer; padding: 8px 12px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 4px 12px; border-top: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  @media (max-width: 640px) { th:nth-child(6), td:nth-child(6) { display: none; } }
</style>
