<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Candle, type Position } from "../lib/api";
  import { acquireSymbol, cardCandles } from "../lib/cardStream";
  import { money, num, signClass, agoFromIso, DASH } from "../lib/format";
  import LiveChart from "./LiveChart.svelte";

  // Expanded open-trade card: every field the row already carries (missing → "—")
  // + a LiveChart for the trade's symbol with entry/SL/TP drawn by LiveChart.
  // Live candles come from ONE shared MarketStream (lib/cardStream) subscribed to
  // the union of open cards' symbols; candles are also seeded over REST so the
  // chart renders if the socket can't connect.
  let { p, interval = "15m" }: { p: Position; interval?: string } = $props();

  let seeded = $state<Candle[]>([]);
  const candles = $derived($cardCandles[p.symbol] ?? seeded);
  const a = $derived(p as any);

  const sell = $derived(String(p.side ?? "").toLowerCase().startsWith("s"));
  // Reward:risk from the row's own entry/SL/TP; null when any leg is missing.
  const rr = $derived.by(() => {
    const e = p.entryPrice, s = p.stopLoss, t = p.takeProfit;
    if (e == null || s == null || t == null || !s || !t) return null;
    const risk = Math.abs(e - s), reward = Math.abs(t - e);
    return risk > 0 ? reward / risk : null;
  });
  const modelScores = $derived.by(() => {
    const ms = a.modelScores;
    if (!ms || typeof ms !== "object") return null;
    const parts = Object.entries<any>(ms).map(([k, v]) => `${k}: ${v?.score != null ? Number(v.score).toFixed(2) : DASH}`);
    return parts.length ? parts.join(" · ") : null;
  });

  onMount(() => {
    let alive = true;
    api.candles(p.symbol, interval, 200)
      .then((r) => { if (alive && r?.candles?.length) seeded = r.candles; })
      .catch(() => {});
    const release = acquireSymbol(p.symbol);
    return () => { alive = false; release(); };
  });

  function f(v: unknown): string {
    return v == null || v === "" ? DASH : String(v);
  }
</script>

<div class="card">
  <dl>
    <div><dt>Side</dt><dd class={sell ? "neg" : "pos"}>{sell ? "SHORT" : "LONG"}</dd></div>
    <div><dt>Entry</dt><dd class="mono">{money(p.entryPrice)}</dd></div>
    <div><dt>Stop loss</dt><dd class="mono">{p.stopLoss ? money(p.stopLoss) : DASH}</dd></div>
    <div><dt>Take profit</dt><dd class="mono">{p.takeProfit ? money(p.takeProfit) : DASH}</dd></div>
    <div><dt>Size</dt><dd class="mono">{p.qty == null ? DASH : num(p.qty, 4)}</dd></div>
    <div><dt>R (reward:risk)</dt><dd class="mono">{rr == null ? DASH : `${rr.toFixed(2)}R`}</dd></div>
    <div><dt>Strategy</dt><dd>{f(p.pattern)}</dd></div>
    <div><dt>Account</dt><dd>{f(p.account)}</dd></div>
    <div><dt>Opened</dt><dd>{p.openedAt ? `${agoFromIso(p.openedAt)} ago` : DASH}</dd></div>
    <div><dt>uPnL</dt><dd class="mono {signClass(p.unrealizedPnl)}">{p.unrealizedPnl == null ? DASH : money(p.unrealizedPnl, { sign: true })}</dd></div>
    <div><dt>uPnL source</dt><dd>{f(p.unrealizedPnlSource)}</dd></div>
    <div><dt>Confidence</dt><dd class="mono">{a.confidence == null ? DASH : String(a.confidence)}</dd></div>
    <div class="wide"><dt>Model scores</dt><dd>{modelScores ?? DASH}</dd></div>
  </dl>
  <LiveChart {candles} positions={[p]} height={260} />
</div>

<style>
  .card { padding: 10px 12px 12px; background: var(--panel-2); border-top: 1px solid var(--border); }
  dl { margin: 0 0 10px; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px 12px; }
  dt { color: var(--muted); font-size: 11px; }
  dd { margin: 2px 0 0; font-size: 13px; font-weight: 600; }
  .wide { grid-column: 1 / -1; }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
