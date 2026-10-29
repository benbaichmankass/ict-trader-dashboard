<script lang="ts">
  import type { BotStats, Performance, Position } from "../lib/api";
  import { money, pct, num, signClass, agoFromIso, DASH } from "../lib/format";
  import { accountBooks, bookOfRow, FUNDING_BOOKS, FUNDING_LABEL, type FundingBook } from "../lib/funding";

  // Mirrors streamlit_app.py::_render_exec_summary — funding/window-scoped, real
  // and paper never blended. Status line + six cards (equity · open trades ·
  // realized P&L+% · unrealized P&L+% · win rate · profit factor) + the
  // other-funding-class one-liner + a compact open-trades table.
  let {
    stats, perf, positions = [], balances = null, config = null, strategies = null,
    funding = "real", win = "7d", propOverview = null, testingPerf = null,
  }: {
    stats: BotStats | null; perf: Performance | null; positions?: Position[];
    balances?: any; config?: any; strategies?: any; funding?: string; win?: string; propOverview?: any;
    testingPerf?: { totalPnl: number | null; winRate: number | null; profitFactor: number | null; totalTrades: number; sampled: boolean } | null;
  } = $props();

  const WIN_LABEL: Record<string, string> = { "24h": "24h", "7d": "7d", "30d": "30d", all: "all-time" };
  const winLabel = $derived(WIN_LABEL[win] ?? win);
  const segName = $derived((FUNDING_LABEL[funding as FundingBook] ?? "live money").toLowerCase());

  // account id → book (from /config account_class + paper_role); never blended.
  const books = $derived(accountBooks(config));

  // Total equity for the funding class = sum of that class's tracked balances.
  const equity = $derived.by(() => {
    if (funding === "prop") return propOverview?.equity?.total_usd ?? null;
    const bals = balances?.balances ?? {};
    let sum = 0, any = false;
    for (const [id, b] of Object.entries<any>(bals)) {
      if (books[id] !== funding || typeof b?.balance !== "number") continue;
      sum += b.balance; any = true;
    }
    return any ? sum : null;
  });

  // Open positions for the book (from REST /positions; prop from its own journal — not here).
  // Prop open trades come from the prop journal via /api/bot/prop/overview
  // (the manual bridge has no broker positions). Mapped to the Position shape
  // the shared table renders. uPnL is the bot's per-trade figure (PROP-TRACKING,
  // bot #17745): venue-measured (`venue_snapshot` / `venue_position`) or a
  // labelled mark ESTIMATE (`mark_estimate`, rendered with "est."); null -> "—".
  const propOpen = $derived<Position[]>(
    (propOverview?.open_trades ?? []).map((t: any) => ({
      id: `prop-${t.id}`, symbol: t.symbol, side: t.side === "short" ? "sell" : "buy",
      qty: t.qty, entryPrice: t.entry_price, pattern: "prop", account: t.account_id,
      unrealizedPnl: typeof t.unrealized_pnl === "number" ? t.unrealized_pnl : null,
      unrealizedPnlSource: t.unrealized_provenance === "estimated" ? "estimate" : (t.unrealized_state ?? null),
      openedAt: t.opened_at, accountClass: "prop",
    }) as unknown as Position),
  );
  const segOpen = $derived(
    funding === "prop" ? propOpen : positions.filter((p) => bookOfRow(p, books) === funding),
  );
  const openUpnl = $derived.by(() => {
    // Prop: the bot's BOOK figure, never a client sum of whichever trades happen to carry one. The measured
    // total first; else the total including labelled mark estimates (shown as "est."); else "—".
    if (funding === "prop") {
      const m = propOverview?.unrealized_pnl, e = propOverview?.unrealized_pnl_incl_estimates;
      if (typeof m === "number") return { sum: m, known: segOpen.length, est: false, partial: null };
      if (typeof e === "number") return { sum: e, known: segOpen.length, est: true, partial: null };
      // No book figure (an account's uPnL is unknown): the trades that DO carry one, summed and labelled as a
      // partial "k of n trades" — never presented as the book total. "—" only when no trade carries a figure.
      let ps = 0, pk = 0, pe = false;
      for (const p of segOpen) if (typeof p.unrealizedPnl === "number") {
        ps += p.unrealizedPnl; pk++; if ((p as any).unrealizedPnlSource === "estimate") pe = true;
      }
      return pk ? { sum: ps, known: pk, est: pe, partial: `${pk} of ${segOpen.length} trades` }
                : { sum: null, known: 0, est: false, partial: null };
    }
    let sum = 0, known = 0;
    for (const p of segOpen) if (typeof p.unrealizedPnl === "number") { sum += p.unrealizedPnl; known++; }
    return { sum: known ? sum : null, known, est: false, partial: null };
  });

  // Windowed realized P&L / win rate / profit factor for the segment. "Paper"
  // prefers the portfolio-mirror sub-block (paper_role: portfolio) the bot
  // serves, which itself falls back to the all-paper `paper` block server-side.
  // Paper testing has no /performance block: it uses the totals Overview
  // computed from that window's closed trades (testingPerf), and carries no
  // per-asset / per-strategy breakdown.
  const segPerf = $derived<any>(
    funding === "paper_portfolio"
      ? (perf?.paperPortfolio ?? perf?.paper ?? null)
      : funding === "paper_testing"
        ? (testingPerf ?? null)
        : funding === "prop"
          ? null
          : perf,
  );
  const propRealized = $derived(funding === "prop" ? (propOverview?.realized ?? null) : null);
  const realized = $derived(funding === "prop" ? (propRealized?.total_pnl ?? null) : (segPerf?.totalPnl ?? null));
  const winRate = $derived(funding === "prop" ? (propRealized?.win_rate ?? null) : (segPerf?.winRate ?? null));
  const profitFactor = $derived(funding === "prop" ? (propRealized?.profit_factor ?? null) : (segPerf?.profitFactor ?? null));
  // PnL measurement coverage (bot P0.3): shown only when the bot reports the
  // field AND coverage is incomplete — an older bot makes no claim.
  const pnlCoverage = $derived(segPerf?.pnlCoverage ?? null);

  function pctOfEquity(v: number | null | undefined): string | null {
    if (v == null || !equity) return null;
    return `${((v / equity) * 100).toFixed(2)}%`;
  }
  const realizedPct = $derived(pctOfEquity(realized));
  const unrealPct = $derived(openUpnl.known ? pctOfEquity(openUpnl.sum) : null);

  // System status line.
  const status = $derived(String(stats?.status ?? "unknown"));
  const statusCls = $derived(status === "running" ? "pos" : status === "stopped" ? "neg" : "warn");
  const tickAge = $derived(strategies?.runtime?.tick_age_seconds ?? null);
  function fmtAge(s: number | null): string {
    if (s == null) return DASH;
    if (s < 90) return `${Math.round(s)}s`;
    if (s < 5400) return `${Math.round(s / 60)}m`;
    return `${(s / 3600).toFixed(1)}h`;
  }

  // The OTHER funding class one-liner (never let the other side be invisible).
  // The paper side prefers the portfolio-mirror sub-block, same as segPerf.
  const otherPerf = $derived(funding === "real" ? (perf?.paperPortfolio ?? perf?.paper ?? null) : perf);
  const otherTag = $derived(funding === "real" ? "🧪 Paper portfolio" : "💰 Live");

  // Books at a glance: open count + uPnL for every book, so no book is invisible
  // behind the toggle. Prop comes from its own journal; uPnL "—" when none known.
  const glance = $derived(
    FUNDING_BOOKS.map((b) => {
      const rows = b === "prop" ? propOpen : positions.filter((p) => bookOfRow(p, books) === b);
      let sum = 0, known = 0;
      for (const p of rows) if (typeof p.unrealizedPnl === "number") { sum += p.unrealizedPnl; known++; }
      return { book: b, open: rows.length, upnl: known ? sum : null };
    }),
  );

  // Asset-class P&L breakdown (mirrors Streamlit's perAssetClass row).
  const ASSET_EMOJI: Record<string, string> = { crypto: "🪙", index: "📊", commodity: "🛢️", equity: "📈", bond: "🏛️", fx: "💱", unknown: "•" };
  const perAsset = $derived.by(() => {
    const rows = segPerf?.perAssetClass ?? [];
    return [...rows].filter((r) => (r?.trades ?? 0) > 0).sort((a, b) => (b.totalPnl ?? 0) - (a.totalPnl ?? 0));
  });

  // Strategy fleet best / worst by P&L (from perStrategy).
  const perStrat = $derived(segPerf?.perStrategy ?? []);
  const bestStrat = $derived.by(() => {
    const r = [...perStrat].filter((s) => s?.trades).sort((a, b) => (b.totalPnl ?? 0) - (a.totalPnl ?? 0));
    return r.length ? r[0] : null;
  });
  const worstStrat = $derived.by(() => {
    const r = [...perStrat].filter((s) => s?.trades).sort((a, b) => (a.totalPnl ?? 0) - (b.totalPnl ?? 0));
    return r.length && r[0] !== bestStrat ? r[0] : null;
  });
