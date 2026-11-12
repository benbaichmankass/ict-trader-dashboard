<script lang="ts">
  // Models TABLE view (UI workplan §7 UI-MODELS-STRATEGIES-TABLES). Same rows as
  // the card view (/api/bot/ml/registry), one sortable line each. Read surface:
  // no stage/promotion control.
  //
  // Headline metric: the first of HEADLINE present on the row, with its
  // population (`n_eval`) on hover; no metric → "—". Drift is not on the
  // registry rows, so it is not a column here (it would need /shadow/drift).
  import { DASH } from "../lib/format";

  let { models = [], stageOf }: { models?: any[]; stageOf: (m: any) => string } = $props();

  const HEADLINE = ["auc", "roc_auc", "macro_f1", "ic", "rank_ic", "sharpe", "accuracy", "r2", "brier", "logloss"];
  type Key = "name" | "slot" | "stage" | "bucket" | "created" | "metric";
  let key = $state<Key>("stage");
  let asc = $state(true);
  const STAGE_RANK: Record<string, number> = { advisory: 0, shadow: 1, candidate: 2 };
  const BUCKET_RANK: Record<string, number> = { LIVE: 0, SHADOW: 1, OFFLINE: 2 };

  function headline(m: any): { k: string; v: number; n: number | null } | null {
    const mt = m?.metrics;
    if (!mt || typeof mt !== "object") return null;
    for (const k of HEADLINE) {
      const v = mt[k];
      if (typeof v === "number" && Number.isFinite(v)) return { k, v, n: typeof mt.n_eval === "number" ? mt.n_eval : null };
    }
    return null;
  }
  const linked = (m: any): string[] => (Array.isArray(m?.linked_strategies) ? m.linked_strategies : []).map((x: any) => (typeof x === "string" ? x : x?.name ?? x?.strategy)).filter(Boolean);

  function val(m: any, k: Key): string | number | null {
    switch (k) {
      case "name": return String(m.display_name ?? m.model_id ?? "").toLowerCase();
      case "slot": return m.slot ?? null;
      case "stage": { const s = stageOf(m); return s && s !== DASH ? STAGE_RANK[s] ?? 5 : null; }
      case "bucket": return m.deployment_bucket ? BUCKET_RANK[m.deployment_bucket] ?? 5 : null;
      case "created": return m.created_at ?? null;
      case "metric": return headline(m)?.v ?? null;
    }
  }
  const rows = $derived(
    [...models].sort((a, b) => {
      const x = val(a, key), y = val(b, key);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = x < y ? -1 : x > y ? 1 : 0;
      return asc ? c : -c;
    }),
  );
  function sortBy(k: Key) {
    if (key === k) asc = !asc;
    else { key = k; asc = !(k === "created" || k === "metric"); }
  }
  const ar = (k: Key) => (key === k ? (asc ? " ▲" : " ▼") : "");
</script>

<div class="panel scroll">
  <table>
    <thead>
      <tr>
        <th class="s" onclick={() => sortBy("name")}>Model{ar("name")}</th>
        <th class="s" onclick={() => sortBy("slot")}>Slot{ar("slot")}</th>
        <th>Breed / family</th>
        <th class="s" onclick={() => sortBy("stage")} title="registry stage: candidate → shadow → advisory">Stage{ar("stage")}</th>
        <th class="s" onclick={() => sortBy("bucket")} title="deployment bucket from config: LIVE / SHADOW / OFFLINE">Deployed{ar("bucket")}</th>
        <th>Linked strategies</th>
        <th class="s" onclick={() => sortBy("created")}>Created{ar("created")}</th>
        <th class="r s" onclick={() => sortBy("metric")}>Headline metric{ar("metric")}</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as m, i (String(m.model_id ?? "") + i)}
        {@const h = headline(m)}
        <tr>
          <td><div class="nm">{m.display_name ?? DASH}</div><div class="muted mono small">{m.model_id ?? DASH}</div></td>
          <td class="mono">{m.slot ?? DASH}</td>
          <td class="muted">{m.breed ?? DASH}{m.model_family ? ` · ${m.model_family}` : ""}</td>
          <td>{stageOf(m)}</td>
          <td class="muted">{m.deployment_bucket ?? DASH}</td>
          <td class="muted small">{linked(m).join(", ") || DASH}</td>
          <td class="muted mono small">{m.created_at ? String(m.created_at).slice(0, 10) : DASH}</td>
          <td class="r mono" title={h ? `${h.k} over n_eval ${h.n ?? DASH}` : "no headline metric on this row"}>{h ? `${h.k} ${h.v.toFixed(3)}` : DASH}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .scroll { overflow-x: auto; padding: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 7px 9px; text-align: left; vertical-align: top; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; white-space: nowrap; }
  th.s { cursor: pointer; user-select: none; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .r { text-align: right; white-space: nowrap; }
  .nm { font-weight: 600; }
  .small { font-size: 11px; }
</style>
