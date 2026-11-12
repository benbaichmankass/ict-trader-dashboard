<script lang="ts">
  // PERF-PAGE-CATEGORY-TABLE + PERF-PAGE-PNL-CHART (UI workplan §4/§5, bot #24893).
  // One row per funding CATEGORY from `GET /api/bot/performance/categories`, and
  // a cumulative-P&L line per category from `/performance/pnl-series`. Both
  // share this panel's own window (7d/30d/90d/All — the routes 400 on 24h, so
  // the page-level 24h/7d/30d/All axis cannot drive them) and the
  // "measured only" toggle.
  //
  // Rendering rules: null → "—" (never 0). Measured and not-measured P&L are
  // shown side by side, never folded. A category with no capital record has no
  // % line; it is drawn only in $ mode and the gap is named, not zero-filled.
  import { api, type PerfCategories, type PnlSeries, type PerfCategoryRow } from "../lib/api";
  import { money, num, signClass, DASH } from "../lib/format";
  import Segmented from "./Segmented.svelte";
  import PnlSeriesChart from "./PnlSeriesChart.svelte";

  const CAT_LABEL: Record<string, string> = {
    live: "Live money",
    prop: "Prop",
    paper_portfolio: "Paper portfolio",
    paper_testing: "Paper testing",
  };
  const WINDOWS = [
    { value: "7d", label: "7d" },
    { value: "30d", label: "30d" },
    { value: "90d", label: "90d" },
    { value: "all", label: "All" },
  ];
  const ASSET_CLASSES = ["", "crypto", "equity", "index", "commodity", "fx"];

  let win = $state("30d");
  let measuredOnly = $state(true);
  let unit = $state<"pct" | "usd">("pct");
  let picked = $state<Record<string, boolean>>({ live: true, prop: true, paper_portfolio: true, paper_testing: true });
  let assetClass = $state("");
  let strategy = $state("");
  let symbol = $state("");
  let applied = $state({ strategy: "", symbol: "" });

  let cats = $state<PerfCategories | null>(null);
  let catErr = $state<string | null>(null);
  let series = $state<PnlSeries | null>(null);
  let seriesErr = $state<string | null>(null);

  async function loadCats(w: string) {
    catErr = null;
    try {
      cats = await api.perfCategories(w);
    } catch (e) {
      cats = null;
      catErr = e instanceof Error ? e.message : String(e);
    }
  }
  async function loadSeries(w: string, mo: boolean, sel: string[], ac: string, f: { strategy: string; symbol: string }) {
    seriesErr = null;
    if (!sel.length) { series = { series: [] }; return; }
    try {
      series = await api.pnlSeries({ window: w, measuredOnly: mo, category: sel, assetClass: ac || undefined,
        strategy: f.strategy || undefined, symbol: f.symbol || undefined });
    } catch (e) {
      series = null;
      seriesErr = e instanceof Error ? e.message : String(e);
    }
  }
  const selected = $derived(Object.keys(picked).filter((k) => picked[k]));
  $effect(() => { loadCats(win); });
  $effect(() => { loadSeries(win, measuredOnly, selected, assetClass, applied); });

  function pnlHead(r: PerfCategoryRow): number | null | undefined {
    return measuredOnly ? r.measured_usd : r.net_pnl_usd;
  }
  function rot(r: PerfCategoryRow): number | null | undefined {
    return measuredOnly ? r.return_on_time_in_trade_bps_per_notional_day : r.return_on_time_in_trade_all_rows_bps_per_notional_day;
  }
  const fx = (v: number | null | undefined, d = 2) => (v == null || Number.isNaN(v) ? DASH : v.toFixed(d));
  const pctOf = (v: number | null | undefined, d = 1) => (v == null || Number.isNaN(v) ? DASH : `${(v * 100).toFixed(d)}%`);
  // u5 (operator decision 2026-11-12: "four separate rows, plus a computed total").
  // Only ADDITIVE columns are totalled, and only from the bot's own per-category
  // figures — a plain sum, not a recomputed metric. Ratios (win rate, PF, avg R,
  // ret/time, utilisation, hold) and max drawdown do not add across books, and
  // the route publishes no total for them, so they stay "—". A category with no
  // figure (null) is left out of the sum, never counted as 0, and the cell carries
  // a visible "excl." badge naming it, so a partial sum never passes for a
  // complete one. No figure in any category → "—".
  type Sum = { v: number | null; missing: string[] };
  function sumOf(rows: PerfCategoryRow[], pick: (r: PerfCategoryRow) => number | null | undefined): Sum {
    let v = 0;
    const missing: string[] = [];
    for (const r of rows) {
      const x = pick(r);
      if (x == null || Number.isNaN(x)) missing.push(CAT_LABEL[r.category] ?? r.category);
      else v += x;
    }
    return { v: missing.length < rows.length ? v : null, missing };
  }
  const totals = $derived.by(() => {
    const rows = cats?.categories ?? [];
    return {
      n: rows.length,
      closed: sumOf(rows, (r) => r.n_closed),
      pnl: sumOf(rows, pnlHead),
      notMeasured: sumOf(rows, (r) => r.not_measured_usd),
      fees: sumOf(rows, (r) => r.fees_usd),
      funding: sumOf(rows, (r) => r.funding_usd),
    };
  });
  const sumTitle = (s: Sum) =>
    s.v == null ? "no category has a figure" : s.missing.length ? `sum of the other rows; no figure for ${s.missing.join(", ")}` : "sum of the category rows above";
  const NOT_ADDITIVE = "not additive across books, and the bot publishes no total for it";
  const noCapital = $derived(
    (series?.series ?? []).filter((s) => s.start_capital_usd == null).map((s) => CAT_LABEL[s.category] ?? s.category),
  );