</script>

<div class="exec panel">
  <div class="title">Executive summary · {segName} · {winLabel}</div>

  <div class="status">
    <span class="dot {statusCls}"></span>
    <b>System {status.toUpperCase()}</b> · last tick {fmtAge(tickAge)} ago · datasource {stats?.datasource ?? "?"}
  </div>

  {#if funding === "prop"}
    <div class="propnote">
      {#if propOverview?.present}
        Prop journal (never blended into real/paper) · {propOverview.population}.
        {#each (propOverview.equity?.accounts ?? []).filter((a: any) => !a.counted_in_total) as a (a.account_id)}
          <span class="warn"> ⚠ {a.account_id} {a.status_freshness}{a.equity != null ? ` (last ${money(a.equity)}, excluded)` : ""}</span>
        {/each}
      {:else}
        Prop overview unavailable from the bot — see the <b>Prop</b> tab.
      {/if}
    </div>
  {/if}

  <div class="books">
    {#each glance as g (g.book)}
      <div class="bk" class:sel={g.book === funding}>
        <span class="bn">{FUNDING_LABEL[g.book]}</span>
        <span class="bv">{g.book === "prop" && !propOverview?.present ? DASH : num(g.open)} open</span>
        <span class="bu {signClass(g.upnl)}">{g.upnl == null ? DASH : money(g.upnl, { sign: true })}</span>
      </div>
    {/each}
  </div>

  {#if funding === "paper_testing"}
    <div class="cap">
      Paper testing = every paper/demo account without <code>paper_role: portfolio</code> (soak / demo floor).
      {#if testingPerf?.sampled}Realized figures use the latest 200 closed trades in this window.{/if}
    </div>
  {/if}

  <div class="grid">
    <div class="metric"><div class="k">Total equity</div><div class="v">{equity == null ? DASH : money(equity)}</div></div>
    <div class="metric"><div class="k">Open trades</div><div class="v">{funding === "prop" && !propOverview?.present ? DASH : num(segOpen.length)}</div></div>
    <div class="metric">
      <div class="k">Realized P&L · {winLabel}</div>
      <div class="v {signClass(realized)}">{realized == null ? DASH : money(realized, { sign: true })}</div>
      {#if realizedPct}<div class="d {signClass(realized)}">{realized != null && realized >= 0 ? "+" : ""}{realizedPct}</div>{/if}
    </div>
    <div class="metric">
      <div class="k">Unrealized P&L</div>
      <div class="v {signClass(openUpnl.sum)}">{openUpnl.sum == null ? DASH : money(openUpnl.sum, { sign: true })}{#if openUpnl.est}<span class="est" title="Includes mark estimates: (Bybit mark − entry) × qty, not a venue figure"> est.</span>{/if}</div>
      {#if openUpnl.partial}<div class="d est" title="Some trades carry no uPnL figure yet; this sums only the ones that do">partial · {openUpnl.partial}</div>{/if}
      {#if unrealPct}<div class="d {signClass(openUpnl.sum)}">{openUpnl.sum != null && openUpnl.sum >= 0 ? "+" : ""}{unrealPct}</div>{/if}
    </div>
    <div class="metric"><div class="k">Win rate · {winLabel}</div><div class="v">{winRate == null ? DASH : pct(winRate)}</div></div>
    <div class="metric"><div class="k">Profit factor</div><div class="v">{profitFactor == null ? DASH : profitFactor.toFixed(2)}</div></div>
  </div>

  {#if equity}
    <div class="cap">P&amp;L % = return on the tracked equity above ({money(equity)}).</div>
  {/if}

  {#if pnlCoverage != null && pnlCoverage < 1}
    <div class="cap warn">⚠ Realized P&amp;L is broker-measured for {Math.round(pnlCoverage * 100)}% of trades in this window ({segPerf?.pnlFabricatedCount ?? 0} mark-substituted, {segPerf?.pnlUnverifiedCount ?? 0} unrecorded) — the remainder is estimated, not broker truth.</div>
  {/if}

  {#if perAsset.length}
    <div class="assets">
      <div class="sech">P&amp;L by asset class · {winLabel}</div>
      <div class="chips">
        {#each perAsset as a (a.assetClass)}
          <div class="chip">
            <span class="cl">{ASSET_EMOJI[a.assetClass] ?? "•"} {a.assetClass}</span>
            <span class="cv {signClass(a.totalPnl)}">{a.totalPnl == null ? DASH : money(a.totalPnl, { sign: true })}</span>
            <span class="cn">{num(a.trades)} tr · {a.winRate == null ? DASH : pct(a.winRate)}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  {#if bestStrat || worstStrat}
    <div class="fleet">
      <div class="sech">Strategy fleet · {winLabel}</div>
      {#if bestStrat}
        <div class="fl"><span class="fk pos">▲ Best</span> <b>{bestStrat.name}</b> · <span class="pos">{money(bestStrat.totalPnl, { sign: true })}</span> · {num(bestStrat.trades)} tr · win {bestStrat.winRate == null ? DASH : pct(bestStrat.winRate)}</div>
      {/if}
      {#if worstStrat}
        <div class="fl"><span class="fk neg">▼ Worst</span> <b>{worstStrat.name}</b> · <span class="neg">{money(worstStrat.totalPnl, { sign: true })}</span> · {num(worstStrat.trades)} tr · win {worstStrat.winRate == null ? DASH : pct(worstStrat.winRate)}</div>
      {/if}
    </div>
  {/if}

  {#if otherPerf}
    <div class="other">
      {otherTag} · {winLabel} · P&L {money(otherPerf.totalPnl)} · win {otherPerf.winRate == null ? DASH : pct(otherPerf.winRate)} · trades {num(otherPerf.totalTrades)}
    </div>
  {/if}

  <div class="ot">
    <div class="oth">Open trades · {segName}</div>
    {#if segOpen.length === 0}
      <div class="cap">No open {segName} trades right now.</div>
    {:else}
      <div class="scroll">
        <table>
          <thead><tr><th>Symbol</th><th>Side</th><th class="r">Qty</th><th class="r">Entry</th><th>Strategy</th><th>Account</th><th class="r">uPnL</th><th>Age</th></tr></thead>
          <tbody>
            {#each segOpen as p, i (p.id ?? i)}
              <tr>
                <td class="sym">{p.symbol ?? DASH}</td>
                <td class={String(p.side).toLowerCase() === "sell" ? "neg" : "pos"}>{(p.side ?? DASH).toString().toUpperCase()}</td>
                <td class="r mono">{p.qty ?? DASH}</td>
                <td class="r mono">{money(p.entryPrice)}</td>
                <td class="muted">{p.pattern ?? DASH}</td>
                <td class="muted">{p.account ?? DASH}</td>
                <td class="r mono {signClass(p.unrealizedPnl)}">{p.unrealizedPnl == null ? DASH : money(p.unrealizedPnl, { sign: true })}{#if p.unrealizedPnl != null && (p as any).unrealizedPnlSource === "estimate"}<span class="est" title="Mark estimate: (Bybit mark − entry) × qty, not a venue figure"> est.</span>{/if}</td>
                <td class="muted">{agoFromIso(p.openedAt)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>

<style>
  .exec { padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .title { font-weight: 700; font-size: 15px; }
  .status { font-size: 13px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
  .dot.pos { background: var(--pos); } .dot.neg { background: var(--neg); } .dot.warn { background: #e0a800; }
  .books { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  @media (max-width: 560px) { .books { grid-template-columns: 1fr 1fr; } }
  .bk { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; gap: 1px; font-size: 11.5px; }
  .bk.sel { border-color: var(--accent); }
  .bn { color: var(--muted); }
  .bv { font-weight: 600; font-size: 13px; }
  .bu.pos { color: var(--pos); } .bu.neg { color: var(--neg); }
  .propnote { color: var(--muted); font-size: 12.5px; }
  .est { color: var(--muted); font-size: 11px; font-weight: 400; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .metric { background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
  .k { color: var(--muted); font-size: 11.5px; margin-bottom: 4px; }
  .v { font-size: 20px; font-weight: 600; }
  .v.pos, .d.pos { color: var(--pos); } .v.neg, .d.neg { color: var(--neg); }
  .d { font-size: 12px; margin-top: 2px; }
  .cap.warn { color: var(--warn, #d97706); }
  .cap { color: var(--muted); font-size: 12px; }
  .other { font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--border); padding-top: 8px; }
  .sech { font-weight: 600; font-size: 12.5px; margin-bottom: 6px; }
  .assets, .fleet { border-top: 1px solid var(--border); padding-top: 8px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; display: flex; flex-direction: column; gap: 1px; min-width: 92px; }
  .cl { font-size: 11.5px; text-transform: capitalize; }
  .cv { font-size: 14px; font-weight: 600; }
  .cn { font-size: 10.5px; color: var(--muted); }
  .fl { font-size: 12.5px; margin-bottom: 3px; }
  .fk { font-weight: 600; margin-right: 4px; }
  .ot { border-top: 1px solid var(--border); padding-top: 8px; }
  .oth { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { padding: 6px 8px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 11.5px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; } .sym { font-weight: 600; }
  .pos { color: var(--pos); } .neg { color: var(--neg); } .muted { color: var(--muted); }
</style>
