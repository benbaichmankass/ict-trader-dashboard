<script lang="ts">
  // Performance — book selector + start/end date range (UI-REDESIGN-2026-11,
  // PERFORMANCE). Replaces the 24h/7d/30d/All buttons. /api/bot/performance only
  // serves fixed windows, so this view computes its roll-ups IN THE BROWSER from
  // the closed-trade rows of the chosen book and range (lib/perfStats) and says so.
  //   real / paper books → /api/bot/trades/closed?since=<start>&include_paper=true,
  //                        walked by offset (200-row pages, capped), split by
  //                        lib/funding's book of each row, filtered to ≤ end.
  //   prop               → the prop journal (/api/bot/prop/fills, closed fills).
  import { api } from "../lib/api";
  import { FUNDING_OPTIONS } from "../lib/nav";
  import { accountBooks, bookOfRow, normalizeFunding, type FundingBook } from "../lib/funding";
  import { closedFills, fillClosedAt, fillProvenance, fillRaw } from "../lib/propPnl";
  import { stats, equity, breakdown, isoDaysAgo, inRange, type PerfRow, type PerfStats } from "../lib/perfStats";
  import { money, num, pct, signClass, DASH } from "../lib/format";
  import Segmented from "./Segmented.svelte";
  import EquityChart from "./EquityChart.svelte";

  const MAX_PAGES = 10; // 2,000 closed trades per range read

  let book = $state<FundingBook>(normalizeFunding("real"));
  let start = $state(isoDaysAgo(30));
  let end = $state(isoDaysAgo(0));
  const PRESETS: Array<[string, () => [string, string]]> = [
    ["7d", () => [isoDaysAgo(7), isoDaysAgo(0)]],
    ["30d", () => [isoDaysAgo(30), isoDaysAgo(0)]],
    ["90d", () => [isoDaysAgo(90), isoDaysAgo(0)]],
    ["YTD", () => [`${new Date().getUTCFullYear()}-01-01`, isoDaysAgo(0)]],
    ["1y", () => [isoDaysAgo(365), isoDaysAgo(0)]],
  ];

  let rows = $state<PerfRow[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let truncated = $state(false);
  let unassigned = $state(0);

  async function load(b: FundingBook, s: string, e: string, isCurrent: () => boolean) {
    loading = true; error = null; truncated = false; unassigned = 0;
    try {
      let out: PerfRow[] = [];
      if (b === "prop") {
        const r = await api.propFills(500);
        const fills = closedFills(Array.isArray(r?.fills) ? r.fills : []);
        out = fills
          .filter((f) => inRange(fillClosedAt(f), s, e))
          .map((f) => ({
            pnl: typeof f.pnl === "number" ? f.pnl : null,
            closedAt: fillClosedAt(f),
            strategy: fillRaw(f)?.strategy ?? null,
            assetClass: null,
            account: f.account_id ?? null,
            provenance: fillProvenance(f).toLowerCase(),
          }));
      } else {
        const books = accountBooks(await api.config());
        const all: any[] = [];
        let offset = 0;
        for (let page = 0; page < MAX_PAGES; page++) {
          const p: any = await api.closedTradesPage({ since: `${s}T00:00:00Z`, includePaper: true, limit: 200, offset });
          all.push(...(p.rows ?? []));
          if (!p.hasMore || !(p.rows ?? []).length) break;
          offset += (p.rows ?? []).length;
          if (page === MAX_PAGES - 1) truncated = true;
        }
        for (const t of all) {
          const rb = bookOfRow(t, books);
          if (rb !== b) { if (rb === null && (b === "paper_portfolio" || b === "paper_testing")) unassigned++; continue; }
          if (!inRange(t.closedAt, s, e)) continue;
          out.push({
            pnl: typeof t.pnl === "number" ? t.pnl : null,
            closedAt: t.closedAt ?? null,
            strategy: t.strategy ?? t.pattern ?? null,
            assetClass: t.assetClass ?? null,
            account: t.account ?? null,
            provenance: t.pnlProvenance ?? null,
          });
        }
      }
      if (isCurrent()) rows = out;
    } catch (err) {
      if (isCurrent()) { error = err instanceof Error ? err.message : String(err); rows = []; }
    } finally {
      if (isCurrent()) loading = false;
    }
  }

  let seq = 0;
  $effect(() => {
    const b = book, s = start, e = end;
    if (!s || !e || s > e) return;
    const my = ++seq;
    load(b, s, e, () => my === seq);
  });

  const st = $derived<PerfStats>(stats(rows));
  const eq = $derived(equity(rows));
  const byStrategy = $derived(breakdown(rows, (r) => r.strategy));
  const byAsset = $derived(breakdown(rows, (r) => r.assetClass));
  const byAccount = $derived(breakdown(rows, (r) => r.account));
  const sections = $derived<Array<{ title: string; col: string; list: Array<{ name: string; s: PerfStats }> }>>([
    { title: "By strategy", col: "Strategy", list: byStrategy },
    { title: "By asset class", col: "Asset class", list: byAsset },
    { title: "By account", col: "Account", list: byAccount },
  ]);
  const m = (v: number | null) => (v == null ? DASH : money(v, { sign: true }));
</script>

<div class="pr">
  <div class="controls">
    <Segmented options={FUNDING_OPTIONS} bind:value={book} />
    <div class="range">
      <label>From <input type="date" bind:value={start} max={end} /></label>
      <label>To <input type="date" bind:value={end} min={start} /></label>
      <span class="presets">
        {#each PRESETS as [label, f] (label)}
          <button onclick={() => { const [a, b] = f(); start = a; end = b; }}>{label}</button>
        {/each}
      </span>
    </div>
  </div>
  <div class="muted small">
    {start} → {end} (UTC) · computed in the browser from {book === "prop" ? "the prop journal's closed fills" : "/trades/closed"}
    {#if truncated}· ⚠ capped at {MAX_PAGES * 200} trades — narrow the range for a complete figure{/if}
    {#if unassigned}· {unassigned} paper trade(s) fit neither paper book (no account / config unreadable) and are left out{/if}
  </div>

  {#if error}
    <div class="err panel">Couldn't load trades: <span class="mono">{error}</span></div>
  {:else if loading && !rows.length}
    <div class="muted pad">Loading…</div>
  {:else}
    <div class="grid">
      <div class="metric panel"><div class="k">Trades</div><div class="v mono">{num(st.trades)}</div>{#if st.unpriced}<div class="muted small">{st.unpriced} without P&amp;L</div>{/if}</div>
      <div class="metric panel"><div class="k">Win rate</div><div class="v mono">{st.winRate == null ? DASH : pct(st.winRate * 100)}</div><div class="muted small">{st.wins}W · {st.losses}L</div></div>
      <div class="metric panel"><div class="k">Net P&amp;L</div><div class="v mono {signClass(st.net)}">{m(st.net)}</div></div>
      <div class="metric panel"><div class="k">Expectancy</div><div class="v mono {signClass(st.expectancy)}">{m(st.expectancy)}</div></div>
      <div class="metric panel"><div class="k">Profit factor</div><div class="v mono">{st.profitFactor == null ? DASH : st.profitFactor.toFixed(2)}</div></div>
      <div class="metric panel"><div class="k">Max drawdown</div><div class="v mono {signClass(st.maxDrawdown)}">{st.maxDrawdown == null ? DASH : money(st.maxDrawdown)}</div></div>
      <div class="metric panel"><div class="k">Avg win / loss</div><div class="v mono">{m(st.avgWin)} / {m(st.avgLoss)}</div></div>
      <div class="metric panel"><div class="k">Best / worst</div><div class="v mono">{m(st.best)} / {m(st.worst)}</div></div>
    </div>
    {#if st.estimated}<div class="caveat">⚠ {st.estimated} of {st.priced} priced trade(s) carry an estimated (non-broker) P&amp;L.</div>{/if}

    {#if eq.length > 1}
      <div class="panel card">
        <div class="ph">Equity curve — cumulative realised P&amp;L</div>
        <EquityChart points={eq} />
      </div>
    {/if}

    <div class="bds">
      {#each sections as { title, col, list } (title)}
        <div class="panel card">
          <div class="ph">{title}</div>
          {#if !list.length}
            <div class="muted pad">No trades in this range.</div>
          {:else}
            <div class="scroll">
              <table>
                <thead><tr><th>{col}</th><th class="r">Trades</th><th class="r">Win rate</th><th class="r">Net P&amp;L</th><th class="r">Expectancy</th><th class="r">PF</th></tr></thead>
                <tbody>
                  {#each list as { name, s } (name)}
                    <tr>
                      <td class="sym">{name}</td>
                      <td class="r mono">{num(s.trades)}</td>
                      <td class="r mono">{s.winRate == null ? DASH : pct(s.winRate * 100)}</td>
                      <td class="r mono {signClass(s.net)}">{m(s.net)}</td>
                      <td class="r mono {signClass(s.expectancy)}">{m(s.expectancy)}</td>
                      <td class="r mono">{s.profitFactor == null ? DASH : s.profitFactor.toFixed(2)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .pr { display: flex; flex-direction: column; gap: 10px; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  .range { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 13px; }
  .range input { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 3px 6px; font: inherit; }
  .presets { display: inline-flex; gap: 4px; }
  .presets button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; font-size: 12px; cursor: pointer; }
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
  .err { padding: 10px 12px; color: var(--neg); }
  .caveat { color: #d4a017; font-size: 12px; }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
