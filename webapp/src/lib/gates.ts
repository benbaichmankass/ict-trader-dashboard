// Gate registry (Admin → Gates) — types + the pure helpers the panel renders
// through. Operator ask 2026-11-12: "the Admin tab in the UI needs to keep an
// actively-updated gate registry so we can have visibilty and make changes
// more quickly".
//
// Contract (bot repo, built in parallel with this panel):
//   GET  /api/bot/gates?category=&decision=&state=&real_money=
//   GET  /api/bot/gates/{id}
//   POST /api/bot/gates/{id}/decision  {decision, note}   (operator session)
//
// ⚠️ SELF-CONTAINED ON PURPOSE: no imports, so `tests/gates-registry.mjs` can
// load this file straight into node 22 (type stripping) the same way
// `funding-books.mjs` loads `funding.ts`. Keep it that way.
//
// Rendering rule (the app's, see format.ts): a null / missing field is "not
// provided" and renders as an em-dash — never 0, never "unknown".

export const GATE_DASH = "—";

export type Decision = "keep" | "remove" | "report_only" | "undecided";
export type ImplState = "as_is" | "pending" | "implemented";
export type StateFilter = ImplState | "unregistered" | "drift";
export type Drift = "site_missing" | "unregistered" | "not_in_place";

export const DECISIONS: { value: Decision; label: string }[] = [
  { value: "keep", label: "Keep" },
  { value: "remove", label: "Remove" },
  { value: "report_only", label: "Report-only" },
  { value: "undecided", label: "Undecided" },
];

export const STATE_FILTERS: { value: StateFilter; label: string }[] = [
  { value: "as_is", label: "As is" },
  { value: "pending", label: "Pending" },
  { value: "implemented", label: "Implemented" },
  { value: "unregistered", label: "Unregistered" },
  { value: "drift", label: "Drift" },
];

export interface GateRow {
  id: string;
  category?: string | null;
  where?: string | null;
  where_more?: string[] | null;
  blocks?: string | null;
  real_money?: boolean | null;
  authorization?: string | null;
  authorization_class?: "VERBATIM" | "PARAPHRASE" | "NONE" | null;
  operator_decision?: Decision | null;
  decision_note?: string | null;
  decided_at?: string | null;
  decided_by?: string | null;
  decision_source?: string | null;
  implementation_state?: ImplState | null;
  implementation_pr?: number | null;
  implementation_sha?: string | null;
  mode_in_code?: "blocks" | "report_only" | "removed" | null;
  registry_state?: "registered" | "unregistered" | null;
  drift?: Drift | null;
  drift_detail?: string | null;
  hits_last_fired?: string | null;
  hits_14d?: number | null;
  hits_read_state?: "measured" | "not_measurable" | null;
  hits_note?: string | null;
  added_by?: string | null;
  added_at?: string | null;
  recommendation?: string | null;
  effect?: string | null;
  updated_at?: string | null;
  // bot #25551 (sort=attention): the route's own rank and the audit recommendation
  // mapped onto a decision value (null = operator-preference row, no recommendation).
  attention_rank?: 1 | 2 | 3 | null;
  recommended_decision?: Decision | null;
}

export interface GatesResponse {
  readState?: "read" | "unreadable" | string | null;
  as_of?: string | null;
  error?: string | null;
  population?: { total?: number | null; returned?: number | null; description?: string | null } | null;
  counts?: {
    by_decision?: Record<string, number | null> | null;
    by_state?: Record<string, number | null> | null;
    by_category?: Record<string, number | null> | null;
    by_mode?: Record<string, number | null> | null;
    real_money?: number | null;
    drift?: number | null;
    unregistered?: number | null;
    by_attention_rank?: Record<string, number | null> | null;
    recommendation_acceptable?: number | null;
  } | null;
  sort?: string | null;
  refresh?: { at?: string | null; head_sha?: string | null; read_state?: string | null; error?: string | null } | null;
  gates?: GateRow[] | null;
}

