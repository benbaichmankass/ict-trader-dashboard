<script lang="ts">
  import { onMount } from "svelte";
  import { api, type ClosedTrade } from "../lib/api";
  import { sinceFor, WINDOW_OPTIONS, FUNDING_OPTIONS } from "../lib/nav";
  import { portfolioPaperIds, isPortfolioPaperRow } from "../lib/funding";
  import { money, num, pct, signClass, DASH, agoFromIso } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  let funding = $state("real");
  let win = $state("7d");
  let rows = $state<ClosedTrade[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  // Set to the server's total-match count when a window has more rows than we
  // fetched (walked up to MAX_PAGES pages of PAGE_LIMIT each) — the bot caps
  // one page at 200 (le=200, trades_closed.py). null = nothing truncated.
  let truncatedAt = $state<number | null>(null);

  function classOf(t: ClosedTrade): string {
    const c = (t.accountClass ?? "").toLowerCase();
    if (c === "prop") return "prop";
    if (c === "paper") return "paper";
    return "real";
  }

  const PAGE_LIMIT = 200; // the bot's hard cap (le=200) on /api/bot/trades/closed
  const MAX_PAGES = 5; // bounds worst-case fetch cost for a very wide window (All)

  // Walks `offset` past the bot's 200-row page cap using the `X-Has-More`
  // header (trades_closed.py) rather than silently truncating a wide window.
  // Stops at MAX_PAGES and reports the server's total so the UI can say so.
  async function fetchAllClosed(since: string | undefined, includePaper: boolean) {
    let offset = 0;
    let all: ClosedTrade[] = [];
    let total = 0;
    for (let page = 0; page < MAX_PAGES; page++) {
      const { rows: pageRows, total: pageTotal, hasMore } = await api.closedTradesPage({
        since,
        includePaper,
        limit: PAGE_LIMIT,
        offset,
      });
      all = all.concat(pageRows);
      total = pageTotal;
      offset += pageRows.length;
      if (!hasMore || pageRows.length === 0) return { rows: all, truncated: null as number | null };
    }
    return { rows: all, truncated: total };
  }

  async function load() {
    loading = true;
    error = null;
    truncatedAt = null;
    try {
      // Prop closed trades come from the prop journal, not /trades/closed — not
      // wired into this SPA screen yet, so show an empty-with-note rather than
      // mislabel real-money rows as prop.
      if (funding === "prop") {
        rows = [];
        return;
      }
      // "Paper" scopes to the live-portfolio-mirror books (paper_role: portfolio)
      // — the soak roster stays on the Accounts page only. Resolve the portfolio
      // ids from /config; a config read failure falls back to ALL paper so the
      // view is never stranded. S-PAPER-PORTFOLIO.
      const [{ rows: raw, truncated }, cfg] = await Promise.all([
        fetchAllClosed(sinceFor(win), funding === "paper"),
        funding === "paper" ? api.config().catch(() => null) : Promise.resolve(null),
      ]);
      truncatedAt = truncated;
      if (funding === "paper") {
        const ids = portfolioPaperIds(cfg);
        rows = (raw ?? []).filter((t) => isPortfolioPaperRow(t, ids));
      } else {
        rows = (raw ?? []).filter((t) => classOf(t) === funding);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }

  // Re-load whenever funding or window changes.
  $effect(() => {
    funding;
    win;
    load();
  });
  onMount(load);

  const stats = $derived.by(() => {
    const resolved = rows.filter((r) => r.pnl != null);
    const wins = resolved.filter((r) => (r.pnl ?? 0) > 0).length;
    const total = resolved.reduce((a, r) => a + (r.pnl ?? 0), 0);
    return {
      count: rows.length,
      resolved: resolved.length,
      winRate: resolved.length ? (wins / resolved.length) * 100 : null,
      total: resolved.length ? total : null,
    };
  });

  // PnL provenance (bot P0.3): flag rows whose realized P&L is NOT a broker
  // measurement so manufactured money never reads identically to truth.
  function provMark(t: ClosedTrade): string {
    const p = (t.pnlProvenance ?? "").toLowerCase();
    if (p === "fabricated") return "⚠";
    if (p === "unverified") return "?";
    return "";
  }
  const untrusted = $derived(
    rows.filter((r) => ["fabricated", "unverified"].includes((r.pnlProvenance ?? "").toLowerCase())).length,
  );
  const graded = $derived(rows.filter((r) => r.pnlProvenance != null).length);

  function dirLabel(t: ClosedTrade): string {
    const d = (t.direction ?? t.side ?? "").toLowerCase();
    if (d === "sell" || d === "short") return "SHORT";
    if (d === "buy" || d === "long") return "LONG";
    return DASH;
  }
</script>

<section>
  <div class="head">
    <h2>Trades</h2>
    <div class="controls">
      <Segmented options={FUNDING_OPTIONS} bind:value={funding} />
      <Segmented options={WINDOW_OPTIONS} bind:value={win} />
    </div>
  </div>

  <div class="summary">
    <div class="s"><span class="muted">Closed</span> <b class="mono">{num(stats.count)}</b></div>
    <div class="s"><span class="muted">Win rate</span> <b class="mono">{pct(stats.winRate)}</b></div>
    <div class="s"><span class="muted">Net P&L</span> <b class="mono {signClass(stats.total)}">{money(stats.total, { sign: true })}</b></div>
  </div>

  {#if untrusted > 0}
    <div class="muted caveat">⚠ {untrusted} of {graded} graded trade(s) carry an unmeasured realized P&L (⚠ mark-substituted / ? unrecorded) — estimates, not broker truth.</div>
  {/if}

  {#if truncatedAt != null}
    <div class="muted caveat">Showing the latest {num(rows.length)} of {num(truncatedAt)} closed trades matching this window — narrow the window or funding filter to see the rest.</div>
  {/if}

  {#if error}
    <div class="err panel">Couldn't load trades: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if rows.length === 0}
    <div class="muted pad">
      {funding === "prop" ? "Prop closed trades come from the prop journal (Prop tab) — not on this screen yet." : "No closed trades in this window."}
    </div>
  {:else}
    <div class="panel scroll">
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Dir</th><th>Strategy</th><th class="r">Entry</th><th class="r">Exit</th><th class="r">P&L</th><th>Closed</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as t (t.id ?? `${t.symbol}-${t.closedAt}`)}
            <tr>
              <td class="sym">{t.symbol}</td>
              <td class={dirLabel(t) === "SHORT" ? "neg" : "pos"}>{dirLabel(t)}</td>
              <td class="muted">{t.strategy ?? DASH}</td>
              <td class="r mono">{money(t.entryPrice)}</td>
              <td class="r mono">{money(t.exitPrice)}</td>
              <td class="r mono {signClass(t.pnl)}" title={t.pnlProvenance ? `PnL provenance: ${t.pnlProvenance}` : undefined}>{money(t.pnl, { sign: true })}{#if provMark(t)}<sup class="prov">{provMark(t)}</sup>{/if}</td>
              <td class="muted">{agoFromIso(t.closedAt)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  h2 { margin: 0; font-size: 18px; }
  .controls { display: flex; gap: 8px; flex-wrap: wrap; }
  .summary { display: flex; gap: 20px; flex-wrap: wrap; }
  .s { font-size: 13px; }
  .s b { font-size: 16px; margin-left: 4px; }
  .scroll { overflow-x: auto; padding: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .prov { color: var(--warn, #d97706); margin-left: 2px; }
  .caveat { font-size: 12px; margin: 4px 0 8px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
