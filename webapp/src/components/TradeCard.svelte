<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Candle, type Position, type BracketHistory } from "../lib/api";
  import { acquireSymbol, cardCandles, cardFeed, seedCandles } from "../lib/cardStream";
  import { bracketsForPosition, packageForPosition } from "../lib/brackets";
  import { money, num, signClass, agoFromIso, DASH } from "../lib/format";
  import LiveChart from "./LiveChart.svelte";
  import EntryWhy from "./EntryWhy.svelte";

  // Expanded open-trade card: every field the row already carries (missing → "—")
  // + a LiveChart for the trade's symbol with entry/SL/TP drawn by LiveChart.
  // Live candles come from ONE shared MarketStream (lib/cardStream) subscribed to
  // the union of open cards' symbols; candles are also seeded over REST so the
  // chart renders if the socket can't connect.
  let { p, interval = "15m" }: { p: Position; interval?: string } = $props();

  let seeded = $state<Candle[]>([]);
  const candles = $derived($cardCandles[p.symbol] ?? seeded);
  const feed = $derived($cardFeed[p.symbol]);
  let brackets = $state<BracketHistory | null>(null);
  // LTR / Claude decisions on this open trade (GET /trades/{id}/markers, bot #25216;
  // prop rows → /prop-trades/{fill}/markers). 404 = route not deployed → none drawn.
  let decisions = $state<any[]>([]);
  let decisionState = $state("loading");
  let bracketState = $state<string>("loading");
  const a = $derived(p as any);

  const sell = $derived(String(p.side ?? "").toLowerCase().startsWith("s"));
  // Reward:risk from the row's own entry/SL/TP; null when any leg is missing.
  const rr = $derived.by(() => {
    const e = p.entryPrice, s = p.stopLoss, t = p.takeProfit;
    if (e == null || s == null || t == null || !s || !t) return null;
    const risk = Math.abs(e - s), reward = Math.abs(t - e);
    return risk > 0 ? reward / risk : null;
  });
  // The order package this trade was opened from (UI-REDESIGN-2026-11 (3): indicators,
  // confidence, which models saw it). null = no linked package → "—".
  let pkg = $state<any>(null);
  let pkgState = $state("loading");
  const logic = $derived((pkg?.signalLogic ?? null) as any);
  // The entry signal as a chart marker at its decision bar.
  const entrySignals = $derived.by(() => {
    const ts = logic?.decision_bar ?? logic?.entry_time ?? pkg?.createdAt;
    if (!ts) return [];
    return [{ timestamp: ts, side: pkg?.direction ?? p.side, pattern: `signal · ${logic?.strategy_name ?? pkg?.strategy ?? "entry"}` }];
  });

  onMount(() => {
    let alive = true;
    api.candles(p.symbol, interval, 200)
      .then((r) => { if (alive && r?.candles?.length) { seeded = r.candles; seedCandles(p.symbol, r.candles); } })
      .catch(() => {});
    {
      const pid = String(p.id ?? "");
      const call = pid.startsWith("prop-") ? api.propTradeMarkers(pid.slice(5), interval) : api.tradeMarkers(pid, interval);
      call.then((r) => {
        if (!alive) return;
        if (r.status === 200) {
          const ms = (r.body?.decisions?.markers ?? []) as any[];
          decisions = ms.map((m) => ({ review_id: m.id ?? null, at: m.bar_ts ?? m.ts ?? null, action: m.action ?? null, disposition: m.disposition ?? null }));
          decisionState = r.body?.decisions?.read_state ?? "read";
        } else decisionState = r.status === 404 ? "route not deployed" : `could not look (${r.status})`;
      }).catch(() => { if (alive) decisionState = "could not look"; });
    }
    packageForPosition(p.id)
      .then((x) => { if (!alive) return; pkg = x; pkgState = x ? "linked" : "no linked order package"; })
      .catch(() => { if (alive) pkgState = "could not look"; });
    bracketsForPosition(p.id, interval)
      .then((b) => { if (!alive) return; brackets = b; bracketState = b ? (b.read_state ?? "—") : "no linked order package"; })
      .catch(() => { if (alive) bracketState = "could not look"; });
    const release = acquireSymbol(p.symbol);
    return () => { alive = false; release(); };
  });

  // Phones get a shorter chart and a 2-column field grid.
  let vw = $state(typeof window !== "undefined" ? window.innerWidth : 1024);
  const narrow = $derived(vw < 640);

  function f(v: unknown): string {
    return v == null || v === "" ? DASH : String(v);
  }
</script>

<svelte:window bind:innerWidth={vw} />
<div class="card">
  <dl>
    <div><dt>Side</dt><dd class={sell ? "neg" : "pos"}>{sell ? "SHORT" : "LONG"}</dd></div>
    <div><dt>Entry</dt><dd class="mono">{money(p.entryPrice)}</dd></div>
    <div><dt>Stop loss</dt><dd class="mono">{p.stopLoss ? money(p.stopLoss) : DASH}</dd></div>
    <div><dt>Take profit</dt><dd class="mono">{p.takeProfit ? money(p.takeProfit) : DASH}</dd></div>
    <div><dt>Size</dt><dd class="mono">{p.qty == null ? DASH : num(p.qty, 4)}</dd></div>
    <div><dt>R (reward:risk)</dt><dd class="mono">{rr == null ? DASH : `${rr.toFixed(2)}R`}</dd></div>
    <div><dt>Strategy</dt><dd>{f(p.pattern ?? pkg?.strategy)}</dd></div>
    <div><dt>Account</dt><dd>{f(p.account)}</dd></div>
    <div><dt>Opened</dt><dd>{p.openedAt ? agoFromIso(p.openedAt) : DASH}</dd></div>
    <div><dt>uPnL</dt><dd class="mono {signClass(p.unrealizedPnl)}">{p.unrealizedPnl == null ? DASH : money(p.unrealizedPnl, { sign: true })}</dd></div>
    <div><dt>uPnL source</dt><dd>{f(p.unrealizedPnlSource)}</dd></div>
    <div><dt>Confidence</dt><dd class="mono">{(a.confidence ?? pkg?.confidence) == null ? DASH : String(a.confidence ?? pkg?.confidence)}</dd></div>
  </dl>
  <LiveChart {candles} positions={[p]} signals={entrySignals} {brackets} {decisions} height={narrow ? 220 : 260} />
  <EntryWhy {pkg} {pkgState} modelScores={a.modelScores} />
  <div class="feed">
    {feed === "bybit" ? "● live · Bybit public stream (browser-direct)" : feed === "ws_market" ? "● live · bot /ws/market" : "REST snapshot"}
    · LTR decisions: {decisionState === "loading" ? "…" : decisions.length ? `${decisions.length} (${decisionState})` : decisionState}
    · bracket history: {bracketState}{brackets?.updates?.length ? ` · ${brackets.updates.length} move(s)` : ""}{(brackets?.partial_reasons ?? []).length ? ` (${brackets?.partial_reasons?.join(", ")})` : ""}
  </div>
</div>

<style>
  .card { padding: 10px 12px 12px; background: var(--panel-2); border-top: 1px solid var(--border); }
  dl { margin: 0 0 10px; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px 12px; }
  @media (max-width: 640px) { dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } .card { padding: 8px; } }
  dt { color: var(--muted); font-size: 11px; }
  dd { margin: 2px 0 0; font-size: 13px; font-weight: 600; }
  .wide { grid-column: 1 / -1; }
  .feed { color: var(--muted); font-size: 11px; margin-top: 4px; }

  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
