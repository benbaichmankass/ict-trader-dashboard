// Funding-class scoping helpers — the webapp mirror of streamlit_app.py's
// _portfolio_paper_ids / _row_is_portfolio_paper (S-PAPER-PORTFOLIO, 2026-07-16)
// and the Android app's paper_role logic. On every funding-scoped tab, "Paper"
// means the live-PORTFOLIO-mirror paper books (paper_role: portfolio) — the two
// accounts that mirror the actual live-traded portfolio on paper money. The
// data-only SOAK paper books (which trade the full instrument roster for ML
// data) stay on the Accounts page ONLY, never under the Paper toggle elsewhere.
//
// Data-driven off the bot's `paper_role` field (/api/bot/config) — never a
// hardcoded id list — so a roster change needs no webapp edit.

/**
 * Account ids of the live-portfolio-mirror paper books (`paper_role: portfolio`)
 * from a /api/bot/config payload. Returns an EMPTY set when the field is absent
 * (a bot predating it) OR the config is unreadable — callers treat empty as
 * "fall back to ALL paper", so the paper view is never stranded pre-deploy.
 */
export function portfolioPaperIds(config: any): Set<string> {
  const ids = new Set<string>();
  for (const a of config?.accounts ?? []) {
    if (
      String(a?.account_class ?? "").toLowerCase() === "paper" &&
      String(a?.paper_role ?? "").toLowerCase() === "portfolio"
    ) {
      const id = a?.id ?? a?.account_id;
      if (id) ids.add(String(id));
    }
  }
  return ids;
}

/**
 * True for a paper-class row that belongs to a live-portfolio-mirror book. A row
 * qualifies when it is paper-class AND (its account is in the declared portfolio
 * set, OR no portfolio books are declared yet — the graceful all-paper fallback,
 * OR it carries no per-account attribution — over-include beats blanking the
 * view, matching the bot's contract). Non-paper rows never qualify. `ids` is the
 * pre-resolved set from {@link portfolioPaperIds}.
 */
export function isPortfolioPaperRow(
  row: { accountClass?: string | null; account?: string | null; account_id?: string | null },
  ids: Set<string>,
): boolean {
  if (String(row?.accountClass ?? "").toLowerCase() !== "paper") return false;
  if (ids.size === 0) return true; // no portfolio books declared → treat all paper as portfolio
  const acct = String(row?.account ?? row?.account_id ?? "");
  if (!acct) return true; // no per-account attribution → include, don't drop
  return ids.has(acct);
}
