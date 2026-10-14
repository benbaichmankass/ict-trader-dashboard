// Research-catalog types + pure helpers (query building, last-visit store).
// No network here — the fetch lives in api.ts (the ONE chokepoint). Kept pure
// so webapp/tests/catalog-contract.mjs can exercise it without a DOM.
//
// Shapes come from the bot's `GET /api/bot/research/catalog` (handoff doc
// docs/plans/DATA-EXPLORER-SPA-HANDOFF.md in the bot repo). Every field may be
// null/absent and renders as an em-dash.

export const FACETS = ["theme", "status", "verdict", "goal", "backend", "kind", "stuck"] as const;
export type FacetKey = (typeof FACETS)[number];

export const SORTS = ["id", "title", "theme", "status", "verdict", "priority", "lastActivity", "created"] as const;
export type SortKey = (typeof SORTS)[number];

export interface CatalogRoadmapRef {
  id?: string | null;
  name?: string | null;
  goal?: string | null;
  goalName?: string | null;
  status?: string | null;
}

export interface CatalogItem {
  id: string;
  title?: string | null;
  summary?: string | null;
  whyItMatters?: string | null;
  kind?: string | null;
  cadence?: string | null;
  theme?: string | null;
  priority?: number | null;
  roadmap?: CatalogRoadmapRef[] | null;
  status?: string | null;
  fileStatus?: string | null;
  dueState?: string | null;
  dueReason?: string | null;
  blockedReason?: string | null;
  stuck?: boolean | null;
  stuckReason?: string | null;
  rule?: {
    id?: string | null;
    registeredAt?: string | null;
    registeredBeforeRun?: boolean | null;
    statistic?: string | null;
    text?: string | null;
  } | null;
  power?: { state?: string | null; expectedN?: number | null; minDetectableEffect?: number | null } | null;
  verdict?: string | null;
  readState?: string | null;
  resultNote?: string | null;
  metrics?: { scalars?: Record<string, unknown> | null } | Record<string, unknown> | null;
  resultCount?: number | null;
  dataUsed?: {
    workflow?: string | null;
    harness?: string | null;
    inputs?: Record<string, unknown> | null;
    dataInputs?: Record<string, unknown> | null;
    population?: string | null;
    n?: number | null;
    store?: string | null;
  } | null;
  backend?: string | null;
  estMinutes?: number | null;
  createdAt?: string | null;
  lastDispatchedAt?: string | null;
  latestResultAt?: string | null;
  lastActivity?: string | null;
  links?: { unit?: string | null; results?: string[] | null; run?: string | null } | null;
}

export interface StayItem {
  id: string;
  title?: string | null;
  theme?: string | null;
  status?: string | null;
  verdict?: string | null;
  lastActivity?: string | null;
  stuckReason?: string | null;
  createdAt?: string | null;
}

export interface StayBucket {
  count: number;
  items?: StayItem[] | null;
}

export interface StayOnTop {
  since?: string | null;
  sinceKnown?: boolean | null;
  // null (NOT zero) on a first visit — render "first visit", not "0 new".
  new?: StayBucket | null;
  stuck?: StayBucket | null;
  due?: StayBucket | null;
  recentVerdicts?: StayItem[] | null;
}

export interface CatalogResponse {
  present?: boolean | null;
  // read | partial | unreadable — an unreadable store must never look empty.
  readState?: string | null;
  readErrors?: string[] | null;
  total?: number | null;
  matched?: number | null;
  limit?: number | null;
  offset?: number | null;
  sort?: string | null;
  order?: string | null;
  facets?: Record<string, Record<string, number>> | null;
  items?: CatalogItem[] | null;
  stayOnTop?: StayOnTop | null;
  generatedAt?: string | null;
  roadmapAvailable?: boolean | null;
  freshness?: string | null;
}

export interface CatalogDetail {
  present?: boolean | null;
  id?: string | null;
  unit?: CatalogItem | Record<string, unknown> | null;
  resultRows?: Array<Record<string, unknown>> | null;
  resultRowsTruncated?: boolean | null;
}

export interface CatalogQuery {
  q?: string;
  facets?: Partial<Record<FacetKey, string[]>>;
  sort?: SortKey;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
  since?: string | null;
}

export const CATALOG_MAX_LIMIT = 200;

/** Build the query string. Facets go as CSV; limit is clamped to the API's 1..200. */
export function buildCatalogQuery(o: CatalogQuery): string {
  const p = new URLSearchParams();
  if (o.q && o.q.trim()) p.set("q", o.q.trim());
  for (const f of FACETS) {
    const v = o.facets?.[f];
    if (v && v.length) p.set(f, v.join(","));
  }
  if (o.sort) p.set("sort", o.sort);
  if (o.order) p.set("order", o.order);
  p.set("limit", String(Math.max(1, Math.min(CATALOG_MAX_LIMIT, o.limit ?? 50))));
  if (o.offset) p.set("offset", String(Math.max(0, o.offset)));
  if (o.since) p.set("since", o.since);
  return p.toString();
}

/**
 * Three-way load state for a catalog response. A response that is present but
 * unreadable is a FAILURE to load, never "0 results" — the API returns
 * readState precisely for this.
 */
export type CatalogState = "ok" | "partial" | "unreadable" | "absent" | "empty";

export function catalogState(r: CatalogResponse | null | undefined): CatalogState {
  if (!r) return "unreadable";
  if (r.present === false) return "absent";
  if (r.readState === "unreadable") return "unreadable";
  if (r.readState === "partial") return "partial";
  if ((r.matched ?? r.total ?? 0) === 0 && (r.items ?? []).length === 0) return "empty";
  return "ok";
}

/** Resolve a metrics blob to a flat scalar map regardless of {scalars:{…}} wrapping. */
export function metricScalars(m: CatalogItem["metrics"]): Array<[string, unknown]> {
  if (!m || typeof m !== "object") return [];
  const inner = (m as any).scalars;
  const src = inner && typeof inner === "object" ? inner : m;
  return Object.entries(src as Record<string, unknown>).filter(([, v]) => v !== null && typeof v !== "object");
}

export function toggleFacet(sel: string[] | undefined, value: string): string[] {
  const cur = sel ?? [];
  return cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value];
}

// ---- last-visit store -------------------------------------------------------
// Per-browser convenience only; every access is try/catch so the page renders
// with storage blocked. `since` is read ONCE at load and sent to the API; the
// stamp is advanced only when the operator acknowledges, so reloading the page
// does not silently erase what was new.
const LS_SINCE = "ict.catalog.lastSeen";

export function readLastSeen(): string | null {
  try {
    const v = localStorage.getItem(LS_SINCE);
    return v && !Number.isNaN(Date.parse(v)) ? v : null;
  } catch {
    return null;
  }
}

export function writeLastSeen(iso: string): boolean {
  try {
    localStorage.setItem(LS_SINCE, iso);
    return true;
  } catch {
    return false;
  }
}
