// Single source of truth for the bot API base URL.
//
// Resolution order (first wins):
//   1. runtime override in localStorage  (Settings field — lets the operator
//      repoint without a redeploy)
//   2. build-time VITE_BOT_API_URL       (set in the Pages workflow)
//   3. the HTTPS default below           (Caddy reverse-proxy on the live VM)
//
// The browser calls this host DIRECTLY (unlike the old Streamlit server-side
// hop), so it MUST be HTTPS — a GitHub Pages page is HTTPS and a mixed-content
// http:// fetch is hard-blocked. The plain-HTTP :8001 origin only works for
// local dev (a localhost page is exempt from mixed-content).

const LS_KEY = "ict.botApiUrl";

// The DuckDNS hostname the operator pointed at the live VM (141.145.193.91),
// fronted by Caddy for Let's Encrypt HTTPS. See webapp/README.md § HTTPS.
const DEFAULT_BOT_API_URL = "https://ict-bot.duckdns.org";

function stripTrailingSlash(u: string): string {
  return u.replace(/\/+$/, "");
}

export function getBotApiUrl(): string {
  try {
    const override = localStorage.getItem(LS_KEY);
    if (override && override.trim()) return stripTrailingSlash(override.trim());
  } catch {
    /* localStorage unavailable (private mode) — fall through */
  }
  const built = import.meta.env.VITE_BOT_API_URL;
  if (built && built.trim()) return stripTrailingSlash(built.trim());
  return DEFAULT_BOT_API_URL;
}

export function setBotApiUrl(url: string): void {
  try {
    if (url && url.trim()) localStorage.setItem(LS_KEY, stripTrailingSlash(url.trim()));
    else localStorage.removeItem(LS_KEY);
  } catch {
    /* ignore */
  }
}

/** ws(s):// origin derived from the API base, for /ws/market. */
export function getBotWsUrl(): string {
  const http = getBotApiUrl();
  return http.replace(/^http/, "ws");
}
