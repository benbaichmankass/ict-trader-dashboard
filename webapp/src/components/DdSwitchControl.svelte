<script lang="ts">
  // Daily drawdown switch + its once-a-day override (operator m7, 2026-11-12: "Build
  // the one-time override button and fix the day-start reading first"; bot
  // DD-SWITCH-OVERRIDE #25181). One control per ARMED account.
  //
  // State: GET /api/bot/accounts/{id}/daily-dd-switch (open read) when deployed.
  // Until it is, the bot's own /config `daily_dd_switch` block is shown read-only
  // (labelled as such) and the override says "not available yet" — never a fake state.
  //
  // REAL-MONEY ACTION. The override re-allows new entries on a tripped account for
  // the rest of the day. Styled like the red trade-decision box. ONE PRESS POSTs it
  // (no confirm step — operator 2026-11-12: "no more gates that I don't explicitly give
  // you permission for"), with an optional inline reason, the session bearer
  // (require_session); enabled exactly when the bot says tripped AND
  // override_available; every 4xx/503 shown verbatim; the state re-read afterwards.
  //
  // `onlyTripped`: the Overview "waiting on me" placement — render only tripped accounts.
  import { onMount } from "svelte";
  import { api, AuthRequiredError } from "../lib/api";
  import { money, DASH } from "../lib/format";

  let { onlyTripped = false, trippedCount = $bindable(0) }: { onlyTripped?: boolean; trippedCount?: number } = $props();

  type Row = { id: string; cls: string; route: "live" | "missing" | "error"; s: any; err: string | null };
  let rows = $state<Row[]>([]);
  let loaded = $state(false);
  let configError = $state<string | null>(null);
  let reasons = $state<Record<string, string>>({});
  let busy = $state<string | null>(null);
  let results = $state<Record<string, { ok: boolean; text: string }>>({});

  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

  async function load() {
    try {
      const cfg = await api.config();
      const armed = ((cfg?.accounts ?? []) as any[]).filter((a) => a?.daily_dd_switch?.armed === true);
      const out: Row[] = [];
      for (const a of armed) {
        const id = String(a.id ?? a.account_id);
        try {
          const r = await api.dailyDdSwitch(id);
          if (r.status === 200 && r.body?.status) out.push({ id, cls: a.account_class ?? DASH, route: "live", s: r.body.status, err: null });
          else if (r.status === 404) out.push({ id, cls: a.account_class ?? DASH, route: "missing", s: a.daily_dd_switch, err: null });
          else out.push({ id, cls: a.account_class ?? DASH, route: "error", s: a.daily_dd_switch, err: `${r.status} ${typeof r.body?.detail === "string" ? r.body.detail : ""}`.trim() });
        } catch (e) {
          if (e instanceof AuthRequiredError) throw e;
          out.push({ id, cls: a.account_class ?? DASH, route: "error", s: a.daily_dd_switch, err: e instanceof Error ? e.message : String(e) });
        }
      }
      rows = out;
      configError = null;
    } catch (e) {
      configError = e instanceof Error ? e.message : String(e);
    } finally {
      loaded = true;
    }
  }
  onMount(load);

  // ok / awaiting_day_start / tripped / overridden — from the live route when present.
  function stateOf(r: Row): "tripped" | "overridden" | "awaiting_day_start" | "ok" | "unknown" {
    const s = r.s ?? {};
    if (s.override && (s.override === true || typeof s.override === "object")) return "overridden";
    if (s.tripped === true) return "tripped";
    if (s.awaiting_day_start === true || s.state === "awaiting_day_start" || (r.route === "live" && s.day_start_equity == null)) return "awaiting_day_start";
    if (s.tripped === false) return "ok";
    return "unknown";
  }
  const shown = $derived(onlyTripped ? rows.filter((r) => stateOf(r) === "tripped") : rows);
  $effect(() => { trippedCount = rows.filter((r) => stateOf(r) === "tripped").length; });
  const canOverride = (r: Row) => r.route === "live" && stateOf(r) === "tripped" && r.s?.override_available === true;

  async function doOverride(r: Row) {
    busy = r.id;
    try {
      const res = await api.overrideDdSwitch(r.id, (reasons[r.id] ?? "").trim() || undefined);
      const b = res.body ?? {};
      const why = typeof b.detail === "string" ? b.detail : b.detail?.error ?? b.outcome ?? b.error ?? null;
      results = { ...results, [r.id]: res.status === 200
        ? { ok: true, text: `Overridden${b.override?.at ? ` at ${b.override.at}` : ""}: new entries allowed again on ${r.id} for the rest of today.` }
        : { ok: false, text: `${res.status}: ${why ?? "refused"} — nothing was overridden.` } };
    } catch (e) {
      results = { ...results, [r.id]: { ok: false, text: e instanceof AuthRequiredError ? "Session expired — sign in again; nothing was overridden." : (e instanceof Error ? e.message : String(e)) } };
    } finally {
      busy = null; reasons = { ...reasons, [r.id]: "" };
      await load();
    }
  }
  const STATE_LABEL = { tripped: "TRIPPED — refusing new entries", overridden: "overridden today", awaiting_day_start: "awaiting day start", ok: "ok", unknown: "—" } as const;
