<script lang="ts">
  import { onMount } from "svelte";
  import { api, AuthRequiredError } from "../lib/api";
  import { DASH, num, agoFromIso } from "../lib/format";
  import { catalogState, type CatalogResponse } from "../lib/catalog";

  let resp = $state<CatalogResponse | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);

  // Per-table row counts come from the gated /db/tables route — the closest
  // thing to DB health available until /api/bot/db/overview exists. Three
  // states are kept apart: not signed in / failed / loaded.
  let tables = $state<any[] | null>(null);
  let tablesState = $state<"loading" | "auth" | "error" | "ok">("loading");
  let tablesError = $state<string | null>(null);

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
    (async () => {
      try {
        const raw = await api.dbTables();
        tables = raw?.tables ?? [];
        tablesState = "ok";
      } catch (e) {
        if (e instanceof AuthRequiredError) tablesState = "auth";
        else {
          tablesState = "error";
          tablesError = e instanceof Error ? e.message : String(e);
        }
      }
    })();
  });

  const status = $derived(Object.entries(resp?.facets?.status ?? {}));
  const rstate = $derived(catalogState(resp));
  const byDb = $derived.by(() => {
    const m = new Map<string, any[]>();
    for (const t of tables ?? []) m.set(t.db ?? "unknown", [...(m.get(t.db ?? "unknown") ?? []), t]);
    return [...m.entries()];
  });
  const empties = $derived((tables ?? []).filter((t) => t.rows === 0));
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
      <div class="muted s">generated {resp?.generatedAt ? agoFromIso(resp.generatedAt) + " ago" : DASH}</div>
    {/if}
  </div>

  <div class="panel pad">
    <div class="ph">Database health</div>
    <div class="muted s">
      Per-database size, WAL/integrity, newest-row age, STALE flags and 24h/7d growth need the bot's
      <span class="mono">/api/bot/db/overview</span> endpoint, which is <b>not available yet</b>.
      Nothing is shown rather than zeros.
    </div>
    {#if tablesState === "loading"}
      <div class="muted s">Loading table row counts…</div>
    {:else if tablesState === "auth"}
      <div class="muted s">Row counts per table need a signed-in session (Settings → sign in).</div>
    {:else if tablesState === "error"}
      <div class="err s">Could not load table row counts: <span class="mono">{tablesError}</span></div>
    {:else}
      {#if empties.length}
        <div class="warn s">Empty tables ({empties.length}): {empties.map((t) => `${t.name} (${t.db})`).join(", ")}</div>
      {:else}
        <div class="muted s">No empty tables.</div>
      {/if}
      {#each byDb as [db, ts] (db)}
        <div class="dbh">{db} <span class="muted">· {ts.length} tables · {num(ts.reduce((n, t) => n + (t.rows ?? 0), 0))} rows</span></div>
        <div class="tl">
          {#each ts as t (t.name)}
            <span class="t" class:e={t.rows === 0}>{t.name} <span class="muted">{num(t.rows)}</span></span>
          {/each}
        </div>
      {/each}
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
  .err { color: var(--neg); font-size: 13px; }
  .warn { color: #d9a441; }
  .dbh { margin-top: 12px; font-weight: 600; font-size: 13px; }
  .tl { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
  .t { font-size: 12px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; }
  .t.e { border-color: var(--neg); color: var(--neg); }
</style>
