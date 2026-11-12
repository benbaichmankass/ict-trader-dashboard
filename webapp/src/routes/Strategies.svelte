<script lang="ts">
  // Strategies table (UI workplan §7 UI-MODELS-STRATEGIES-TABLES, bot #24924).
  // One sortable row per strategy from /api/bot/strategies, with the DERIVED
  // three-way status (testing | production | inactive — computed bot-side by
  // scripts/ops/strategy_status.py, never stored) and a status filter.
  //
  // ⚠️ Stats keys (fixed 2026-11-12): the bot's `stats` block is
  // {total_trades, resolved_trades, wins, losses, win_rate_pct, total_pnl,
  // avg_pnl_per_trade, exit_reasons}. This page used to read `stats.trades` /
  // `stats.winRate` / `stats.totalPnl`, keys with no writer, so every number
  // rendered "—". Not yet served bot-side (gaps filed by the backend lane):
  // the §4 per-strategy `perf` block and the TP-doctrine column.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, num, pct, signClass, DASH } from "../lib/format";
  import StatusDot from "../components/StatusDot.svelte";

  interface Row {
    name: string;
    status: string | null;
    statusReadState: string | null;
    running: boolean;
    loaded: boolean;
    execution: string | null;
    timeframe: string | null;
    symbols: string[];
    accounts: string[];
    books: string[];
    trades: number | null;
    winRatePct: number | null;
    totalPnl: number | null;
    avgPnl: number | null;
    exitReasons: Record<string, number>;
    pnlTip: string;
    short: string | null;
    how: string | null;
  }

  type SortKey = "status" | "name" | "execution" | "trades" | "winRatePct" | "totalPnl" | "avgPnl";
  const STATUS_ORDER: Record<string, number> = { production: 0, testing: 1, inactive: 2 };

  let rows = $state<Row[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let botRunning = $state<boolean | null>(null);
  let filter = $state<string>("all");
  let sortKey = $state<SortKey>("status");
  let asc = $state(true);
  let open = $state<string | null>(null);

  const numOrNull = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

  function normalize(raw: any): Row[] {
    const src = Array.isArray(raw) ? raw : raw?.strategies ?? [];
    const list: any[] = Array.isArray(src) ? src : Object.values(src ?? {});
    return list.map((s) => {
      const st = s.stats ?? {};
      return {
        name: s.name ?? s.id ?? DASH,
        status: s.status ?? null,
        statusReadState: s.status_read_state ?? null,
        running: !!(s.running ?? s.runtime?.running),
        loaded: !!(s.loaded ?? s.runtime?.loaded),
        execution: s.execution ?? null,
        timeframe: s.timeframe ?? null,
        symbols: Array.isArray(s.symbols) ? s.symbols : [],
        accounts: (s.accounts ?? []).map((a: any) => (typeof a === "string" ? a : a?.id)).filter(Boolean),
        books: Array.isArray(s.books) ? s.books : [],
        trades: numOrNull(st.total_trades),
        winRatePct: numOrNull(st.win_rate_pct),
        totalPnl: numOrNull(st.total_pnl),
        avgPnl: numOrNull(st.avg_pnl_per_trade),
        exitReasons: st.exit_reasons && typeof st.exit_reasons === "object" ? st.exit_reasons : {},
        pnlTip: st.pnlCoverage == null ? "" : `measured-only ${money(numOrNull(st.totalPnLMeasuredOnly), { sign: true })} over ${num(numOrNull(st.pnlMeasuredCount))} row(s) · estimated ${money(numOrNull(st.totalPnLEstimated), { sign: true })} over ${num(numOrNull(st.pnlEstimatedCount))} · coverage ${Math.round(st.pnlCoverage * 100)}%`,
        short: s.description?.short ?? null,
        how: s.description?.how_it_works ?? null,
      };
    });
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.strategies();
      botRunning = raw?.runtime?.bot_running ?? null;
      rows = normalize(raw);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function sortVal(r: Row, k: SortKey): number | string | null {
    if (k === "status") return r.status == null ? 9 : STATUS_ORDER[r.status] ?? 8;
    if (k === "name" || k === "execution") return (r[k] ?? "").toString().toLowerCase();
    if (k !== "trades" && !r.trades) return null; // a stat over 0 trades is not data: sort it with the nulls
    return r[k];
  }
  const counts = $derived(
    rows.reduce<Record<string, number>>((m, r) => ((m[r.status ?? "unknown"] = (m[r.status ?? "unknown"] ?? 0) + 1), m), {}),
  );
  const shown = $derived(
    rows
      .filter((r) => filter === "all" || (r.status ?? "unknown") === filter)
      .sort((a, b) => {
        const x = sortVal(a, sortKey), y = sortVal(b, sortKey);
        // nulls always last, whichever direction
        if (x == null && y == null) return a.name.localeCompare(b.name);
        if (x == null) return 1;
        if (y == null) return -1;
        const c = x < y ? -1 : x > y ? 1 : 0;
        return (asc ? c : -c) || a.name.localeCompare(b.name);
      }),
  );
  function sortBy(k: SortKey) {
    if (sortKey === k) asc = !asc;
    else { sortKey = k; asc = k === "status" || k === "name" || k === "execution"; }
  }
  const arrow = (k: SortKey) => (sortKey === k ? (asc ? " ▲" : " ▼") : "");

  function dot(r: Row): "pos" | "neg" | "warn" | "flat" {
    if (r.execution === "shadow") return "warn";
    if (r.running) return "pos";
    if (r.loaded) return "warn";
    return "flat";
  }
  function exitMix(m: Record<string, number>): string {
    const e = Object.entries(m).filter(([, n]) => typeof n === "number" && n > 0).sort((a, b) => b[1] - a[1]);
    return e.length ? e.slice(0, 3).map(([k, n]) => `${k} ${n}`).join(" · ") : DASH;
  }
</script>

<section>
  <div class="head">
    <h2>Strategies</h2>
    {#if botRunning != null}
      <div class="run"><StatusDot status={botRunning ? "pos" : "neg"} label={botRunning ? "pipeline running" : "pipeline stopped"} /></div>
    {/if}
  </div>

  {#if error}
    <div class="err panel">Couldn't load strategies: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    <div class="filters">
      {#each ["all", "production", "testing", "inactive"] as f (f)}
        <button class:on={filter === f} onclick={() => (filter = f)}>
          {f === "all" ? "All" : f[0].toUpperCase() + f.slice(1)} · {f === "all" ? rows.length : counts[f] ?? 0}
        </button>
      {/each}
      {#if counts.unknown}<span class="muted small">{counts.unknown} without a status (older bot / unreadable)</span>{/if}
    </div>
    <div class="panel scroll">
      <table>
        <thead>
          <tr>
            <th></th>
            <th class="s" onclick={() => sortBy("status")} title="testing = general paper (Stage 1) · production = real money + its mirror · inactive = retired by record. Derived by strategy_status.py.">Status{arrow("status")}</th>
            <th class="s" onclick={() => sortBy("name")}>Strategy{arrow("name")}</th>
            <th class="s" onclick={() => sortBy("execution")}>Exec{arrow("execution")}</th>
            <th>TF</th>
            <th>Symbols</th>
            <th>Accounts</th>
            <th class="r s" onclick={() => sortBy("trades")}>Trades{arrow("trades")}</th>
            <th class="r s" onclick={() => sortBy("winRatePct")}>Win rate{arrow("winRatePct")}</th>
            <th class="r s" onclick={() => sortBy("totalPnl")}>Net P&L{arrow("totalPnl")}</th>
            <th class="r s" onclick={() => sortBy("avgPnl")}>Avg / trade{arrow("avgPnl")}</th>
            <th>Exit mix</th>
          </tr>
        </thead>
        <tbody>
          {#each shown as r (r.name)}
            <tr class="row" onclick={() => (open = open === r.name ? null : r.name)}>
              <td><StatusDot status={dot(r)} /></td>
              <td><span class="badge {r.status ?? 'none'}" title={r.statusReadState ?? ""}>{r.status ?? DASH}</span></td>
              <td>
                <div class="sym">{r.name}</div>
                {#if r.short}<div class="sub muted">{r.short}</div>{/if}
              </td>
              <td class="muted">{r.execution ?? DASH}</td>
              <td class="muted">{r.timeframe ?? DASH}</td>
              <td class="muted small">{r.symbols.length ? r.symbols.slice(0, 4).join(", ") + (r.symbols.length > 4 ? ` +${r.symbols.length - 4}` : "") : DASH}</td>
              <td class="muted small">{r.accounts.length ? r.accounts.join(", ") : DASH}</td>
              <td class="r mono">{num(r.trades)}</td>
              <td class="r mono">{r.trades ? pct(r.winRatePct) : DASH}</td>
              <td class="r mono {signClass(r.totalPnl)}" title={r.pnlTip}>{r.trades ? money(r.totalPnl, { sign: true }) : DASH}</td>
              <td class="r mono {signClass(r.avgPnl)}">{r.trades ? money(r.avgPnl, { sign: true }) : DASH}</td>
              <td class="muted small">{exitMix(r.exitReasons)}</td>
            </tr>
            {#if open === r.name && r.how}
              <tr><td></td><td colspan="11" class="how muted">{r.how}</td></tr>
            {/if}
          {/each}
          {#if shown.length === 0}
            <tr><td colspan="12" class="muted pad">No strategies in this filter.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
    <div class="muted small">{rows.length} strategies from /api/bot/strategies. Win rate and P&L show "—" for a strategy with no trades (a 0% win rate over 0 trades is not data). Click a row for how it works.</div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .filters button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; cursor: pointer; font-size: 13px; }
  .filters button.on { border-color: var(--accent); color: var(--accent); }
  .scroll { overflow-x: auto; padding: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; white-space: nowrap; }
  th.s { cursor: pointer; user-select: none; }
  tbody tr { border-bottom: 1px solid var(--border); }
  tr.row { cursor: pointer; }
  .r { text-align: right; white-space: nowrap; }
  .sym { font-weight: 600; }
  .sub { font-size: 12px; max-width: 320px; white-space: normal; }
  .small { font-size: 12px; }
  .how { font-size: 12px; white-space: normal; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); white-space: nowrap; }
  .badge.production { color: var(--pos); border-color: var(--pos); }
  .badge.testing { color: var(--accent); border-color: var(--accent); }
  .badge.inactive { color: var(--muted); }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
