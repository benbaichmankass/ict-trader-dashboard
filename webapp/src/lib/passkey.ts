// UI-UPGRADE-1-AUTH (SPA side) — Google ID token + WebAuthn passkey flows.
import { authCall, saveSession } from './session';

declare const google: any; // Google Identity Services (https://accounts.google.com/gsi/client)

interface IssuedSession {
  session_token: string;
  session_handle: string;
  expires_at: number;
}

const b64uToBuf = (s: string): ArrayBuffer => {
  const p = s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4);
  const bin = atob(p);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
};
const bufToB64u = (b: ArrayBuffer): string => {
  let s = '';
  new Uint8Array(b).forEach((c) => (s += String.fromCharCode(c)));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

export function loadGoogleScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if ((window as any).google?.accounts?.id) return resolve();
    const el = document.createElement('script');
    el.src = 'https://accounts.google.com/gsi/client';
    el.async = true;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error('google_script_failed'));
    document.head.appendChild(el);
  });
}

/** Renders the Google button; resolves with the pre-auth ticket once the API accepts the ID token. */
export async function googleSignIn(
  container: HTMLElement,
): Promise<{ preauth: string; passkeyEnrolled: boolean }> {
  const cfg = await authCall<{ google_client_id: string | null }>('/api/auth/config', { token: null });
  if (!cfg.google_client_id) throw { status: 503, error: 'auth_unavailable' };
  await loadGoogleScript();
  return new Promise((resolve, reject) => {
    google.accounts.id.initialize({
      client_id: cfg.google_client_id,
      callback: async (resp: { credential: string }) => {
        try {
          const r = await authCall<{ preauth_ticket: string; passkey_enrolled: boolean }>(
            '/api/auth/google',
            { body: { id_token: resp.credential }, token: null },
          );
          resolve({ preauth: r.preauth_ticket, passkeyEnrolled: r.passkey_enrolled });
        } catch (e) {
          reject(e);
        }
      },
    });
    google.accounts.id.renderButton(container, { theme: 'outline', size: 'large', text: 'signin_with' });
  });
}

function toRequestOptions(o: any): PublicKeyCredentialRequestOptions {
  return {
    ...o,
    challenge: b64uToBuf(o.challenge),
    allowCredentials: (o.allowCredentials ?? []).map((c: any) => ({ ...c, id: b64uToBuf(c.id) })),
  };
}
function toCreationOptions(o: any): PublicKeyCredentialCreationOptions {
  return {
    ...o,
    challenge: b64uToBuf(o.challenge),
    user: { ...o.user, id: b64uToBuf(o.user.id) },
    excludeCredentials: (o.excludeCredentials ?? []).map((c: any) => ({ ...c, id: b64uToBuf(c.id) })),
  };
}

function creationToJson(c: PublicKeyCredential) {
  const r = c.response as AuthenticatorAttestationResponse;
  return {
    id: c.id,
    rawId: bufToB64u(c.rawId),
    type: c.type,
    response: {
      clientDataJSON: bufToB64u(r.clientDataJSON),
      attestationObject: bufToB64u(r.attestationObject),
      transports: (r as any).getTransports?.() ?? [],
    },
  };
}
function assertionToJson(c: PublicKeyCredential) {
  const r = c.response as AuthenticatorAssertionResponse;
  return {
    id: c.id,
    rawId: bufToB64u(c.rawId),
    type: c.type,
    response: {
      clientDataJSON: bufToB64u(r.clientDataJSON),
      authenticatorData: bufToB64u(r.authenticatorData),
      signature: bufToB64u(r.signature),
      userHandle: r.userHandle ? bufToB64u(r.userHandle) : null,
    },
  };
}

function store(s: IssuedSession): void {
  saveSession({ token: s.session_token, handle: s.session_handle, expiresAt: s.expires_at });
}

/** Returning device: passkey assertion -> device session. */
export async function passkeySignIn(preauth: string, deviceLabel: string): Promise<void> {
  const b = await authCall<{ challenge_id: string; options: any }>('/api/auth/passkey/assert/begin', {
    body: { preauth_ticket: preauth },
    token: null,
  });
  const cred = (await navigator.credentials.get({ publicKey: toRequestOptions(b.options) })) as PublicKeyCredential;
  const s = await authCall<IssuedSession>('/api/auth/passkey/assert/finish', {
    body: {
      preauth_ticket: preauth,
      challenge_id: b.challenge_id,
      credential: assertionToJson(cred),
      device_label: deviceLabel,
    },
    token: null,
  });
  store(s);
}

/** First device: pre-auth ticket + the one-time enrolment code from the SYSTEM ping. Signs the device in. */
export async function enrolFirstDevice(preauth: string, enrolCode: string, label: string): Promise<void> {
  const b = await authCall<{ challenge_id: string; options: any }>('/api/auth/passkey/register/begin', {
    body: { preauth_ticket: preauth, enrol_code: enrolCode, label },
    token: null,
  });
  const cred = (await navigator.credentials.create({ publicKey: toCreationOptions(b.options) })) as PublicKeyCredential;
  const s = await authCall<IssuedSession>('/api/auth/passkey/register/finish', {
    body: { challenge_id: b.challenge_id, credential: creationToJson(cred) },
    token: null,
  });
  store(s);
}

/** Additional device from an already-signed-in one (no enrolment code). */
export async function addThisDevice(label: string): Promise<void> {
  const b = await authCall<{ challenge_id: string; options: any }>('/api/auth/passkey/register/begin', {
    body: { label },
  });
  const cred = (await navigator.credentials.create({ publicKey: toCreationOptions(b.options) })) as PublicKeyCredential;
  await authCall('/api/auth/passkey/register/finish', {
    body: { challenge_id: b.challenge_id, credential: creationToJson(cred) },
  });
}
