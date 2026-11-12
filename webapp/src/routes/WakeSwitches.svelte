<script lang="ts">
  // Admin → Wake switches (UI-REDESIGN-2026-11 addendum 4): the JTA console's wake-
  // switch page — which events wake a Claude session. Source: GET
  // /api/bot/wake-toggles (ungated). Every flip is logged bot-side with who/when.
  //
  // FLIP (addendum 4: "view + flip, same backend as set_wake_toggle"): one press POSTs
  // /api/bot/wake-toggles {key, on} with the SESSION bearer (no confirm step);
  // the bot's answer is shown verbatim and the page re-reads. ⚠️ As of 2026-11-12 the
  // bot gates that POST with its static service token (prop.py::_require_write_token),
  // so a flip from here is refused with 401 until the bot also accepts require_session.
  // That 401 does NOT sign the operator out (api.flipWakeToggle keepSessionOn401).
  // The service token itself never comes to the browser.
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

  let busy = $state(false);
  let result = $state<{ ok: boolean; text: string } | null>(null);
  // One press flips (operator 2026-11-12: "no more gates that I don't explicitly give
  // you permission for") — no confirm step, no signed-out disable; the bot decides and
  // its answer is shown verbatim.
  async function flip(c: { key: string; label: string; to: boolean }) {
    busy = true;
    result = null;
    try {
      const r = await api.flipWakeToggle(c.key, c.to);
      const why = typeof r.body?.detail === "string" ? r.body.detail : r.body?.detail ? JSON.stringify(r.body.detail) : null;
      result = r.status === 200
        ? { ok: true, text: `${c.label} is now ${c.to ? "ON" : "OFF"} (bot confirmed).` }
        : { ok: false, text: `${r.status}${why ? `: ${why}` : ""} — nothing changed.${r.status === 401 ? " The bot accepts flips only with its service token today; flipping from the dashboard needs the bot to accept the session sign-in on this route." : ""}` };
      if (r.status === 200 && r.body?.rows) data = r.body;
    } catch (e) {
      result = { ok: false, text: e instanceof Error ? e.message : String(e) };
    } finally {
      busy = false;
      await load();
    }
  }

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
  {#if result}<div class="panel res" class:okmsg={result.ok} class:err={!result.ok}>{result.text}</div>{/if}

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
          <thead><tr><th>Switch</th><th>State</th><th>Default</th><th>Last changed</th><th>By</th><th></th></tr></thead>
          <tbody>
            {#each rows as r (r.key)}
              <tr>
                <td><b>{r.label ?? r.key}</b> <span class="muted mono">{r.key}</span></td>
                <td><span class="st" class:on={r.on === true} class:off={r.on === false}>{stateText(r.on)}</span>{#if r.on != null && r.default != null && r.on !== r.default}<span class="muted small"> (not default)</span>{/if}</td>
                <td class="muted">{stateText(r.default)}</td>
                <td class="muted">{r.changed_at ? agoFromIso(r.changed_at) : DASH}</td>
                <td class="muted">{r.changed_by ?? DASH}</td>
                <td>{#if r.on === true || r.on === false}<button class="flip" disabled={busy} onclick={() => flip({ key: r.key, label: r.label ?? r.key, to: !r.on })}>{busy ? "Sending…" : `Turn ${r.on ? "off" : "on"}`}</button>{/if}</td>
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
  .flip { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12.5px; }
  .flip:disabled { opacity: 0.5; cursor: not-allowed; }
  .res { padding: 8px 12px; font-size: 13px; }
  .okmsg { color: var(--pos); }
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
