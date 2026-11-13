<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type BotStats, type Performance, type Position, type ClosedTrade } from "../lib/api";
  import { FUNDING_OPTIONS, DAY_SNAPS, sinceDays, perfWindowFor, gotoDetail } from "../lib/nav";
  import { accountBooks, bookOfRow, isPaperBook, normalizeFunding, countUnassigned, FUNDING_BOOKS, FUNDING_LABEL, type FundingBook } from "../lib/funding";
  import ClosedTradeCard from "../components/ClosedTradeCard.svelte";
  import { closedFills, fillClosedAt, fillProvenance } from "../lib/propPnl";
  import { money, signClass, DASH, agoFromIso } from "../lib/format";
  import ExecSummary from "../components/ExecSummary.svelte";
  import EquityChart from "../components/EquityChart.svelte";
  import TradeApprovals from "../components/TradeApprovals.svelte";
  import { acquireStream, onStreamFrame, streamStatus, isStreamLive } from "../lib/stream";
  import HealthBar from "../components/HealthBar.svelte";

  // One funding toggle per tab — four books, never blended: Live money · Prop ·
  // Paper portfolio · Paper testing (lib/funding.ts) — + the 24h/7d/30d/All
  // window, at the top. normalizeFunding migrates an old stored "paper" choice.
  // The selected book is driven by clicking an Executive Summary book card
  // (default live money); the days-back slider replaces the window buttons.
  let funding = $state<FundingBook>(normalizeFunding("real"));
  let days = $state(30);
  // /performance + /prop/overview serve only 24h|7d|30d|all → the effective window.
  const win = $derived(perfWindowFor(days));
  // Last-closed-trades book filter: multi-select, any combination.
  let closedBooks = $state<FundingBook[]>(["real"]);
  function toggleClosedBook(b: FundingBook) {
    closedBooks = closedBooks.includes(b) ? closedBooks.filter((x) => x !== b) : [...closedBooks, b];
  }
  // Slider position = index into DAY_SNAPS (snap points); the days value shown.
  const snapIdx = $derived(Math.max(0, DAY_SNAPS.indexOf(days)));

  let stats = $state<BotStats | null>(null);
  let perf = $state<Performance | null>(null);
  let positions = $state<Position[]>([]);
  let balances = $state<any>(null);
  let config = $state<any>(null);
  let strategies = $state<any>(null);
  let signals = $state<any[]>([]);
  let closedTrades = $state<ClosedTrade[]>([]);
  let news = $state<any>(null);
  let propOverview = $state<any>(null); // /api/bot/prop/overview (Prop book only)
  let workSnap = $state<any>(null); // /api/bot/work/snapshot (UI-UPGRADE-1 item 2)
  let workSnapError = $state<string | null>(null);
  let ltrPending = $state(0);
  // Work "testing queue" (GET /api/bot/work/testing-queue, bot #25231); null until it answers 200.
  let tq = $state<any>(null);
  let tqState = $state("loading"); // LTR trade decisions waiting (bound out of TradeApprovals)
  let pnl30 = $state<Array<{ date?: string; pnl?: number | null }>>([]);
  let apiError = $state<string | null>(null);

  // "In flight now": open rows a Claude lane is working (state in_flight, lane set).
  const inFlight = $derived(((workSnap?.openNow ?? []) as any[]).filter((r) => r?.state === "in_flight" && r?.lane));

  // News banner: the most recent news-layer decision + its strongest headline.
  const latestNews = $derived.by(() => {
    const recs = ((news?.records ?? []) as any[]).filter((r) => r?.ts);
    if (!recs.length) return null;
    return recs.reduce((a, b) => (Date.parse(b.ts) > Date.parse(a.ts) ? b : a));
  });
  const newsHeadline = $derived.by(() => {
    const items = ((latestNews?.top_items ?? []) as any[]).filter((it) => it?.headline);
    return items.length ? items.reduce((a, b) => (Math.abs(b.score ?? 0) > Math.abs(a.score ?? 0) ? b : a)) : null;
  });

  // 30-day realised-P&L → cumulative points for the sparkline.
  const pnlPoints = $derived.by(() => {
    let cum = 0;
    return pnl30
      .filter((d) => d?.date)
      .map((d) => ({ t: d.date as string, cum: (cum += Number(d.pnl ?? 0)) }));
  });

  let pollTimer: ReturnType<typeof setInterval> | null = null;
  // T2 (UI-TRADING-PUSH): positions follow the bot's push stream. positionsAt = when the
  // REST /positions snapshot (incl. broker uPnL) was last read, shown on the page so a
  // pushed view never looks fresher than it is.
  let positionsAt = $state<number | null>(null);
  let posTimer: ReturnType<typeof setTimeout> | null = null;
  function refreshPositionsSoon() {
    if (posTimer) return;
    posTimer = setTimeout(() => {
      posTimer = null;
      api.positions().then((v) => { positions = v; positionsAt = Date.now(); }).catch(() => {});
    }, 400);
  }
  let refreshing = $state(false);
  let lastUpdated = $state<number | null>(null);

  // The exec summary needs the same inputs Streamlit's _render_exec_summary uses:
  // stats + windowed performance + REST positions + tracked balances (equity) +
  // config (account_class map) + strategies (tick age). Positions come via REST
  // here so the open-trades table/count is populated even when the market
  // WebSocket can't connect (sandbox, or a flaky mobile network) — the WS's
  // onPositions still overwrites this with the live snapshot when it's up.
  // UI-UPGRADE-1 item 1. This used to be ONE Promise.all over nine calls, so
  // nothing rendered until the slowest returned — measured 2026-10-11:
  // /positions 5-12 s cold, /signals ~3.3 s, the other seven 0.3-0.9 s. Each
  // call now assigns its own slice the moment it lands, the previous value stays
  // on screen while a refresh is in flight (show-stale-then-refresh), and a
  // failed slice keeps its last good value instead of blanking the page.
  // `apiError` is raised only when the core reads (stats + positions) fail.
  let inflight = 0;
  async function poll() {
    if (inflight > 0) return; // never stack polls behind a slow call
    inflight = 1;
    const slices: Array<Promise<unknown>> = [
      api.stats().then((v) => { stats = v; }),
      (() => { const w = win; return api.performance(w).then((v) => { if (w === win) perf = v; }); })(),
      // T2: while the push stream is live, /positions is re-read ONLY on its frames
      // (see onStreamFrame below) — this poll reads it only as the labelled fallback.
      isStreamLive() ? Promise.resolve() : api.positions().then((v) => { positions = v; positionsAt = Date.now(); }),
      api.balances().then((v) => { balances = v; }),
      api.config().then((v) => { config = v; }),
      api.strategies().then((v) => { strategies = v; }),
      api.signals().then((sig: any) => {
        signals = Array.isArray(sig) ? sig : (sig?.signals ?? sig?.records ?? []);
      }),
      api.closedTrades({ includePaper: true, limit: 100 }).then((v) => {
        closedTrades = Array.isArray(v) ? v : [];
      }),
      // Prop lives in its own journal; a failure here must not blank the rest.
      (() => { const w = win; return api.propOverview(w).then((v) => { if (w === win) propOverview = v; }); })(),
      api.testingQueue().then((r) => { if (r.status === 200 && r.body) { tq = r.body; tqState = "read"; } else { tq = null; tqState = String(r.status); } })
        .catch(() => { tq = null; tqState = "error"; }),
      api.workSnapshot().then((v) => { workSnap = v; workSnapError = null; })
        .catch((e) => { workSnapError = e instanceof Error ? e.message : String(e); throw e; }),
      // Glance-card + sparkline data — each degrades to its own empty state.
      api.news(8).then((v) => { news = v; }),
      api.pnlHistory(30).then((h) => { pnl30 = Array.isArray(h) ? h : []; }),
    ];
    const core = Promise.all([slices[0], slices[2]]);
    core.then(() => { apiError = null; lastUpdated = Date.now(); })
      .catch((e) => { apiError = e instanceof Error ? e.message : String(e); });
    try {
      await Promise.allSettled(slices);
    } finally {
      inflight = 0;
    }
  }

  // Refresh: re-fetch this view's data now (every fetch already goes through
  // api.ts — there is no client cache to bypass) and reset the closed-trades
  // "Show more" paging to its first batch, WITHOUT touching the user's
  // funding/window selection.
  async function refresh() {
    refreshing = true;
    try {
      await Promise.all([poll(), loadRecentClosed()]);
    } finally {
      refreshing = false;
    }
  }

  // Window change → re-fetch ONLY the windowed reads, at once. Not via poll():
  // its in-flight guard would drop the tap while a slow call is outstanding.
  // A late answer for a window the user has already left is discarded.
  $effect(() => {
    const w = win;
    api.performance(w).then((v) => { if (w === win) perf = v; }).catch(() => {});
    api.propOverview(w).then((v) => { if (w === win) propOverview = v; }).catch(() => {});
  });

  // account id → book, from /config (account_class + paper_role).
  const books = $derived(accountBooks(config));
  const unassignedPaper = $derived(isPaperBook(funding) ? countUnassigned(positions, books) : 0);


  // Last closed trades under the open-positions table — same funding scope as
  // the rest of this page. Overview has no organize-by/focus control (that's
  // Streamlit-only, not ported to the SPA), so funding + window is the whole
  // scope. Paginated independently of the flat `closedTrades` fetch above
  // (which feeds the chart's symClosed overlay and isn't window-scoped): a
  // "Load more" here should pull the NEXT server batch, not just reveal more
  // of an already-fetched flat 100, so this makes its own paged requests.
  function dirLabel(t: ClosedTrade): string {
    const d = (t.direction ?? t.side ?? "").toLowerCase();
    if (d === "sell" || d === "short") return "SHORT";
    if (d === "buy" || d === "long") return "LONG";
    return DASH;
  }
  function rowKey(t: ClosedTrade): string {
    return String(t.id ?? `${t.symbol}-${t.closedAt}`);
  }

  // Expanded closed-trade cards (UI-REDESIGN-2026-11 addendum 2) — several at once.
  let openClosed = $state<Set<string>>(new Set());
  function toggleClosed(k: string) {
    const n = new Set(openClosed);
    if (n.has(k)) n.delete(k); else n.add(k);
    openClosed = n;
  }
  const RECENT_BATCH = 10; // "Show more" fetches the next server batch; // well within the bot's 200-row page cap (trades_closed.py)

  let recentClosedRows = $state<ClosedTrade[]>([]);
  let recentClosedLoading = $state(true);
  let recentClosedLoadingMore = $state(false);
  let recentClosedHasMore = $state(false);
  let recentClosedError = $state<string | null>(null);
  let recentClosedOffset = 0; // server-side offset consumed so far; not reactive

  async function loadRecentClosedPage(reset: boolean) {
    if (reset) {
      recentClosedOffset = 0;
      recentClosedRows = [];
      recentClosedHasMore = false;
    }
    // Prop closed trades come from the prop journal, not /trades/closed — not
    // wired into this fetch (a visible note says so when Prop is ticked).
    const sel = [...closedBooks];
    if (!sel.some((b) => b !== "prop")) {
      recentClosedHasMore = false;
      return;
    }
    const [{ rows: pageRaw, hasMore }, cfg] = await Promise.all([
      api.closedTradesPage({
        since: sinceDays(days),
        includePaper: sel.some(isPaperBook),
        limit: RECENT_BATCH,
        offset: recentClosedOffset,
      }),
      api.config().catch(() => null),
    ]);
    recentClosedOffset += pageRaw.length;
    recentClosedHasMore = hasMore;
    const cfgBooks = accountBooks(cfg);
    const filtered = pageRaw.filter((t) => (sel as string[]).includes(bookOfRow(t, cfgBooks)));
    if (reset) {
      recentClosedRows = filtered;
    } else {
      // De-dupe by id — rows can shift between pages between "Load more" clicks.
      const seen = new Set(recentClosedRows.map(rowKey));
      recentClosedRows = [...recentClosedRows, ...filtered.filter((t) => !seen.has(rowKey(t)))];
    }
  }

  async function loadRecentClosed() {
    recentClosedLoading = true;
    recentClosedError = null;
    try {
      await loadRecentClosedPage(true);
    } catch (e) {
      recentClosedError = e instanceof Error ? e.message : String(e);
      recentClosedRows = [];
    } finally {
      recentClosedLoading = false;
    }
  }

  async function loadMoreRecentClosed() {
    if (recentClosedLoadingMore || recentClosedLoading || !recentClosedHasMore) return;
    recentClosedLoadingMore = true;
    try {
      await loadRecentClosedPage(false);
    } catch (e) {
      recentClosedError = e instanceof Error ? e.message : String(e);
    } finally {
      recentClosedLoadingMore = false;
    }
  }

  // Prop closed trades (spec: the Last-closed filter covers live / prop / paper
  // portfolio / paper testing). Prop is not in /trades/closed — it lives in the
  // prop journal — so when Prop is ticked a separate sub-list reads /prop/fills
  // (the same closedFills / fillClosedAt / fillProvenance helpers as the Prop
  // tab), keeps the days-back window, newest first, 10 at a time.
  const PROP_FILLS_LIMIT = 200;
  const PROP_BATCH = 10;
  let propFillsRaw = $state<any[] | null>(null);
  let propClosedErr = $state<string | null>(null);
  let propShown = $state(PROP_BATCH);
  $effect(() => {
    const on = closedBooks.includes("prop");
    days;
    propShown = PROP_BATCH;
    if (!on) return;
    propClosedErr = null;
    api.propFills(PROP_FILLS_LIMIT)
      .then((r) => { propFillsRaw = r?.fills ?? []; })
      .catch((e) => { propFillsRaw = null; propClosedErr = e instanceof Error ? e.message : String(e); });
  });
  const propClosedRows = $derived.by(() => {
    if (!propFillsRaw) return [];
    const cut = sinceDays(days);
    return closedFills(propFillsRaw)
      .filter((f) => { const at = fillClosedAt(f); return at != null && at >= cut; })
      .sort((a, b) => String(fillClosedAt(b)).localeCompare(String(fillClosedAt(a))));
  });
  // The journal read is the newest PROP_FILLS_LIMIT fills; if it came back full,
  // older closes inside the window may not have been read — say so.
  const propReadFull = $derived((propFillsRaw?.length ?? 0) >= PROP_FILLS_LIMIT);

  // Reset to the first batch whenever the book filter or days-back changes.
  $effect(() => {
    closedBooks;
    days;
    loadRecentClosed();
  });

  // The testing book has no /performance block (the bot serves `paper` = all
  // paper and `paperPortfolio`), so its windowed totals are computed here from
  // that window's closed trades — real counts, labelled with their sample size.
  let testingPerf = $state<{ totalPnl: number | null; winRate: number | null; profitFactor: number | null;
    totalTrades: number; sampled: boolean } | null>(null);
  $effect(() => {
    const w = win, d = days;
    if (funding !== "paper_testing") { testingPerf = null; return; }
    Promise.all([
      api.closedTradesPage({ since: sinceDays(d), includePaper: true, limit: 200 }),
      api.config().catch(() => null),
    ]).then(([{ rows, hasMore }, cfg]) => {
      if (w !== win || funding !== "paper_testing") return;
      const b = accountBooks(cfg);
      const mine = rows.filter((t) => bookOfRow(t, b) === "paper_testing" && t.pnl != null);
      const wins = mine.filter((t) => (t.pnl as number) > 0);
      const gain = wins.reduce((a, t) => a + (t.pnl as number), 0);
      const loss = mine.filter((t) => (t.pnl as number) < 0).reduce((a, t) => a - (t.pnl as number), 0);
      testingPerf = {
        totalPnl: mine.length ? mine.reduce((a, t) => a + (t.pnl as number), 0) : null,
        winRate: mine.length ? wins.length / mine.length : null,
        profitFactor: loss > 0 ? gain / loss : null,
        totalTrades: mine.length,
        sampled: hasMore,
      };
    }).catch(() => { if (w === win) testingPerf = null; });
  });

  let releaseStream: (() => void) | null = null;
  let offFrames: (() => void) | null = null;
  onMount(() => {
    releaseStream = acquireStream();
    offFrames = onStreamFrame((f) => {
      if (f.type === "resnapshot" || f.type === "position") refreshPositionsSoon();
      else if (f.type === "trade" && f.payload?.exit_price != null) refreshPositionsSoon(); // a close
      else if (f.type === "bracket" && f.payload?.trade_id != null) {
        // SL/TP moved: update that row in place (the chart's price lines follow).
        const id = String(f.payload.trade_id);
        positions = positions.map((p) => String(p.id) === id
          ? { ...p, stopLoss: f.payload.stop_loss ?? p.stopLoss, takeProfit: f.payload.take_profit_1 ?? p.takeProfit } : p);
      }
    });
    poll();
    // 15 s (was 30 s): /positions is now a server-side snapshot, so a poll is
    // cheap. Skipped while the tab is hidden; refreshed at once when it returns.
    pollTimer = setInterval(() => { if (!document.hidden) poll(); }, 15000);
    document.addEventListener("visibilitychange", onVisible);
  });
  function onVisible() {
    if (!document.hidden) poll();
  }
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    if (posTimer) clearTimeout(posTimer);
    offFrames?.(); releaseStream?.();
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisible);
  });

