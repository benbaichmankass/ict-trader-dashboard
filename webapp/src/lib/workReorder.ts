// Overview work-queue reorder (row UI-WORK-QUEUE-REORDER). Contract agreed with the bot lane
// WORK-REORDER-ROUTE (2026-11-15): POST /api/bot/work/reorder {id, direction: "up"|"down", over} —
// session-gated, the swap is atomic server-side, null ranks are assigned server-side, and a LOWER
// priority_rank is HIGHER in the list, nulls last. `over` is the id of the row's VISIBLE neighbour in
// the card it is shown in: the swap is within the visible list (the In-flight card is a filter of the
// open rows), so the server swaps order with that row rather than with its neighbour in the full list. Pure helpers, no DOM: tests/work-reorder.mjs
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

/** The id of the visible neighbour a row would swap with (above for "up", below for "down"), or null when it cannot move. */
export function neighbourId(rows: readonly { id?: unknown }[], idx: number, dir: ReorderDir): string | null {
  if (!canMove(rows.length, idx, dir)) return null;
  const id = rows[dir === "up" ? idx - 1 : idx + 1]?.id;
  return typeof id === "string" && id !== "" ? id : null;
}

/** A reorder answer that is a refusal: a non-2xx, or a 2xx whose body says `accepted: false`. */
export function isRefusal(r: { ok: boolean; body?: unknown }): boolean {
  return !r.ok || (r.body as { accepted?: unknown } | null | undefined)?.accepted === false;
}

/**
 * The server's refusal, shown verbatim. The bot answers every refusal as JSON `{accepted:false, error, detail}`
 * (e.g. 409 at_top / at_bottom / version_conflict, 422 finished row): both are shown, `error: detail`; either
 * alone as-is; a body that is neither (a proxy error page) falls back to its raw text; never blank.
 */
export function refusalText(r: { status: number; body?: unknown; text?: string }): string {
  const b = r.body as { error?: unknown; detail?: unknown } | null | undefined;
  const asText = (v: unknown) => (v == null || v === "" ? null : typeof v === "string" ? v : JSON.stringify(v));
  const error = asText(b?.error);
  const detail = asText(b?.detail);
  const raw = (r.text ?? "").trim();
  const msg = error && detail ? `${error}: ${detail}` : error ?? detail ?? (raw !== "" ? raw.slice(0, 400) : "no detail");
  return `HTTP ${r.status}: ${msg}`;
}

/**
 * Drag-and-drop (UI-WORK-QUEUE-DND): the POST body for dropping row `id` at insertion slot `slot` of the list
 * `rows` as it is displayed (slot 0 = above the first row, rows.length = below the last). The dragged row is
 * ignored if it is in `rows` (a within-list drag), so "drop X directly above Y" is {id: X, direction: "up",
 * over: Y} and "below Y" is direction "down". Cross-list drops use the same shape (the bot adopts Y's rank).
 * null when there is no other row to anchor to, or the drop would put X where it already is.
 */
export function dropPayload(
  rows: readonly { id?: unknown }[],
  id: string,
  slot: number,
): { id: string; direction: ReorderDir; over: string } | null {
  const ids = rows.map((r) => (typeof r?.id === "string" ? r.id : "")).filter((x) => x !== "");
  const at = ids.indexOf(id);
  const others = ids.filter((x) => x !== id);
  if (others.length === 0 || !Number.isFinite(slot)) return null;
  // slot counts slots of the full list; convert to a slot among the others
  let s = Math.max(0, Math.min(ids.length, Math.trunc(slot)));
  if (at >= 0 && s > at) s -= 1;
  if (at >= 0 && s === at) return null; // dropped back where it was
  return s >= others.length
    ? { id, direction: "down", over: others[others.length - 1] }
    : { id, direction: "up", over: others[s] };
}

/** Newest-first notes of a full work row: `extra.notes` (array, oldest→newest) when present, else the single `extra.note`. */
export function rowNotes(row: { extra?: { note?: unknown; notes?: unknown } | null } | null | undefined): string[] {
  const ex = row?.extra;
  const asText = (v: unknown) => (typeof v === "string" ? v : v && typeof v === "object" ? JSON.stringify(v) : String(v));
  if (Array.isArray(ex?.notes) && ex.notes.length) return ex.notes.map(asText).filter((t) => t.trim() !== "").reverse();
  return typeof ex?.note === "string" && ex.note.trim() !== "" ? [ex.note] : [];
}
