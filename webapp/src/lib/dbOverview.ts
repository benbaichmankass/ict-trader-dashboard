// Types + pure helpers for GET /api/bot/db/overview (session-gated).
// Contract: docs/plans/DATA-EXPLORER-SPA-HANDOFF.md (bot repo), follow-up 2026-10-14.
// Render rules that matter: rows null -> "—" never 0; readState "missing" is
// "database not on disk", not an empty list; integrity "not_requested" is
// "not checked", never a green tick; empty:true flags the table. 24h/7d growth
// and a stale verdict are NOT provided and must not be invented.

export interface OverviewTable {
  name: string;
  db?: string | null;
  rows?: number | null;
  rowsState?: "read" | "count_failed" | "count_timed_out" | string | null;
  // Only meaningful when rowsState is count_timed_out: an upper bound (MAX(rowid)),
  // NEVER an exact count. Other per-table timing fields are ignored here.
  rowsEstimate?: number | null;
  empty?: boolean | null;
  columnCount?: number | null;
  newestRowColumn?: string | null;
  newestRowAt?: string | null;
  newestRowState?: string | null;
  ageSeconds?: number | null;
}

export interface OverviewDb {
  db: string;
  file?: string | null;
  present?: boolean | null;
  readState?: "read" | "missing" | "unreadable" | string | null;
  reason?: string | null;
  sizeBytes?: number | null;
  walBytes?: number | null;
  journalMode?: string | null;
  integrity?: { state?: string | null; result?: string | null } | null;
  tables?: OverviewTable[] | null;
}

export interface DbOverview {
  present?: boolean | null;
  generatedAt?: string | null;
  dbs?: OverviewDb[] | null;
  summary?: {
    tables?: number | null;
    emptyTables?: number | null;
    unknownRowCount?: number | null;
    dbsUnreadable?: number | null;
    dbsMissing?: number | null;
  } | null;
  notProvided?: string[] | null;
}

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${u[i]}`;
}

/** Age as a raw fact ("3h 12m"), never a verdict. */
export function fmtAge(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  if (sec < 60) return `${Math.floor(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
  return `${Math.floor(sec / 86400)}d ${Math.floor((sec % 86400) / 3600)}h`;
}

/** Integrity label: only "ok" is good; not_requested is explicitly "not checked". */
export function integrityLabel(i: OverviewDb["integrity"]): { text: string; tone: "ok" | "bad" | "none" } {
  switch (i?.state) {
    case "ok":
      return { text: "ok", tone: "ok" };
    case "failed":
      return { text: `FAILED${i.result ? `: ${i.result}` : ""}`, tone: "bad" };
    case "error":
      return { text: "check errored", tone: "bad" };
    case "not_requested":
    case "not_checked":
      return { text: "not checked", tone: "none" };
    default:
      return { text: "—", tone: "none" };
  }
}

/** Row count cell text. An estimate is always marked as one; never shown as exact. */
export function rowsLabel(t: OverviewTable): string {
  const fmt = (n: number) => n.toLocaleString("en-US");
  if (t.rowsState === "count_timed_out") {
    return t.rowsEstimate === null || t.rowsEstimate === undefined ? "count timed out" : `~${fmt(t.rowsEstimate)} (estimate)`;
  }
  if (t.rowsState === "count_failed") return "count failed";
  if (t.rows === null || t.rows === undefined || Number.isNaN(t.rows)) return "—";
  return fmt(t.rows);
}

/**
 * Short, mobile-safe "newest row" text: a relative age computed client-side from
 * newestRowAt ("17m ago"), else a short reason. The full timestamp lives in the
 * row drawer. `now` is injectable for tests.
 */
export function newestShort(t: OverviewTable, now: number = Date.now()): string {
  if (t.newestRowAt) {
    const ms = Date.parse(t.newestRowAt);
    if (!Number.isNaN(ms)) {
      const sec = Math.max(0, Math.floor((now - ms) / 1000));
      return `${fmtAge(sec)} ago`;
    }
    return "bad timestamp";
  }
  switch (t.newestRowState) {
    case "empty":
      return "no rows";
    case "no_timestamp_column":
      return "no ts column";
    case "null_value":
      return "null value";
    case "unparseable":
      return "bad timestamp";
    case "error":
      return "read error";
    default:
      return "—";
  }
}
