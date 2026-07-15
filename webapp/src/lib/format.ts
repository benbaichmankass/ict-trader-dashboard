// Rendering rules mirror the bot's contract: a null/undefined field is "not
// provided" and renders as an em-dash — never 0, never "unknown". A real 0 is
// data and renders as 0.

export const DASH = "—";

export function isNil(v: unknown): v is null | undefined {
  return v === null || v === undefined;
}

export function money(v: number | null | undefined, opts: { sign?: boolean } = {}): string {
  if (isNil(v) || Number.isNaN(v)) return DASH;
  const abs = Math.abs(v).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (v < 0) return `-${abs}`;
  return opts.sign ? `+${abs}` : abs;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (isNil(v) || Number.isNaN(v)) return DASH;
  return `${v.toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (isNil(v) || Number.isNaN(v)) return DASH;
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

/** Sign class for coloring PnL values green/red/neutral. */
export function signClass(v: number | null | undefined): "pos" | "neg" | "flat" {
  if (isNil(v) || Number.isNaN(v) || v === 0) return "flat";
  return v > 0 ? "pos" : "neg";
}

export function agoFromIso(iso: string | null | undefined): string {
  if (isNil(iso)) return DASH;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return DASH;
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