export interface GateHistoryEntry {
  decision?: string | null;
  note?: string | null;
  decided_at?: string | null;
  decided_by?: string | null;
  source?: string | null;
}

export interface GateDetailResponse {
  readState?: string | null;
  error?: string | null;
  gate?: GateRow | null;
  history?: GateHistoryEntry[] | null;
}

export interface GateFilters {
  category?: string;
  decision?: string;
  state?: string;
  real_money?: string; // "true" | "false" | "" (any)
  sort?: string; // "attention" = the route's attention order (bot #25551)
}

/** Query string for GET /api/bot/gates — empty filters are omitted, never sent blank. */
export function buildGatesQuery(f: GateFilters): string {
  const q = new URLSearchParams();
  for (const k of ["category", "decision", "state", "real_money", "sort"] as const) {
    const v = f[k];
    if (v != null && v !== "") q.set(k, v);
  }
  return q.toString();
}

/** A drift or unregistered row: always flagged, always sorted on top. */
export function isFlagged(g: GateRow): boolean {
  return (g.drift != null && g.drift !== ("" as any)) || g.registry_state === "unregistered";
}

/**
 * Flagged rows (drift / unregistered) first; otherwise the server's order is
 * kept (stable). Returns a new array — never sorts the caller's in place.
 */
export function sortGates(rows: GateRow[]): GateRow[] {
  return rows
    .map((g, i) => ({ g, i }))
    .sort((a, b) => Number(isFlagged(b.g)) - Number(isFlagged(a.g)) || a.i - b.i)
    .map((x) => x.g);
}

/** null / undefined / "" → em-dash; anything else as text. A real 0 stays 0. */
export function dash(v: unknown): string {
  if (v === null || v === undefined || v === "") return GATE_DASH;
  return String(v);
}

export function realMoneyText(v: boolean | null | undefined): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  return GATE_DASH;
}

export function decisionLabel(v: string | null | undefined): string {
  const d = DECISIONS.find((x) => x.value === v);
  return d ? d.label : dash(v);
}

export function prUrl(n: number | null | undefined): string | null {
  if (n === null || n === undefined || !Number.isFinite(n)) return null;
  return `https://github.com/benbaichmankass/JTA-Trader/pull/${n}`;
}

export function shortSha(s: string | null | undefined): string {
  if (!s) return GATE_DASH;
  return s.slice(0, 7);
}

/** hits_14d: a measured 0 is 0; a null (or not_measurable) is a dash, never 0. */
export function hitsText(g: GateRow): string {
  if (g.hits_read_state === "not_measurable") return GATE_DASH;
  return dash(g.hits_14d);
}

export function driftText(g: GateRow): string | null {
  if (g.drift) return g.drift.replace(/_/g, " ");
  if (g.registry_state === "unregistered") return "unregistered";
  return null;
}

/**
 * The server's answer to a decision POST, VERBATIM. Success → its `message`;
 * error → its `detail` (a string as-is, anything else as JSON). Nothing is
 * paraphrased: the operator sees exactly what the bot said.
 */
export function serverAnswer(status: number, body: unknown, rawText: string): string {
  const b = body as any;
  if (b && typeof b === "object") {
    if (status >= 200 && status < 300 && typeof b.message === "string") return b.message;
    if ("detail" in b) return typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    if (typeof b.message === "string") return b.message;
    return JSON.stringify(b);
  }
  return rawText || `HTTP ${status} (empty body)`;
}

/** Category options: union of what the counts and the rows have shown, sorted. */
export function categoryOptions(seen: Iterable<string>, resp: GatesResponse | null): string[] {
  const s = new Set<string>(seen);
  for (const k of Object.keys(resp?.counts?.by_category ?? {})) if (k) s.add(k);
  for (const g of resp?.gates ?? []) if (g.category) s.add(g.category);
  return [...s].sort();
}

/** The route's attention ranks (bot #25551), in the design's words. */
export const ATTENTION_LABEL: Record<string, string> = {
  "1": "real money · no authorization on record",
  "2": "other real money",
  "3": "the rest",
};