</script>

<div class="panel card">
  <div class="top">
    <div class="ph">By category</div>
    <Segmented options={WINDOWS} bind:value={win} />
    <label class="tog"><input type="checkbox" bind:checked={measuredOnly} /> Measured only</label>
  </div>

  {#if catErr}
    <div class="err">Couldn't load categories: <span class="mono">{catErr}</span></div>
  {:else if !cats}
    <div class="muted">Loading…</div>
  {:else if cats.read_state !== "measured"}
    <div class="err">Category table unavailable: <span class="mono">{cats.read_state ?? DASH}</span></div>
  {:else}
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th class="r">Closed</th>
            <th class="r" title={measuredOnly ? "Σ pnl over broker-MEASURED rows" : "Σ pnl over all rows with a pnl"}>Net P&L</th>
            <th class="r" title="Σ pnl over ESTIMATED + FABRICATED + UNVERIFIED rows — shown beside, never folded in">Not measured</th>
            <th class="r" title="wins ÷ priced closes">Win rate</th>
            <th class="r" title="mean pnl ÷ entry risk over R-graded rows">Avg R</th>
            <th class="r" title="Σ wins ÷ |Σ losses|; — when there are no losses">PF</th>
            <th class="r" title="Return on time in trade: Σ net P&L ÷ Σ(|qty × entry| × hold days), bps per notional-day (ESTIMATED)">Ret/time (bps/nd)</th>
            <th class="r" title="Gross notional-days ÷ equity-days (ESTIMATED). May exceed 100% (leverage).">Capital util.</th>
            <th class="r">Avg hold (d)</th>
            <th class="r">Max DD</th>
            <th class="r">Fees</th>
            <th class="r">Funding</th>
          </tr>
        </thead>
        <tbody>
          {#each cats.categories ?? [] as r (r.category)}
            <tr title={(r.accounts ?? []).length ? `accounts: ${(r.accounts ?? []).join(", ")}` : "no accounts in this category"}>
              <td class="sym">{CAT_LABEL[r.category] ?? r.category}{#if r.read_state && r.read_state !== "measured"} <span class="muted small">({r.read_state})</span>{/if}</td>
              <td class="r mono">{num(r.n_closed)}</td>
              <td class="r mono {signClass(pnlHead(r))}">{money(pnlHead(r), { sign: true })}</td>
              <td class="r mono muted" title={`${num(r.n_not_measured)} row(s)`}>{money(r.not_measured_usd, { sign: true })}</td>
              <td class="r mono" title={`over ${num(r.n_priced)} priced close(s)`}>{pctOf(r.win_rate)}</td>
              <td class="r mono {signClass(r.avg_realised_r)}" title={`over ${num(r.n_r_graded)} R-graded row(s)`}>
                {fx(r.avg_realised_r, 2)}{#if r.r_insufficient_n && r.avg_realised_r != null} <span class="badge" title="fewer than 10 R-graded rows">n&lt;10</span>{/if}
              </td>
              <td class="r mono">{fx(r.profit_factor, 2)}</td>
              <td class="r mono {signClass(rot(r))}" title={rot(r) == null ? "" : `annualised ≈ ${((rot(r) ?? 0) * 365 / 100).toFixed(1)}% of notional · all rows: ${fx(r.return_on_time_in_trade_all_rows_bps_per_notional_day, 1)}`}>{fx(rot(r), 1)}</td>
              <td class="r mono" title={r.capital_utilisation == null ? (r.capital_utilisation_read_state ?? "") : "ESTIMATED"}>{pctOf(r.capital_utilisation, 0)}</td>
              <td class="r mono">{fx(r.avg_hold_days, 2)}</td>
              <td class="r mono">{money(r.max_drawdown_usd)}</td>
              <td class="r mono" title={`${num(r.n_fees)} fee record(s)`}>{money(r.fees_usd)}</td>
              <td class="r mono" title={`${num(r.n_funding)} funding record(s)`}>{money(r.funding_usd)}</td>
            </tr>
          {/each}
        </tbody>
        {#if totals.n > 1}
          <tfoot>
            <tr class="total">
              <td class="sym" title="sum of the {totals.n} category rows; accounts outside every category are not included">Total</td>
              <td class="r mono" title={sumTitle(totals.closed)}>{num(totals.closed.v)}{#if totals.closed.v != null && totals.closed.missing.length} <span class="badge">excl. {totals.closed.missing.length}</span>{/if}</td>
              <td class="r mono {signClass(totals.pnl.v)}" title={sumTitle(totals.pnl)}>{money(totals.pnl.v, { sign: true })}{#if totals.pnl.v != null && totals.pnl.missing.length} <span class="badge">excl. {totals.pnl.missing.length}</span>{/if}</td>
              <td class="r mono muted" title={sumTitle(totals.notMeasured)}>{money(totals.notMeasured.v, { sign: true })}{#if totals.notMeasured.v != null && totals.notMeasured.missing.length} <span class="badge">excl. {totals.notMeasured.missing.length}</span>{/if}</td>
              <!-- win rate · avg R · PF · ret/time · utilisation · avg hold · max DD -->
              {#each Array(7) as _, i (i)}<td class="r mono muted" title={NOT_ADDITIVE}>{DASH}</td>{/each}
              <td class="r mono" title={sumTitle(totals.fees)}>{money(totals.fees.v)}{#if totals.fees.v != null && totals.fees.missing.length} <span class="badge">excl. {totals.fees.missing.length}</span>{/if}</td>
              <td class="r mono" title={sumTitle(totals.funding)}>{money(totals.funding.v)}{#if totals.funding.v != null && totals.funding.missing.length} <span class="badge">excl. {totals.funding.missing.length}</span>{/if}</td>
            </tr>
          </tfoot>
        {/if}
      </table>
    </div>
    <div class="muted small foot">
      Window {cats.population?.window ?? DASH}{cats.population?.since ? ` (since ${cats.population.since.slice(0, 10)})` : ""}
      · {num(cats.population?.n_closed)} closed
      · {num(cats.population?.rows_excluded_null_pnl)} excluded for null P&L
      · also excluded: {cats.population?.also_excluded ?? DASH}
      {#if (cats.excluded ?? []).length} · accounts outside every category: {(cats.excluded ?? []).map((e) => `${e.account_id} (${e.reason})`).join(", ")}{/if}
    </div>
  {/if}

  <div class="sub">
    <div class="ph2">Cumulative P&L</div>
    <div class="filters">
      {#each Object.keys(CAT_LABEL) as c (c)}
        <label class="tog"><input type="checkbox" bind:checked={picked[c]} /> {CAT_LABEL[c]}</label>
      {/each}
      <select bind:value={assetClass} aria-label="Asset class">
        {#each ASSET_CLASSES as a (a)}<option value={a}>{a || "All asset classes"}</option>{/each}
      </select>
      <input placeholder="Strategy" bind:value={strategy} onkeydown={(e) => e.key === "Enter" && (applied = { strategy: strategy.trim(), symbol: symbol.trim() })} />
      <input placeholder="Symbol" bind:value={symbol} onkeydown={(e) => e.key === "Enter" && (applied = { strategy: strategy.trim(), symbol: symbol.trim() })} />
      <button onclick={() => (applied = { strategy: strategy.trim(), symbol: symbol.trim() })}>Apply</button>
      <Segmented options={[{ value: "pct", label: "% of capital" }, { value: "usd", label: "$" }]} bind:value={unit} />
    </div>
    {#if seriesErr}
      <div class="err">Couldn't load the P&L series: <span class="mono">{seriesErr}</span></div>
    {:else if !series}
      <div class="muted">Loading…</div>
    {:else if series.read_state && series.read_state !== "measured"}
      <div class="err">P&L series unavailable: <span class="mono">{series.read_state}</span></div>
    {:else}
      <PnlSeriesChart data={series} {unit} labels={CAT_LABEL} showAllRows={measuredOnly} />
      <div class="muted small foot">
        {series.bucket === "trade" ? "One point per closed trade" : "One point per UTC day"}
        · {num(series.population?.n_rows)} row(s)
        {#if measuredOnly} · dotted line = all rows incl. not-measured{/if}
        {#if unit === "pct" && noCapital.length} · no capital record, shown in $ mode only: {noCapital.join(", ")}{/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .card { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .top, .filters { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .ph { font-weight: 600; margin-right: auto; }
  .ph2 { font-weight: 600; margin: 4px 0; }
  .sub { border-top: 1px solid var(--border); padding-top: 10px; display: flex; flex-direction: column; gap: 8px; }
  .tog { display: inline-flex; gap: 4px; align-items: center; font-size: 13px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 7px 9px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  tfoot .total td { border-top: 2px solid var(--border); font-weight: 600; }
  .sym { font-weight: 600; }
  .small { font-size: 12px; }
  .foot { line-height: 1.5; }
  .err { color: var(--neg); }
  .badge { font-size: 10px; padding: 1px 5px; border-radius: 6px; background: #d4a01733; color: #d4a017; }
  select, input:not([type="checkbox"]), button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
  input:not([type="checkbox"]) { width: 110px; }
  button { cursor: pointer; }
</style>
