<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, signClass, agoFromIso, num, DASH } from "../lib/format";
  import { closedFills, fillBasis, fillBasisText, fillClosedAt, fillProvenance, shortUtc } from "../lib/propPnl";

  // One cushion/reconcile per LIVE prop account. Until 2026-10-15 this page
  // read status/reconcile for a hardcoded `breakout_1` — an account retired
  // by then (last snapshot 10-09, ~146 h stale) — so the cushion shown was a
  // dead account's and breakout_2 / tradeify_1 / velotrade_1 never appeared.
  // Accounts come from /prop/overview (the bot's roster), falling back to the
  // accounts seen in the fills journal — never a hardcoded id.
  let accounts = $state<{ id: string; status: any | null; reconcile: any | null }[]>([]);
  let tickets = $state<any[]>([]);
  let fills = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [ov, tk, fl] = await Promise.all([
        api.propOverview("7d").catch(() => null),
        api.propTickets(50).catch(() => null),
        api.propFills(200).catch(() => null),
      ]);
      tickets = tk?.tickets ?? [];
      fills = fl?.fills ?? [];
      let ids: string[] = (ov?.equity?.accounts ?? [])
        .map((a: any) => a?.account_id)
        .filter((x: unknown): x is string => typeof x === "string" && x.length > 0);
      if (ids.length === 0) {
        ids = [...new Set(fills.map((f) => f?.account_id).filter((x): x is string => typeof x === "string" && x.length > 0))];
      }
      ids.sort();
      accounts = await Promise.all(
        ids.map(async (id) => {
          const [st, rc] = await Promise.all([
            api.propStatus(id).catch(() => null),
            api.propReconcile(id).catch(() => null),
          ]);
          return { id, status: st, reconcile: rc };
        }),
      );
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  const closed = $derived(closedFills(fills));
  // The lifecycle log (placed / open / skipped / closed reports), newest first.
  const lifecycle = $derived([...fills].sort((a, b) => (b?.id ?? 0) - (a?.id ?? 0)));

  // BL-20260820-SPA-PROP-RULE-DISTANCE-DEAD-KEYS: these read
  // `daily_loss_remaining` / `static_dd_remaining` from 2026-07-16 (#194) to
  // 2026-08-20. Neither key has ever existed on the payload, so BOTH cushions
  // rendered as an em-dash — indistinguishable from a genuinely absent value —
  // and the `!= null` guard on the thin-cushion alert below made that alert
  // UNREACHABLE for 35 days, on the panel whose only job is to warn before an
  // account-killer breach. The real names are the ones the producer emits and
  // the Streamlit app has always read (streamlit_app.py:8183,8187).
  const rdOf = (st: any) => st?.rule_distance ?? null;
  const dailyLeftOf = (st: any): number | null => rdOf(st)?.distance_to_daily_loss_usd ?? null;
  const ddLeftOf = (st: any): number | null => rdOf(st)?.distance_to_dd_floor_usd ?? null;

  // Freshness is NOT decoration and must not be dropped again. The manual
  // bridge has no broker feed, so every distance above is a function of ONE
  // operator-reported snapshot; a three-week-old row renders a full-looking
  // cushion that is byte-identical to a live one. The bot publishes
  // `status_freshness` for exactly this reason and the contract says to read it
  // before treating any distance as a live cushion. Four states, never
  // collapsed — `ok` / `stale` (too old, OR undateable: a row that cannot be
  // dated cannot be shown to be current, and the fail-safe reading of a safety
  // cushion is stale) / `absent` (nothing ever reported) / `unchecked` (the
  // threshold is off — *we did not look*, which is NOT ok). A fifth, `error`,
  // rides on the envelope when the read itself failed.
  const freshnessOf = (st: any): string =>
    String(st?.status_freshness ?? rdOf(st)?.status_freshness ?? "unknown");
  const ageHoursOf = (st: any): number | null =>
    st?.status_age_hours ?? rdOf(st)?.status_age_hours ?? null;
  const FRESHNESS_NOTE: Record<string, string> = {
    ok: "",
    stale: "the snapshot is older than the freshness threshold, or cannot be dated — treat every figure below as a LAST-KNOWN cushion, not a live one",
    absent: "no account status has ever been reported for this account",
    unchecked: "the freshness check is switched off — nothing established whether this snapshot is current",
    error: "the freshness of this snapshot could not be read",
    unknown: "this build could not read a freshness verdict from the payload",
  };

  // Cushion severity: loud when a killer limit is close.
  function cushionClass(v: number | null): string {
    if (v == null) return "flat";
    if (v <= 25) return "neg";
    if (v <= 75) return "warn";
    return "pos";
  }
</script>

