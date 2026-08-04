<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type BotStats, type Performance, type Position, type Candle, type ClosedTrade } from "../lib/api";
  import { MarketStream, type MarketStatus } from "../lib/ws";
  import { FUNDING_OPTIONS, WINDOW_OPTIONS } from "../lib/nav";
  import { portfolioPaperIds, isPortfolioPaperRow } from "../lib/funding";
  import { money, signClass, DASH, agoFromIso } from "../lib/format";
  import ExecSummary from "../components/ExecSummary.svelte";
  import PositionsTable from "../components/PositionsTable.svelte";
  import LiveChart from "../components/LiveChart.svelte";
  import EquityChart from "../components/EquityChart.svelte";
  import StatusDot from "../components/StatusDot.svelte";
  import Segmented from "../components/Segmented.svelte";

  // One funding toggle per tab (Real money / Paper / Prop — never blended) + the
  // 24h/7d/30d/All window, at the top — mirrors the Streamlit UI.
  let funding = $state("real");
  let win = $state("7d");

  let stats = $state<BotStats | null>(null);
  let perf = $state<Performance | null>(null);
  let positions = $state<Position[]>([]);
  let balances = $state<any>(null);
  let config = $state<any>(null);
  let strategies = $state<any>(null);
  let signals = $state<any[]>([]);
  let closedTrades = $state<ClosedTrade[]>([]);
  let news = $state<any>(null);
  let reports = $state<any>(null);
  let pnl30 = $state<Array<{ date?: string; pnl?: number | null }>>([]);
  let candlesBySymbol = $state<Record<string, Candle[]>>({});
  let wsStatus = $state<MarketStatus>("connecting");
  let apiError = $state<string | null>(null);

  const interval = "15m";
  let selected = $state("BTCUSDT");
  let userPicked = false; // once the user taps, stop auto-retargeting `selected`

  // Discover the traded-symbol universe the way Streamlit's _discover_symbols does:
  // union of every account's configured `symbols` + strategy symbols + any symbol
  // with an open position / recent signal — never a hardcoded list, so a newly
  // wired instrument appears with no code change. Symbols holding an open position
  // float to the front.
  const symbols = $derived.by(() => {
    const s = new Set<string>();
    for (const a of config?.accounts ?? []) for (const sym of a?.symbols ?? []) s.add(sym);
    for (const st of Object.values<any>(config?.strategies ?? {})) {
      for (const sym of st?.symbols ?? []) s.add(sym);
    }
    for (const p of positions) if (p.symbol) s.add(p.symbol);
    for (const g of signals) if (g?.symbol) s.add(g.symbol);
    if (s.size === 0) s.add("BTCUSDT"); // never render an empty picker
    // Float symbols held IN THE CURRENT FUNDING CLASS to the front so the chart
    // defaults to one you actually hold under this toggle (e.g. a real-money
    // symbol under "Real money", not a paper one).
    const held = new Set(
      positions.filter((p) => p.symbol && matchesFunding(p)).map((p) => p.symbol as string));
    return [...s].sort((a, b) =>
      (held.has(b) ? 1 : 0) - (held.has(a) ? 1 : 0) || a.localeCompare(b));
  });

  // Symbol-scoped overlays for the charted symbol (Streamlit's per-symbol monitor).
  const symSignals = $derived(signals.filter((g) => g?.symbol === selected).slice(0, 40));
  const symClosed = $derived(closedTrades.filter((c) => c.symbol === selected).slice(0, 30));

  // News glance — top clickable source headlines across recent decisions.
  const headlines = $derived.by(() => {
    const items: Array<{ headline: string; url?: string; score?: number }> = [];
    const seen = new Set<string>();
    for (const rec of news?.records ?? []) {
      for (const it of rec?.top_items ?? []) {
        if (it?.headline && !seen.has(it.headline)) { seen.add(it.headline); items.push(it); }
      }
    }
    return items.sort((a, b) => Math.abs(b.score ?? 0) - Math.abs(a.score ?? 0)).slice(0, 4);
  });

  // Latest system report (newest-first index).
  const latestReport = $derived((reports?.reports ?? [])[0] ?? null);

  // 30-day realised-P&L → cumulative points for the sparkline.
  const pnlPoints = $derived.by(() => {
    let cum = 0;
    return pnl30
      .filter((d) => d?.date)
      .map((d) => ({ t: d.date as string, cum: (cum += Number(d.pnl ?? 0)) }));
  });

  let stream: MarketStream | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  // The exec summary needs the same inputs Streamlit's _render_exec_summary uses:
  // stats + windowed performance + REST positions + tracked balances (equity) +
  // config (account_class map) + strategies (tick age). Positions come via REST
  // here so the open-trades table/count is populated even when the market
  // WebSocket can't connect (sandbox, or a flaky mobile network) — the WS's
  // onPositions still overwrites this with the live snapshot when it's up.
  async function poll() {
    try {
      const [s, p, pos, bal, cfg, strat, sig, closed] = await Promise.all([
        api.stats(),
        api.performance(win),
        api.positions(),
        api.balances(),
        api.config(),
        api.strategies(),
        api.signals(),
        api.closedTrades({ includePaper: true, limit: 100 }),
      ]);
      // Glance-card + sparkline data — non-blocking: a failure here must not
      // blank the core overview (each degrades to its own empty state).
      Promise.all([
        api.news(8).catch(() => null),
        api.reports().catch(() => null),
        api.pnlHistory(30).catch(() => []),
      ]).then(([n, r, h]) => { news = n; reports = r; pnl30 = Array.isArray(h) ? h : []; });
      stats = s;
      perf = p;
      positions = pos; // REST is authoritative — the WS only refreshes uPnL below
      balances = bal;
      config = cfg;
      strategies = strat;
      signals = Array.isArray(sig) ? sig : (sig?.signals ?? sig?.records ?? []);
      closedTrades = Array.isArray(closed) ? closed : [];
      apiError = null;
    } catch (e) {
      apiError = e instanceof Error ? e.message : String(e);
    }
  }

  // Re-poll performance when the window changes (control tap → fresh window).
  $effect(() => {
    win;
    poll();
  });

  function fundingOf(p: Position): string {
    const c = (p.accountClass ?? "").toLowerCase();
    if (c === "prop") return "prop";
    if (c === "paper") return "paper";
    return "real";
  }
  // "Paper" scopes to the live-portfolio-mirror books (paper_role: portfolio);
  // the data-only soak books stay off every tab but Accounts. Falls back to ALL
  // paper when none are declared / config unreadable. S-PAPER-PORTFOLIO.
  const paperIds = $derived(portfolioPaperIds(config));
  // True when a position belongs to the currently-selected funding class — the
  // portfolio-mirror scoping is applied for the Paper toggle.
  function matchesFunding(p: Position): boolean {
    return funding === "paper" ? isPortfolioPaperRow(p, paperIds) : fundingOf(p) === funding;
  }
  // Positions scoped to the selected funding class (never blended).
  const shownPositions = $derived(positions.filter((p) => matchesFunding(p)));
  const symOpen = $derived(shownPositions.filter((p) => p.symbol === selected));

  // REST candle fallback so the chart renders even when the market WebSocket
  // can't connect (sandbox / flaky mobile). The WS's onCandles overwrites this
  // with per-tick data when it's live — REST only fills the gap.
  async function fetchCandles(sym: string) {
    try {
      const r = await api.candles(sym, interval, 200);
      if (r?.candles?.length) candlesBySymbol = { ...candlesBySymbol, [sym]: r.candles };
    } catch {
      /* leave the chart's empty state; not fatal */
    }
  }

  function startStream() {
    stream?.stop();
    fetchCandles(selected); // seed the chart immediately via REST
    stream = new MarketStream([selected], interval, {
      onCandles: (sym, _iv, cs) => {
        candlesBySymbol = { ...candlesBySymbol, [sym]: cs };
      },
      onPositions: (ps) => {
        // Only let a NON-EMPTY WS snapshot refresh positions (for ~2s uPnL
        // freshness). An empty/paper-excluded WS frame must never blank the
        // REST-populated tables — that was the "Open trades: N but no
        // positions shown" bug on mobile where the WS connects but delivers
        // an empty positions frame.
        if (ps && ps.length) positions = ps;
      },
      onStatus: (st) => {
        wsStatus = st;
      },
    });
    stream.start();
  }

  onMount(() => {
    poll();
    pollTimer = setInterval(poll, 30000);
    startStream();
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    stream?.stop();
  });

  function pick(sym: string) {
    userPicked = true;
    if (sym === selected) return;
    selected = sym;
    startStream(); // re-subscribe so the picked symbol streams
  }

  // Until the user taps a symbol, keep the chart on a sensible default: a symbol
  // holding an open position (they sort to the front), else the first discovered
  // one. Re-seeds the stream/candles when the target changes.
  $effect(() => {
    if (userPicked || symbols.length === 0) return;
    const want = symbols[0];
    if (want && want !== selected) {
      selected = want;
      startStream();
    }
  });

  const wsLabel = $derived(wsStatus === "open" ? "live" : wsStatus === "connecting" ? "connecting" : "reconnecting");
