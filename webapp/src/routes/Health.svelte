<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso, DASH } from "../lib/format";

  let services = $state<any[]>([]);
  let systemctl = $state<boolean | null>(null);
  let latest = $state<any | null>(null);
  let banners = $state<any[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [svc, lat, notif] = await Promise.all([
        api.healthServices().catch(() => null),
        api.healthLatest().catch(() => null),
        api.notifications().catch(() => null),
      ]);
      services = svc?.services ?? [];
      systemctl = svc?.systemctl_available ?? null;
      latest = lat?.snapshot ?? null;
      banners = notif?.banners ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function stateClass(s: string): string {
    const v = (s ?? "").toLowerCase();
    if (v === "active") return "pos";
    if (v === "failed" || v === "inactive") return "neg";
    return "warn";
  }
  function bannerClass(sev: string): string {
    const v = (sev ?? "").toLowerCase();
    if (v === "alert") return "neg";
    if (v === "warning") return "warn";
    return "flat";
  }
</script>

<section>
  <h2>Health</h2>
  {#if error}
    <div class="err panel">Couldn't load health: <span class="mono">{error}</span></div>
  {:else if loading}
    <div class="muted pad">Loading…</div>
  {:else}
    {#if banners.length}
      <div class="banners">
        {#each banners as b, i (i)}
          <div class="banner {bannerClass(b.severity)}">
            <span class="bkind">{b.kind ?? b.severity}</span>
            <span class="bmsg">{b.message}</span>
            {#if b.since}<span class="muted when">{agoFromIso(b.since)}</span>{/if}
          </div>
        {/each}
      </div>
    {/if}

    <div class="panel pad">
      <div class="ph">Services {#if systemctl === false}<span class="muted">(systemctl unavailable)</span>{/if}</div>
      {#if services.length === 0}
        <div class="muted">No service state reported.</div>
      {:else}
        <div class="svcs">
          {#each services as s (s.unit)}
            <div class="svc">
              <span class="dot {stateClass(s.state)}"></span>
              <span class="unit mono">{s.unit}</span>
              <span class="state {stateClass(s.state)}">{s.state}{s.sub_state ? ` · ${s.sub_state}` : ""}</span>
              <span class="muted since">{s.active_enter_iso ?? DASH}</span>
            </div>
          {/each}
        </div>
      {/if}
    </div>

    {#if latest}
      <div class="panel pad">
        <div class="ph">Latest health snapshot</div>
        <pre class="snap">{JSON.stringify(latest, null, 2)}</pre>
      </div>
    {/if}
  {/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 14px; }
  h2 { margin: 0; font-size: 18px; }
  .pad { padding: 14px; }
  .ph { font-weight: 600; margin-bottom: 10px; font-size: 13.5px; }
  .banners { display: flex; flex-direction: column; gap: 6px; }
  .banner { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 8px; border: 1px solid var(--border); font-size: 13px; }
  .banner.neg { border-color: var(--neg); }
  .banner.warn { border-color: #e0a800; }
  .bkind { font-size: 11px; text-transform: uppercase; color: var(--muted); }
  .bmsg { flex: 1; }
  .when { font-size: 12px; }
  .svcs { display: flex; flex-direction: column; gap: 6px; }
  .svc { display: flex; align-items: center; gap: 10px; font-size: 13px; flex-wrap: wrap; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; background: var(--muted); }
  .dot.pos { background: var(--pos); }
  .dot.neg { background: var(--neg); }
  .dot.warn { background: #e0a800; }
  .unit { flex: 1; min-width: 160px; }
  .state.pos { color: var(--pos); }
  .state.neg { color: var(--neg); }
  .state.warn { color: #e0a800; }
  .since { font-size: 12px; }
  .snap { overflow-x: auto; font-size: 12px; margin: 0; white-space: pre; max-height: 400px; }
  .err { padding: 10px 12px; color: var(--neg); }
</style>
