<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { money, pct, agoFromIso, DASH } from "../lib/format";

  let rows = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.signals();
      const list: any[] = Array.isArray(raw) ? raw : (raw?.signals ?? raw?.records ?? []);
      // Keep any signal that identifies an instrument. (The "skip null pattern"
      // rule is only for the Overview chart's per-strategy toggle — live signals
      // normally carry a `strategy` with a null `pattern`, so filtering on
      // pattern here wrongly hid every signal. Render a null pattern as "—".)
      rows = list.filter((s) => s?.symbol);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      rows = [];
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function sideClass(s: any): string {
    const d = String(s?.side ?? s?.direction ?? "").toLowerCase();
    if (d.includes("sell") || d.includes("short")) return "neg";
    if (d.includes("buy") || d.includes("long")) return "pos";
    return "flat";
  }
</script>

<section>
  <h2>Signals</h2>
  {#if error}
    <div class="err panel">Couldn't load signals: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if rows.length === 0}
    <div class="muted pad">No recent signals.</div>
  {:else}
    <div class="panel scroll">
      <table>
        <thead>
          <tr><th>Symbol</th><th>Pattern</th><th>Strategy</th><th>Side</th><th class="r">Price</th><th class="r">Conf.</th><th>When</th></tr>
        </thead>
        <tbody>
          {#each rows as s, i (s.id ?? `${s.symbol}-${s.timestamp ?? i}`)}
            <tr>
              <td class="sym">{s.symbol ?? DASH}</td>
              <td>{s.pattern ?? DASH}</td>
              <td class="muted">{s.strategy ?? DASH}</td>
              <td class={sideClass(s)}>{(s.side ?? s.direction ?? DASH).toString().toUpperCase()}</td>
              <td class="r mono">{money(s.price)}</td>
              <td class="r mono">{s.confidence == null ? DASH : pct(s.confidence * (s.confidence <= 1 ? 100 : 1))}</td>
              <td class="muted">{agoFromIso(s.timestamp ?? s.ts)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .scroll { overflow-x: auto; padding: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .sym { font-weight: 600; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
