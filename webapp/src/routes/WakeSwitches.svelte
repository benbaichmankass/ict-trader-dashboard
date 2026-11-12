<script lang="ts">
  // Admin → Wake switches (UI-REDESIGN-2026-11 addendum 4): the JTA console's wake-
  // switch page — which events wake a Claude session. Source: GET
  // /api/bot/wake-toggles (ungated). Every flip is logged bot-side with who/when.
  //
  // ⚠️ VIEW ONLY for now. The bot's POST /api/bot/wake-toggles is gated by the static
  // DASHBOARD_API_TOKEN bearer, NOT by the SPA's session login. Putting that token in
  // the browser would be a new credential surface, and a 401 from it would sign the
  // operator out (the SPA clears its session on any 401). Flipping needs the bot to
  // accept require_session on that POST — the same pattern as /trade-approvals.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { DASH, agoFromIso } from "../lib/format";

  let data = $state<any>(null);
  let error = $state<string | null>(null);

  async function load() {
    try { data = await api.wakeToggles(); error = null; }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
  }
  onMount(load);

  const groups = $derived.by(() => {
    const m = new Map<string, any[]>();
    for (const r of (data?.rows ?? []) as any[]) {
      const g = r?.group ?? "other";
      (m.get(g) ?? m.set(g, []).get(g)!).push(r);
    }
    return [...m.entries()];
  });
  const stateText = (on: boolean | null | undefined) => (on === true ? "ON" : on === false ? "OFF" : DASH);
</script>

<section>
  <div class="head"><h2>Wake switches</h2><button class="refresh" onclick={load}>↻ Refresh</button></div>
  <div class="muted small">Which events wake a Claude session. Source: /api/bot/wake-toggles{data?.population ? ` · ${data.population}` : ""}{data?.read_state ? ` · read_state ${data.read_state}` : ""}.</div>
  <div class="note panel">Flipping from this dashboard is not wired yet: the bot accepts flips only with its service token, not your session sign-in. Flip from the console for now.</div>

  {#if error}
    <div class="err panel">Couldn't load wake switches: <span class="mono">{error}</span></div>
  {:else if !data}
    <div class="muted pad">Loading…</div>
  {:else}
    {#if data.read_state && data.read_state !== "read"}
      <div class="warn panel">State is <b>{data.read_state}</b>{data.note ? ` — ${data.note}` : ""}.</div>
    {/if}
    {#each groups as [g, rows] (g)}
      <div class="panel grp">
        <div class="ph">{g}</div>
        <table>
          <thead><tr><th>Switch</th><th>State</th><th>Default</th><th>Last changed</th><th>By</th></tr></thead>
          <tbody>
            {#each rows as r (r.key)}
              <tr>
                <td><b>{r.label ?? r.key}</b> <span class="muted mono">{r.key}</span></td>
                <td><span class="st" class:on={r.on === true} class:off={r.on === false}>{stateText(r.on)}</span>{#if r.on != null && r.default != null && r.on !== r.default}<span class="muted small"> (not default)</span>{/if}</td>
                <td class="muted">{stateText(r.default)}</td>
                <td class="muted">{r.changed_at ? agoFromIso(r.changed_at) : DASH}</td>
                <td class="muted">{r.changed_by ?? DASH}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/each}
    {#if (data.recent_flips ?? []).length}
      <div class="panel grp">
        <div class="ph">Recent flips</div>
        <table>
          <thead><tr><th>When (UTC)</th><th>Switch</th><th>Change</th><th>By</th></tr></thead>
          <tbody>
            {#each data.recent_flips as f, i (i)}
              <tr><td class="mono">{String(f.at ?? "").slice(0, 16).replace("T", " ") || DASH}</td><td class="mono">{f.key ?? DASH}</td><td>{stateText(f.old)} → {stateText(f.new)}</td><td class="muted">{f.by ?? DASH}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 18px; }
  .refresh { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 5px 12px; cursor: pointer; font-size: 13px; }
  .note { padding: 8px 12px; font-size: 12.5px; color: var(--muted); }
  .warn { padding: 8px 12px; color: #d4a017; }
  .grp { padding: 4px 4px 8px; overflow-x: auto; }
  .ph { padding: 10px 10px 6px; font-weight: 600; text-transform: capitalize; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--border); font-size: 12px; }
  tbody tr { border-bottom: 1px solid var(--border); }
  .st { font-weight: 700; font-size: 12px; padding: 1px 7px; border-radius: 4px; border: 1px solid var(--border); }
  .st.on { color: var(--pos); border-color: var(--pos); }
  .st.off { color: var(--muted); }
  .muted { color: var(--muted); }
  .small { font-size: 12px; }
  .pad { padding: 12px; }
  .err { padding: 10px 12px; color: var(--neg); }
  .mono { font-variant-numeric: tabular-nums; }
</style>