</script>

{#if configError}
  <div class="err small">Couldn't read the drawdown switches: <span class="mono">{configError}</span></div>
{:else if !loaded}
  {#if !onlyTripped}<div class="muted small">Loading…</div>{/if}
{:else if !shown.length}
  {#if !onlyTripped}<div class="muted small">No account has the daily drawdown switch armed.</div>{/if}
{:else}
  {#each shown as r (r.id)}
    {@const st = stateOf(r)}
    <div class="dd" class:money={st === "tripped"}>
      <div class="top">
        {#if st === "tripped"}<span class="tag">💰 DRAWDOWN SWITCH</span>{/if}
        <b>{r.id}</b> <span class="muted">{r.cls}</span>
        <span class="st {st}">{STATE_LABEL[st]}</span>
      </div>
      <div class="meta">
        <span>Day-start equity <b class="mono">{num(r.s?.day_start_equity) == null ? DASH : money(r.s.day_start_equity)}</b></span>
        <span>Loss <b class="mono">{num(r.s?.loss_usd) == null ? DASH : money(r.s.loss_usd)}</b> of limit <b class="mono">{num(r.s?.limit_usd) == null ? DASH : money(r.s.limit_usd)}</b>{r.s?.limit_desc ? ` (${r.s.limit_desc})` : ""}</span>
        <span>Override today: <b>{r.route !== "live" ? DASH : r.s?.override_available === true ? "available" : st === "overridden" ? "used" : st === "ok" || st === "awaiting_day_start" ? "n/a (not tripped)" : r.s?.override_available === false ? "not available" : DASH}</b></span>
        {#if r.s?.read_state && r.s.read_state !== "ok"}<span class="warn">read_state {r.s.read_state}</span>{/if}
      </div>
      {#if r.route === "missing"}
        <div class="muted small">Override not available yet — the bot's switch route isn't deployed. State above is the bot's /config reading.</div>
      {:else if r.route === "error"}
        <div class="err small">Switch route error: <span class="mono">{r.err}</span>. State above is the bot's /config reading.</div>
      {/if}
      {#if canOverride(r)}
        <!-- One press POSTs the override (operator: no gates not asked for). Shown only
             when the bot says tripped AND override_available — the server's own state. -->
        <div class="btns">
          <input class="reason" placeholder="Reason (optional)" bind:value={reasons[r.id]} maxlength="200" />
          <button class="go" disabled={busy === r.id} onclick={() => doOverride(r)}>{busy === r.id ? "Sending…" : "Override once today"}</button>
        </div>
      {/if}
      {#if results[r.id]}<div class="small" class:okmsg={results[r.id].ok} class:err={!results[r.id].ok}>{results[r.id].text}</div>{/if}
    </div>
  {/each}
{/if}

<style>
  .dd { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin: 6px 0; display: grid; gap: 5px; font-size: 12.5px; }
  .dd.money { border: 2px solid var(--neg); background: color-mix(in srgb, var(--neg) 8%, transparent); }
  .top { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .tag { background: var(--neg); color: #fff; font-size: 10.5px; font-weight: 700; padding: 1px 6px; border-radius: 4px; }
  .st { margin-left: auto; font-weight: 700; font-size: 11.5px; }
  .st.tripped { color: var(--neg); } .st.ok { color: var(--pos); } .st.overridden { color: #d4a017; } .st.awaiting_day_start, .st.unknown { color: var(--muted); }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--muted); }
  .meta b { color: var(--text); }
  .reason { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font: inherit; }
  .btns { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .btns button { padding: 8px 14px; border-radius: 8px; border: 1px solid var(--border); font-weight: 600; cursor: pointer; font-size: 13px; }
  .go { background: var(--neg); color: #fff; border-color: var(--neg); }
  .btns button:disabled { opacity: 0.45; cursor: not-allowed; }
  .warn { color: #d4a017; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .err { color: var(--neg); }
  .okmsg { color: var(--pos); }
  .mono { font-variant-numeric: tabular-nums; }
</style>
