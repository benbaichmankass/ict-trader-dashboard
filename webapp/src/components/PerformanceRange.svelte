<script lang="ts">
  // Performance — book selector + start/end DATE RANGE (UI-REDESIGN-2026-11 +
  // reconciliation § 4: the four books, a date-range picker with no window buttons,
  // max drawdown included; default the last 30 days).
  //
  // The figures are the BOT's (/api/bot/performance, /api/bot/prop/overview) — never
  // recomputed here (AM-UI, 2026-11-12). Those routes serve fixed windows only
  // (24h | 7d | 30d | all), so a range that is exactly "the last 1 / 7 / 30 days" is
  // read from the matching window; any other range renders "could not look" until the
  // bot's /performance?since=&until= ships (lane UI-SPA-BACKEND-ROUTES).
  import { api } from "../lib/api";
  import { FUNDING_OPTIONS } from "../lib/nav";
  import { normalizeFunding, type FundingBook } from "../lib/funding";
  import { money, num, pct, signClass, DASH } from "../lib/format";
  import Segmented from "./Segmented.svelte";
  import EquityChart from "./EquityChart.svelte";

  const today = () => new Date().toISOString().slice(0, 10);
  const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

  let book = $state<FundingBook>(normalizeFunding("real"));
  // The range is bindable so the page can share it (the category table follows it).
  let { start = $bindable(daysAgo(30)), end = $bindable(today()) }: { start?: string; end?: string } = $props();

  // The bot window that equals [start, end], or null.
  const win = $derived.by(() => {
    if (end !== today()) return null;
    for (const [d, w] of [[1, "24h"], [7, "7d"], [30, "30d"]] as Array<[number, string]>) if (start === daysAgo(d)) return w;
    return null;
  });

  let perf = $state<any>(null);
  let prop = $state<any>(null);
  let error = $state<string | null>(null);
  let loading = $state(false);
  // "range" when the bot answered the exact [start, end] (bot #25231, echo
  // window === "range"); "window" when read from the matching fixed window.
  let basis = $state<"range" | "window" | null>(null);
  let seq = 0;
  $effect(() => {
    const w = win, b = book, s0 = start, e0 = end;
    perf = null; prop = null; error = null; basis = null;
    const my = ++seq;
    loading = true;
    (async () => {
      try {
        if (b !== "prop" && s0 && e0 && s0 <= e0) {
          const r = await api.performanceRange(s0, e0);
          if (my !== seq) return;
          if (r.status === 200 && r.body?.window === "range") { perf = r.body; basis = "range"; return; }
        }
        if (!w) return; // no exact range from the bot, and no fixed window equals it
        if (b === "prop") { const v = await api.propOverview(w); if (my === seq) { prop = v; basis = "window"; } }
        else { const v = await api.performance(w); if (my === seq) { perf = v; basis = "window"; } }
      } catch (e) {
        if (my === seq) error = e instanceof Error ? e.message : String(e);
      } finally {
        if (my === seq) loading = false;
      }
    })();
  });

  // One shape for the stats band. Paper testing has no bot block (could not look).
  type Band = { trades: number | null; winRatePct: number | null; net: number | null; expectancy: number | null; pf: number | null; maxDd: number | null; note: string | null };
  const band = $derived.by<Band | null>(() => {
    if (book === "prop") {
      const r = prop?.realized;
      if (!r) return null;
      return {
        trades: r.closed_trades ?? null, winRatePct: typeof r.win_rate === "number" ? r.win_rate * 100 : null,
        net: r.total_pnl ?? null, expectancy: null, pf: r.profit_factor ?? null, maxDd: null,
        note: r.closed_unpriced ? `${r.closed_unpriced} of ${r.closed_trades} closed prop trade(s) have no P&L (prop journal)` : null,
      };
    }
    const p = book === "paper_portfolio" ? (perf?.paperPortfolio ?? perf?.paper ?? null) : book === "real" ? perf : null;
    if (!p) return null;
    const bad = (p.pnlFabricatedCount ?? 0) + (p.pnlUnverifiedCount ?? 0);
    return {
      trades: p.totalTrades ?? null, winRatePct: p.winRate ?? null, net: p.totalPnl ?? null, expectancy: p.expectancy ?? null,
      pf: p.profitFactor ?? null, maxDd: p.maxDrawdown ?? null,
      note: bad > 0 && p.pnlCoverage != null ? `includes best-estimate (non-broker) values — ${Math.round(p.pnlCoverage * 100)}% broker-measured` : null,
    };
  });
  const block = $derived(book === "real" ? perf : book === "paper_portfolio" ? (perf?.paperPortfolio ?? perf?.paper ?? null) : null);
  const m = (v: number | null | undefined) => (v == null ? DASH : money(v, { sign: true }));
</script>

