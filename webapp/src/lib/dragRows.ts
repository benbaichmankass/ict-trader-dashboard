// Pointer-based drag for the Overview work queue (UI-WORK-QUEUE-DND). One code path for mouse AND touch:
// pressing the row's drag handle (touch-action:none) starts the drag, so no long-press is needed and the page
// still scrolls everywhere else. Lists are `[data-wlist]` elements whose rows are `[data-rid]`; the drop
// slot is derived from the rows' DOM order, and the payload from the pure `dropPayload` helper.
import { dropPayload, type ReorderDir } from "./workReorder";

export type Drop = { id: string; direction: ReorderDir; over: string };

const MARK = ["dnd-above", "dnd-below", "dnd-dragging"];

function clearMarks() {
  for (const c of MARK) document.querySelectorAll("." + c).forEach((e) => e.classList.remove(c));
}

function target(x: number, y: number, id: string): { rows: HTMLElement[]; slot: number } | null {
  const list = (document.elementFromPoint(x, y) as HTMLElement | null)?.closest<HTMLElement>("[data-wlist]");
  if (!list) return null;
  const rows = Array.from(list.querySelectorAll<HTMLElement>("[data-rid]"));
  let slot = 0;
  for (const r of rows) {
    const b = r.getBoundingClientRect();
    if (y > b.top + b.height / 2) slot++;
  }
  return { rows, slot };
}

/** Start a drag of row `id` from a pointerdown on its handle. `onDrop` gets the POST body, or null for a no-op drop. */
export function startDrag(e: PointerEvent, id: string, onDrop: (d: Drop) => void, onNoop?: () => void) {
  if (e.button !== undefined && e.button > 0) return;
  e.preventDefault();
  const handle = e.currentTarget as HTMLElement;
  try { handle.setPointerCapture(e.pointerId); } catch { /* not capturable: window listeners still work */ }
  const src = handle.closest<HTMLElement>("[data-rid]");
  src?.classList.add("dnd-dragging");
  let x = e.clientX, y = e.clientY, raf = 0;

  const paint = () => {
    for (const c of ["dnd-above", "dnd-below"]) document.querySelectorAll("." + c).forEach((el) => el.classList.remove(c));
    const t = target(x, y, id);
    if (!t || t.rows.length === 0) return;
    if (t.slot >= t.rows.length) t.rows[t.rows.length - 1].classList.add("dnd-below");
    else t.rows[t.slot].classList.add("dnd-above");
  };
  const tick = () => {
    const m = 56;
    if (y < m) window.scrollBy(0, -Math.ceil((m - y) / 4));
    else if (y > window.innerHeight - m) window.scrollBy(0, Math.ceil((y - (window.innerHeight - m)) / 4));
    paint();
    raf = requestAnimationFrame(tick);
  };
  const move = (ev: PointerEvent) => { x = ev.clientX; y = ev.clientY; };
  const finish = (ev: PointerEvent | null) => {
    cancelAnimationFrame(raf);
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", up);
    handle.removeEventListener("pointercancel", cancel);
    const t = ev ? target(ev.clientX, ev.clientY, id) : null;
    clearMarks();
    if (!t) return onNoop?.();
    const d = dropPayload(t.rows.map((r) => ({ id: r.dataset.rid })), id, t.slot);
    if (d) onDrop(d); else onNoop?.();
  };
  const up = (ev: PointerEvent) => finish(ev);
  const cancel = () => finish(null);
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", up);
  handle.addEventListener("pointercancel", cancel);
  raf = requestAnimationFrame(tick);
}
