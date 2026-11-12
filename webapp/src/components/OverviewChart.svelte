<script lang="ts">
  // The Overview's live chart (UI-OVERVIEW-WORK-PROP + T3a, UI-TWO-SURFACE-
  // DESIGN-2026-11 § 4.3): ONE chart directly under the trade overview, with a
  // symbol picker. `*USDT` legs tick from Bybit's public WebSocket in the
  // browser; everything else rides the bot's /ws/market — both through the
  // shared lib/cardStream (one socket per feed for the whole page, shared with
  // the open-trade cards). History is seeded once from REST /api/bot/candles.
  //
  // Markers are the system's own: signals (▲/▼), open entries (● open), fills
  // of closed trades (circle with P&L), and SL/TP bracket moves + earlier
  // levels (from /api/bot/brackets/history for the first open position on the
  // symbol). Until the T1 stream lands, markers refresh with the Overview's
  // REST poll rather than per event.
  import { api, type Candle, type Position, type ClosedTrade, type BracketHistory } from "../lib/api";
  import { acquireSymbol, cardCandles, cardFeed, seedCandles } from "../lib/cardStream";
  import { bracketsForPosition } from "../lib/brackets";
  import { DASH } from "../lib/format";
  import LiveChart from "./LiveChart.svelte";

  let {
    positions = [], signals = [], closedTrades = [],
  }: { positions?: Position[]; signals?: any[]; closedTrades?: ClosedTrade[] } = $props();

  const INTERVAL = "15m"; // cardStream's one live interval

  // Open-position symbols first (badged), then recently signalled / traded ones.
  const symbols = $derived.by(() => {
    const out: string[] = [];
    const add = (s: unknown) => { const v = typeof s === "string" ? s.trim() : ""; if (v && !out.includes(v)) out.push(v); };
    for (const p of positions) add(p.symbol);
    for (const s of signals) add(s?.symbol);
    for (const c of closedTrades) add(c.symbol);
    return out.slice(0, 16);
  });
  const openSet = $derived(new Set(positions.map((p) => p.symbol)));

  let picked = $state<string | null>(null);
  const symbol = $derived(picked && symbols.includes(picked) ? picked : (symbols[0] ?? null));

  let seeded = $state<Candle[]>([]);
  let seedState = $state<string>("—");
  const candles = $derived(symbol ? ($cardCandles[symbol] ?? seeded) : []);
  const feed = $derived(symbol ? $cardFeed[symbol] : undefined);

  const symPositions = $derived(symbol ? positions.filter((p) => p.symbol === symbol) : []);
  const symSignals = $derived(symbol ? signals.filter((s) => s?.symbol === symbol && s?.pattern != null) : []);
  const symClosed = $derived(symbol ? closedTrades.filter((c) => c.symbol === symbol) : []);

  // Seed + subscribe whenever the symbol changes; release the old one.
  $effect(() => {
    const s = symbol;
    if (!s) return;
    let alive = true;
    seeded = [];
    seedState = "loading";
    api.candles(s, INTERVAL, 300)
      .then((r) => {
        if (!alive) return;
        if (r?.candles?.length) { seeded = r.candles; seedCandles(s, r.candles); seedState = r.source ?? "rest"; }
        else seedState = r?.error ? `no candles (${r.error})` : "no candles";
      })
      .catch((e) => { if (alive) seedState = `could not look (${e instanceof Error ? e.message : String(e)})`; });
    const release = acquireSymbol(s);
    return () => { alive = false; release(); };
  });

  // Bracket history for the first open position on the symbol.
  let brackets = $state<BracketHistory | null>(null);
  const bracketPid = $derived(symPositions[0]?.id ?? null);
  $effect(() => {
    const pid = bracketPid;
    brackets = null;
    if (pid == null) return;
    let alive = true;
    bracketsForPosition(String(pid), INTERVAL).then((b) => { if (alive) brackets = b; }).catch(() => {});
    return () => { alive = false; };
  });

  let vw = $state(typeof window !== "undefined" ? window.innerWidth : 1024);
  const narrow = $derived(vw < 640);
</script>

<svelte:window bind:innerWidth={vw} />
<div class="panel oc">
  <div class="ph">
    <span>📈 Live chart · {INTERVAL}</span>
    {#if symbols.length}
      <div class="picker" role="tablist" aria-label="Chart symbol">
        {#each symbols as s (s)}
          <button role="tab" aria-selected={s === symbol} class:on={s === symbol} onclick={() => (picked = s)}>
            {#if openSet.has(s)}<span class="dot" title="open position">●</span>{/if}{s}
          </button>
        {/each}
      </div>
    {/if}
  </div>
  {#if !symbol}
    <div class="muted pad">No symbol to chart yet — no open positions, signals or recent closed trades in view.</div>
  {:else}
    <LiveChart {candles} positions={symPositions} signals={symSignals} closedTrades={symClosed} {brackets} height={narrow ? 260 : 360} />
    <div class="feed">
      {feed === "bybit" ? "● live · Bybit public stream (browser-direct)" : feed === "ws_market" ? "● live · bot /ws/market" : "REST snapshot"}
      · history: {seedState}
      · markers: {symSignals.length} signal(s), {symPositions.length} open, {symClosed.length} closed{brackets?.updates?.length ? `, ${brackets.updates.length} bracket move(s)` : ""}
      {#if symPositions.length > 1}· brackets shown for the first of {symPositions.length} open legs{/if}
      {#if bracketPid != null && !brackets}· bracket history: {DASH}{/if}
    </div>
  {/if}
</div>

<style>
  .oc { padding: 4px 12px 10px; }
  .ph { padding: 10px 0 6px; font-weight: 600; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
  .picker { display: flex; gap: 4px; overflow-x: auto; max-width: 100%; padding-bottom: 2px; }
  .picker button {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px;
    padding: 3px 8px; font-size: 12px; cursor: pointer; white-space: nowrap; font-weight: 500;
  }
  .picker button.on { border-color: var(--accent); color: var(--accent); font-weight: 700; }
  .dot { color: var(--pos); margin-right: 3px; font-size: 10px; }
  .feed { color: var(--muted); font-size: 11px; margin-top: 4px; }
  .muted { color: var(--muted); }
  .pad { padding: 16px 0; }
</style>
