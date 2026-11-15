// Overview work-queue reorder (row UI-WORK-QUEUE-REORDER). Contract agreed with the bot lane
// WORK-REORDER-ROUTE (2026-11-15): POST /api/bot/work/reorder {id, direction: "up"|"down"} —
// session-gated, the swap is atomic server-side, null ranks are assigned server-side, and a LOWER
// priority_rank is HIGHER in the list, nulls last. Pure helpers, no DOM: tests/work-reorder.mjs
// imports this file directly (node 22 strips the types).

export type ReorderDir = "up" | "down";
type Ranked = { priorityRank?: number | null };

/** Lower rank first, null/absent last; stable among equals (the server's order for ties is kept). */
export function byRank<T extends Ranked>(rows: readonly T[]): T[] {
  const key = (r: T) => (typeof r?.priorityRank === "number" && Number.isFinite(r.priorityRank) ? r.priorityRank : Infinity);
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => key(a.r) - key(b.r) || a.i - b.i)
    .map((x) => x.r);
}

/** Can the row at `idx` move that way within the list it is shown in? (First can't go up, last can't go down.) */
export function canMove(len: number, idx: number, dir: ReorderDir): boolean {
  if (!Number.isInteger(idx) || idx < 0 || idx >= len) return false;
  return dir === "up" ? idx > 0 : idx < len - 1;
}

/** The server's refusal, shown verbatim: its `detail` (string as-is, anything else as JSON), else the raw text, else the status. */
export function refusalText(r: { status: number; body?: unknown; text?: string }): string {
  const d = (r.body as { detail?: unknown } | null | undefined)?.detail;
  const detail = d == null ? null : typeof d === "string" ? d : JSON.stringify(d);
  const raw = (r.text ?? "").trim();
  return `HTTP ${r.status}: ${detail ?? (raw !== "" ? raw.slice(0, 400) : "no detail")}`;
}
