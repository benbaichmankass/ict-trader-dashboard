// Shared time helpers for the trade charts.

/** Any bot timestamp (epoch s/ms, ISO, or naive "YYYY-MM-DD HH:MM:SS" UTC) → epoch seconds, or null. */
export function toSec(v: unknown): number | null {
  if (v == null || v === "") return null;
  if (typeof v === "number") return v > 1e12 ? Math.floor(v / 1000) : Math.floor(v);
  let s = String(v).trim().replace(" ", "T");
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
  const ms = Date.parse(s);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

/** The bar time in `times` nearest to `sec` (times ascending), or null when empty. */
export function snapTo(sec: number, times: number[]): number | null {
  if (!times.length) return null;
  let best = times[0], bestD = Math.abs(sec - times[0]);
  for (const t of times) {
    const d = Math.abs(sec - t);
    if (d < bestD) { best = t; bestD = d; }
  }
  return best;
}

/** Colour for an LTR / Claude decision by its disposition (bot trade_markers v1). */
export function dispositionColor(d: unknown): string {
  switch (String(d ?? "").toLowerCase()) {
    case "applied": return "#4c8dff";
    case "advice_only": return "#d4a017";
    case "refused": return "#e5484d";
    case "operator_ask": return "#c2410c";
    case "dry_run": return "#a06cd5";
    case "no_action": return "#8b93a3";
    default: return "#8b93a3";
  }
}
