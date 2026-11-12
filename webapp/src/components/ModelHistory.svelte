<script lang="ts">
  // Promotion history folded into Strategies & Models (UI-REDESIGN-2026-11: "Remove
  // Promotion ladder as a page; fold the promotion history into strategies/models").
  // Reads the registry row's own logs — nothing is derived:
  //   stage_history[] {at, by, from_stage, to_stage, reason}  — the promotions
  //   history[]       {at, by, from_status, to_status, reason} — registration,
  //                    re-trains and status changes (the newest entry is shown as
  //                    "latest", e.g. the last re-train)
  import { agoFromIso, DASH } from "../lib/format";

  let { row }: { row: any } = $props();
  let open = $state(false);

  const stages = $derived<any[]>(Array.isArray(row?.stage_history) ? row.stage_history : []);
  const log = $derived<any[]>(Array.isArray(row?.history) ? row.history : []);
  // Status CHANGES from the history log (from ≠ to, not the initial registration).
  const statusMoves = $derived(log.filter((h) => h?.from_status != null && h.from_status !== h.to_status));
  const latest = $derived(log.length ? [...log].sort((a, b) => String(b.at).localeCompare(String(a.at)))[0] : null);
  const moves = $derived(
    [
      ...stages.map((s) => ({ at: s.at, by: s.by, from: s.from_stage, to: s.to_stage, reason: s.reason, kind: "stage" })),
      ...statusMoves.map((h) => ({ at: h.at, by: h.by, from: h.from_status, to: h.to_status, reason: h.reason, kind: "status" })),
    ].sort((a, b) => String(b.at).localeCompare(String(a.at))),
  );
  const iso = (v: unknown) => (v ? String(v).slice(0, 16).replace("T", " ") + "Z" : DASH);
</script>

<div class="mh-hist small">
  <span class="muted">registered {row?.created_at ? `${iso(row.created_at)} (${agoFromIso(row.created_at)})` : DASH}</span>
  <span class="muted" title={latest?.reason ?? ""}>· latest: {latest ? `${latest.reason ?? DASH} · ${agoFromIso(latest.at)}` : DASH}</span>
  <button class="link" onclick={() => (open = !open)}>
    {open ? "▾" : "▸"} Promotion history ({moves.length})
  </button>
  {#if open}
    {#if moves.length}
      <table>
        <thead><tr><th>When (UTC)</th><th>Move</th><th>By</th><th>Reason</th></tr></thead>
        <tbody>
          {#each moves as m, i (i)}
            <tr>
              <td class="mono">{iso(m.at)}</td>
              <td><span class="mono">{m.from ?? DASH} → {m.to ?? DASH}</span> <span class="muted">({m.kind})</span></td>
              <td class="muted">{m.by ?? DASH}</td>
              <td class="reason">{m.reason ?? DASH}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <div class="muted">No stage or status change recorded for this model ({log.length} history entr{log.length === 1 ? "y" : "ies"}, none a move).</div>
    {/if}
  {/if}
</div>

<style>
  .mh-hist { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; margin: 2px 0 6px 18px; }
  .small { font-size: 12px; }
  .link { background: none; border: none; color: var(--accent, #4c8dff); cursor: pointer; padding: 0; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  th, td { padding: 4px 6px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; }
  .reason { overflow-wrap: anywhere; max-width: 640px; }
</style>
