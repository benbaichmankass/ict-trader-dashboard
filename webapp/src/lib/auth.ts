// Session-token store for the bot API's `require_session` gate.
//
// WHY THIS EXISTS
// ---------------
// The bot gates four handlers behind `Depends(require_session)`; two of them —
// `GET /api/bot/db/tables` and `GET /api/bot/db/table/{name}` — are the Data
// Explorer's entire data source. Measured 2026-09-11 across all 40
// `.svelte`/`.ts`/`.js` files under `webapp/src`: there was no token store and
// no login UI, and the one network chokepoint (`api.ts::get`) sent only an
// `Accept` header. So the SPA could not send a bearer AT ALL and the tab was
// dark no matter what the host did.
//
// This module is the client half of the fix. The host half — the three auth
// envs — is the operator's, and is NOT satisfied by anything here.
//
// SHAPE: mirrors `config.ts` — a localStorage key, plain accessors, and a
// try/catch around every storage touch so private-mode browsing degrades to
// "not signed in" instead of throwing.
//
// ⚠️ THE PASSWORD IS NEVER STORED, anywhere, for any length of time. It is a
// function argument to `login()`, sent once over HTTPS, and dropped. Only the
// minted token is persisted.
//
// ⚠️ localStorage, not sessionStorage, is deliberate and matches `config.ts`:
// the token is short-lived (the bot mints a 1-hour HS256 JWT,
// `auth.py::TOKEN_TTL_SECONDS`) and surviving a tab reload is the difference
// between signing in once and signing in on every navigation. The tradeoff —
// script-accessible storage — is the same one the API base URL already makes,
// and this page loads no third-party script but the charting library.

import { writable } from "svelte/store";
import { getBotApiUrl } from "./config";

const LS_KEY = "ict.authSession";

/** Refuse to send a token this close to its expiry — clock skew + flight time. */
const EXPIRY_MARGIN_MS = 30_000;

export interface StoredSession {
  token: string;
  /** Epoch ms at which the bot stops accepting the token. */
  expiresAt: number;
  /** The email the token was minted for — shown in the UI, never a secret. */
  email: string;
}

/** The signed-in identity, minus the token. `null` = no usable session. */
export const session = writable<{ email: string; expiresAt: number } | null>(null);

/**
 * Non-null when the UI should put the login form in front of the operator:
 * either they asked for it, or a gated read came back 401/403. Carries the
 * reason so the form can say WHY it appeared rather than just appearing.
 */
export const authPrompt = writable<string | null>(null);

function readStored(): StoredSession | null {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(LS_KEY);
  } catch {
    return null; // localStorage unavailable (private mode) — treat as signed out
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (
      !parsed ||
      typeof parsed.token !== "string" ||
      !parsed.token ||
      typeof parsed.expiresAt !== "number"
    ) {
      return null;
    }
    return { token: parsed.token, expiresAt: parsed.expiresAt, email: String(parsed.email ?? "") };
  } catch {
    return null; // malformed blob from an older build — treat as signed out
  }
}

function writeStored(s: StoredSession | null): void {
  try {
    if (s) localStorage.setItem(LS_KEY, JSON.stringify(s));
    else localStorage.removeItem(LS_KEY);
  } catch {
    /* ignore — the in-memory store still drives this tab */
  }
}

/**
 * The bearer to send, or `null`.
 *
 * Returns `null` for a token already past (or within `EXPIRY_MARGIN_MS` of)
 * its expiry, so the app does not spend a round-trip proving what it already
 * knows. ⚠️ This is a UX shortcut, NOT a security check — the bot verifies the
 * signature and `exp` itself and is the only thing that decides.
 */
export function getAuthToken(): string | null {
  const s = readStored();
  if (!s) return null;
  if (Date.now() + EXPIRY_MARGIN_MS >= s.expiresAt) return null;
  return s.token;
}

/** True when a usable (unexpired) token is held. */
export function isSignedIn(): boolean {
  return getAuthToken() != null;
}

/** Drop the stored session. Safe to call when already signed out. */
export function clearSession(): void {
  writeStored(null);
  session.set(null);
}

/** Ask the UI to show the login form. */
export function requestLogin(reason: string): void {
  authPrompt.set(reason);
}

/** Dismiss the login prompt (the form stays reachable from Settings). */
export function dismissLoginPrompt(): void {
  authPrompt.set(null);
}

/** Re-seed the in-memory store from localStorage. Call once at startup. */
export function initSession(): void {
  const s = readStored();
  if (!s || Date.now() + EXPIRY_MARGIN_MS >= s.expiresAt) {
    // Sweep an expired blob rather than leaving it to look like a session.
    if (s) writeStored(null);
    session.set(null);
    return;
  }
  session.set({ email: s.email, expiresAt: s.expiresAt });
}

/**
 * What a failed sign-in actually means.
 *
 * The bot's handler (`routers/auth.py::login`) checks in a FIXED ORDER, so the
 * status code says precisely how far it got. This mapping is the client-side
 * copy of the status ladder in the bot repo's
 * `docs/runbooks/restore-webapp-auth.md` § 3.1 — keep the two in step.
 */
export type AuthFailure =
  | "invalid_credentials" // 401 — email matched, password did not
  | "email_not_allowlisted" // 403 — not the allowlisted operator account
  | "auth_unavailable" // 500 — the HOST is missing its auth envs
  | "malformed" // 422 — Pydantic rejected the body before the handler ran
  | "network" // never reached the host (DNS/TLS/CORS/offline)
  | "unexpected";

