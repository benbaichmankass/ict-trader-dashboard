// Decision-request grading — ONE owner for the SPA (shared by Work.svelte's
// decision inbox and the Work → Decisions tab). Every fact here comes FROM THE
// BOT (`work_decisions.py`): `settled` (SETTLED_STATES) and `actionable`
// (decision_subject.is_actionable). Never re-derive them from answerState.
//
// ⚠️ THREE STATES, NEVER TWO. Both fields are ABSENT on an older bot, and a strict
// true/false pair sends those rows to NEITHER bucket — they vanish (measured
// 2026-09-10: all 26 decisions disappeared). `ungraded` is "WE COULD NOT TELL",
// never "answered", and it rides WITH the waiting rows (fail toward surfacing).
export type Tri = "yes" | "no" | "ungraded";

export const isSettled = (r: any): Tri =>
  r?.settled === true ? "yes" : r?.settled === false ? "no" : "ungraded";

export const isActionable = (r: any): Tri =>
  r?.actionable === true ? "yes" : r?.actionable === false ? "no" : "ungraded";

// MOOT: not settled AND not actionable — nobody answered and there is nothing
// left to answer about. Composed from two facts the bot owns.
export const isMoot = (r: any): boolean => isSettled(r) === "no" && isActionable(r) === "no";

// Waiting = not settled (incl. ungraded) and not moot.
export const isWaiting = (r: any): boolean => isSettled(r) !== "yes" && !isMoot(r);
