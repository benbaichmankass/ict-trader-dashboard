// Funding "books" — the one axis every funding-scoped tab filters on.
//
// Four books, in toggle order, never blended (UI-FOUR-BOOKS, 2026-10-29):
//   real             Live money        account_class real_money
//   prop             Prop              account_class prop
//   paper_portfolio  Paper portfolio   account_class paper, paper_role portfolio
//                                      (the books that mirror the live-traded portfolio)
//   paper_testing    Paper testing     every other paper/demo account (paper_role soak /
//                                      demo, or NO paper_role at all)
//
// Classification is data-driven off the bot's /api/bot/config (`account_class` +
// `paper_role`) — never a hardcoded id list — so a roster change needs no
// webapp edit. An account with no `paper_role` falls into Paper TESTING: the
// portfolio book is an explicit declaration, so absence must not promote an
// account into the book the operator reads as the live mirror.
//
// Before this, "Paper" meant portfolio-only and the testing/demo-floor accounts
// appeared in no Overview tab ("Open trades 0" while 8 testing trades were open).

export type FundingBook = "real" | "prop" | "paper_portfolio" | "paper_testing";

/**
 * A paper row we cannot place in either paper book: it carries no account id
 * (e.g. /order-packages rows), or /config was unreadable so no account→book map
 * exists. It matches NO toggle position — guessing would blend the two books.
 */
export type RowBook = FundingBook | "paper_unassigned";

export const FUNDING_BOOKS: FundingBook[] = ["real", "prop", "paper_portfolio", "paper_testing"];

export const FUNDING_LABEL: Record<FundingBook, string> = {
  real: "Live money",
  prop: "Prop",
  paper_portfolio: "Paper portfolio",
  paper_testing: "Paper testing",
};

export function isPaperBook(b: string): boolean {
  return b === "paper_portfolio" || b === "paper_testing";
}

/**
 * Coerce any stored/stale funding choice into a valid book. The old toggle was
 * Real money / Paper / Prop with values real | paper | prop (and Streamlit's
 * older "All"), so a returning viewer may hold "paper" — that meant the
 * portfolio mirror, so it migrates to paper_portfolio. Anything unknown → real.
 */
export function normalizeFunding(v: unknown): FundingBook {
  const s = String(v ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (s === "paper") return "paper_portfolio";
  if ((FUNDING_BOOKS as string[]).includes(s)) return s as FundingBook;
  if (s === "real_money" || s === "live" || s === "live_money") return "real";
  return "real";
}

const PAPER_CLASSES = new Set(["paper", "demo"]);

/**
 * account id → book, from a /api/bot/config payload. Accounts whose class is
 * unrecognised are left OUT (the row's own accountClass decides for them) rather
 * than guessed into real money.
 */
export function accountBooks(config: any): Record<string, FundingBook> {
  const m: Record<string, FundingBook> = {};
  for (const a of config?.accounts ?? []) {
    const id = a?.id ?? a?.account_id;
    if (!id) continue;
    const cls = String(a?.account_class ?? "").toLowerCase();
    const role = String(a?.paper_role ?? "").toLowerCase();
    if (cls === "prop") m[String(id)] = "prop";
    else if (cls === "real_money" || cls === "real" || cls === "live") m[String(id)] = "real";
    else if (PAPER_CLASSES.has(cls) || role) {
      // No paper_role (or soak / demo / anything not "portfolio") → testing.
      m[String(id)] = role === "portfolio" ? "paper_portfolio" : "paper_testing";
    }
  }
  return m;
}

type BookRow = { accountClass?: string | null; account?: string | null; account_id?: string | null };

/** The book one position / closed trade / order package belongs to. */
export function bookOfRow(row: BookRow, books: Record<string, FundingBook>): RowBook {
  const cls = String(row?.accountClass ?? "").toLowerCase();
  const acct = String(row?.account ?? row?.account_id ?? "");
  const mapped = acct ? books[acct] : undefined;
  if (cls === "prop") return "prop";
  if (PAPER_CLASSES.has(cls)) {
    if (mapped && isPaperBook(mapped)) return mapped;
    if (!acct) return "paper_unassigned";
    // Account named but absent from a non-empty config → no paper_role → testing.
    // Config unreadable (empty map) → can't tell → unassigned, never guessed.
    return Object.keys(books).length ? "paper_testing" : "paper_unassigned";
  }
  if (mapped) return mapped; // row carries no class: the account's declared book
  return "real";
}

/** True when `row` belongs to the selected funding book. */
export function matchesBook(row: BookRow, funding: string, books: Record<string, FundingBook>): boolean {
  return bookOfRow(row, books) === normalizeFunding(funding);
}

/** Paper rows that fit neither paper book (for an honest "N unassigned" caption). */
export function countUnassigned(rows: BookRow[], books: Record<string, FundingBook>): number {
  let n = 0;
  for (const r of rows) if (bookOfRow(r, books) === "paper_unassigned") n++;
  return n;
}