export class AuthError extends Error {
  readonly kind: AuthFailure;
  readonly status: number | null;
  constructor(kind: AuthFailure, status: number | null, message: string) {
    super(message);
    this.name = "AuthError";
    this.kind = kind;
    this.status = status;
  }
}

/** Operator-readable text for each rung of the ladder. */
export function authFailureMessage(e: AuthError): string {
  switch (e.kind) {
    case "invalid_credentials":
      return "Wrong password for that account.";
    case "email_not_allowlisted":
      return "That email is not the allowlisted operator account on this host.";
    case "auth_unavailable":
      return (
        "The bot host cannot mint a session — its auth environment is not fully " +
        "configured (HTTP 500 auth_unavailable). This is a host-side setting, " +
        "not something signing in again will fix."
      );
    case "malformed":
      return "The bot rejected the request as malformed — check the email is a valid address.";
    case "network":
      return "Could not reach the bot API. Check the base URL in Settings and that the host is up.";
    default:
      return e.message || "Sign-in failed for an unrecognised reason.";
  }
}

/** Pull the bot's `detail.error` slug out of an error body, if there is one. */
function errorSlug(body: unknown): string | null {
  const detail = (body as any)?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.error === "string") return detail.error;
  return null;
}

/**
 * Mint a session against `POST /api/auth/login`.
 *
 * ⚠️ This is the ONE deliberately unauthenticated call the SPA makes — the
 * route is in the bot's `PUBLIC_ROUTES`, and it is the only mint path there is
 * (`decode_token` has no static-token bypass). The CI guard
 * `webapp/tests/auth-bearer.mjs` exempts it BY NAME for that reason.
 *
 * On success the token is persisted and `session` is updated. On failure it
 * throws an `AuthError` whose `kind` names which rung of the ladder was hit,
 * and the stored session is left untouched.
 */
export async function login(email: string, password: string, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    // The path is spelled out AT the call site on purpose: `auth-bearer.mjs`
    // pins this exemption to the literal `/api/auth/login`, so the exemption
    // cannot be reused to wave an arbitrary unauthenticated URL through.
    res = await fetch(`${getBotApiUrl()}/api/auth/login`, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      // A WELL-FORMED body, always. An empty/malformed one returns 422 from
      // Pydantic BEFORE the handler runs, which measures nothing about auth.
      body: JSON.stringify({ email, password }),
    });
  } catch (e) {
    if ((e as any)?.name === "AbortError") throw e;
    throw new AuthError("network", null, "Could not reach the bot API.");
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* a non-JSON body is survivable — the status code carries the meaning */
  }

  if (!res.ok) {
    const slug = errorSlug(body);
    if (res.status === 401) throw new AuthError("invalid_credentials", 401, slug ?? "invalid_credentials");
    if (res.status === 403) throw new AuthError("email_not_allowlisted", 403, slug ?? "email_not_allowlisted");
    if (res.status === 422) throw new AuthError("malformed", 422, "malformed request body");
    if (res.status === 500 && slug === "auth_unavailable") {
      throw new AuthError("auth_unavailable", 500, "auth_unavailable");
    }
    throw new AuthError("unexpected", res.status, `${res.status} ${res.statusText}`);
  }

  const token = (body as any)?.access_token;
  if (typeof token !== "string" || !token) {
    throw new AuthError("unexpected", res.status, "login succeeded but returned no access_token");
  }
  // `expires_in` is seconds (the bot sends 3600). Fall back to the same value
  // if an older build omits it, rather than treating the token as immortal.
  const ttlSeconds = Number((body as any)?.expires_in);
  const ttl = Number.isFinite(ttlSeconds) && ttlSeconds > 0 ? ttlSeconds : 3600;
  const stored: StoredSession = {
    token,
    expiresAt: Date.now() + ttl * 1000,
    email: email.trim(),
  };
  writeStored(stored);
  session.set({ email: stored.email, expiresAt: stored.expiresAt });
  authPrompt.set(null);
}

/**
 * Headers for an authenticated read. Always returns `Accept`; adds
 * `Authorization: Bearer` when a usable token is held.
 *
 * ⚠️ Only ever pass these to `getBotApiUrl()`-derived URLs. The token is
 * scoped to the bot host and must not be attached to any other origin.
 */
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json", ...(extra ?? {}) };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/**
 * Call when a gated read comes back 401/403: drop the dead session and put the
 * form in front of the operator.
 *
 * ⚠️ ASSUMPTION, recorded because it is the thing that would make this wrong:
 * every 401 the SPA can receive today comes from `require_session`. The bot
 * DOES have other bearer schemes that 401 — the diag token (`routers/diag.py`),
 * and the write tokens on `routers/prop.py` / `work.py` / `devices.py` — but
 * `api.ts` calls none of those routes (they are POST/write paths; the SPA is
 * read-only apart from routes it does not call). If a SPA route ever starts
 * calling a differently-gated endpoint, a 401 from it would wrongly clear the
 * session here, and this function needs to discriminate by path.
 */
export function handleUnauthorized(status: number, path: string): void {
  clearSession();
  authPrompt.set(
    status === 403
      ? `The bot refused the session for ${path} (403 — the account is no longer allowlisted). Sign in again.`
      : `${path} needs a signed-in session (401). Sign in to load it.`,
  );
}
