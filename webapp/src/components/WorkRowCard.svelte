<script lang="ts">
  // Expanded detail card for one work-queue row (UI-WORK-QUEUE-DND). The snapshot carries a trimmed
  // projection, so the full row is fetched from GET /api/bot/work/items/{id} on open (re-read when `rev`
  // changes, i.e. after a reorder). Until it answers, the snapshot row's own fields are shown. Null → "—".
  import { api } from "../lib/api";
  import { DASH, agoFromIso } from "../lib/format";
  import { rowNotes } from "../lib/workReorder";

  let { row, rev = 0 }: { row: any; rev?: number } = $props();
  let full = $state<any>(null);
  let err = $state<string | null>(null);
  let allNotes = $state(false);

  $effect(() => {
    void rev;
    const id = row?.id;
    if (!id) return;
    let live = true;
    api.workItem(id).then((r: any) => { if (live) { full = r?.item ?? null; err = full ? null : "no row in the answer"; } })
      .catch((e: unknown) => { if (live) err = e instanceof Error ? e.message : String(e); });
    return () => { live = false; };
  });

  const r = $derived({ ...(row ?? {}), ...(full ?? {}) });
  const rank = $derived(full?.priority_rank ?? row?.priorityRank);
  const due = $derived(r.due_at ?? r.due_rule?.due_date ?? null);
  const notes = $derived(rowNotes(full));
  const txt = (v: unknown) => (v == null || v === "" ? DASH : typeof v === "string" ? v : JSON.stringify(v));
  const list = (v: unknown) => (Array.isArray(v) && v.length ? v.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(" · ") : DASH);
  const fields = $derived<[string, string][]>([
    ["state", txt(r.state)],
    ["owner", txt(r.owner)],
    ["tier", txt(r.tier)],
    ["priority_rank", txt(rank)],
    ["roadmap", list(r.roadmap)],
    ["blocked_on", list(r.blocked_on)],
    ["PRs", list(r.prs)],
    ["due_by", txt(due)],
    ["updated", r.updated_at || r.updatedAt ? agoFromIso(r.updated_at ?? r.updatedAt) : DASH],
  ]);
  const long = $derived(notes.join("").length > 360 || notes.length > 1);
</script>

<div class="rcard">
  <div class="rt">{r.title ?? DASH}</div>
  <div class="rid mono">{r.id}</div>
  <dl>
    {#each fields as [k, v]}<dt>{k}</dt><dd>{v}</dd>{/each}
  </dl>
  {#if (row?.asks ?? []).length}
    <div class="rk">Asks</div>
    {#each row.asks as a}<div class="note">{a.what ?? DASH}{a.ref ? ` (${a.ref})` : ""}</div>{/each}
  {/if}
  <div class="rk">Notes{notes.length ? ` · newest first` : ""}</div>
  {#if !full && !err}<div class="muted small">Loading the full row…</div>{/if}
  {#if err}<div class="muted small">Full row not read ({err}) — showing the snapshot fields only.</div>{/if}
  {#if full && !notes.length}<div class="muted small">{DASH}</div>{/if}
  {#each long && !allNotes ? notes.slice(0, 1) : notes as n}
    <div class="note" class:clamp={long && !allNotes}>{n}</div>
  {/each}
  {#if long}<button class="more" onclick={() => (allNotes = !allNotes)}>{allNotes ? "Collapse notes" : "Show full notes"}</button>{/if}
</div>

<style>
  .rcard { border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); padding: 8px 10px; margin: 3px 0 6px; font-size: 12px; white-space: normal; }
  .rt { font-weight: 600; font-size: 12.5px; line-height: 1.35; }
  .rid { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
  dl { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 1px 10px; margin: 4px 0; }
  dt { color: var(--muted); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .rk { color: var(--muted); margin-top: 6px; font-size: 11.5px; }
  .note { margin-top: 2px; overflow-wrap: anywhere; white-space: pre-wrap; }
  .note.clamp { display: -webkit-box; -webkit-line-clamp: 5; line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; }
  .more { margin-top: 4px; font-size: 11.5px; background: none; border: 0; color: var(--accent); cursor: pointer; padding: 2px 0; }
</style>
