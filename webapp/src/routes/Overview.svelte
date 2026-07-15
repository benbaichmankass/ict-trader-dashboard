<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type BotStats, type Performance, type Position, type Candle } from "../lib/api";
  import { MarketStream, type MarketStatus } from "../lib/ws";
  import ExecSummary from "../components/ExecSummary.svelte";
  import PositionsTable from "../components/PositionsTable.svelte";
  import LiveChart from "../components/LiveChart.svelte";
  import StatusDot from "../components/StatusDot.svelte";

  let stats = $state<BotStats | null>(null);
  let perf = $state<Performance | null>(null);
  let positions = $state<Position[]>([]);
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

  async function poll() {
    try {
      const [s, p] = await Promise.all([api.stats(), api.performance("7d")]);
      stats = s;
      perf = p;
      apiError = null;
    } catch (e) {
      apiError = e instanceof Error ? e.message : String(e);
    }
  }

  function startStream() {
    stream?.stop();
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

  {#if apiError}
    <div class="err panel">Couldn't reach the bot API: <span class="mono">{apiError}</span></div>
  {/if}

  <ExecSummary {stats} {perf} />

  <div class="chartcard panel">
    <div class="picker">
      {#each symbols as sym (sym)}
        <button class:active={sym === selected} onclick={() => pick(sym)}>{sym}</button>
      {/each}
    </div>
    <LiveChart candles={candlesBySymbol[selected] ?? []} />
  </div>

  <div class="panel positions">
    <div class="ph">Open positions</div>
    <PositionsTable {positions} />
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
