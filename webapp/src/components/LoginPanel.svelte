<script lang="ts">
  // The login form. Lives in the Settings panel (App.svelte) next to the API
  // base-URL field, because that is where the operator already goes to point
  // the app at a host — and because the session and the host it belongs to are
  // the same decision.
  //
  // ⚠️ The password is held in a local `$state` for exactly as long as the
  // operator is typing it, passed to `login()`, and cleared in a `finally`. It
  // is never stored, never logged, and never put in a URL.
  import {
    login,
    clearSession,
    session,
    authPrompt,
    dismissLoginPrompt,
    AuthError,
    authFailureMessage,
  } from "../lib/auth";

  let email = $state("");
  let password = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);
  let hostSideProblem = $state(false);

  async function submit(e: Event) {
    e.preventDefault();
    if (busy) return;
    busy = true;
    error = null;
    hostSideProblem = false;
    try {
      await login(email, password);
      password = "";
      // A fresh session changes what the gated tabs can load; reloading is the
      // simplest correct way to re-run every route's onMount fetch.
      location.reload();
    } catch (err) {
      if (err instanceof AuthError) {
        error = authFailureMessage(err);
        hostSideProblem = err.kind === "auth_unavailable";
      } else {
        error = err instanceof Error ? err.message : String(err);
      }
    } finally {
      password = "";
      busy = false;
    }
  }

  function signOut() {
    clearSession();
    location.reload();
  }

  function expiryLabel(ts: number): string {
    const mins = Math.round((ts - Date.now()) / 60000);
    if (mins <= 0) return "expired";
    if (mins < 60) return `${mins} min`;
    return `${Math.round(mins / 60)} h`;
  }
</script>

<div class="auth">
  <div class="hdr">Session</div>

  {#if $authPrompt}
    <div class="prompt">
      <span>{$authPrompt}</span>
      <button class="link" onclick={dismissLoginPrompt}>dismiss</button>
    </div>
  {/if}

  {#if $session}
    <div class="row signed">
      <span class="ok">● Signed in</span>
      <span class="mono who">{$session.email}</span>
      <span class="muted">· expires in {expiryLabel($session.expiresAt)}</span>
      <button class="ghost" onclick={signOut}>Sign out</button>
    </div>
    <p class="muted note">
      Most of this app is ungated and works signed out. A session is only needed
      for the Data Explorer.
    </p>
  {:else}
    <form onsubmit={submit}>
      <div class="fields">
        <input
          type="email"
          autocomplete="username"
          placeholder="operator email"
          bind:value={email}
          disabled={busy}
          required
        />
        <input
          type="password"
          autocomplete="current-password"
          placeholder="password"
          bind:value={password}
          disabled={busy}
          required
        />
        <button class="save" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </div>
    </form>
    {#if error}
      <div class="err">{error}</div>
      {#if hostSideProblem}
        <p class="muted note">
          Nothing on this page can fix that one — the bot host is missing auth
          configuration. The Data Explorer stays dark until an operator sets it.
        </p>
      {/if}
    {/if}
    <p class="muted note">
      Signing in is only needed for the Data Explorer; every other tab reads
      ungated endpoints and works signed out.
    </p>
  {/if}
</div>

<style>
  .auth { border-top: 1px solid var(--border); margin-top: 14px; padding-top: 12px; }
  .hdr { color: var(--muted); font-size: 12px; margin-bottom: 8px; }
  .fields { display: flex; gap: 8px; flex-wrap: wrap; }
  .fields input {
    flex: 1;
    min-width: 160px;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 8px 10px;
  }
  .save { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 14px; cursor: pointer; }
  .save:disabled { opacity: 0.6; cursor: default; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .ok { color: var(--pos); }
  .who { font-size: 12.5px; }
  .ghost { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 5px 12px; cursor: pointer; font-size: 12.5px; }
  .prompt {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
    margin-bottom: 10px;
    font-size: 12.5px;
  }
  .link { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 12px; text-decoration: underline; padding: 0; }
  .err { color: var(--neg); font-size: 12.5px; margin-top: 8px; }
  .note { font-size: 12px; margin: 8px 0 0; }
</style>
