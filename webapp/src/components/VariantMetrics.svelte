<script lang="ts">
  // "Performance vs past versions" (UI-REDESIGN-2026-11 S&M) — the SPA-only half:
  // each variant of one lineage, side by side, with the metrics the registry row
  // itself reports. Values are shown exactly as reported; no deltas, rankings or
  // "better/worse" are computed here (a real version comparison needs a bot route).
  import { agoFromIso, DASH } from "../lib/format";

  let { variants, rowOf }: { variants: any[]; rowOf: (id: string) => any } = $props();
  let all = $state(false);

  const HEADLINE = ["n_eval", "accuracy", "macro_f1", "weighted_f1", "brier", "f1", "precision", "cost_gate_passed", "cost_net_value_r"];
  const rows = $derived(variants.map((v) => ({ v, r: rowOf(v.model_id) })));
  const metricKeys = $derived.by(() => {
    const keys: string[] = [];
    for (const { r } of rows) for (const k of Object.keys(r?.metrics ?? {})) if (!keys.includes(k)) keys.push(k);
    return keys;
  });
  const cols = $derived(all ? metricKeys : HEADLINE.filter((k) => metricKeys.includes(k)));
  function cell(v: unknown): string {
    if (v == null) return DASH;
    if (typeof v === "boolean") return v ? "yes" : "no";
    if (typeof v === "number") return Number.isFinite(v) ? (Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(4)) : DASH;
    return String(v);
  }
</script>

{#if rows.length > 1}
  <div class="vm">
    <div class="vh small">
      <span class="muted">Variants side by side · as each registry row reports them (not a ranking)</span>
      {#if metricKeys.length > cols.length || all}
        <button class="link" onclick={() => (all = !all)}>{all ? "headline metrics" : `all ${metricKeys.length} metrics`}</button>
      {/if}
    </div>
    <div class="scroll">
      <table>
        <thead><tr><th>Variant</th><th>Stage</th><th>Registered</th>{#each cols as c (c)}<th class="r">{c}</th>{/each}</tr></thead>
        <tbody>
          {#each rows as { v, r } (v.model_id)}
            <tr>
              <td><span>{v.display_name ?? v.model_id}</span> <span class="mono muted">{v.model_id}</span></td>
              <td>{v.status ?? DASH}</td>
              <td class="muted">{r?.created_at ? agoFromIso(r.created_at) : DASH}</td>
              {#each cols as c (c)}<td class="r mono">{cell(r?.metrics?.[c])}</td>{/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if !metricKeys.length}<div class="muted small">No variant of this lineage reports metrics.</div>{/if}
  </div>
{/if}

<style>
  .vm { margin: 6px 0 4px; }
  .vh { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .small { font-size: 12px; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); cursor: pointer; padding: 0; font-size: 12px; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; font-size: 12px; width: 100%; margin-top: 4px; }
  th, td { padding: 4px 8px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  .r { text-align: right; }
</style>
