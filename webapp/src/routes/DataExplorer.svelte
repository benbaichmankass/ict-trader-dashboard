<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, DASH } from "../lib/format";

  let tables = $state<any[]>([]);
  let selected = $state<string | null>(null);
  let selectedDb = $state<string | null>(null);
  let page = $state<any | null>(null);
  let offset = $state(0);
  let loadingTables = $state(true);
  let loadingRows = $state(false);
  let error = $state<string | null>(null);

  const LIMIT = 50;

  async function loadTables() {
    loadingTables = true;
    error = null;
    try {
      const raw = await api.dbTables();
      tables = raw?.tables ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loadingTables = false;
    }
  }

  async function loadRows(name: string, db: string | null) {
    loadingRows = true;
    try {
      page = await api.dbTable(name, { db: db ?? undefined, limit: LIMIT, offset });
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      page = null;
    } finally {
      loadingRows = false;
    }
  }

  function pick(t: any) {
    selected = t.name;
    selectedDb = t.db ?? null;
    offset = 0;
    loadRows(t.name, t.db ?? null);
  }
  function nextPage() { offset += LIMIT; if (selected) loadRows(selected, selectedDb); }
  function prevPage() { offset = Math.max(0, offset - LIMIT); if (selected) loadRows(selected, selectedDb); }

  onMount(loadTables);

  const cols = $derived(page?.columns ?? []);
  const rows = $derived(page?.rows ?? []);
  const total = $derived(page?.total ?? null);

  function cell(v: any): string {
    if (v == null) return DASH;
    if (typeof v === "object") return JSON.stringify(v);
    const s = String(v);
    return s.length > 80 ? s.slice(0, 77) + "…" : s;
  }
</script>

<section>
  <h2>Data Explorer <span class="muted sub">· federated read-only (trade_journal + trainer_store)</span></h2>
  {#if error}
    <div class="err panel">{error}</div>
  {/if}

  {#if loadingTables}
    <div class="muted pad">Loading tables…</div>
  {:else}
    <div class="panel pad">
      <div class="ph">Tables</div>
      <div class="tlist">
        {#each tables as t (t.db + ":" + t.name)}
          <button class="tbtn" class:active={selected === t.name && selectedDb === (t.db ?? null)} onclick={() => pick(t)}>
            <span class="tn">{t.name}</span>
            <span class="tmeta muted">{num(t.rows)} rows · {t.db}</span>
          </button>
        {/each}
      </div>
    </div>

    {#if selected}
      <div class="panel">
        <div class="th">
          <span class="ph">{selected} <span class="muted">({selectedDb})</span></span>
          <span class="pager">
            <button onclick={prevPage} disabled={offset === 0 || loadingRows}>‹</button>
            <span class="muted">{offset + 1}–{offset + rows.length}{total != null ? ` of ${num(total)}` : ""}</span>
            <button onclick={nextPage} disabled={loadingRows || (total != null && offset + LIMIT >= total)}>›</button>
          </span>
        </div>
        {#if loadingRows}
          <div class="muted pad">Loading rows…</div>
        {:else if rows.length === 0}
          <div class="muted pad">No rows.</div>
        {:else}
          <div class="scroll">
            <table>
              <thead><tr>{#each cols as c}<th>{typeof c === "string" ? c : c.name}</th>{/each}</tr></thead>
              <tbody>
                {#each rows as r, i (i)}
                  <tr>{#each cols as c}<td class="mono">{cell(r[typeof c === "string" ? c : c.name])}</td>{/each}</tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .pad { padding: 14px; }
  .ph { font-weight: 600; font-size: 13.5px; }
  .tlist { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .tbtn { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; cursor: pointer; color: var(--text); }
  .tbtn.active { border-color: var(--accent); }
  .tn { font-size: 12.5px; font-weight: 600; }
  .tmeta { font-size: 11px; }
  .th { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; gap: 10px; flex-wrap: wrap; }
  .pager { display: flex; align-items: center; gap: 8px; font-size: 12px; }
  .pager button { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; width: 26px; height: 24px; cursor: pointer; }
  .pager button:disabled { opacity: 0.4; cursor: default; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 6px 9px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; position: sticky; top: 0; background: var(--panel); }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
