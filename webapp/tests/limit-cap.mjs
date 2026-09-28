#!/usr/bin/env node
/**
 * Limit-cap check: a hardcoded `limit` passed to the bot API must not exceed
 * the endpoint's declared cap.
 *
 * WHY THIS EXISTS
 * ----------------
 * `Trades.svelte` called `api.closedTrades({ ..., limit: 300 })`. The bot's
 * `/api/bot/trades/closed` declares `limit: int = Query(DEFAULT_LIMIT, ge=1,
 * le=MAX_LIMIT)` with `MAX_LIMIT = 200` (ict-trading-bot
 * `src/web/api/routers/trades_closed.py:57,297`, measured 2026-09-28) — so
 * every request from that screen 422'd: `{"type":"less_than_equal",
 * "loc":["query","limit"],"ctx":{"le":200}}`. The Activity → Trades tab was
 * dark for every funding class on every window, and nothing caught it: the
 * call compiled, the route rendered, the build was green, and the only
 * symptom was a 422 behind a "Couldn't load trades" banner.
 *
 * That is the same CLASS as the defects `api-contract.mjs` / `auth-bearer.mjs`
 * exist for: a request that is well-formed in every way except the one value
 * that decides whether the bot accepts it. This is the third guard of that
 * shape, this time for the query cap rather than a payload key or a header.
 *
 * WHAT IT CHECKS
 * ---------------
 * For every call site `api.<method>(...)` under `webapp/src` where `<method>`
 * is one of the endpoints below that the bot caps with `Query(..., le=N)`,
 * extract the `limit` argument — named (`{ limit: 200 }`) for the endpoints
 * the SPA calls that way, positional (`api.candles(sym, iv, 200)`) for the
 * ones it calls that way — and flag it if it resolves to a literal number, or
 * a same-file `const NAME = <number>` the call references by name, above the
 * endpoint's cap.
 *
 * The caps are PINNED HERE rather than read from the bot repo at CI time: the
 * two repos are checked out independently and reading cross-repo in CI is not
 * practical for a fast, zero-dependency job. Each cap below cites the router
 * file, the line(s), and the date measured (2026-09-28) — re-measure and
 * update the citation if the bot repo's caps ever change; a stale citation
 * that still matches the bot's actual behaviour is harmless, but the cap
 * VALUE must track the bot's `le=` or this guard passes bad requests.
 *
 * WHAT IT DELIBERATELY DOES NOT CHECK
 * ------------------------------------
 * A `limit` whose value is a computed expression (`someVar + 1`, a ternary, a
 * function call) is not statically resolvable and is silently skipped rather
 * than guessed at — a guard that flags what it cannot prove is the false
 * positive that gets guards suppressed. It also does not check `since` /
 * `offset` / other query params, or endpoints the SPA never overrides with a
 * literal (their `api.ts` defaults were hand-verified against the same caps
 * on 2026-09-28 and are all at-or-under; only a call-site OVERRIDE — the
 * pattern that actually broke — is in scope here).
 *
 * Zero dependencies — plain node, so it runs in CI without an install step.
 *
 * Usage:  node webapp/tests/limit-cap.mjs [--self-test]
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");
const EXTS = [".ts", ".js", ".svelte"];

/**
 * One entry per bot endpoint the SPA calls with a `limit` the caller can
 * override with a literal. `kind: "named"` extracts `limit: <token>` from the
 * call's argument text; `kind: "positional"` takes the `argIndex`'th
 * top-level argument. `cite` names the bot repo's router file, the line(s) of
 * the cap constant + the `Query(..., le=...)` declaration, and the date
 * measured — see the file banner above for why the cap is pinned rather than
 * read live.
 */
