// Prop-journal P&L labelling. A prop fill's `pnl` is NOT one kind of number:
// measured 2026-10-15 on live /api/bot/prop/fills, three accounts closing the
// same ETH short carried three different bases —
//   tradeify_1  "venue net closed P&L"                          (venue, NET)
//   velotrade_1 "venue fills: (exit - entry fill) … gross of …" (venue, GROSS)
//   breakout_2  "gross: (exit-entry)*qty, before fees/funding"  provenance ESTIMATED
// and older breakout_2 closes are provenance UNVERIFIED. The bot carries the
// basis/provenance only inside the `raw` JSON string, so the SPA must read it
// from there (top-level first, in case the API promotes them later). A bare
// number would present an estimate as a measurement — never do that.

export type Provenance = "MEASURED" | "ESTIMATED" | "UNVERIFIED" | "UNKNOWN";
export type PnlBasis = "net" | "gross" | null;

export function fillRaw(f: any): Record<string, any> {
  const r = f?.raw;
  if (r && typeof r === "object") return r;
  if (typeof r !== "string" || !r) return {};
  try {
    const o = JSON.parse(r);
    return o && typeof o === "object" ? o : {};
  } catch {
    return {};
  }
}

export function fillBasisText(f: any): string | null {
  const b = f?.pnl_basis ?? fillRaw(f).pnl_basis;
  return typeof b === "string" && b.trim() ? b : null;
}

/** Explicit provenance wins; else a venue-sourced basis is MEASURED; else UNKNOWN (never assumed measured). */
export function fillProvenance(f: any): Provenance {
  const p = String(f?.provenance ?? fillRaw(f).provenance ?? "").trim().toUpperCase();
  if (p === "MEASURED" || p === "ESTIMATED" || p === "UNVERIFIED") return p;
  const basis = (fillBasisText(f) ?? "").toLowerCase();
  if (basis.startsWith("venue")) return "MEASURED";
  return "UNKNOWN";
}

export function fillBasis(f: any): PnlBasis {
  const basis = (fillBasisText(f) ?? "").toLowerCase();
  if (/\bgross\b/.test(basis)) return "gross";
  if (/\bnet\b/.test(basis)) return "net";
  return null;
}

/** Close time for ordering/rendering: the venue close time, falling back to when it was reported. */
export function fillClosedAt(f: any): string | null {
  return f?.closed_at ?? f?.reported_at ?? f?.created_at ?? null;
}

function ts(iso: string | null): number {
  const t = iso == null ? NaN : Date.parse(iso);
  return Number.isNaN(t) ? -Infinity : t;
}

/** Closed prop trades, newest close first (ties broken by journal id, newest first). */
export function closedFills(fills: any[]): any[] {
  return fills
    .filter((f) => String(f?.status ?? "").toLowerCase() === "closed")
    .sort((a, b) => ts(fillClosedAt(b)) - ts(fillClosedAt(a)) || (b?.id ?? 0) - (a?.id ?? 0));
}

/** "10-15 14:13Z" — compact UTC stamp; em-dash when undateable. */
export function shortUtc(iso: string | null | undefined): string {
  if (iso == null) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const d = new Date(t).toISOString();
  return `${d.slice(5, 10)} ${d.slice(11, 16)}Z`;
}
