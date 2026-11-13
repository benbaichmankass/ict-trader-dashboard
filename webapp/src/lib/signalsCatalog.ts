// Signals Catalog (UI-UPGRADE-1 item 8) — query builder + render helpers for
// GET /api/bot/signals/catalog (bot PR #25199). Pure functions, no DOM, so
// tests/signals-catalog.mjs can import-free re-check them.
//
// Rule: null / undefined / empty renders as "—", never 0 and never "unknown".
// Nothing here derives a number the route does not publish.

export const SC_DASH = "—";
export const SC_PAGE_SIZE = 100;

// The route's own consumer vocabulary, probed live 2026-11-12: any | strategy |
// model | none. Any other value is silently treated as "any" (the response's
// `filters.consumer` echoes what was applied), so "with"/"without" would be a
// no-op — there is no published "has any consumer" filter.
export const CONSUMER_OPTIONS = [
  { value: "any", label: "Any consumer" },
  { value: "strategy", label: "Used by a strategy" },
  { value: "model", label: "Used by a model" },
  { value: "none", label: "No consumer" },
] as const;
export type Consumer = (typeof CONSUMER_OPTIONS)[number]["value"];

export interface SignalsCatalogQuery {
  limit?: number;
  offset?: number;
  family?: string | null;
  kind?: string | null;
  q?: string | null;
  consumer?: Consumer;
}

export function buildSignalsCatalogQuery(o: SignalsCatalogQuery): string {
  const p = new URLSearchParams();
  p.set("limit", String(o.limit ?? SC_PAGE_SIZE));
  if (o.offset) p.set("offset", String(o.offset));
  if (o.family) p.set("family", o.family);
  if (o.kind) p.set("kind", o.kind);
  const q = (o.q ?? "").trim();
  if (q) p.set("q", q);
  if (o.consumer && o.consumer !== "any") p.set("consumer", o.consumer);
  return p.toString();
}

/** Text cell: null/undefined/"" → "—". A real 0 stays "0". */
export function cell(v: unknown): string {
  if (v === null || v === undefined) return SC_DASH;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : SC_DASH;
  const s = String(v).trim();
  return s === "" ? SC_DASH : s;
}

/** List cell: missing or empty list → "—". */
export function listCell(v: unknown): string {
  if (!Array.isArray(v)) return SC_DASH;
  const xs = v.map((x) => (x === null || x === undefined ? "" : String(x).trim())).filter(Boolean);
  return xs.length ? xs.join(", ") : SC_DASH;
}

/** Age in seconds (as published in freshness.age_s) → "42s" / "5m" / "3h" / "2d"; null → "—". */
export function ageCell(s: unknown): string {
  if (typeof s !== "number" || !Number.isFinite(s) || s < 0) return SC_DASH;
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** "state · age" for the freshness column; either half may be "—". */
export function freshnessCell(f: { state?: unknown; age_s?: unknown } | null | undefined): string {
  if (!f || typeof f !== "object") return SC_DASH;
  const st = cell(f.state);
  const age = ageCell(f.age_s);
  return age === SC_DASH ? st : `${st} · ${age}`;
}

/** Truncate long text for a table cell; the full text goes in the title. */
export function truncate(v: unknown, n = 90): string {
  const s = cell(v);
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Short list cell: first `k` names + "+N" (the rest go in the title via listCell). */
export function listShort(v: unknown, k = 3): string {
  const full = listCell(v);
  if (full === SC_DASH) return SC_DASH;
  const xs = full.split(", ");
  return xs.length > k ? `${xs.slice(0, k).join(", ")} +${xs.length - k}` : full;
}