<section>
  <h2>Prop <span class="muted sub">· manual-bridge prop accounts (isolated journal — never blended into real/paper)</span></h2>
  {#if error}
    <div class="err panel">Couldn't load prop journal: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    <!-- Closed trades — the newest closes first, each P&L labelled with its basis and provenance -->
    <div class="panel scroll">
      <div class="ph pad-h">Closed trades <span class="muted sub">· newest first · P&amp;L is per-row: net/gross and MEASURED/ESTIMATED/UNVERIFIED are never mixed into one number</span></div>
      {#if closed.length === 0}
        <div class="muted pad">No closed prop trades reported yet.</div>
      {:else}
        <table>
          <thead><tr><th>Closed (UTC)</th><th>Account</th><th>Symbol</th><th>Dir</th><th class="r">Qty</th><th class="r">Entry</th><th class="r">Exit</th><th class="r">P&amp;L</th><th>Basis</th><th>Provenance</th><th>Reason</th></tr></thead>
          <tbody>
            {#each closed as f, i (f.id ?? i)}
              {@const prov = fillProvenance(f)}
              {@const basis = fillBasis(f)}
              <tr>
                <td class="muted" title={fillClosedAt(f) ?? ""}>{shortUtc(fillClosedAt(f))} <span class="small">· {agoFromIso(fillClosedAt(f))}</span></td>
                <td class="mono">{f.account_id ?? DASH}</td>
                <td class="sym">{f.symbol ?? DASH}</td>
                <td class={String(f.direction).toLowerCase() === "sell" || String(f.direction).toLowerCase() === "short" ? "neg" : "pos"}>{(f.direction ?? DASH).toString().toUpperCase()}</td>
                <td class="r mono">{num(f.qty, 4)}</td>
                <td class="r mono">{money(f.entry_price)}</td>
                <td class="r mono">{money(f.exit_price)}</td>
                <td class="r mono {prov === 'MEASURED' ? signClass(f.pnl) : 'unmeasured'}">{f.pnl == null ? DASH : money(f.pnl, { sign: true })}</td>
                <td class="muted" title={fillBasisText(f) ?? "no P&L basis reported"}>{basis == null ? DASH : basis.toUpperCase()}</td>
                <td><span class="badge {prov.toLowerCase()}">{prov === "UNKNOWN" ? DASH : prov}</span></td>
                <td class="muted reason" title={f.reason ?? ""}>{f.reason == null ? DASH : String(f.reason).split(" ")[0]}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <!-- Rule-distance cushion, one per live prop account -->
    {#if accounts.length === 0}
      <div class="panel pad muted">No prop accounts found on the bot's roster.</div>
    {/if}
    {#each accounts as acct (acct.id)}
      {@const st = acct.status}
      {@const rd = rdOf(st)}
      {@const dailyLeft = dailyLeftOf(st)}
      {@const ddLeft = ddLeftOf(st)}
      {@const freshness = freshnessOf(st)}
      {@const ageHours = ageHoursOf(st)}
      <div class="panel pad">
        <div class="ph">Rule-distance cushion · <span class="mono">{acct.id}</span></div>
        {#if st == null}
          <div class="muted">Couldn't read this account's status.</div>
        {:else if st.present === false || rd == null}
          <div class="muted">No account-status snapshot yet — report a <span class="mono">bal</span> to compute the cushion.</div>
        {:else}
          <div class="grid2">
            <div class="metric {cushionClass(dailyLeft)}">
              <span class="mlabel">Daily-loss remaining</span>
              <span class="mval">{dailyLeft == null ? DASH : money(dailyLeft)}</span>
            </div>
            <div class="metric {cushionClass(ddLeft)}">
              <span class="mlabel">Static-DD cushion</span>
              <span class="mval">{ddLeft == null ? DASH : money(ddLeft)}</span>
            </div>
          </div>
          {#if (dailyLeft != null && dailyLeft <= 25) || (ddLeft != null && ddLeft <= 25)}
            <div class="alert neg">⚠ A killer limit is very close — the cushion is thin.</div>
          {/if}
          {#if dailyLeft == null && ddLeft == null}
            <div class="alert warn">
              ⚠ Neither cushion could be read from this snapshot — this is a
              <strong>failure to measure</strong>, not a wide cushion.
            </div>
          {/if}
          {#if freshness !== "ok"}
            <div class="alert warn">
              ⚠ Snapshot freshness: <span class="mono">{freshness}</span>{ageHours == null
                ? ""
                : ` · ${num(ageHours, 1)} h old`} — {FRESHNESS_NOTE[freshness] ??
                FRESHNESS_NOTE.unknown}
            </div>
          {:else}
            <div class="muted small">
              Snapshot {ageHours == null ? "age unknown" : `${num(ageHours, 1)} h old`} · freshness
              <span class="mono">ok</span>
            </div>
          {/if}
        {/if}
        {#if acct.reconcile?.summary}
          {@const rs = acct.reconcile.summary}
          <div class="recon muted">
            Reconciliation: {num(rs.tickets_total)} tickets emitted ·
            {num(rs.fills_total)} fills reported ·
            <span class={rs.unacted_count > 0 ? "neg" : "pos"}>{num(rs.unacted_count)} un-acted</span>
          </div>
          {#if acct.reconcile.unacted_tickets?.length}
            <div class="unacted">
              {#each acct.reconcile.unacted_tickets as t, i (t.ticket_id ?? i)}
                <div class="urow">
                  <span class="sym">{t.symbol ?? DASH}</span>
                  <span class={String(t.direction).toLowerCase() === "sell" ? "neg" : "pos"}>{(t.direction ?? DASH).toString().toUpperCase()}</span>
                  <span class="muted">emitted {agoFromIso(t.created_at ?? t.emitted_at)}</span>
                </div>
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    {/each}

    <!-- Tickets -->
    <div class="panel scroll">
      <div class="ph pad-h">Outbound tickets</div>
      {#if tickets.length === 0}
        <div class="muted pad">No prop tickets emitted.</div>
      {:else}
        <table>
          <thead><tr><th>Account</th><th>Symbol</th><th>Dir</th><th class="r">Entry</th><th class="r">SL</th><th class="r">TP</th><th>Status</th><th>When</th></tr></thead>
          <tbody>
            {#each tickets as t, i (t.ticket_id ?? i)}
              <tr>
                <td class="mono">{t.account_id ?? DASH}</td>
                <td class="sym">{t.symbol ?? DASH}</td>
                <td class={String(t.direction).toLowerCase() === "sell" || String(t.direction).toLowerCase() === "short" ? "neg" : "pos"}>{(t.direction ?? DASH).toString().toUpperCase()}</td>
                <td class="r mono">{money(t.entry_price ?? t.entry)}</td>
                <td class="r mono">{money(t.stop_loss ?? t.sl)}</td>
                <td class="r mono">{money(t.take_profit ?? t.tp)}</td>
                <td class="muted">{t.status ?? DASH}</td>
                <td class="muted">{agoFromIso(t.created_at ?? t.emitted_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>

    <!-- Fill lifecycle log -->
    <div class="panel scroll">
      <div class="ph pad-h">Fill lifecycle log <span class="muted sub">· every report (placed / open / skipped / closed), newest first</span></div>
      {#if lifecycle.length === 0}
        <div class="muted pad">No fills reported yet.</div>
      {:else}
        <table>
          <thead><tr><th>#</th><th>Account</th><th>Symbol</th><th>Dir</th><th>Status</th><th class="r">Entry</th><th class="r">Exit</th><th class="r">P&amp;L</th><th>Reported</th></tr></thead>
          <tbody>
            {#each lifecycle as f, i (f.id ?? i)}
              {@const prov = fillProvenance(f)}
              <tr>
                <td class="muted mono">{f.id ?? DASH}</td>
                <td class="mono">{f.account_id ?? DASH}</td>
                <td class="sym">{f.symbol ?? DASH}</td>
                <td class={String(f.direction).toLowerCase() === "sell" || String(f.direction).toLowerCase() === "short" ? "neg" : "pos"}>{(f.direction ?? DASH).toString().toUpperCase()}</td>
                <td class="muted">{f.status ?? DASH}</td>
                <td class="r mono">{money(f.entry_price)}</td>
                <td class="r mono">{money(f.exit_price)}</td>
                <td class="r mono {prov === 'MEASURED' ? signClass(f.pnl) : 'unmeasured'}">{f.pnl == null ? DASH : `${money(f.pnl, { sign: true })}${prov === "MEASURED" ? "" : prov === "UNKNOWN" ? " (basis ?)" : ` (${prov.toLowerCase()})`}`}</td>
                <td class="muted">{agoFromIso(f.reported_at ?? f.created_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .pad { padding: 14px; }
  .pad-h { padding: 12px 14px 4px; }
  .ph { font-weight: 600; margin-bottom: 10px; font-size: 13.5px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .metric { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; }
  .mlabel { font-size: 11.5px; color: var(--muted); }
  .mval { font-size: 18px; font-weight: 600; }
  .metric.pos .mval { color: var(--pos); }
  .metric.neg .mval { color: var(--neg); }
  .metric.warn .mval { color: #e0a800; }
  .alert { margin-top: 10px; font-size: 13px; }
  .alert.neg { color: var(--neg); }
  /* The freshness caveat must be legible, not decorative: a cushion whose
     snapshot cannot be shown to be current is a different claim from a wide
     cushion, and the reader has to be able to tell at a glance. */
  .alert.warn { color: #e0a800; }
  .small { font-size: 12px; }
  .recon { font-size: 13px; }
  .unacted { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
  .urow { display: flex; gap: 10px; font-size: 13px; align-items: center; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pos { color: var(--pos); }
  .neg { color: var(--neg); }
  .err { padding: 10px 12px; color: var(--neg); }
  .recon { margin-top: 10px; }
  /* A non-MEASURED P&L is shown, but never in the win/loss colours a measured
     figure gets — an estimate must not read as a result at a glance. */
  .unmeasured { color: var(--muted); font-style: italic; }
  .badge { font-size: 11px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border); }
  .badge.measured { color: var(--pos); border-color: var(--pos); }
  .badge.estimated { color: #e0a800; border-color: #e0a800; }
  .badge.unverified { color: var(--neg); border-color: var(--neg); }
  .badge.unknown { color: var(--muted); }
  .reason { max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
</style>