const CAPS = {
  closedTrades: {
    cap: 200,
    kind: "named",
    cite: "ict-trading-bot src/web/api/routers/trades_closed.py:57,297 " +
      "(DEFAULT_LIMIT=50 / MAX_LIMIT=200, Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) — measured 2026-09-28",
  },
  closedTradesPage: {
    cap: 200,
    kind: "named",
    cite: "same endpoint as closedTrades — trades_closed.py:57,297 — measured 2026-09-28",
  },
  orderPackages: {
    cap: 200,
    kind: "named",
    cite: "order_packages.py:48,226 (MAX_LIMIT=200, Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) — measured 2026-09-28",
  },
  logs: {
    cap: 1000,
    kind: "named",
    cite: "dashboard.py:690 (Query(_LOG_TAIL, ge=1, le=1000)) — measured 2026-09-28",
  },
  dbTable: {
    cap: 500,
    kind: "named",
    cite: "db_explorer.py:99-100,298 (DEFAULT_LIMIT=100 / MAX_LIMIT=500, le=MAX_LIMIT) — measured 2026-09-28",
  },
  candles: {
    cap: 1000,
    kind: "positional",
    argIndex: 2, // api.candles(symbol, interval, limit, signal?)
    cite: "candles.py:36-37,175 (DEFAULT_LIMIT=200 / MAX_LIMIT=1000, le=MAX_LIMIT) — measured 2026-09-28",
  },
  news: {
    cap: 500,
    kind: "positional",
    argIndex: 0, // api.news(limit, signal?)
    cite: "news.py:25 (Query(100, ge=1, le=500)) — measured 2026-09-28",
  },
  exitLadderSoak: {
    cap: 500,
    kind: "positional",
    argIndex: 0, // api.exitLadderSoak(limit, signal?)
    cite: "exit_ladder.py:24 (Query(100, ge=1, le=500)) — measured 2026-09-28",
  },
  backtestSweeps: {
    cap: 100,
    kind: "positional",
    argIndex: 0, // api.backtestSweeps(limit, signal?)
    cite: "backtests.py:56-57,245 (SWEEPS_DEFAULT_LIMIT=20 / SWEEPS_MAX_LIMIT=100, le=SWEEPS_MAX_LIMIT) — measured 2026-09-28",
  },
  propFills: {
    cap: 500,
    kind: "positional",
    argIndex: 0, // api.propFills(limit, signal?)
    cite: "prop.py:98,103 (no Query cap — server clamps via max(1, min(limit, 500)), not a 422) — measured 2026-09-28",
  },
  propTickets: {
    cap: 500,
    kind: "positional",
    argIndex: 0, // api.propTickets(limit, signal?)
    cite: "prop.py:115,120 (clamped server-side to 500, same as propFills) — measured 2026-09-28",
  },
};

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (EXTS.some((e) => name.endsWith(e))) out.push(full);
  }
  return out;
}

function posix(p) {
  return p.split(sep).join("/");
}

/**
 * Blank comments AND string CONTENTS (preserving offsets and quotes), so a
 * stray bracket or the word "limit" inside a string/comment cannot confuse
 * call-site or bracket matching. Same technique as auth-bearer.mjs's scan().
 */
function scan(src) {
  const masked = src.split("");
  let i = 0;
  const n = src.length;
  const blank = (at) => {
    if (src[at] !== "\n") masked[at] = " ";
  };
  while (i < n) {
    const c = src[i];
    const next = src[i + 1];
    if (c === "/" && next === "/") {
      while (i < n && src[i] !== "\n") blank(i++);
      continue;
    }
    if (c === "/" && next === "*") {
      blank(i++);
      blank(i++);
      while (i < n && !(src[i] === "*" && src[i + 1] === "/")) blank(i++);
      if (i < n) {
        blank(i++);
        blank(i++);
      }
      continue;
    }
    if (c === "<" && src.startsWith("<!--", i)) {
      while (i < n && !src.startsWith("-->", i)) blank(i++);
      for (let k = 0; k < 3 && i < n; k++) blank(i++);
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      i++;
      while (i < n) {
        if (src[i] === "\\") {
          blank(i++);
          if (i < n) blank(i++);
          continue;
        }
        if (src[i] === quote) break;
        blank(i++);
      }
      i++;
      continue;
    }
    i++;
  }
  return masked.join("");
}

