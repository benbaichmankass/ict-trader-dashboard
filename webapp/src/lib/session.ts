// UI-UPGRADE-1-AUTH (SPA side) — device-session store + signed fetch.
//
// The API issues a 30-day sliding, revocable device session (`ws_…` bearer)
// after Google + passkey sign-in. localStorage is deliberate (the SPA is on
// github.io and the API on duckdns.org, so a cookie would be third-party and
// blocked by Safari ITP) — the cost is XSS exposure, which the Pages site's CSP
// and instant server-side revocation mitigate (design §2a.5).
//
// Wire-up: call configureSession({ apiBase }) once at start-up with the same
// base URL api.ts uses, and have api.ts's single fetch call site spread
// `authHeaders()` into its headers (see README).

import { getBotApiUrl } from './config';

const KEY = 'metis.session.v1';

export interface StoredSession {
  token: string;
  handle: string;
  expiresAt: number; // epoch seconds, as issued by the server
}

// Defaults to the SPA's configured bot API base (config.ts), so a base URL
// changed in Settings applies here too; configureSession() can still pin one.
let base: string | null = null;
export function configureSession(opts: { apiBase: string }): void {
  base = opts.apiBase.replace(/\/+$/, '');
}
export function apiBase(): string {
  return (base ?? getBotApiUrl()).replace(/\/+$/, '');
}

export function loadSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as StoredSession;
    return s && typeof s.token === 'string' && s.token.startsWith('ws_') ? s : null;
  } catch {
    return null;
  }
}

export function saveSession(s: StoredSession): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* private mode: the session simply lasts for this page view */
    memory = s;
  }
}
let memory: StoredSession | null = null;

export function clearSession(): void {
  memory = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export function currentToken(): string | null {
  return (loadSession() ?? memory)?.token ?? null;
}

/** Headers api.ts spreads into its one fetch call site. Empty when signed out. */
export function authHeaders(): Record<string, string> {
  const t = currentToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** Raw JSON call to /api/auth/*; throws {status, error} on non-2xx. */
export async function authCall<T>(
  path: string,
  init: { method?: string; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const tok = init.token === undefined ? currentToken() : init.token;
  const res = await fetch(apiBase() + path, {
    method: init.method ?? (init.body !== undefined ? 'POST' : 'GET'),
    headers: {
      Accept: 'application/json',
      ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(tok ? { Authorization: `Bearer ${tok}` } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = (j as any)?.detail?.error ?? (j as any)?.detail ?? `http_${res.status}`;
    throw { status: res.status, error: String(e) };
  }
  return j as T;
}

/** A 401 from any API call means the session is gone/revoked: drop it, show sign-in. */
export function onUnauthorized(handler: () => void): void {
  window.addEventListener('metis:unauthorized', handler);
}
export function signalUnauthorized(): void {
  clearSession();
  window.dispatchEvent(new Event('metis:unauthorized'));
}

/** Single-use 60 s ticket for WS /ws/market?ticket=… (a browser WebSocket cannot send headers). */
export async function marketSocketUrl(query = ''): Promise<string> {
  const { ticket } = await authCall<{ ticket: string }>('/api/auth/ws-ticket', { method: 'POST' });
  const wsBase = apiBase().replace(/^http/, 'ws');
  return `${wsBase}/ws/market?${query ? query + '&' : ''}ticket=${encodeURIComponent(ticket)}`;
}
