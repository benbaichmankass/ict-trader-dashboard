<script lang="ts">
  // UI-UPGRADE-1-AUTH — Admin → Devices: the revocable device-session list.
  import { onMount } from 'svelte';
  import { authCall, clearSession, signalUnauthorized } from '../lib/session';
  import { addThisDevice } from '../lib/passkey';

  interface Row {
    handle: string; label: string; user_agent: string; ip: string;
    created_at: number; last_seen_at: number; expires_at: number;
    revoked_at: number | null; active: boolean; current: boolean;
  }
  let rows: Row[] = [];
  let err = '';
  let busy = false;

  const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : '—');

  async function load() {
    try {
      rows = (await authCall<{ sessions: Row[] }>('/api/auth/sessions')).sessions;
      err = '';
    } catch (e: any) {
      if (e?.status === 401) return signalUnauthorized();
      err = 'Could not load devices.';
    }
  }
  // POST twin of DELETE: the API's CORS allow-list is GET/POST only.
  async function revoke(r: Row) {
    if (!confirm(`Sign out “${r.label}”?`)) return;
    busy = true;
    try {
      await authCall(`/api/auth/sessions/${r.handle}/revoke`, { method: 'POST', body: {} });
      if (r.current) return signalUnauthorized();
      await load();
    } finally { busy = false; }
  }
  async function signOutEverywhere() {
    if (!confirm('Sign out every other device?')) return;
    busy = true;
    try { await authCall('/api/auth/sessions/revoke-others', { method: 'POST', body: {} }); await load(); }
    finally { busy = false; }
  }
  async function addDevice() {
    busy = true;
    try { await addThisDevice(prompt('Name for this device’s passkey', 'This device') || 'This device'); err = ''; }
    catch { err = 'Passkey registration failed or was cancelled.'; }
    finally { busy = false; }
  }
  onMount(load);
</script>

<section>
  <h2>Devices</h2>
  <p>Each row is a signed-in device (30-day sliding session). Revoking takes effect on its next request.</p>
  <div class="bar">
    <button disabled={busy} on:click={addDevice}>Register a passkey on this device</button>
    <button disabled={busy} on:click={signOutEverywhere}>Sign out everywhere else</button>
    <button on:click={() => { clearSession(); signalUnauthorized(); }}>Sign out here</button>
  </div>
  {#if err}<p class="err" role="alert">{err}</p>{/if}
  <table>
    <thead><tr><th>Device</th><th>Last seen</th><th>Created</th><th>Expires</th><th>IP</th><th></th></tr></thead>
    <tbody>
      {#each rows as r (r.handle)}
        <tr class:revoked={!r.active}>
          <td title={r.user_agent}>{r.label}{#if r.current} <b>(this device)</b>{/if}</td>
          <td>{when(r.last_seen_at)}</td><td>{when(r.created_at)}</td>
          <td>{r.revoked_at ? 'revoked ' + when(r.revoked_at) : when(r.expires_at)}</td>
          <td>{r.ip || '—'}</td>
          <td>{#if r.active}<button disabled={busy} on:click={() => revoke(r)}>Revoke</button>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<style>
  .bar { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
  .err { color: #c0392b; }
  .revoked { opacity: 0.5; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 4px 8px; }
  @media (max-width: 640px) { table { display: block; overflow-x: auto; } }
</style>