/** Bracket-match from the `(` at `open`; returns the index after the closing `)`. */
function matchParen(masked, open) {
  let depth = 0;
  for (let i = open; i < masked.length; i++) {
    const c = masked[i];
    if (c === "(") depth++;
    else if (c === ")") {
      depth--;
      if (depth === 0) return i + 1;
    }
  }
  return -1;
}

/** Split a masked argument-list text on TOP-LEVEL commas (nested brackets kept intact). */
function splitTopLevel(s) {
  const parts = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === "," && depth === 0) {
      parts.push(s.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(s.slice(start));
  return parts.map((p) => p.trim()).filter((p) => p.length > 0);
}

/** Resolve a token to a number: a bare numeric literal, or a same-file `const NAME = N` it names. */
function resolveValue(token, constMap) {
  const t = token.trim();
  if (/^\d+$/.test(t)) return { value: Number(t), source: "literal" };
  if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(t) && constMap.has(t)) {
    return { value: constMap.get(t), source: `const ${t} = ${constMap.get(t)}` };
  }
  return null; // a computed expression — not statically resolvable, not flagged
}

/** Every `api.<method>(...)` call site for a method in CAPS, with its raw argument text. */
function findCallSites(masked) {
  const names = Object.keys(CAPS).join("|");
  const re = new RegExp(`\\.(${names})\\s*\\(`, "g");
  const sites = [];
  let m;
  while ((m = re.exec(masked)) !== null) {
    const open = re.lastIndex - 1; // position of the "(" the match ended on
    const end = matchParen(masked, open);
    if (end === -1) continue;
    sites.push({
      method: m[1],
      line: masked.slice(0, m.index).split("\n").length,
      argsText: masked.slice(open + 1, end - 1),
    });
    re.lastIndex = end;
  }
  return sites;
}

/** Grade one file. Returns { checked, findings[] }. */
function gradeFile(relPath, src) {
  const masked = scan(src);
  const constMap = new Map();
  for (const cm of masked.matchAll(/\bconst\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(\d+)\s*;/g)) {
    constMap.set(cm[1], Number(cm[2]));
  }
  const findings = [];
  let checked = 0;
  for (const site of findCallSites(masked)) {
    const rule = CAPS[site.method];
    let token = null;
    if (rule.kind === "named") {
      const nm = site.argsText.match(/\blimit\s*:\s*([A-Za-z0-9_.$]+)/);
      if (nm) token = nm[1];
    } else {
      token = splitTopLevel(site.argsText)[rule.argIndex] ?? null;
    }
    if (token == null) continue; // this call didn't pass a limit at all — nothing to check
    const resolved = resolveValue(token, constMap);
    if (resolved == null) continue; // computed expression — can't statically resolve; not flagged
    checked++;
    if (resolved.value > rule.cap) {
      findings.push({
        file: relPath,
        line: site.line,
        detail:
          `api.${site.method}(...) passes limit=${resolved.value} (${resolved.source}) — ` +
          `the bot caps this endpoint's limit at ${rule.cap} (${rule.cite}). A value above the ` +
          `cap gets a 422 from FastAPI and the screen shows "Couldn't load ..." for every request.`,
      });
    }
  }
  return { checked, findings };
}

function runOverTree() {
  const files = walk(SRC);
  let checked = 0;
  const findings = [];
  for (const full of files) {
    const relPath = posix(relative(SRC, full));
    const graded = gradeFile(relPath, readFileSync(full, "utf8"));
    checked += graded.checked;
    findings.push(...graded.findings);
  }
  return { files: files.length, checked, findings };
}

// ---------------------------------------------------------------------------
// Self-test — the checker must be able to FAIL, and must not over-fire.
// ---------------------------------------------------------------------------

