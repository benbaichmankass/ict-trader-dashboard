// Navigation model — mirrors streamlit_app.py's SECTIONS / PAGE_DESC exactly so
// the SPA matches the production Streamlit UI: a left sidebar of 8 sections,
// each a landing of summary cards that drill into detail sub-pages (except
// Overview / Roadmap / Learning, which render directly).

import { writable } from "svelte/store";

// Section → sub-pages. Empty list = special-cased view rendered directly.
export const SECTIONS: Record<string, string[]> = {
  Overview: [],
  Performance: ["Performance", "Insights", "Reports"],
  "Strategies & Models": ["Strategies", "Models", "GPU Spend", "Exit Ladder", "Backtesting", "Promotion", "News"],
  Accounts: ["Accounts", "Prop"],
  Activity: ["Positions", "Trades", "Order Packages", "Signals"],
  Roadmap: [],
  Learning: [],
  Admin: ["Data Explorer", "Logs", "Health"],
};
export const SECTION_NAMES = Object.keys(SECTIONS);

// One-line blurb per sub-page (mirrors PAGE_DESC).
export const PAGE_DESC: Record<string, string> = {
  Performance: "Analytics deep-dive: equity curve, win-rate, expectancy, per-strategy + per-symbol.",
  Insights: "AI-analyst narrative + grade for the book and each strategy.",
  Reports: "Consolidated /system-report executive reports (health + trading + ML).",
  Strategies: "Live-runtime per-strategy status, routing, P&L curve, review packet.",
  Models: "ML fleet — per-model stage, training metric, drift.",
  "GPU Spend": "Spot-GPU training cost — per-session + monthly total vs the $10 cap.",
  "Exit Ladder": "ExitPlan laddered-vs-single-target soak (observe-only).",
  Backtesting: "Trainer-VM sweeps + on-demand /test runs.",
  Promotion: "Shadow-model promotion-readiness tracker.",
  News: "News-layer decisions (veto / boost / reduce) per actionable signal.",
  Accounts: "Per-account balance, realised/unrealised P&L, trade log.",
  Prop: "Breakout rule-distance cushion, report-back, journal.",
  Positions: "Open positions — full detail cards (entry/SL/TP/uPnL + decision).",
  Trades: "Closed-trade history (real / paper / prop).",
  "Order Packages": "Decision-level table with model scores + Claude grade.",
  Signals: "Recent ICT detections.",
  "Data Explorer": "Read-only browse of the federated canonical store.",
  Logs: "Merged pipeline + outcome log feed.",
  Health: "VM / service health + last-tick + snapshot checks.",
  Roadmap: "Product-roadmap progress — milestones → sprints → work-session notes.",
  Learning: "Trading + AI curriculum with per-resource progress.",
};

// Which detail sub-pages are actually implemented as SPA routes today. A card
// for an unimplemented page opens a "coming soon" placeholder — the section
// structure stays complete and pages fill in over time.
export const IMPLEMENTED_PAGES = new Set<string>([
  "Performance",
  "Reports",
  "Strategies",
  "News",
  "Accounts",
  "Positions",
  "Trades",
  "Signals",
  "Order Packages",
  "Insights",
  "Prop",
  "Health",
  "Logs",
  "Data Explorer",
  "GPU Spend",
  "Models",
  "Exit Ladder",
  "Backtesting",
  "Promotion",
]);

const SPECIAL_SECTIONS = new Set(["Overview", "Roadmap", "Learning"]);
export function isSpecial(section: string): boolean {
  return SPECIAL_SECTIONS.has(section);
}

// Nav state: the current section, and (for card sections) the open detail page
// or null (= showing the card landing).
export interface Nav {
  section: string;
  detail: string | null;
}

function parseHash(): Nav {
  const raw = typeof location !== "undefined" ? decodeURIComponent(location.hash.replace(/^#\/?/, "")) : "";
  const [sec, det] = raw.split("/");
  const section = SECTION_NAMES.includes(sec) ? sec : "Overview";
  const detail = det && SECTIONS[section]?.includes(det) ? det : null;
  return { section, detail };
}

// Report deep-link (`…/?report=<id>`) — the URL the bot's Telegram system-report
// ping points at. Parsed once from the query string on load; Reports.svelte
// consumes it to pre-select that report. Same `?report=` scheme the Streamlit
// app used, so the bot only had to swap the base URL to this SPA.
export function parseReportParam(): string | null {
  if (typeof location === "undefined") return null;
  try {
    return new URLSearchParams(location.search).get("report");
  } catch {
    return null;
  }
}
export const reportDeepLink = writable<string | null>(parseReportParam());

// When a ?report= deep-link is present and the hash didn't already target a
// page, land directly on the Reports detail page so the ping opens the report.
function initialNav(): Nav {
  const fromHash = parseHash();
  if (parseReportParam() && fromHash.section === "Overview" && fromHash.detail == null) {
    return { section: "Performance", detail: "Reports" };
  }
  return fromHash;
}

export const nav = writable<Nav>(initialNav());

export function gotoSection(section: string): void {
  const next: Nav = { section, detail: null };
  if (typeof location !== "undefined") location.hash = `#/${section}`;
  nav.set(next);
}

export function gotoDetail(section: string, detail: string): void {
  if (typeof location !== "undefined") location.hash = `#/${section}/${detail}`;
  nav.set({ section, detail });
}

if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => nav.set(parseHash()));
}

// ── Shared control axes (mirror _WINDOW_CHOICES / _FUNDING_CHOICES) ──────────

export const WINDOW_OPTIONS = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "all", label: "All" },
];

// One funding toggle per tab: Real money / Paper / Prop — the three are never blended.
export const FUNDING_OPTIONS = [
  { value: "real", label: "Real money" },
  { value: "paper", label: "Paper" },
  { value: "prop", label: "Prop" },
];

export function sinceFor(window: string): string | undefined {
  const now = Date.now();
  const day = 86400_000;
  switch (window) {
    case "24h":
      return new Date(now - day).toISOString();
    case "7d":
      return new Date(now - 7 * day).toISOString();
    case "30d":
      return new Date(now - 30 * day).toISOString();
    default:
      return undefined; // "all"
  }
}
