// Column / facet definitions for the Trades, Signals and Order-packages
// explorer tabs, plus the pure filter/sort engine they share. Every `key` is a
// property name the bot actually returns (checked against real captured
// responses by tests/explorer-views.mjs) — never a guess.

export type Kind = "text" | "time" | "num" | "money" | "pct";

export interface Col {
  key: string;
  label: string;
  kind?: Kind;
  /** Show the row's pnlProvenance beside this value (P&L columns only). */
  provenance?: boolean;
}
export interface View {
  id: string;
  title: string;
  idKey: string;
  cols: Col[];
  /** Facet fields (row property names). */
  facets: string[];
  /** Fields the search box matches against. */
  search: string[];
  defaultSort: string;
}

export const TRADES_VIEW: View = {
  id: "trades",
  title: "Closed trades",
  idKey: "id",
  cols: [
    { key: "closedAt", label: "Closed", kind: "time" },
    { key: "symbol", label: "Symbol" },
    { key: "account", label: "Account" },
    { key: "strategy", label: "Strategy" },
    { key: "side", label: "Side" },
    { key: "accountClass", label: "Class" },
    { key: "pnl", label: "P&L", kind: "money", provenance: true },
    { key: "closeReason", label: "Close reason" },
  ],
  facets: ["accountClass", "account", "strategy", "symbol", "assetClass", "side", "closeReason", "pnlProvenance"],
  search: ["id", "symbol", "account", "strategy", "pattern", "closeReason"],
  defaultSort: "closedAt",
};

export const SIGNALS_VIEW: View = {
  id: "signals",
  title: "Signals",
  idKey: "id",
  cols: [
    { key: "timestamp", label: "When", kind: "time" },
    { key: "symbol", label: "Symbol" },
    { key: "strategy", label: "Strategy" },
    { key: "pattern", label: "Pattern" },
    { key: "side", label: "Side" },
    { key: "price", label: "Price", kind: "num" },
    { key: "confidence", label: "Conf.", kind: "num" },
  ],
  facets: ["strategy", "symbol", "side", "pattern"],
  search: ["id", "symbol", "strategy", "pattern"],
  defaultSort: "timestamp",
};

export const PACKAGES_VIEW: View = {
  id: "packages",
  title: "Order packages",
  idKey: "orderPackageId",
  cols: [
    { key: "createdAt", label: "Created", kind: "time" },
    { key: "strategy", label: "Strategy" },
    { key: "symbol", label: "Symbol" },
    { key: "direction", label: "Dir" },
    { key: "entry", label: "Entry", kind: "num" },
    { key: "sl", label: "SL", kind: "num" },
    { key: "tp", label: "TP", kind: "num" },
    { key: "status", label: "Status" },
    { key: "accountClass", label: "Class" },
    { key: "pnl", label: "P&L", kind: "money" },
  ],
  facets: ["status", "strategy", "symbol", "direction", "accountClass", "assetClass", "closeReason"],
  search: ["orderPackageId", "linkedTradeId", "symbol", "strategy", "status"],
  defaultSort: "createdAt",
};

const NONE = "(none)";

export function facetValue(row: any, key: string): string {
  const v = row?.[key];
  return v === null || v === undefined || v === "" ? NONE : String(v);
}

export function facetCounts(rows: any[], fields: string[], sel: Record<string, string[]>) {
  // A facet's counts ignore its OWN selection (so you can widen it), but honour the others.
  const out: Record<string, Array<[string, number]>> = {};
  for (const f of fields) {
    const others = { ...sel, [f]: [] };
    const m = new Map<string, number>();
    for (const r of rows) {
      if (!matchesFacets(r, others)) continue;
      const v = facetValue(r, f);
      m.set(v, (m.get(v) ?? 0) + 1);
    }
    out[f] = [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }
  return out;
}

export function matchesFacets(row: any, sel: Record<string, string[]>): boolean {
  for (const [f, vals] of Object.entries(sel)) {
    if (vals && vals.length && !vals.includes(facetValue(row, f))) return false;
  }
  return true;
}

export function matchesSearch(row: any, fields: string[], q: string): boolean {
  const n = q.trim().toLowerCase();
  if (!n) return true;
  return fields.some((f) => String(row?.[f] ?? "").toLowerCase().includes(n));
}

/** Null/absent always sorts last regardless of direction, so gaps never lead. */
export function compareRows(a: any, b: any, key: string, dir: "asc" | "desc"): number {
  const av = a?.[key];
  const bv = b?.[key];
  const an = av === null || av === undefined || av === "";
  const bn = bv === null || bv === undefined || bv === "";
  if (an || bn) return an && bn ? 0 : an ? 1 : -1;
  const c =
    typeof av === "number" && typeof bv === "number"
      ? av - bv
      : String(av).localeCompare(String(bv), undefined, { numeric: true });
  return dir === "asc" ? c : -c;
}
