<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Candle, type Position, type BracketHistory } from "../lib/api";
  import { acquireSymbol, cardCandles, cardFeed, seedCandles } from "../lib/cardStream";
  import { bracketsForPosition, packageForPosition } from "../lib/brackets";
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
  const feed = $derived($cardFeed[p.symbol]);
  let brackets = $state<BracketHistory | null>(null);
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
  // Which models saw it: the position row's modelScores, else the package's.
  const models = $derived.by(() => {
    const ms = a.modelScores ?? pkg?.modelScores;
    if (!ms || typeof ms !== "object") return [] as Array<{ id: string; stage: string; score: string }>;
    return Object.entries<any>(ms).map(([id, v]) => ({
      id, stage: v?.stage ?? DASH, score: v?.score != null && Number.isFinite(Number(v.score)) ? Number(v.score).toFixed(3) : DASH,
    }));
  });
  // Indicators at decision time — the numeric features the entry was scored on.
  const features = $derived.by(() => {
    const f = logic?.features;
    if (!f || typeof f !== "object") return [] as Array<[string, string]>;
    return Object.entries<any>(f).map(([k, v]) => [k, typeof v === "number" && Number.isFinite(v) ? String(+v.toPrecision(4)) : v == null ? DASH : String(v)] as [string, string]);
  });
  const contributing = $derived(((logic?.contributing_strategies ?? logic?.aggregation?.contributing_strategies ?? []) as string[]).join(", "));
  const meta = $derived((pkg?.meta ?? {}) as any);
  // The entry signal as a chart marker at its decision bar.
  const entrySignals = $derived.by(() => {
    const ts = logic?.decision_bar ?? logic?.entry_time ?? pkg?.createdAt;
    if (!ts) return [];
    return [{ timestamp: ts, side: pkg?.direction ?? p.side, pattern: `signal · ${logic?.strategy_name ?? pkg?.strategy ?? "entry"}` }];
  });
  const fx = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? String(+v.toFixed(d)) : v == null || v === "" ? DASH : String(v));

  onMount(() => {
    let alive = true;
    api.candles(p.symbol, interval, 200)
      .then((r) => { if (alive && r?.candles?.length) { seeded = r.candles; seedCandles(p.symbol, r.candles); } })
      .catch(() => {});
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
  <LiveChart {candles} positions={[p]} signals={entrySignals} {brackets} height={narrow ? 220 : 260} />
  <div class="why">
    <div class="wt">Why we entered <span class="muted">· {pkgState}{pkg?.orderPackageId ? ` · ${pkg.orderPackageId}` : ""}</span></div>
    {#if pkg}
      <div class="kv">
        <span>Strategy <b>{logic?.strategy_name ?? pkg.strategy ?? DASH}</b></span>
        <span>Model <b class="mono">{logic?.model_id ?? DASH}</b></span>
        <span>Decision bar <b class="mono">{logic?.decision_bar ? String(logic.decision_bar).slice(0, 16).replace("T", " ") + "Z" : DASH}</b></span>
        <span>p(long) <b class="mono">{fx(logic?.p_long)}</b> · p(short) <b class="mono">{fx(logic?.p_short)}</b> · τ <b class="mono">{fx(logic?.tau)}</b></span>
        <span>Confidence <b class="mono">{fx(pkg.confidence ?? logic?.confidence, 2)}</b></span>
        <span>Claude score <b class="mono">{fx(pkg.claudeScore, 2)}</b></span>
        <span>Contributing <b>{contributing || DASH}</b>{logic?.aggregation?.resolution ? ` (${logic.aggregation.resolution})` : ""}</span>
        {#if meta.setup_type || meta.killzone || meta.bias}<span>Setup <b>{meta.setup_type ?? DASH}</b> · killzone <b>{meta.killzone ?? DASH}</b> · bias <b>{meta.bias ?? DASH}</b></span>{/if}
        {#if logic?.tp_intent || logic?.tp_basis}<span class="wide" title={logic?.tp_basis ?? ""}>TP intent <b>{logic?.tp_intent ?? DASH}</b>{logic?.tp_basis ? ` — ${logic.tp_basis}` : ""}</span>{/if}
      </div>
      {#if features.length}
        <div class="wsub">Indicators at decision time</div>
        <div class="chips">{#each features as [k, v] (k)}<span class="chip"><span class="muted">{k}</span> <span class="mono">{v}</span></span>{/each}</div>
      {/if}
    {/if}
    <div class="wsub">Models that saw it</div>
    {#if models.length}
      <div class="chips">{#each models as m (m.id)}<span class="chip"><span class="mono">{m.id}</span> <span class="muted">{m.stage}</span> <b class="mono">{m.score}</b></span>{/each}</div>
    {:else}
      <div class="muted small">{DASH}</div>
    {/if}
  </div>
  <div class="feed">
    {feed === "bybit" ? "● live · Bybit public stream (browser-direct)" : feed === "ws_market" ? "● live · bot /ws/market" : "REST snapshot"}
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
  .why { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; font-size: 12px; }
  .wt { font-weight: 600; margin-bottom: 4px; }
  .kv { display: flex; flex-wrap: wrap; gap: 4px 16px; }
  .kv .wide { flex-basis: 100%; overflow-wrap: anywhere; }
  .wsub { color: var(--muted); font-size: 11px; margin: 8px 0 3px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px; font-size: 11px; white-space: nowrap; }
  .muted { color: var(--muted); }
  .small { font-size: 11px; }
  .mono { font-variant-numeric: tabular-nums; }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