</script>

<section>
  <div class="head">
    <h2>Overview</h2>
    <div class="ws">
      <StatusDot status={wsStatus === "open" ? "pos" : wsStatus === "connecting" ? "warn" : "neg"} label={wsLabel} />
    </div>
  </div>

  <div class="controls">
    <Segmented options={FUNDING_OPTIONS} bind:value={funding} />
    <Segmented options={WINDOW_OPTIONS} bind:value={win} />
  </div>

  {#if apiError}
    <div class="err panel">Couldn't reach the bot API: <span class="mono">{apiError}</span></div>
  {/if}

  <ExecSummary {stats} {perf} {positions} {balances} {config} {strategies} {funding} {win} />

  <div class="glances">
    {#if latestReport}
      <a class="glance panel" href="#/Performance/Reports">
        <div class="gh">📄 Latest report<span class="muted"> · {latestReport.window ?? ""}</span></div>
        <div class="gbody">{latestReport.headline ?? latestReport.id}</div>
        <div class="muted gsub">{latestReport.roll_up_grade ?? ""} · {latestReport.generated_at ? agoFromIso(latestReport.generated_at) : ""}</div>
      </a>
    {/if}
    {#if headlines.length}
      <div class="glance panel">
        <div class="gh">📰 News</div>
        <ul class="hl">
          {#each headlines as h (h.headline)}
            <li>{#if h.url}<a href={h.url} target="_blank" rel="noopener">{h.headline}</a>{:else}{h.headline}{/if}</li>
          {/each}
        </ul>
      </div>
    {/if}
  </div>

  <div class="chartcard panel">
    <div class="picker">
      {#each symbols as sym (sym)}
        {@const held = positions.some((p) => p.symbol === sym && matchesFunding(p))}
        <button class:active={sym === selected} onclick={() => pick(sym)}>
          {held ? "🟢 " : ""}{sym}
        </button>
      {/each}
    </div>
    <div class="monh">
      <b>{selected}</b>
      <span class="muted">· {symSignals.length} signal{symSignals.length === 1 ? "" : "s"} · {symClosed.length} recent closed{symOpen.length ? ` · ${symOpen.length} open` : ""}</span>
    </div>
    <LiveChart
      candles={candlesBySymbol[selected] ?? []}
      positions={symOpen}
      signals={symSignals}
      closedTrades={symClosed}
    />
    <div class="legend muted">▬ entry · ┄ SL/TP · ▲▼ signals · ● closed</div>

    {#if symOpen.length}
      <div class="cards">
        {#each symOpen as p (p.id)}
          <div class="tcard">
            <div class="tr1">
              <span class={String(p.side).toLowerCase().startsWith("s") ? "neg" : "pos"}>
                {(p.side ?? "").toString().toUpperCase().startsWith("S") ? "SHORT" : "LONG"}
              </span>
              <span class="mono">{p.qty ?? DASH}</span> @ <span class="mono">{money(p.entryPrice)}</span>
              <span class="grow"></span>
              <span class="mono {signClass(p.unrealizedPnl)}">{p.unrealizedPnl == null ? DASH : money(p.unrealizedPnl, { sign: true })}</span>
            </div>
            <div class="tr2 muted">
              SL {money(p.stopLoss)} · TP {money(p.takeProfit)} · {p.pattern ?? DASH} · {p.account ?? DASH}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <div class="panel positions">
    <div class="ph">Open positions · {FUNDING_OPTIONS.find((f) => f.value === funding)?.label}</div>
    <PositionsTable positions={shownPositions} />
  </div>

  {#if pnlPoints.length > 1}
    <div class="panel spark">
      <div class="ph">30-day realised P&amp;L (cumulative) · real money</div>
      <EquityChart points={pnlPoints} height={180} />
    </div>
  {/if}
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .controls {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  h2 {
    margin: 0;
    font-size: 18px;
  }
  .chartcard {
    padding: 12px;
  }
  .monh { font-size: 14px; margin: 8px 2px 4px; }
  .legend { font-size: 11px; margin: 6px 2px 0; }
  .cards { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
  .tcard { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
  .tr1 { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
  .tr1 .grow { flex: 1; }
  .tr2 { font-size: 11.5px; margin-top: 3px; }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); } .muted { color: var(--muted); }
  .picker {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }
  .picker button {
    background: var(--panel-2);
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 13px;
  }
  .picker button.active {
    color: var(--text);
    border-color: var(--accent);
  }
  .glances {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  @media (max-width: 560px) { .glances { grid-template-columns: 1fr; } }
  .glance { padding: 12px; text-decoration: none; color: inherit; display: block; }
  .gh { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
  .gbody { font-size: 13px; line-height: 1.35; }
  .gsub { font-size: 11.5px; margin-top: 6px; }
  .hl { margin: 0; padding-left: 16px; font-size: 12.5px; line-height: 1.5; }
  .hl a { color: var(--accent); text-decoration: none; }
  .hl a:hover { text-decoration: underline; }
  .spark { padding: 4px 12px 12px; }
  .spark .ph { padding: 12px 0 6px; }
  .positions {
    padding: 4px 4px 8px;
  }
  .ph {
    padding: 12px 12px 6px;
    font-weight: 600;
  }
  .err {
    padding: 10px 12px;
    color: var(--neg);
  }
</style>
