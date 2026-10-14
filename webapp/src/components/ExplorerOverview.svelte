<script lang="ts">
  import { onMount } from "svelte";
  import { api, AuthRequiredError } from "../lib/api";
  import { DASH, num, agoFromIso } from "../lib/format";
  import { requestLogin } from "../lib/auth";
  import { catalogState, type CatalogResponse } from "../lib/catalog";
  import { fmtBytes, fmtAge, integrityLabel, newestLabel, type DbOverview } from "../lib/dbOverview";

  let { onOpenTable }: { onOpenTable?: (db: string, name: string) => void } = $props();

  let resp = $state<CatalogResponse | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);

  // DB-health half: five distinct states, none of which is "zero".
  //   loading | auth (401, sign in) | missing (404, route not deployed) | error | ok
  let ov = $state<DbOverview | null>(null);
  let ovState = $state<"loading" | "auth" | "missing" | "error" | "ok">("loading");
  let ovError = $state<string | null>(null);
  let checking = $state(false);

  async function loadOverview(integrity: "off" | "quick" = "off") {
    checking = integrity === "quick";
    try {
      ov = await api.dbOverview(integrity);
      ovState = "ok";
    } catch (e) {
      if (e instanceof AuthRequiredError) ovState = "auth";
      else if (e instanceof Error && /^404\b/.test(e.message)) ovState = "missing";
      else {
        ovState = "error";
        ovError = e instanceof Error ? e.message : String(e);
      }
    } finally {
      checking = false;
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
      <div class="muted s">Loading…</div>
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
              {checking ? "checking…" : "Check integrity"}
            </button>
          </div>
          <div class="scroll">
            <table>
              <thead><tr><th>Table</th><th class="r">Rows</th><th>Newest row</th><th class="r">Age</th><th></th></tr></thead>
              <tbody>
                {#each d.tables ?? [] as t (t.name)}
                  <tr class:e={t.empty === true}>
                    <td>
                      <button class="lnk mono" onclick={() => onOpenTable?.(t.db ?? d.db, t.name)}>{t.name}</button>
                    </td>
                    <td class="r mono">{t.rowsState === "count_failed" ? "count failed" : num(t.rows)}</td>
                    <td class="mono nw">{newestLabel(t)}</td>
                    <td class="r mono">{fmtAge(t.ageSeconds)}</td>
                    <td>{#if t.empty === true}<b class="flag">EMPTY</b>{/if}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      {/each}
      {#if ov?.notProvided?.length}
        <div class="s muted">Not provided by the host: {ov.notProvided.join(", ")}. Age is shown as a raw fact, with no stale verdict.</div>
      {/if}
    {/if}
  </div>
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
  .flag { color: var(--neg); font-size: 11px; }
  .lnk { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0; }
  .lnk:disabled { color: var(--muted); cursor: default; }
  .btn { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 6px 12px; cursor: pointer; margin-top: 8px; }
</style>
