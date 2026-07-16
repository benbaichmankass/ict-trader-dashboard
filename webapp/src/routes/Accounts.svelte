<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, num, agoFromIso, DASH } from "../lib/format";
  import StatusDot from "../components/StatusDot.svelte";

  interface Row {
    id: string;
    balance: number | null;
    openPositions: number | null;
    apiOk: boolean | null;
    ts: string | null;
    accountClass: string | null;
    mode: string | null;
  }

  let rows = $state<Row[]>([]);
  let source = $state<string | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [bal, cfg] = await Promise.all([api.balances(), api.config().catch(() => null)]);
      source = bal?.source ?? null;
      const balances = bal?.balances ?? {};
      // account_class + mode from /config, keyed by account id
      const cfgAccts: Record<string, any> = {};
      const accts = cfg?.accounts ?? cfg?.config?.accounts ?? {};
      if (Array.isArray(accts)) for (const a of accts) cfgAccts[a.id ?? a.name] = a;
      else for (const [k, v] of Object.entries(accts)) cfgAccts[k] = v;
      rows = Object.entries(balances).map(([id, b]: [string, any]) => ({
        id,
        balance: b?.balance ?? null,
        openPositions: b?.open_positions ?? null,
        apiOk: b?.api_ok ?? null,
        ts: b?.ts ?? null,
        accountClass: cfgAccts[id]?.account_class ?? null,
        mode: cfgAccts[id]?.mode ?? null,
      }));
      rows.sort((a, b) => a.id.localeCompare(b.id));
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function classLabel(c: string | null): string {
    if (c === "real_money") return "Real";
    if (c === "paper") return "Paper";
    return c ?? DASH;
  }
</script>

<section>
  <div class="head">
    <h2>Accounts</h2>
    {#if source}<span class="muted src">source: {source}</span>{/if}
  </div>

  {#if error}
    <div class="err panel">Couldn't load accounts: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    <div class="grid">
      {#each rows as r (r.id)}
        <div class="card panel">
          <div class="top">
            <StatusDot status={r.apiOk === false ? "neg" : r.apiOk ? "pos" : "flat"} />
            <span class="name">{r.id}</span>
            <span class="tag">{classLabel(r.accountClass)}</span>
          </div>
          <div class="bal mono">{money(r.balance)}</div>
          <div class="meta muted">
            {num(r.openPositions)} open · {r.mode ?? DASH} · {agoFromIso(r.ts)}
          </div>
        </div>
      {/each}
      {#if rows.length === 0}<div class="muted pad">No account balances reported.</div>{/if}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: baseline; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .src { font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
  .card { padding: 14px; }
  .top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .name { font-weight: 600; }
  .tag { margin-left: auto; font-size: 11px; color: var(--muted); border: 1px solid var(--border); border-radius: 6px; padding: 1px 7px; }
  .bal { font-size: 22px; font-weight: 600; }
  .meta { font-size: 12px; margin-top: 6px; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
