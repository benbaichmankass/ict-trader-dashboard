<script lang="ts">
  // UI-UPGRADE-1-AUTH — sign-in screen: Google, then passkey (or first-device enrolment).
  import { onMount } from 'svelte';
  import { googleSignIn, passkeySignIn, enrolFirstDevice } from '../lib/passkey';

  // Called once a device session is stored (the parent is a runes component).
  export let onsignedin: () => void = () => {};

  let googleBtn: HTMLElement;
  let preauth = '';
  let passkeyEnrolled = true;
  let enrolCode = '';
  let label = guessLabel();
  let busy = false;
  let msg = '';

  function guessLabel(): string {
    const ua = navigator.userAgent;
    const os = /iPhone|iPad/.test(ua) ? 'iPhone' : /Android/.test(ua) ? 'Android' : /Mac/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : 'Device';
    const br = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : /Firefox\//.test(ua) ? 'Firefox' : 'browser';
    return `${os} · ${br}`;
  }

  const WORDS: Record<string, string> = {
    email_not_allowlisted: 'That Google account is not allowed here.',
    email_not_verified: 'That Google account has no verified email.',
    invalid_google_token: 'Google sign-in could not be verified. Try again.',
    invalid_enrol_code: 'That enrolment code is wrong, used or expired.',
    invalid_preauth_ticket: 'Sign-in timed out. Start again.',
    too_many_attempts: 'Too many attempts. Wait a few minutes.',
    assertion_failed: 'Passkey check failed.',
    auth_unavailable: 'Sign-in is not configured on the server yet.',
    no_passkey_enrolled: 'No passkey is enrolled yet — enter the enrolment code.',
  };
  const say = (e: any) => (msg = WORDS[e?.error] ?? (e?.name === 'NotAllowedError' ? 'Passkey prompt was cancelled.' : 'Sign-in failed.'));

  onMount(async () => {
    try {
      const r = await googleSignIn(googleBtn);
      preauth = r.preauth;
      passkeyEnrolled = r.passkeyEnrolled;
      msg = '';
    } catch (e) {
      say(e);
    }
  });

  async function usePasskey() {
    busy = true;
    msg = '';
    try {
      await passkeySignIn(preauth, label);
      onsignedin();
    } catch (e) {
      say(e);
    } finally {
      busy = false;
    }
  }
  async function enrol() {
    busy = true;
    msg = '';
    try {
      await enrolFirstDevice(preauth, enrolCode.trim(), label);
      onsignedin();
    } catch (e) {
      say(e);
    } finally {
      busy = false;
    }
  }
</script>

<main class="signin">
  <h3>Sign in with Google + passkey</h3>
  {#if !preauth}
    <p>Sign in with Google, then confirm with your passkey.</p>
    <div bind:this={googleBtn}></div>
  {:else}
    <label>Device name <input bind:value={label} maxlength="80" /></label>
    {#if passkeyEnrolled}
      <button disabled={busy} on:click={usePasskey}>Use passkey</button>
      <details>
        <summary>New device with no passkey yet?</summary>
        <input placeholder="enrolment code" bind:value={enrolCode} autocomplete="off" />
        <button disabled={busy || !enrolCode.trim()} on:click={enrol}>Enrol this device</button>
        <p class="hint">Ask for a code with the <code>passkey-enrol-code</code> system action; it arrives in the private SYSTEM chat.</p>
      </details>
    {:else}
      <p>No passkey is registered yet. Enter the one-time enrolment code from the SYSTEM chat.</p>
      <input placeholder="enrolment code" bind:value={enrolCode} autocomplete="off" />
      <button disabled={busy || !enrolCode.trim()} on:click={enrol}>Enrol this device</button>
    {/if}
  {/if}
  {#if msg}<p class="err" role="alert">{msg}</p>{/if}
</main>

<style>
  .signin { max-width: 24rem; margin: 8px 0; padding: 0; display: grid; gap: 12px; }
  .err { color: #c0392b; }
  .hint { opacity: 0.7; font-size: 0.85em; }
  input { width: 100%; box-sizing: border-box; }
</style>
