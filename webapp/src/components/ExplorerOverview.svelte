<script lang="ts">
  import { onMount } from "svelte";
  import { api, AuthRequiredError } from "../lib/api";
  import { DASH, num, agoFromIso } from "../lib/format";
  import { requestLogin } from "../lib/auth";
  import { catalogState, type CatalogResponse } from "../lib/catalog";
  import { fmtBytes, integrityLabel, newestShort, rowsLabel, type DbOverview, type OverviewTable } from "../lib/dbOverview";

  let { onOpenTable }: { onOpenTable?: (db: string, name: string) => void } = $props();

  let resp = $state<CatalogResponse | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);

  // DB-health half: five distinct states, none of which is "zero".
  //   loading | auth (401, sign in) | missing (404, route not deployed) | error | ok
  let ov = $state<DbOverview | null>(null);
  let ovState = $state<"loading" | "auth" | "missing" | "timeout" | "error" | "ok">("loading");
  let ovError = $state<string | null>(null);
  let checking = $state(false);
  // The count over a multi-million-row table can be slow bot-side: say so after
  // ~3 s, and give up (with a Retry) after 30 s rather than spin forever.
  let slow = $state(false);
  let openTbl = $state<(OverviewTable & { _db: string }) | null>(null);
  const SLOW_MS = 3000;
  const TIMEOUT_MS = 30000;
  let inflight: AbortController | undefined;

  async function loadOverview(integrity: "off" | "quick" = "off") {
    inflight?.abort();
    const ctl = new AbortController();
    inflight = ctl;
    let timedOut = false;
    checking = integrity === "quick";
    slow = false;
    if (ovState !== "ok") ovState = "loading";
    const slowT = setTimeout(() => (slow = true), SLOW_MS);
    const killT = setTimeout(() => {
      timedOut = true;
      ctl.abort();
    }, TIMEOUT_MS);
    try {
      ov = await api.dbOverview(integrity, ctl.signal);
      ovState = "ok";
    } catch (e) {
      if (ctl !== inflight) return; // superseded by a newer request
      if (timedOut) ovState = "timeout";
      else if (e instanceof AuthRequiredError) ovState = "auth";
      else if (e instanceof Error && /^404\b/.test(e.message)) ovState = "missing";
      else {
        ovState = "error";
        ovError = e instanceof Error ? e.message : String(e);
      }
    } finally {
      clearTimeout(slowT);
      clearTimeout(killT);
      if (ctl === inflight) {
        checking = false;
        slow = false;
      }
    }
  }

  onMount(() => {
    (async () => {
      try {
        resp = await api.researchCatalog({ limit: 1 });
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    })();
    loadOverview();
  });

  const status = $derived(Object.entries(resp?.facets?.status ?? {}));
  const rstate = $derived(catalogState(resp));
  const summary = $derived(ov?.summary ?? null);
  const emptyTables = $derived(
    (ov?.dbs ?? []).flatMap((d) => (d.tables ?? []).filter((t) => t.empty === true).map((t) => ({ ...t, db: t.db ?? d.db }))),
  );
</script>

<section>
  <div class="panel pad">
    <div class="ph">Research queue</div>
    {#if loading}
      <div class="muted">Loading…</div>
    {:else if error}
      <div class="err">Could not load the research catalog: <span class="mono">{error}</span></div>
    {:else if rstate === "unreadable" || rstate === "absent"}
      <div class="err">Research store {rstate === "absent" ? "not present" : "unreadable"} on the host — not zero.</div>
    {:else}
      <div class="grid">
        <div class="stat"><div class="v">{num(resp?.total)}</div><div class="k">total units</div></div>
        {#each status as [s, n] (s)}
          <div class="stat"><div class="v">{num(n)}</div><div class="k">{s}</div></div>
        {/each}
        <div class="stat"><div class="v neg">{num(resp?.stayOnTop?.stuck?.count)}</div><div class="k">stuck</div></div>
      </div>
      <div class="muted s">generated {agoFromIso(resp?.generatedAt)}</div>
    {/if}
  </div>

  <div class="panel pad">
    <div class="ph">Database health</div>
    {#if ovState === "loading"}
      <div class="muted s">Loading…{#if slow} still loading — counting rows on large tables can take a few seconds.{/if}</div>
    {:else if ovState === "timeout"}
      <div class="err s">Could not load DB health (timed out after 30 s) — this is a timeout, not an empty database.
        <button class="lnk" onclick={() => loadOverview()}>Retry</button></div>
    {:else if ovState === "auth"}
      <div class="s">Sign in to see DB health — this view is session-gated.</div>
      <button class="btn" onclick={() => requestLogin("Database health needs a signed-in session.")}>Sign in</button>
    {:else if ovState === "missing"}
      <div class="muted s">
        Overview not available yet — <span class="mono">/api/bot/db/overview</span> is not deployed on the host (404).
        Nothing is shown rather than zeros.
      </div>
    {:else if ovState === "error"}
      <div class="err s">Could not load DB health (a failed request, not an empty database): <span class="mono">{ovError}</span>
        <button class="lnk" onclick={() => loadOverview()}>Retry</button></div>
    {:else if ov?.present === false}
      <div class="muted s">The host reports no database overview (<span class="mono">present: false</span>).</div>
    {:else}
      <div class="s muted">
        {num(summary?.tables)} tables · <b class:warn={(summary?.emptyTables ?? 0) > 0}>{num(summary?.emptyTables)} empty</b>
        · {num(summary?.unknownRowCount)} row counts unknown
        · {num(summary?.dbsUnreadable)} unreadable DB · {num(summary?.dbsMissing)} missing DB
        · generated {agoFromIso(ov?.generatedAt)}
      </div>
      {#if emptyTables.length}
        <div class="warn s">Empty tables: {emptyTables.map((t) => `${t.name} (${t.db})`).join(", ")}</div>
      {/if}
      {#each ov?.dbs ?? [] as d (d.db)}
        {@const ig = integrityLabel(d.integrity)}
        <div class="dbh">
          {d.db}
          <span class="muted">· {d.file ?? DASH}</span>
        </div>
        {#if d.readState === "missing" || d.present === false}
          <div class="err s">Database not on disk{d.reason ? ` (${d.reason})` : ""}.</div>
        {:else if d.readState === "unreadable"}
          <div class="err s">Database unreadable{d.reason ? `: ${d.reason}` : ""} — not an empty database.</div>
        {:else}
          <div class="s muted">
            size {fmtBytes(d.sizeBytes)} · WAL {fmtBytes(d.walBytes)} · journal {d.journalMode ?? DASH} ·
            integrity <b class:bad={ig.tone === "bad"} class:good={ig.tone === "ok"}>{ig.text}</b>
            <button class="lnk" disabled={checking} onclick={() => loadOverview("quick")}>
              {checking ? (slow ? "checking… (still running)" : "checking…") : "Check integrity"}
            </button>
          </div>
          <div class="scroll">
            <table>
              <thead><tr><th>Table</th><th class="r">Rows</th><th>Newest</th><th></th></tr></thead>
              <tbody>
                {#each d.tables ?? [] as t (t.name)}
                  <tr class:e={t.empty === true} onclick={() => (openTbl = { ...t, _db: t.db ?? d.db })}>
                    <td>
                      <button class="lnk mono" onclick={(e) => { e.stopPropagation(); onOpenTable?.(t.db ?? d.db, t.name); }}>{t.name}</button>
                    </td>
                    <td class="r mono" class:est={t.rowsState === "count_timed_out"}>{rowsLabel(t)}</td>
                    <td class="mono nw">{newestShort(t)}</td>
                    <td class="emptycell">{#if t.empty === true}<b class="emptybadge">EMPTY</b>{/if}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      {/each}
      {#if ov?.notProvided?.length}
        <div class="s muted">Not provided by the host: {ov.notProvided.join(", ")}. Newest-row age is a raw fact, with no stale verdict. Tap a row for its full timestamp and detail.</div>
      {/if}
    {/if}
  </div>

  {#if openTbl}
    <aside class="drawer panel" aria-label="Table detail">
      <div class="dh">
        <span class="mono">{openTbl.name} <span class="muted">({openTbl._db})</span></span>
        <button class="lnk" onclick={() => (openTbl = null)}>Close ✕</button>
      </div>
      <div class="dbody">
        <div class="kvr"><span class="muted">rows</span><span class="mono">{rowsLabel(openTbl)}</span></div>
        {#each Object.entries(openTbl).filter(([k]) => k !== "_db") as [k, v] (k)}
          <div class="kvr"><span class="muted">{k}</span><span class="mono">{v === null || v === undefined || v === "" ? DASH : typeof v === "object" ? JSON.stringify(v) : String(v)}</span></div>
        {/each}
      </div>
    </aside>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .pad { padding: 14px; }
  .ph { font-weight: 600; font-size: 13.5px; margin-bottom: 8px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
  .stat { background: var(--panel-2); border-radius: 8px; padding: 8px 10px; }
  .v { font-size: 20px; font-weight: 700; }
  .k { font-size: 11px; color: var(--muted); text-transform: uppercase; }
  .s { font-size: 12px; margin-top: 8px; line-height: 1.5; }
  .err, .bad { color: var(--neg); }
  .good { color: var(--pos); }
  .warn { color: #d9a441; }
  .dbh { margin-top: 14px; font-weight: 600; font-size: 13px; }
  .scroll { overflow-x: auto; margin-top: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 5px 9px; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  .r { text-align: right; }
  .nw { white-space: nowrap; }
  tr.e td { background: color-mix(in srgb, var(--neg) 8%, transparent); }
  /* never let a narrow phone column clip the badge to "EM" */
  .emptycell { white-space: nowrap; min-width: 56px; }
  .emptybadge { color: var(--neg); font-size: 11px; white-space: nowrap; flex-shrink: 0; }
  .lnk { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0; }
  .lnk:disabled { color: var(--muted); cursor: default; }
  .est { color: #d9a441; }
  tbody tr { cursor: pointer; }
  .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(420px, 100vw); z-index: 40; overflow-y: auto; border-radius: 0; box-shadow: -4px 0 18px rgba(0,0,0,.4); }
  .dh { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--panel); }
  .dbody { padding: 6px 14px 24px; }
  .kvr { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
  .kvr .mono { text-align: right; overflow-wrap: anywhere; }
  .btn { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 6px 12px; cursor: pointer; margin-top: 8px; }
</style>
