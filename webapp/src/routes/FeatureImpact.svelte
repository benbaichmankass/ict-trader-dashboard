<script lang="ts">
  // Feature impact (UI workplan §15.6 FEATURE-IMPACT-MAP, bot #24926).
  // Heat map of feature FAMILY × (asset class | ML type | stage) from
  // /api/bot/feature-impact/heatmap; click a cell → feature × model:side grid
  // from /feature-impact/detail; /feature-impact/invest is shown with its own
  // read_state (v0: not_computed, with the bot's reason — never a made-up order).
  //
  // v0 measures are model-internal importance SHARES (sequential scale). They
  // are not edge and not per symbol — the bot's caveat is printed verbatim.
  // An absent cell is hatched "—", never colour-0.
  import { api } from "../lib/api";
  import { num, DASH } from "../lib/format";
  import Segmented from "../components/Segmented.svelte";

  let by = $state("asset_class");
  let measure = $state("gain_share");
  let heat = $state<any>(null);
  let heatErr = $state<string | null>(null);
  let pick = $state<{ row: string; col: string } | null>(null);
  let detail = $state<any>(null);
  let detailErr = $state<string | null>(null);
  let invest = $state<any>(null);

  async function loadHeat(b: string, m: string) {
    heatErr = null;
    pick = null;
    detail = null;
    try { heat = await api.featureImpactHeatmap(b, m); } catch (e) { heat = null; heatErr = e instanceof Error ? e.message : String(e); }
  }
  async function loadDetail(p: { row: string; col: string }) {
    detailErr = null;
    detail = null;
    try {
      detail = await api.featureImpactDetail({ family: p.row, assetClass: by === "asset_class" ? p.col : undefined,
        stage: by === "stage" ? p.col : undefined, measure });
    } catch (e) { detailErr = e instanceof Error ? e.message : String(e); }
  }
  $effect(() => { loadHeat(by, measure); });
  $effect(() => { api.featureImpactInvest().then((r) => (invest = r)).catch(() => (invest = { read_state: "could_not_look" })); });

  function cellMap(cells: any[]): Map<string, any> {
    const m = new Map<string, any>();
    for (const c of cells ?? []) m.set(`${c.row}\u0000${c.col}`, c);
    return m;
  }
  const heatCells = $derived(cellMap(heat?.cells ?? []));
  const heatMax = $derived(Math.max(0, ...(heat?.cells ?? []).map((c: any) => (typeof c.value === "number" ? c.value : 0))));
  const detCells = $derived(cellMap(detail?.cells ?? []));
  const detMax = $derived(Math.max(0, ...(detail?.cells ?? []).map((c: any) => (typeof c.value === "number" ? c.value : 0))));

  function bg(v: unknown, max: number): string {
    if (typeof v !== "number" || !Number.isFinite(v) || max <= 0) return "";
    return `rgba(76,141,255,${(0.08 + 0.82 * (v / max)).toFixed(3)})`;
  }
  // u6 (operator 2026-11-12): the invest ranking is "edge x coverage gap /
  // collection cost, every factor shown". The bot's item schema is not fixed yet
  // (the route is not_computed), so the columns are the union of the items' own
  // fields in first-seen order: every factor gets a column, never one score alone.
  const investCols = $derived.by(() => {
    const cols: string[] = [];
    for (const it of invest?.items ?? []) for (const k of Object.keys(it ?? {})) if (!cols.includes(k)) cols.push(k);
    return cols;
  });
  const investNumeric = $derived.by(() => {
    const out: Record<string, boolean> = {};
    for (const c of investCols) out[c] = (invest?.items ?? []).every((it: any) => it?.[c] == null || typeof it[c] === "number");
    return out;
  });
  function cellText(v: unknown): string {
    if (v == null || (typeof v === "number" && !Number.isFinite(v))) return DASH;
    if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toPrecision(4);
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }
  const share = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : DASH);
  function tip(c: any): string {
    if (!c) return "no cell: this family has no importance recorded for this column";
    return [`${share(c.value)} ${measure}`, `n ${num(c.n)}${c.n_col != null ? ` of ${num(c.n_col)} booster sets` : ""}`,
      c.coverage != null ? `coverage ${share(c.coverage)}` : null, `provenance ${c.provenance ?? DASH}`, `read_state ${c.read_state ?? DASH}`,
      c.source_artifact ? `source ${c.source_artifact}` : null].filter(Boolean).join("\n");
  }
</script>