const CASES = [
  {
    name: "1 (the historical defect IS flagged: closedTrades limit:300 > cap 200)",
    file: "routes/Trades.svelte",
    src: `const r = await api.closedTrades({ since: sinceFor(win), includePaper: funding === "paper", limit: 300 });`,
    expect: 1,
  },
  {
    name: "2 (the fix at exactly the cap IS accepted: limit:200)",
    file: "routes/Trades.svelte",
    src: `const r = await api.closedTrades({ since: sinceFor(win), limit: 200 });`,
    expect: 0,
  },
  {
    name: "3 (a positional violation IS flagged: candles 3rd arg > cap 1000)",
    file: "routes/Overview.svelte",
    src: `const r = await api.candles(sym, interval, 1500);`,
    expect: 1,
  },
  {
    name: "4 (the same positional call within cap IS accepted)",
    file: "routes/Overview.svelte",
    src: `const r = await api.candles(sym, interval, 200);`,
    expect: 0,
  },
  {
    name: "5 (a named limit resolved through a same-file const IS flagged above the cap)",
    file: "routes/DataExplorer.svelte",
    src: `const LIMIT = 501;\n  page = await api.dbTable(name, { db, limit: LIMIT, offset });`,
    expect: 1,
  },
  {
    name: "6 (the same const at exactly the cap IS accepted)",
    file: "routes/DataExplorer.svelte",
    src: `const LIMIT = 500;\n  page = await api.dbTable(name, { db, limit: LIMIT, offset });`,
    expect: 0,
  },
  {
    name: "7 (a computed limit is unresolvable and NOT a false positive)",
    file: "routes/X.svelte",
    src: `const r = await api.orderPackages({ limit: someVar + 1 });`,
    expect: 0,
  },
  {
    name: "8 (a bad limit named only in a COMMENT is not a finding)",
    file: "routes/Trades.svelte",
    src: `// was: api.closedTrades({ limit: 300 })\nconst x = 1;`,
    expect: 0,
  },
  {
    name: "9 (a bad limit inside a STRING is not a finding)",
    file: "routes/Trades.svelte",
    src: `const note = "api.closedTrades({ limit: 300 })"; const x = 1;`,
    expect: 0,
  },
];

function selfTest() {
  console.log("limit-cap self-test");
  let failed = 0;
  for (const c of CASES) {
    const got = gradeFile(c.file, c.src).findings.length;
    const ok = got === c.expect;
    if (!ok) failed++;
    console.log(`  ${c.name}: ${ok ? "PASS" : `FAIL (expected ${c.expect} finding(s), got ${got})`}`);
  }
  const emptyChecked = gradeFile("lib/empty.ts", "const x = 1;").checked;
  const popOk = emptyChecked === 0;
  if (!popOk) failed++;
  console.log(`  10 (an empty population is recognised as empty): ${popOk ? "PASS" : "FAIL"}`);

  if (failed) {
    console.error(`SELF-TEST FAILED — ${failed} case(s)`);
    process.exit(1);
  }
  console.log(`SELF-TEST PASS (${CASES.length + 1}/${CASES.length + 1})`);
}

// ---------------------------------------------------------------------------

if (process.argv.includes("--self-test")) {
  selfTest();
} else {
  const { files, checked, findings } = runOverTree();

  if (checked === 0) {
    console.error(
      `limit-cap: REFUSING to pass — 0 resolvable limit argument(s) found across ${files} file(s) under ` +
        `webapp/src. The probe has no positive control, so a clean result here would be indistinguishable ` +
        `from a probe pointed at the wrong directory or a method-name table that no longer matches api.ts.`,
    );
    process.exit(1);
  }

  if (findings.length) {
    console.error(
      `limit-cap: ${findings.length} call site(s) pass a limit above the bot's declared cap ` +
        `(${checked} resolvable limit argument(s) checked across ${files} file(s)):`,
    );
    for (const f of findings) console.error(`  ${f.file}:${f.line} — ${f.detail}`);
    console.error(
      `\nFix: lower the literal (or the const it resolves through) to at most the cited cap. If the window ` +
        `genuinely needs more rows than one page, walk the endpoint's \`offset\`/\`X-Has-More\` (see ` +
        `api.ts::closedTradesPage) rather than raising the request past what the bot accepts.`,
    );
    process.exit(1);
  }

  console.log(
    `limit-cap OK — ${checked} resolvable limit argument(s) across ${files} file(s) under webapp/src; ` +
      `none exceed their endpoint's declared cap.`,
  );
}
