<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num, agoFromIso, DASH } from "../lib/format";

  let records = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.shadowStats();
      records = raw?.records ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function daysSoaking(r: any): number | null {
    const first = r.first_seen ?? r.first_ts;
    const last = r.last_seen ?? r.last_ts;
    if (!first || !last) return null;
    const d = (new Date(last).getTime() - new Date(first).getTime()) / 86400000;
    return isFinite(d) ? d : null;
  }
  // Rough soak-readiness heuristic (mirrors the promotion-readiness idea): needs
  // volume + days + a non-degenerate score spread. Not a promotion decision —
  // that's the operator-gated live_agreement gate.
  function verdict(r: any): { label: string; cls: string } {
    const n = r.count ?? 0;
    const days = daysSoaking(r) ?? 0;
    const spread = (r.score_max ?? 0) - (r.score_min ?? 0);
    if (spread < 1e-6) return { label: "degenerate", cls: "neg" };
    if (n >= 1000 && days >= 7) return { label: "soak criteria met", cls: "pos" };
    return { label: "soaking", cls: "warn" };
  }
</script>

<section>
  <h2>Promotion <span class="muted sub">· shadow-model soak readiness (promotion is operator-gated)</span></h2>
  {#if error}
    <div class="err panel">Couldn't load shadow stats: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else if records.length === 0}
    <div class="panel pad muted">No shadow predictions logged yet.</div>
  {:else}
    <div class="panel scroll">
      <table>
        <thead>
          <tr><th>Model</th><th>Stage</th><th class="r">Obs</th><th class="r">Days</th><th class="r">Score range</th><th class="r">Mean</th><th>Readiness</th><th>Last</th></tr>
        </thead>
        <tbody>
          {#each records as r, i (r.model_id + (r.stage ?? "") + i)}
            {@const v = verdict(r)}
            {@const d = daysSoaking(r)}
            <tr>
              <td class="mono mname">{r.model_id ?? DASH}</td>
              <td class="muted">{r.stage ?? DASH}</td>
              <td class="r mono">{num(r.count)}</td>
              <td class="r mono">{d == null ? DASH : num(d, 1)}</td>
              <td class="r mono small">{r.score_min == null ? DASH : `${num(r.score_min, 3)}–${num(r.score_max, 3)}`}</td>
              <td class="r mono">{r.score_mean == null ? DASH : num(r.score_mean, 3)}</td>
              <td><span class="verdict {v.cls}">{v.label}</span></td>
              <td class="muted small">{agoFromIso(r.last_seen ?? r.last_ts)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="muted foot">“Soak criteria met” = volume + days + non-degenerate scores only. Promoting shadow→advisory is the operator-gated live_agreement decision, not shown here.</p>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .mname { max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
  .small { font-size: 12px; }
  .verdict { font-size: 11px; text-transform: uppercase; }
  .verdict.pos { color: var(--pos); }
  .verdict.neg { color: var(--neg); }
  .verdict.warn { color: #e0a800; }
  .foot { font-size: 12px; margin: 0; }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