<section>
  <div class="head">
    <h2>Feature impact</h2>
    <Segmented options={[{ value: "asset_class", label: "By asset class" }, { value: "ml_type", label: "By ML type" }, { value: "stage", label: "By stage" }]} bind:value={by} />
    <Segmented options={[{ value: "gain_share", label: "Gain share" }, { value: "split_share", label: "Split share" }]} bind:value={measure} />
  </div>

  {#if heatErr}
    <div class="err panel">Couldn't load the heat map: <span class="mono">{heatErr}</span></div>
  {:else if !heat}
    <div class="muted pad">Loading…</div>
  {:else}
    <div class="panel card">
      <div class="muted small">
        Run {heat.run_id ?? DASH} · computed {heat.computed_at ?? DASH} · read_state <b>{heat.read_state ?? DASH}</b> · {num(heat.n_booster_sets)} booster set(s)
      </div>
      {#if heat.caveat}<div class="caveat small">⚠ {heat.caveat}</div>{/if}
      {#if !(heat.rows ?? []).length}
        <div class="muted pad">No importance cells{heat.read_state && heat.read_state !== "measured" ? ` (${heat.read_state})` : ""}.</div>
      {:else}
        <div class="scroll">
          <table class="hm">
            <thead><tr><th>Family</th>{#each heat.cols as c (c)}<th class="c">{c}</th>{/each}</tr></thead>
            <tbody>
              {#each heat.rows as r (r)}
                <tr>
                  <th class="rh">{r}</th>
                  {#each heat.cols as c (c)}
                    {@const cell = heatCells.get(`${r}\u0000${c}`)}
                    <td class="c cell" class:none={!cell} class:sel={pick?.row === r && pick?.col === c}
                      style:background={cell ? bg(cell.value, heatMax) : ""} title={tip(cell)}
                      onclick={() => { if (cell) { pick = { row: r, col: c }; loadDetail(pick); } }}>
                      {cell ? share(cell.value) : DASH}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="muted small">Click a cell to drill into its features. Share = the family's fraction of each model's total {measure === "gain_share" ? "gain" : "split count"}, averaged over the booster sets in that column that use the family (hover: n of the column's sets), so a column need not sum to 100%.</div>
      {/if}
    </div>

    {#if pick}
      <div class="panel card">
        <div class="ph">{pick.row} · {pick.col}</div>
        {#if detailErr}
          <div class="err">Couldn't load the drill-down: <span class="mono">{detailErr}</span></div>
        {:else if !detail}
          <div class="muted">Loading…</div>
        {:else if !(detail.rows ?? []).length}
          <div class="muted">No feature cells ({detail.read_state ?? DASH}).</div>
        {:else}
          <div class="scroll">
            <table class="hm">
              <thead><tr><th>Feature</th>{#each detail.cols as c (c)}<th class="c">{c}</th>{/each}</tr></thead>
              <tbody>
                {#each detail.rows as r (r)}
                  <tr>
                    <th class="rh">{r}</th>
                    {#each detail.cols as c (c)}
                      {@const cell = detCells.get(`${r}\u0000${c}`)}
                      <td class="c cell" class:none={!cell} style:background={cell ? bg(cell.value, detMax) : ""} title={tip(cell)}>{cell ? share(cell.value) : DASH}</td>
                    {/each}
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
          {#if detail.resolution?.note}<div class="muted small">Resolution: symbol {detail.resolution.symbol ?? DASH} — {detail.resolution.note}</div>{/if}
        {/if}
      </div>
    {/if}
  {/if}

  <div class="panel card">
    <div class="ph">Where to invest in data collection</div>
    {#if !invest}
      <div class="muted">Loading…</div>
    {:else if (invest.items ?? []).length}
      <div class="scroll">
        <table class="inv">
          <thead><tr><th>#</th>{#each investCols as c (c)}<th class:r={investNumeric[c]}>{c}</th>{/each}</tr></thead>
          <tbody>
            {#each invest.items as it, i (i)}
              <tr><td class="mono muted">{i + 1}</td>{#each investCols as c (c)}<td class="mono" class:r={investNumeric[c]}>{cellText(it?.[c])}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="muted small">Every factor the bot sends is its own column, in the bot's order; nothing is blended or recomputed here.</div>
    {:else}
      <div class="muted small">
        Not ranked yet — read_state <b>{invest.read_state ?? DASH}</b>{invest.reason ? `: ${invest.reason}` : ""}.
        When it is, each factor of the ranking (edge × coverage gap ÷ collection cost) is shown as its own column next to the result, not one blended score.
      </div>
    {/if}
  </div>
</section>

<style>
  .scroll { overflow-x: auto; }
  table.inv { border-collapse: collapse; font-size: 12px; width: 100%; }
  table.inv th, table.inv td { padding: 5px 8px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--border); }
  table.inv th { color: var(--muted); font-weight: 500; }
  table.inv .r { text-align: right; }
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  h2 { margin: 0 auto 0 0; font-size: 18px; }
  .card { padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .ph { font-weight: 600; }
  .small { font-size: 12px; }
  .caveat { color: #d4a017; }
  .scroll { overflow-x: auto; }
  table.hm { border-collapse: separate; border-spacing: 2px; font-size: 12px; }
  th, td { padding: 6px 8px; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; text-align: left; }
  th.c, td.c { text-align: center; min-width: 76px; }
  .rh { font-weight: 600; color: var(--text); }
  td.cell { border-radius: 4px; cursor: pointer; font-variant-numeric: tabular-nums; }
  td.cell.none { cursor: default; color: var(--muted);
    background: repeating-linear-gradient(45deg, transparent 0 4px, var(--border) 4px 5px); }
  td.cell.sel { outline: 2px solid var(--accent); }
  .pad { padding: 16px; }
  .err { color: var(--neg); padding: 10px 12px; }
</style>