<div class="pr">
  <div class="controls">
    <Segmented options={FUNDING_OPTIONS} bind:value={book} />
    <div class="range">
      <label>From <input type="date" bind:value={start} max={end} /></label>
      <label>To <input type="date" bind:value={end} min={start} max={today()} /></label>
    </div>
  </div>
  <div class="muted small">{start} → {end} (UTC){basis === "range" ? ` · the bot's exact range (since ${perf?.since ?? DASH}, until ${perf?.until ?? DASH})` : basis === "window" ? ` · the bot's ${win} window (rolling)` : ""} · figures from {book === "prop" ? "/api/bot/prop/overview" : "/api/bot/performance"}</div>

  {#if loading && !perf && !prop}
    <div class="muted pad">Loading…</div>
  {:else if !basis && !win}
    <div class="cnl panel">could not look — the bot did not answer this exact range (its <span class="mono">/performance?since=&amp;until=</span> is not deployed yet{book === "prop" ? "; prop has no range route" : ""}), and no fixed bot window (last 1 / 7 / 30 days) equals it.</div>
  {:else if book === "paper_testing"}
    <div class="cnl panel">could not look — the bot's performance route has no paper-testing block yet.</div>
  {:else if error}
    <div class="err panel">Couldn't load performance: <span class="mono">{error}</span></div>
  {:else if loading || !band}
    <div class="muted pad">{loading ? "Loading…" : "could not look — no figures for this book."}</div>
  {:else}
    <div class="grid">
      <div class="metric panel"><div class="k">Trades</div><div class="v mono">{num(band.trades)}</div></div>
      <div class="metric panel"><div class="k">Win rate</div><div class="v mono">{pct(band.winRatePct)}</div></div>
      <div class="metric panel"><div class="k">Net P&amp;L</div><div class="v mono {signClass(band.net)}">{m(band.net)}</div></div>
      <div class="metric panel"><div class="k">Expectancy</div><div class="v mono {signClass(band.expectancy)}">{m(band.expectancy)}</div></div>
      <div class="metric panel"><div class="k">Profit factor</div><div class="v mono">{band.pf == null ? DASH : band.pf.toFixed(2)}</div></div>
      <div class="metric panel"><div class="k">Max drawdown</div><div class="v mono {signClass(band.maxDd)}">{band.maxDd == null ? DASH : money(band.maxDd)}</div></div>
    </div>
    {#if band.note}<div class="caveat">⚠ {band.note}</div>{/if}

    {#if (block?.equity ?? []).length > 1}
      <div class="panel card"><div class="ph">Equity curve — cumulative realised P&amp;L</div><EquityChart points={block.equity} /></div>
    {/if}

    <div class="bds">
      <div class="panel card">
        <div class="ph">By strategy</div>
        {#if (block?.perStrategy ?? []).length}
          <div class="scroll"><table>
            <thead><tr><th>Strategy</th><th class="r">Trades</th><th class="r">Win rate</th><th class="r">Net P&amp;L</th><th class="r">Expectancy</th></tr></thead>
            <tbody>{#each [...block.perStrategy].sort((a, b) => (b.totalPnl ?? 0) - (a.totalPnl ?? 0)) as s (s.name)}
              <tr><td class="sym">{s.name}</td><td class="r mono">{num(s.trades)}</td><td class="r mono">{pct(s.winRate)}</td><td class="r mono {signClass(s.totalPnl)}">{m(s.totalPnl)}</td><td class="r mono {signClass(s.expectancy)}">{m(s.expectancy)}</td></tr>
            {/each}</tbody>
          </table></div>
        {:else}<div class="muted pad">{DASH}</div>{/if}
      </div>
      <div class="panel card">
        <div class="ph">By asset class</div>
        {#if (block?.perAssetClass ?? []).length}
          <div class="scroll"><table>
            <thead><tr><th>Asset class</th><th class="r">Trades</th><th class="r">Win rate</th><th class="r">Net P&amp;L</th></tr></thead>
            <tbody>{#each block.perAssetClass as a (a.assetClass)}
              <tr><td class="sym">{a.assetClass}</td><td class="r mono">{num(a.trades)}</td><td class="r mono">{pct(a.winRate)}</td><td class="r mono {signClass(a.totalPnl)}">{m(a.totalPnl)}</td></tr>
            {/each}</tbody>
          </table></div>
        {:else}<div class="muted pad">{DASH}</div>{/if}
      </div>
      <div class="panel card">
        <div class="ph">By account</div>
        <div class="muted pad">could not look — the bot's performance route has no per-account block yet.</div>
      </div>
    </div>
  {/if}
</div>

<style>
  .pr { display: flex; flex-direction: column; gap: 10px; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .range { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 13px; }
  .range input { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 3px 6px; font: inherit; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .metric { padding: 10px 12px; }
  .k { color: var(--muted); font-size: 12px; }
  .v { font-size: 18px; font-weight: 700; margin-top: 2px; }
  .bds { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px; }
  .card { padding: 4px 4px 8px; }
  .ph { padding: 10px 10px 6px; font-weight: 600; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { padding: 6px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .pad { padding: 12px 10px; }
  .cnl { padding: 10px 12px; color: var(--muted); font-size: 13px; }
  .err { padding: 10px 12px; color: var(--neg); }
  .caveat { color: #d4a017; font-size: 12px; }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
