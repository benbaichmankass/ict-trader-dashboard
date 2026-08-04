<script lang="ts">
  import type { BotStats, Performance, Position } from "../lib/api";
  import { money, pct, num, signClass, agoFromIso, DASH } from "../lib/format";
  import { portfolioPaperIds, isPortfolioPaperRow } from "../lib/funding";

  // Mirrors streamlit_app.py::_render_exec_summary — funding/window-scoped, real
  // and paper never blended. Status line + six cards (equity · open trades ·
  // realized P&L+% · unrealized P&L+% · win rate · profit factor) + the
  // other-funding-class one-liner + a compact open-trades table.
  let {
    stats, perf, positions = [], balances = null, config = null, strategies = null,
    funding = "real", win = "7d",
  }: {
    stats: BotStats | null; perf: Performance | null; positions?: Position[];
    balances?: any; config?: any; strategies?: any; funding?: string; win?: string;
  } = $props();

  const WIN_LABEL: Record<string, string> = { "24h": "24h", "7d": "7d", "30d": "30d", all: "all-time" };
  const winLabel = $derived(WIN_LABEL[win] ?? win);
  const segName = $derived(funding === "paper" ? "paper" : funding === "prop" ? "prop" : "real money");

  function fundingOf(p: Position): string {
    const c = (p.accountClass ?? "").toLowerCase();
    if (c === "prop") return "prop";
    if (c === "paper") return "paper";
    return "real";
  }

  // "Paper" scopes to the live-portfolio-mirror books (paper_role: portfolio);
  // soak books stay off this view (Accounts page only). Falls back to ALL paper
  // when none are declared / config is unreadable. S-PAPER-PORTFOLIO.
  const paperIds = $derived(portfolioPaperIds(config));

  // account_id → account_class map (from /config) so we can sum equity per class.
  const acctClass = $derived.by(() => {
    const m: Record<string, string> = {};
    for (const a of config?.accounts ?? []) m[a.id] = a.account_class ?? "";
    return m;
  });

  // Total equity for the funding class = sum of that class's tracked balances.
  const equity = $derived.by(() => {
    if (funding === "prop") return null;
    const want = funding === "paper" ? "paper" : "real_money";
    const bals = balances?.balances ?? {};
    let sum = 0, any = false;
    for (const [id, b] of Object.entries<any>(bals)) {
      if ((acctClass[id] ?? "") !== want || typeof b?.balance !== "number") continue;
      // Paper equity scopes to the portfolio-mirror books (soak excluded); all
      // paper when none are declared.
      if (want === "paper" && paperIds.size > 0 && !paperIds.has(id)) continue;
      sum += b.balance; any = true;
    }
    return any ? sum : null;
  });

  // Open positions for the class (from REST /positions; prop from its own journal — not here).
  // "Paper" keeps only the portfolio-mirror books, not the soak roster.
  const segOpen = $derived(
    funding === "prop"
      ? []
      : funding === "paper"
        ? positions.filter((p) => isPortfolioPaperRow(p, paperIds))
        : positions.filter((p) => fundingOf(p) === funding),
  );
  const openUpnl = $derived.by(() => {
    let sum = 0, known = 0;
    for (const p of segOpen) if (typeof p.unrealizedPnl === "number") { sum += p.unrealizedPnl; known++; }
    return { sum: known ? sum : null, known };
  });

  // Windowed realized P&L / win rate / profit factor for the segment. "Paper"
  // prefers the portfolio-mirror sub-block (paper_role: portfolio) the bot
  // serves, which itself falls back to the all-paper `paper` block server-side.
  const segPerf = $derived(
    funding === "paper"
      ? (perf?.paperPortfolio ?? perf?.paper ?? null)
      : funding === "prop"
        ? null
        : perf,
  );
  const realized = $derived(segPerf?.totalPnl ?? null);
  const winRate = $derived(segPerf?.winRate ?? null);
  const profitFactor = $derived(segPerf?.profitFactor ?? null);
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
  const otherTag = $derived(funding === "real" ? "🧪 Paper" : "💰 Real");

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
    <div class="propnote">Prop equity + open trades live on the <b>Prop</b> tab (its own journal — never blended into real/paper). Realized/PF read “—” here.</div>
  {/if}

  <div class="grid">
    <div class="metric"><div class="k">Total equity</div><div class="v">{equity == null ? DASH : money(equity)}</div></div>
    <div class="metric"><div class="k">Open trades</div><div class="v">{funding === "prop" ? DASH : num(segOpen.length)}</div></div>
    <div class="metric">
      <div class="k">Realized P&L · {winLabel}</div>
      <div class="v {signClass(realized)}">{realized == null ? DASH : money(realized, { sign: true })}</div>
      {#if realizedPct}<div class="d {signClass(realized)}">{realized != null && realized >= 0 ? "+" : ""}{realizedPct}</div>{/if}
    </div>
    <div class="metric">
      <div class="k">Unrealized P&L</div>
      <div class="v {signClass(openUpnl.sum)}">{openUpnl.sum == null ? DASH : money(openUpnl.sum, { sign: true })}</div>
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
                <td class="r mono {signClass(p.unrealizedPnl)}">{p.unrealizedPnl == null ? DASH : money(p.unrealizedPnl, { sign: true })}</td>
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
  .propnote { color: var(--muted); font-size: 12.5px; }
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
