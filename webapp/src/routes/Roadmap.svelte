<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { num } from "../lib/format";

  let summary = $state<any | null>(null);
  let milestones = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let open = $state<Record<string, boolean>>({});

  async function load() {
    loading = true;
    error = null;
    try {
      const raw = await api.roadmap();
      summary = raw?.summary ?? null;
      milestones = raw?.milestones ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  const pct = $derived(
    summary && summary.total ? Math.round((100 * (summary.done ?? 0)) / summary.total) : 0,
  );
</script>

<section>
  <h2>Roadmap</h2>
  {#if error}
    <div class="err panel">Couldn't load roadmap: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    {#if summary}
      <div class="panel roll">
        <div class="bar"><div class="fill" style:width={`${pct}%`}></div></div>
        <div class="stats muted">
          {num(summary.done)} done · {num(summary.active)} active · {num(summary.pending)} planned · {num(summary.total)} total ({pct}%)
        </div>
      </div>
    {/if}
    <div class="list">
      {#each milestones as m (m.id)}
        <div class="panel ms">
          <button class="msh" onclick={() => (open = { ...open, [m.id]: !open[m.id] })}>
            <span class="emoji">{m.statusEmoji ?? "•"}</span>
            <span class="id">{m.id}</span>
            <span class="focus">{m.focus ?? ""}</span>
            <span class="lbl muted">{m.statusLabel ?? m.status ?? ""}</span>
            <span class="chev">{open[m.id] ? "▾" : "▸"}</span>
          </button>
          {#if open[m.id] && m.statusDetail}
            <div class="detail">{m.statusDetail}</div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .roll { padding: 14px; }
  .bar { height: 8px; background: var(--panel-2); border-radius: 5px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); }
  .stats { font-size: 12.5px; margin-top: 8px; }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .ms { overflow: hidden; }
  .msh { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; background: none; border: none; color: var(--text); padding: 12px 14px; cursor: pointer; font-size: 13.5px; }
  .id { font-weight: 600; }
  .focus { flex: 1; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lbl { font-size: 12px; }
  .chev { color: var(--muted); }
  .detail { padding: 0 14px 14px; white-space: pre-wrap; font-size: 13px; line-height: 1.5; color: var(--muted); }
  .pad { padding: 16px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
