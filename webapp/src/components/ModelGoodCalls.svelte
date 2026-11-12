<script lang="ts">
  // Good-call rate for every model that has been in shadow or beyond (UI-REDESIGN-
  // 2026-11, STRATEGIES & MODELS: "for anything that has been in shadow or beyond, a
  // hit-rate / good-call metric").
  //
  // Metric: AUC = P(a winning trade got a higher score than a losing one), over the
  // closed order packages that carry the model's persisted score (modelScores) and a
  // P&L. Scale-free, so it is comparable across models whose scores are on different
  // scales; 0.5 = no skill. NOT graded (→ "—") when a model has < MIN wins or < MIN
  // losses, or a constant score: a number from that would read as a verdict it isn't.
  //
  // Population: the newest 200 order packages (the route's cap; it has no offset),
  // so n is small. A full-history hit-rate needs a bot-side computation
  // (/api/bot/trades/scores recompiles and timed out at 30 s when probed).
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { DASH } from "../lib/format";

  const MIN = 5;
  type Row = { id: string; stage: string; n: number; wins: number; losses: number; auc: number | null; why: string | null };
  let rows = $state<Row[]>([]);
  let pop = $state(0);
  let error = $state<string | null>(null);
  let loaded = $state(false);

  function auc(w: number[], l: number[]): number {
    let s = 0;
    for (const a of w) for (const b of l) s += a > b ? 1 : a === b ? 0.5 : 0;
    return s / (w.length * l.length);
  }

  onMount(async () => {
    try {
      const r: any = await api.orderPackages({ includePaper: true, limit: 200 });
      const pk = ((Array.isArray(r) ? r : r?.rows ?? []) as any[]).filter((x) => typeof x?.pnl === "number" && Number.isFinite(x.pnl) && x?.modelScores && typeof x.modelScores === "object");
      pop = pk.length;
      const by = new Map<string, { stage: string; w: number[]; l: number[] }>();
      for (const x of pk) {
        for (const [id, v] of Object.entries<any>(x.modelScores)) {
          const sc = Number(v?.score);
          if (!Number.isFinite(sc) || x.pnl === 0) continue;
          const e = by.get(id) ?? by.set(id, { stage: v?.stage ?? DASH, w: [], l: [] }).get(id)!;
          (x.pnl > 0 ? e.w : e.l).push(sc);
        }
      }
      rows = [...by.entries()].map(([id, e]) => {
        const all = [...e.w, ...e.l];
        const constant = all.length > 1 && all.every((v) => v === all[0]);
        const why = constant ? "constant score" : e.w.length < MIN || e.l.length < MIN ? `needs ≥${MIN} wins and ≥${MIN} losses` : null;
        return { id, stage: e.stage, n: all.length, wins: e.w.length, losses: e.l.length, auc: why ? null : auc(e.w, e.l), why };
      }).sort((a, b) => (b.auc ?? -1) - (a.auc ?? -1) || b.n - a.n);
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    finally { loaded = true; }
  });
</script>

<div class="panel gc">
  <div class="ph">Good-call rate · shadow and beyond <span class="muted">· AUC over {pop} closed, scored order packages (newest 200)</span></div>
  {#if error}
    <div class="err pad">could not look: <span class="mono">{error}</span></div>
  {:else if !loaded}
    <div class="muted pad">Loading…</div>
  {:else if !rows.length}
    <div class="muted pad">No closed order package carries a model score in the newest 200.</div>
  {:else}
    <div class="scroll">
      <table>
        <thead><tr><th>Model</th><th>Stage</th><th class="r">Scored trades</th><th class="r">W / L</th><th class="r">Good-call (AUC)</th><th>Note</th></tr></thead>
        <tbody>
          {#each rows as r (r.id)}
            <tr>
              <td class="mono">{r.id}</td><td class="muted">{r.stage}</td><td class="r mono">{r.n}</td><td class="r mono">{r.wins} / {r.losses}</td>
              <td class="r mono" class:pos={r.auc != null && r.auc > 0.55} class:neg={r.auc != null && r.auc < 0.45}>{r.auc == null ? DASH : r.auc.toFixed(2)}</td>
              <td class="muted small">{r.why ?? (r.n < 30 ? "small sample" : "")}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="muted small">AUC 0.5 = no skill; above = winners scored higher than losers. A small sample is not a verdict.</div>
  {/if}
</div>

<style>
  .gc { padding: 4px 12px 12px; }
  .ph { padding: 10px 0 6px; font-weight: 600; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-bottom: 6px; }
  th, td { padding: 5px 8px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .pad { padding: 12px 0; }
  .err { color: var(--neg); }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
