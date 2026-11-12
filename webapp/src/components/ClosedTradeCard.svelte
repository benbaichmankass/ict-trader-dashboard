<script lang="ts">
  // Expanded CLOSED-trade card (UI-REDESIGN-2026-11 addenda 2, 3, 5): what got us in,
  // how it closed, the brackets and their history, and the CHART SNAPSHOT.
  //
  // The snapshot is built ONCE at close and stored with the trade (bot lane
  // CLOSED-TRADE-SNAPSHOT); this card only READS it. That route does not exist
  // yet, so the snapshot slot says so — no live re-render stands in for it.
  import { onMount } from "svelte";
  import { api, type ClosedTrade, type BracketHistory } from "../lib/api";
  import { packageForClosedTrade } from "../lib/brackets";
  import { money, num, signClass, DASH } from "../lib/format";
  import EntryWhy from "./EntryWhy.svelte";

  let { t }: { t: ClosedTrade } = $props();
  const a = $derived(t as any);

  let pkg = $state<any>(null);
  let pkgState = $state("loading");
  let brackets = $state<BracketHistory | null>(null);
  let bracketState = $state("—");

  const sell = $derived(/^(s|short)/i.test(String(t.direction ?? t.side ?? "")));
  const exitReason = $derived(a.closeReason ?? a.exitReason ?? a.exit_reason ?? pkg?.closeReason ?? null);
  const iso = (v: string | null | undefined) => (v ? String(v).slice(0, 16).replace("T", " ") + "Z" : DASH);
  const lvl = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(+v.toPrecision(7)) : DASH);
  // Levels set at entry: the package's own SL/TP (the decision), else the first history level.
  const entrySl = $derived(pkg?.sl ?? (brackets?.levels ?? []).find((l) => l.kind === "sl")?.price ?? null);
  const entryTp = $derived(pkg?.tp ?? (brackets?.levels ?? []).find((l) => l.kind === "tp")?.price ?? null);

  onMount(() => {
    let alive = true;
    packageForClosedTrade(t)
      .then(async (x) => {
        if (!alive) return;
        pkg = x;
        pkgState = x ? "linked" : "no linked order package";
        if (!x?.orderPackageId) { bracketState = "no linked order package"; return; }
        bracketState = "loading";
        try {
          brackets = await api.bracketsHistory({ orderPackageId: String(x.orderPackageId) }, "15m");
          if (alive) bracketState = brackets?.read_state ?? "—";
        } catch (e) {
          if (alive) bracketState = `could not look (${e instanceof Error ? e.message : String(e)})`;
        }
      })
      .catch(() => { if (alive) { pkgState = "could not look"; bracketState = "could not look"; } });
    return () => { alive = false; };
  });
</script>

<div class="card">
  <dl>
    <div><dt>Side</dt><dd class={sell ? "neg" : "pos"}>{sell ? "SHORT" : "LONG"}</dd></div>
    <div><dt>Entry</dt><dd class="mono">{money(t.entryPrice)}</dd></div>
    <div><dt>Exit</dt><dd class="mono">{money(t.exitPrice)}</dd></div>
    <div><dt>Size</dt><dd class="mono">{t.qty == null ? DASH : num(t.qty, 4)}</dd></div>
    <div><dt>P&amp;L</dt><dd class="mono {signClass(t.pnl)}">{t.pnl == null ? DASH : money(t.pnl, { sign: true })}</dd></div>
    <div><dt>P&amp;L provenance</dt><dd>{a.pnlProvenance ?? DASH}</dd></div>
    <div><dt>Exit reason</dt><dd><b>{exitReason ?? DASH}</b></dd></div>
    <div><dt>Opened</dt><dd class="mono">{iso(t.openedAt)}</dd></div>
    <div><dt>Closed</dt><dd class="mono">{iso(t.closedAt)}</dd></div>
    <div><dt>Account</dt><dd>{t.account ?? DASH}</dd></div>
    <div><dt>Strategy</dt><dd>{t.strategy ?? pkg?.strategy ?? DASH}</dd></div>
  </dl>

  <div class="snap">
    <div class="st">Chart snapshot</div>
    <div class="muted small">— Not available yet: the snapshot is stored with the trade at close (bot lane CLOSED-TRADE-SNAPSHOT), and its read route has not shipped. Nothing is drawn in its place.</div>
  </div>

  <div class="brk">
    <div class="st">Brackets <span class="muted">· {bracketState}</span></div>
    <div class="kv">
      <span>At entry: SL <b class="mono">{lvl(entrySl)}</b> · TP <b class="mono">{lvl(entryTp)}</b></span>
      <span>Moves: <b>{brackets ? (brackets.updates ?? []).length : DASH}</b></span>
    </div>
    {#if (brackets?.updates ?? []).length}
      <table>
        <thead><tr><th>When (UTC)</th><th>Level</th><th class="r">From</th><th class="r">To</th></tr></thead>
        <tbody>
          {#each brackets?.updates ?? [] as u, i (i)}
            <tr>
              <td class="mono">{iso(u.ts ?? u.bar_ts)}</td>
              <td>{String(u.kind ?? DASH).toUpperCase()}</td>
              <td class="r mono">{lvl(u.from)}</td>
              <td class="r mono">{lvl(u.to)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    {#if (brackets?.partial_reasons ?? []).length}<div class="muted small">partial: {brackets?.partial_reasons?.join(", ")}</div>{/if}
  </div>

  <EntryWhy {pkg} {pkgState} />
</div>

<style>
  .card { padding: 10px 12px 12px; background: var(--panel-2); border-top: 1px solid var(--border); white-space: normal; }
  dl { margin: 0 0 10px; display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px 12px; }
  @media (max-width: 640px) { dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } .card { padding: 8px; } }
  dt { color: var(--muted); font-size: 11px; }
  dd { margin: 2px 0 0; font-size: 13px; font-weight: 600; }
  .snap, .brk { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; font-size: 12px; }
  .st { font-weight: 600; margin-bottom: 4px; }
  .kv { display: flex; flex-wrap: wrap; gap: 4px 16px; }
  table { border-collapse: collapse; margin-top: 6px; font-size: 12px; }
  th, td { padding: 3px 10px 3px 0; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; }
  .r { text-align: right; }
  .muted { color: var(--muted); }
  .small { font-size: 11.5px; }
  .mono { font-variant-numeric: tabular-nums; }
  .pos { color: var(--pos); } .neg { color: var(--neg); }
</style>
