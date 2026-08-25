#!/usr/bin/env node
/**
 * WS-frame-scope check: a SYMBOL-SCOPED frame must never decide row MEMBERSHIP.
 *
 * WHY THIS EXISTS
 * ---------------
 * `Overview.svelte` subscribed the market WebSocket to exactly ONE symbol (the
 * charted one) and then did `positions = ps` in its `onPositions` handler. The
 * server SCOPES that frame to the subscribed symbols — `market_ws.py`:
 *
 *     if symbols:
 *         positions = [p for p in positions if p["symbol"].upper() in symbols]
 *
 * ...so ~2 seconds after every load the SPA's whole positions array collapsed to
 * the charted symbol. Measured 2026-08-25: `/api/bot/positions` returned three
 * real-money rows (XRPUSDT 4934 + ETHUSDT 4922 + ETHUSDT 4904) while the
 * Overview rendered "Open trades 2" with the XRP row gone, ETHUSDT being the
 * charted symbol. Choosing BTCUSDT dropped the ETH rows the same way. Every
 * consumer read from that array: the "Open trades" KPI, the open-trades table,
 * `shownPositions`, the unrealized-P&L card, and the symbol picker itself.
 *
 * The defect had already been half-fixed. A guard `if (ps && ps.length)` was
 * added earlier to stop an EMPTY frame blanking the tables. Emptiness and
 * PARTIALNESS are the same defect and that guard only caught one of them — so
 * this check exists to make the remaining half a build failure rather than a
 * thing someone notices on a phone six weeks later.
 *
 * WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
 * -------------------------------------------------
 * Scoped to the exact shape that broke: inside an `onPositions` handler, a bare
 * assignment of the frame parameter to a state variable —
 *
 *     onPositions: (ps) => { ... positions = ps ... }
 *
 * A MERGE (`positions = positions.map(...)`) is fine and is what the fix does.
 * It does NOT try to prove the merge is correct — that is what review is for.
 * It catches the one transformation that is always wrong: letting a scoped
 * frame define the set.
 *
 * Sibling of `api-contract.mjs`, same house style: a self-test first, so a
 * green run means the probe can actually find a positive.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;

/** Every `onPositions:` handler body in `text`, as source strings. */
function handlerBodies(text) {
  const out = [];
  let i = 0;
  for (;;) {
    const at = text.indexOf("onPositions", i);
    if (at === -1) break;
    const open = text.indexOf("{", at);
    if (open === -1) break;
    let depth = 0, end = -1;
    for (let j = open; j < text.length; j++) {
      if (text[j] === "{") depth++;
      else if (text[j] === "}") { depth--; if (depth === 0) { end = j; break; } }
    }
    if (end === -1) break;
    out.push(text.slice(open, end + 1));
    i = end + 1;
  }
  return out;
}

/** The frame parameter name of an `onPositions` handler, e.g. `ps`. */
function paramOf(text, bodyStart) {
  const head = text.slice(Math.max(0, bodyStart - 80), bodyStart);
  const m = head.match(/\(\s*([A-Za-z_$][\w$]*)\s*\)\s*=>\s*$/);
  return m ? m[1] : null;
}

/**
 * Findings for one file: a bare `<state> = <frameParam>` inside an
 * `onPositions` handler. Comments are stripped first so the narrative above —
 * which quotes the very pattern it forbids — cannot trip its own check.
 */
export function findings(text, path = "<mem>") {
  const stripped = text
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
  const out = [];
  let i = 0;
  for (;;) {
    const at = stripped.indexOf("onPositions", i);
    if (at === -1) break;
    const open = stripped.indexOf("{", at);
    if (open === -1) break;
    const param = paramOf(stripped, open);
    const bodies = handlerBodies(stripped.slice(at));
    const body = bodies.length ? bodies[0] : "";
    if (param) {
      // `positions = ps` / `rows = ps` — assignment of the frame itself.
      const bare = new RegExp(`(^|[^.\\w])([A-Za-z_$][\\w$]*)\\s*=\\s*${param}\\s*[;\\n}]`);
      const m = body.match(bare);
      if (m) out.push({ path, state: m[2], param, snippet: m[0].trim() });
    }
    i = open + 1;
  }
  return out;
}

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(svelte|ts)$/.test(name)) out.push(p);
  }
  return out;
}

function selfTest() {
  const BAD = `stream = new X({ onPositions: (ps) => { if (ps && ps.length) positions = ps; } });`;
  const GOOD = `stream = new X({ onPositions: (ps) => {
      if (!ps || !ps.length) return;
      const live = new Map(ps.map((p) => [String(p.id), p]));
      positions = positions.map((p) => live.get(String(p.id)) ?? p);
    } });`;
  const COMMENTED = `// positions = ps  <- the thing we forbid, written in prose
    stream = new X({ onPositions: (ps) => { positions = positions.map((p) => p); } });`;
  let ok = true;
  const t = (label, cond) => { console.log(`  ${label}: ${cond ? "PASS" : "FAIL"}`); ok &&= cond; };
  t("1 (a wholesale replace IS flagged)", findings(BAD).length === 1);
  t("2 (a merge is NOT flagged)", findings(GOOD).length === 0);
  t("3 (the pattern in a COMMENT is not a finding)", findings(COMMENTED).length === 0);
  return ok;
}

const args = process.argv.slice(2);
if (args.includes("--self-test")) {
  console.log("ws-frame-scope self-test");
  process.exit(selfTest() ? 0 : 1);
}

// Importing this module (the self-test above, or a future harness) must not run
// the scan — a test file with a side effect on import is its own small trap.
const RUN_DIRECTLY = process.argv[1] && process.argv[1].endsWith("ws-frame-scope.mjs");
if (!RUN_DIRECTLY) { /* imported for `findings` only */ }
else {
let bad = 0, scanned = 0, handlers = 0;
for (const f of walk(SRC)) {
  const text = readFileSync(f, "utf8");
  if (!text.includes("onPositions")) continue;
  scanned++;
  handlers += handlerBodies(text).length;
  for (const v of findings(text, f.replace(SRC, "src/"))) {
    bad++;
    console.error(
      `::error::${v.path}: onPositions assigns the SYMBOL-SCOPED frame to \`${v.state}\` ` +
      `(\`${v.snippet}\`). That frame is filtered server-side to the subscribed ` +
      `symbols, so this drops every position in every other symbol. Merge uPnL ` +
      `onto the REST rows instead — REST owns membership.`);
  }
}
console.log(`ws-frame-scope: ${scanned} file(s) with an onPositions handler, ${handlers} handler(s) scanned`);
if (bad) { console.error(`ws-frame-scope: ${bad} finding(s)`); process.exit(1); }
console.log("ws-frame-scope OK — no handler lets a scoped frame define row membership.");
}
