// Minimal client-side routing — a hash-backed current-view store. No router
// dependency: the app is small and every "route" is a top-level view.

import { writable } from "svelte/store";

export const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "trades", label: "Trades" },
  { id: "performance", label: "Performance" },
  { id: "positions", label: "Positions" },
  { id: "strategies", label: "Strategies" },
  { id: "accounts", label: "Accounts" },
  { id: "signals", label: "Signals" },
  { id: "news", label: "News" },
  { id: "reports", label: "Reports" },
] as const;

export type ViewId = (typeof VIEWS)[number]["id"];

const VALID = new Set(VIEWS.map((v) => v.id));

function fromHash(): ViewId {
  const h = (typeof location !== "undefined" ? location.hash.replace(/^#\/?/, "") : "") as ViewId;
  return VALID.has(h) ? h : "overview";
}

export const view = writable<ViewId>(fromHash());

export function goto(id: ViewId): void {
  if (typeof location !== "undefined") location.hash = `#/${id}`;
  view.set(id);
}

if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => view.set(fromHash()));
}

/** Windowed `since=` ISO timestamp for the standard 24h/7d/30d/All axis. */
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

export const WINDOW_OPTIONS = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "all", label: "All" },
];

export const FUNDING_OPTIONS = [
  { value: "real", label: "Real" },
  { value: "paper", label: "Paper" },
];
