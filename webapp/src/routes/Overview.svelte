<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type BotStats, type Performance, type Position, type Candle } from "../lib/api";
  import { MarketStream, type MarketStatus } from "../lib/ws";
  import { FUNDING_OPTIONS, WINDOW_OPTIONS } from "../lib/nav";
  import ExecSummary from "../components/ExecSummary.svelte";
  import PositionsTable from "../components/PositionsTable.svelte";
  import LiveChart from "../components/LiveChart.svelte";
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
  let candlesBySymbol = $state<Record<string, Candle[]>>({});
  let wsStatus = $state<MarketStatus>("connecting");
  let apiError = $state<string | null>(null);

  const interval = "15m";
  // Seed symbols; open-position symbols are merged in as they arrive.
  let baseSymbols = $state<string[]>(["BTCUSDT"]);
  let selected = $state("BTCUSDT");

  const symbols = $derived.by(() => {
    const s = new Set(baseSymbols);
    for (const p of positions) if (p.symbol) s.add(p.symbol);
    return [...s];
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
      const [s, p, pos, bal, cfg, strat] = await Promise.all([
        api.stats(),
        api.performance(win),
        api.positions(),
        api.balances(),
        api.config(),
        api.strategies(),
      ]);
      stats = s;
      perf = p;
      if (wsStatus !== "open") positions = pos; // don't clobber a live WS snapshot
      balances = bal;
      config = cfg;
      strategies = strat;
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
  // Positions scoped to the selected funding class (never blended).
  const shownPositions = $derived(positions.filter((p) => fundingOf(p) === funding));

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
        positions = ps;
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
    if (sym === selected) return;
    selected = sym;
    startStream(); // re-subscribe so the picked symbol streams
  }

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

  <div class="chartcard panel">
    <div class="picker">
      {#each symbols as sym (sym)}
        <button class:active={sym === selected} onclick={() => pick(sym)}>{sym}</button>
      {/each}
    </div>
    <LiveChart candles={candlesBySymbol[selected] ?? []} />
  </div>

  <div class="panel positions">
    <div class="ph">Open positions · {FUNDING_OPTIONS.find((f) => f.value === funding)?.label}</div>
    <PositionsTable positions={shownPositions} />
  </div>
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