</script>

<section>
  <div class="head">
    <h2>Overview</h2>
  </div>

  <!-- UI-REDESIGN-2026-11 (1): health bar across the top, money path first. -->
  <HealthBar />

  <div class="controls">
    <label class="days">
      <span>Days back: <b>{days}</b></span>
      <input type="range" min="0" max={DAY_SNAPS.length - 1} step="1" value={snapIdx}
        oninput={(e) => (days = DAY_SNAPS[Number((e.currentTarget as HTMLInputElement).value)])}
        aria-label="Days back" />
      <span class="ticks">{#each DAY_SNAPS as d (d)}<span class:cur={d === days}>{d}</span>{/each}</span>
    </label>
    <button class="refresh" onclick={refresh} disabled={refreshing}>{refreshing ? "Refreshing…" : "↻ Refresh"}</button>
  </div>
  {#if lastUpdated}
    <div class="muted small">Updated {agoFromIso(new Date(lastUpdated).toISOString())}</div>
  {/if}
  <div class="muted small streamline">
    Open positions: {$streamStatus === "live" ? "pushed (live stream)" : $streamStatus === "connecting" ? "connecting to the live stream…" : "polling every 15 s (live stream down)"}
    · broker uPnL as of {positionsAt ? agoFromIso(new Date(positionsAt).toISOString()) : DASH}{$streamStatus === "live" ? " (re-read when the open set changes; crypto rows tick live from Bybit)" : ""}
  </div>

  {#if unassignedPaper > 0}
    <div class="muted small">{unassignedPaper} open paper position(s) can't be placed in either paper book (no account recorded, or /config unreadable) and are hidden.</div>
  {/if}

  {#if apiError}
    <div class="err panel">Couldn't reach the bot API: <span class="mono">{apiError}</span></div>
  {/if}

  <ExecSummary {stats} {perf} {positions} {balances} {config} {strategies} {funding} {win} {days} {propOverview} {testingPerf} onpick={(b) => (funding = b)} />

  <!-- UI-REDESIGN-2026-11 (4): the work queue as THREE cards — waiting on me ·
       in flight now (Claude lanes) · testing queue — plus the link to Work.
       Addendum 1: "waiting on me" also carries the LTR trade decisions (RED,
       Approve/Reject through the same state machine as Telegram). An unreadable
       source says "could not look", never an empty queue. -->
  <div class="panel workq">
    <div class="ph">Work queue <a class="wlink" href="#/Work">open Work →</a></div>
    <div class="wcards">
      <div class="wcard" class:hotcard={ltrPending > 0 || (workSnap?.waitingOnOperator ?? []).length > 0}>
        <div class="wh">⏳ Waiting on me · {ltrPending + (workSnap?.waitingOnOperator ?? []).length}</div>
        <TradeApprovals embedded bind:pendingCount={ltrPending} />
        <div class="wsub">Other asks</div>
        {#if workSnap && workSnap.present === false}
          <div class="err small">could not look: <span class="mono">{workSnap.reason ?? DASH}</span></div>
        {:else if !workSnap && workSnapError}
          <div class="err small">could not look: <span class="mono">{workSnapError}</span></div>
        {:else if !workSnap}
          <div class="muted small">Loading…</div>
        {:else}
          {#each workSnap.waitingOnOperator ?? [] as r (r.id)}
            <div class="wrow" title={r.title ?? ""}><span class="mono wid">{r.id}</span> {(r.asks ?? []).map((a: any) => a.what).filter(Boolean).join(" · ") || r.title}</div>
          {:else}
            <div class="muted small">Nothing else is blocked on you.</div>
          {/each}
        {/if}
      </div>
      <div class="wcard">
        <div class="wh">🛠 In flight now · {workSnap && workSnap.present !== false ? inFlight.length : DASH}</div>
        {#if !workSnap || workSnap.present === false}
          <div class="muted small">{workSnapError || workSnap?.present === false ? "could not look" : "Loading…"}</div>
        {:else}
          {#each inFlight as r (r.id)}
            <div class="wrow" title={r.title ?? ""}><span class="mono wid">{r.id}</span> <span class="muted">{r.owner ?? r.lane ?? DASH}</span></div>
          {:else}
            <div class="muted small">No Claude lane has a row in flight.</div>
          {/each}
        {/if}
      </div>
      <div class="wcard">
        <div class="wh">🧪 Testing queue · {tq && tq.read_state !== "could_not_look" && tq.n_running != null ? tq.n_running : DASH}</div>
        {#if !tq}
          <div class="muted small">{tqState === "loading" ? "Loading…" : "could not look — the testing-queue route is not deployed on the bot yet."}</div>
        {:else if tq.read_state === "could_not_look"}
          <div class="muted small">could not look — {(tq.sources ?? []).map((x: any) => x.detail).filter(Boolean).join("; ") || "no source readable"}</div>
        {:else}
          {#each tq.running ?? [] as r (r.id)}
            <div class="wrow" title={`${r.source ?? ""}${r.started_at ? ` · started ${r.started_at}` : ""}`}><span class="mono wid">{r.title ?? r.id}</span> <span class="muted">{r.infra ?? r.kind ?? DASH}{r.started_at ? ` · ${agoFromIso(r.started_at)}` : ""}</span></div>
          {:else}
            <div class="muted small">Nothing running on the ML/training infra.</div>
          {/each}
          {#if tq.read_state === "partial"}<div class="muted small">partial: {(tq.sources ?? []).filter((x: any) => x.read_state !== "read").map((x: any) => x.source).join(", ")} could not be read</div>{/if}
          <div class="muted small">Hugging Face jobs: {tq.hf_jobs?.read_state === "could_not_look" ? "could not look" : (tq.hf_jobs?.read_state ?? DASH)}</div>
        {/if}
      </div>
    </div>
  </div>

  <!-- UI-REDESIGN-2026-11 decision: news is ONE LINE — the latest news-layer
       decision's sentiment + one headline. Absent → "—". -->
  <div class="newsbar panel">
    <span class="nb-k">📰 News</span>
    {#if latestNews}
      <span class="nb-s {latestNews.decision === 'boost' ? 'pos' : latestNews.decision === 'reduce' || latestNews.veto ? 'neg' : 'muted'}">
        {latestNews.veto ? "veto" : (latestNews.decision ?? DASH)}{typeof latestNews.adjustment === "number" ? ` ${latestNews.adjustment >= 0 ? "+" : ""}${latestNews.adjustment.toFixed(2)}` : ""}
      </span>
      <span class="muted nb-m">{latestNews.symbol ?? DASH} · {agoFromIso(latestNews.ts)}</span>
      {#if newsHeadline}
        <span class="nb-h">{#if newsHeadline.url}<a href={newsHeadline.url} target="_blank" rel="noopener">{newsHeadline.headline}</a>{:else}{newsHeadline.headline}{/if}</span>
      {:else}
        <span class="muted">{DASH}</span>
      {/if}
    {:else}
      <span class="muted">{DASH}</span>
    {/if}
  </div>

  <div class="panel positions">
    <div class="ph">Last closed trades · last {days}d</div>
    <div class="chkrow" role="group" aria-label="Books to show">
      {#each FUNDING_BOOKS as b (b)}
        <label class="chk"><input type="checkbox" checked={closedBooks.includes(b)} onchange={() => toggleClosedBook(b)} /> {FUNDING_LABEL[b]}</label>
      {/each}
    </div>
    {#if closedBooks.includes("prop")}
      <div class="subh">Prop <span class="muted small">· from the prop journal (P&amp;L provenance per row; never blended with the other books)</span></div>
      {#if propClosedErr}
        <div class="err pad small">Couldn't load prop closed trades: <span class="mono">{propClosedErr}</span></div>
      {:else if propFillsRaw == null}
        <div class="muted pad small">Loading…</div>
      {:else if propClosedRows.length === 0}
        <div class="muted pad small">No prop trades closed in the last {days}d{propReadFull ? ` (only the newest ${PROP_FILLS_LIMIT} journal fills were read)` : ""}.</div>
      {:else}
        <div class="scroll">
          <table>
            <thead><tr><th>Symbol</th><th>Dir</th><th>Account</th><th class="r">P&amp;L</th><th>Provenance</th><th>Closed</th></tr></thead>
            <tbody>
              {#each propClosedRows.slice(0, propShown) as f, i (f.id ?? i)}
                {@const prov = fillProvenance(f)}
                {@const pk = `prop:${f.id ?? i}`}
                <tr class="click" class:openrow={openClosed.has(pk)} onclick={() => toggleClosed(pk)} tabindex="0" role="button" aria-expanded={openClosed.has(pk)}
                  onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleClosed(pk); } }}>
                  <td class="sym">{openClosed.has(pk) ? "▾" : "▸"} {f.symbol ?? DASH}</td>
                  <td class={/^(s|short)/i.test(String(f.direction ?? "")) ? "neg" : "pos"}>{String(f.direction ?? DASH).toUpperCase()}</td>
                  <td class="muted">{f.account_id ?? DASH}</td>
                  <td class="r mono {prov === 'MEASURED' ? signClass(f.pnl) : 'muted'}">{f.pnl == null ? DASH : money(f.pnl, { sign: true })}</td>
                  <td class="muted small">{prov === "UNKNOWN" ? DASH : prov}</td>
                  <td class="muted">{agoFromIso(fillClosedAt(f))}</td>
                </tr>
                {#if openClosed.has(pk)}
                  <tr class="cardrow"><td colspan="6">{#if typeof f.id === "number"}<ClosedTradeCard t={{ id: f.id, symbol: f.symbol, direction: f.direction, qty: f.qty, entryPrice: f.entry_price, exitPrice: f.exit_price, pnl: f.pnl, openedAt: f.opened_at, closedAt: fillClosedAt(f), account: f.account_id, closeReason: f.reason, pnlProvenance: prov } as any} propFillId={f.id} />{:else}<div class="muted small">No fill id on this row, so there is no snapshot to look up.</div>{/if}</td></tr>
                {/if}
              {/each}
            </tbody>
          </table>
        </div>
        {#if propClosedRows.length > propShown}
          <button class="more" onclick={() => (propShown += PROP_BATCH)}>Show more ({propClosedRows.length - propShown} more)</button>
        {/if}
        <div class="muted pad small">
          {propClosedRows.length} prop close(s) in the last {days}d{propReadFull ? ` · only the newest ${PROP_FILLS_LIMIT} journal fills were read, so older closes in this window may be missing` : ""} · click a row for its trade card.
        </div>
      {/if}
      {#if closedBooks.some((b) => b !== "prop")}<div class="subh">Other books</div>{/if}
    {/if}
    {#if recentClosedError}
      <div class="err pad">Couldn't load closed trades: <span class="mono">{recentClosedError}</span></div>
    {:else if closedBooks.length === 0}
      <div class="muted pad">Tick at least one book above.</div>
    {:else if !closedBooks.some((b) => b !== "prop")}
      <!-- only Prop ticked: the prop sub-list above is the whole answer -->
    {:else if recentClosedLoading}
      <div class="muted pad">Loading…</div>
    {:else if recentClosedRows.length === 0}
      <div class="muted pad">No closed trades in this window.</div>
    {:else}
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>Symbol</th><th>Dir</th><th>Strategy</th><th>Account</th><th class="r">P&L</th><th>Closed</th>
            </tr>
          </thead>
          <tbody>
            {#each recentClosedRows as t (rowKey(t))}
              {@const ck = rowKey(t)}
              <tr class="click" class:openrow={openClosed.has(ck)} onclick={() => toggleClosed(ck)} tabindex="0" role="button" aria-expanded={openClosed.has(ck)}
                onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleClosed(ck); } }}>
                <td class="sym">{openClosed.has(ck) ? "▾" : "▸"} {t.symbol}</td>
                <td class={dirLabel(t) === "SHORT" ? "neg" : "pos"}>{dirLabel(t)}</td>
                <td class="muted">{t.strategy ?? DASH}</td>
                <td class="muted">{t.account ?? DASH}</td>
                <td class="r mono {signClass(t.pnl)}">{money(t.pnl, { sign: true })}</td>
                <td class="muted">{agoFromIso(t.closedAt)}</td>
              </tr>
              {#if openClosed.has(ck)}
                <tr class="cardrow"><td colspan="6"><ClosedTradeCard {t} /></td></tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
      {#if recentClosedHasMore}
        <button class="more" onclick={loadMoreRecentClosed} disabled={recentClosedLoadingMore}>
          {recentClosedLoadingMore ? "Loading…" : "Load more"}
        </button>
      {:else}
        <div class="muted pad small">No more trades.</div>
      {/if}
      <button class="more" onclick={() => gotoDetail("Performance", "Performance")}>See all closed trades →</button>
    {/if}
  </div>

  {#if pnlPoints.length > 1}
    <div class="panel spark">
      <div class="ph">30-day realised P&amp;L (cumulative) · real money</div>
      <EquityChart points={pnlPoints} height={180} />
    </div>
  {/if}
</section>

<style>
  tr.click { cursor: pointer; }
  tr.click:hover, tr.openrow { background: var(--panel-2); }
  tr.cardrow > td { padding: 0; white-space: normal; }
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
  .controls {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  h2 {
    margin: 0;
    font-size: 18px;
  }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); } .muted { color: var(--muted); }
  .days { display: flex; flex-direction: column; gap: 2px; min-width: 240px; font-size: 13px; }
  .days input { width: 100%; }
  .ticks { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--muted); }
  .ticks .cur { color: var(--text); font-weight: 700; }
  .chkrow { display: flex; flex-wrap: wrap; gap: 4px 14px; padding: 0 12px 6px; font-size: 12.5px; }
  .chk { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
  .subh { font-weight: 600; font-size: 13px; margin: 10px 12px 4px; }
  .newsbar { display: flex; gap: 10px; align-items: baseline; padding: 8px 12px; font-size: 12.5px; white-space: nowrap; overflow: hidden; }
  .nb-k { font-weight: 600; }
  .nb-s { font-weight: 600; }
  .nb-h { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .nb-h a { color: var(--accent); text-decoration: none; }
  .nb-h a:hover { text-decoration: underline; }
  .spark { padding: 4px 12px 12px; }
  .spark .ph { padding: 12px 0 6px; }
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
  .scroll { overflow-x: auto; padding: 0 4px 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pad { padding: 16px 12px; }
  .small { font-size: 12px; }
  .more {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: none;
    border-top: 1px solid var(--border);
    color: var(--accent);
    cursor: pointer;
    font-size: 12.5px;
    padding: 8px 12px;
  }
  .more:hover { text-decoration: underline; }
  .more:disabled { opacity: 0.6; cursor: default; text-decoration: none; }
  .refresh {
    background: var(--panel-2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 5px 12px;
    cursor: pointer;
    font-size: 13px;
  }
  .refresh:disabled { opacity: 0.6; cursor: default; }
  .workq { padding: 4px 12px 12px; }
  .wlink { float: right; font-weight: 400; font-size: 12px; color: var(--accent); text-decoration: none; }
  .wcards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  @media (max-width: 900px) { .wcards { grid-template-columns: 1fr; } }
  .wcard { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; min-width: 0; }
  .wcard.hotcard { border-color: var(--neg); }
  .wsub { font-size: 11.5px; color: var(--muted); margin: 6px 0 2px; }
  .wh { font-weight: 600; font-size: 12.5px; margin-bottom: 4px; }
  .wrow { font-size: 12.5px; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .wid { font-weight: 600; }
</style>
