#!/usr/bin/env node
/**
 * Auth-bearer check: every network call to the bot API must carry the session
 * bearer — or be the ONE call deliberately exempted, by name.
 *
 * WHY THIS EXISTS
 * ---------------
 * The bot gates four handlers behind `Depends(require_session)`. Two of them,
 * `GET /api/bot/db/tables` and `GET /api/bot/db/table/{name}`, are the Data
 * Explorer's entire data source, and `db_explorer.py` refuses a request with no
 * `Authorization: Bearer` header with 401 BEFORE it opens any database.
 *
 * Measured 2026-09-11 over all 40 `.svelte`/`.ts`/`.js` files under
 * `webapp/src`: the SPA had no token store, no login UI, and its single
 * `fetch` sent `{ Accept: "application/json" }` and nothing else. So the tab
 * was dark, and no test, type or build could notice — the call compiled fine,
 * the route rendered fine, and the only symptom was a 401 in a panel nobody
 * was watching. That is the class this guard exists for: a request that is
 * well-formed in every way except the one header that decides whether it
 * returns data.
 *
 * WHAT MAKES IT SMALL, AND WHY THE GUARD PROTECTS THAT
 * ----------------------------------------------------
 * The fix was four small pieces rather than an auth build for exactly one
 * reason: the SPA has ONE network chokepoint, `api.ts::get`, through which
 * every REST path passes. Attaching the header there attached it everywhere.
 *
 * That property is an INVARIANT, not a fact about one commit. The moment
 * someone adds a second `fetch` — reasonably, for a new endpoint — it silently
 * will not carry the bearer, and any gated route it touches goes dark the same
 * quiet way. This guard makes adding that second call a build failure unless it
 * attaches the header too.
 *
 * WHAT IT CHECKS
 * --------------
 * For every `fetch(` call site under `webapp/src` (comments and string bodies
 * excluded), the argument list must either:
 *   (a) reference `authHeaders` or `Authorization`; or
 *   (b) match an entry in EXEMPT below.
 *
 * There is exactly one exemption: `POST /api/auth/login` in `lib/auth.ts`. It
 * is the bot's only mint path and sits in its `PUBLIC_ROUTES`, so requiring a
 * bearer on it would be circular. The exemption is scoped to that FILE and
 * that PATH — the same call written elsewhere still fails, which self-test 4
 * proves.
 *
 * WHAT IT DELIBERATELY DOES NOT CHECK
 * -----------------------------------
 * `new WebSocket` in `lib/ws.ts`. `/ws/market` is not gated today, and a
 * browser `WebSocket` cannot send an `Authorization` header at all — if the
 * read gate ever widens to the socket, the answer is a query-param or
 * subprotocol scheme and a genuine auth build, not a header. The checker
 * REPORTS the socket rather than ignoring it, so the exclusion stays visible
 * instead of becoming an unexamined silence.
 *
 * It also does not verify the token is VALID, that the host accepts it, or
 * that the tab renders. Those are host-side and human-side facts respectively;
 * no CI job can establish them.
 *
 * Zero dependencies — plain node, so it runs in CI without an install step.
 * `--self-test` plants the historical defect and requires the checker to catch
 * it: a gate that cannot fail proves nothing.
 *
 * Usage:  node webapp/tests/auth-bearer.mjs [--self-test]
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");

/**
 * The only call allowed to go out without a bearer.
 *
 * `file` is a posix-style path relative to `webapp/src`. `mustReference` keeps
 * the exemption pinned to the login route specifically, so it cannot be reused
 * to wave through an unrelated unauthenticated call added to the same file.
 */
const EXEMPT = [
  {
    file: "lib/auth.ts",
    mustReference: "/api/auth/login",
    reason:
      "the bot's only mint path; it is in PUBLIC_ROUTES, so requiring a bearer on it would be circular",
  },
];

const EXTS = [".ts", ".js", ".svelte"];

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (EXTS.some((e) => name.endsWith(e))) out.push(full);
  }
  return out;
}

/**
 * Blank out comments, and (in `masked`) string CONTENTS, preserving every
 * offset so line numbers and cross-indexing stay exact.
 *
 * Returns { stripped, masked }:
 *   stripped — comments blanked, string literals intact (text checks read this)
 *   masked   — comments AND string contents blanked (bracket matching reads
 *              this, so a bracket inside a string cannot throw off the match)
 */
function scan(src) {
  const stripped = src.split("");
  const masked = src.split("");
  let i = 0;
  const n = src.length;
  const blank = (at) => {
    if (src[at] !== "\n") {
      stripped[at] = " ";
      masked[at] = " ";
    }
  };
  const maskOnly = (at) => {
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
      i++; // keep the opening quote
      while (i < n) {
        if (src[i] === "\\") {
          maskOnly(i++);
          if (i < n) maskOnly(i++);
          continue;
        }
        if (src[i] === quote) break;
        // A template literal's ${...} is live code, not string body — leave it
        // masked anyway: it cannot legitimately hold the auth header, and
        // masking it keeps bracket matching honest.
        maskOnly(i++);
      }
      i++; // closing quote
      continue;
    }
    i++;
  }
  return { stripped: stripped.join(""), masked: masked.join("") };
}

/** Bracket-match from the `(` at `open` in `masked`; returns the index after `)`. */
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

/** Every `fetch(` call site in one file, with its argument text. */
function fetchSites(src) {
  const { stripped, masked } = scan(src);
  const sites = [];
  const re = /fetch\s*\(/g;
  let m;
  while ((m = re.exec(masked)) !== null) {
    const start = m.index;
    // `refetch(` / `prefetch(` are not `fetch(`.
    const prev = start > 0 ? masked[start - 1] : "";
    if (/[A-Za-z0-9_$]/.test(prev)) continue;
    const open = masked.indexOf("(", start);
    const end = matchParen(masked, open);
    if (end === -1) continue;
    sites.push({
      line: src.slice(0, start).split("\n").length,
      args: stripped.slice(open, end),
    });
    re.lastIndex = end;
  }
  return sites;
}

function posix(p) {
  return p.split(sep).join("/");
}

/** Grade one file's call sites. Returns { checked, findings[] }. */
function gradeFile(relPath, src) {
  const findings = [];
  let checked = 0;
  for (const site of fetchSites(src)) {
    checked++;
    const carriesBearer = /authHeaders|Authorization/.test(site.args);
    if (carriesBearer) continue;
    const exemption = EXEMPT.find(
      (e) => e.file === relPath && site.args.includes(e.mustReference),
    );
    if (exemption) continue;
    findings.push({
      file: relPath,
      line: site.line,
      detail:
        "fetch() without an Authorization header and not an allowed exemption — " +
        "a gated route called from here returns 401 and the surface goes dark silently",
    });
  }
  return { checked, findings };
}

function runOverTree() {
  const files = walk(SRC);
  let checked = 0;
  const findings = [];
  const sockets = [];
  for (const full of files) {
    const relPath = posix(relative(SRC, full));
    const src = readFileSync(full, "utf8");
    const graded = gradeFile(relPath, src);
    checked += graded.checked;
    findings.push(...graded.findings);
    const { masked } = scan(src);
    if (/new\s+WebSocket\s*\(/.test(masked)) sockets.push(relPath);
  }
  return { files: files.length, checked, findings, sockets };
}

// ---------------------------------------------------------------------------
// Self-test — the checker must be able to FAIL, and must not over-fire.
// ---------------------------------------------------------------------------

const CASES = [
  {
    name: "1 (the historical defect IS flagged)",
    file: "lib/api.ts",
    src: `const res = await fetch(url, { signal, headers: { Accept: "application/json" } });`,
    expectFindings: 1,
  },
  {
    name: "2 (the fix IS accepted)",
    file: "lib/api.ts",
    src: `const res = await fetch(url, { signal, headers: authHeaders() });`,
    expectFindings: 0,
  },
  {
    name: "3 (a bare fetch IS flagged)",
    file: "routes/New.svelte",
    src: `const r = await fetch(getBotApiUrl() + "/api/bot/stats");`,
    expectFindings: 1,
  },
  {
    name: "4 (the login exemption is FILE-scoped, not a blanket pass)",
    file: "routes/Sneaky.svelte",
    src: `await fetch(base + "/api/auth/login", { method: "POST", body });`,
    expectFindings: 1,
  },
  {
    name: "5 (the real login call in lib/auth.ts is exempt)",
    file: "lib/auth.ts",
    src: `res = await fetch(\`\${getBotApiUrl()}/api/auth/login\`, { method: "POST", body });`,
    expectFindings: 0,
  },
  {
    name: "6 (an explicit Authorization header is accepted)",
    file: "lib/other.ts",
    src: `await fetch(u, { headers: { Authorization: "Bearer " + t } });`,
    expectFindings: 0,
  },
  {
    name: "7 (the pattern in a COMMENT is not a finding)",
    file: "lib/api.ts",
    src: `// was: fetch(url, { headers: { Accept: "application/json" } })\nconst x = 1;`,
    expectFindings: 0,
  },
  {
    name: "8 (refetch()/prefetch() are not fetch())",
    file: "lib/api.ts",
    src: `refetch(url); prefetch(url);`,
    expectFindings: 0,
  },
  {
    name: "9 (a URL containing a paren does not break the match)",
    file: "routes/X.svelte",
    src: `await fetch("https://h/x?f=a(b)", { headers: { Accept: "application/json" } });`,
    expectFindings: 1,
  },
];

function selfTest() {
  console.log("auth-bearer self-test");
  let failed = 0;
  for (const c of CASES) {
    const got = gradeFile(c.file, c.src).findings.length;
    const ok = got === c.expectFindings;
    if (!ok) failed++;
    console.log(`  ${c.name}: ${ok ? "PASS" : `FAIL (expected ${c.expectFindings} finding(s), got ${got})`}`);
  }
  // The population guard itself must work: a tree with no fetch at all must be
  // refused, not congratulated.
  const emptyPop = gradeFile("lib/empty.ts", "const x = 1;").checked;
  const popOk = emptyPop === 0;
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
  const { files, checked, findings, sockets } = runOverTree();

  // A checker that reports success over an empty population has measured
  // nothing. If there is no fetch under webapp/src at all, something moved and
  // this guard is pointed at the wrong tree — that is a failure, not a pass.
  if (checked === 0) {
    console.error(
      `auth-bearer: REFUSING to pass — 0 fetch() call sites found across ${files} file(s) ` +
        `under webapp/src. The probe has no positive control, so a clean result here would ` +
        `be indistinguishable from a probe pointed at the wrong directory.`,
    );
    process.exit(1);
  }

  if (sockets.length) {
    console.log(
      `auth-bearer: note — ${sockets.length} file(s) open a WebSocket (${sockets.join(", ")}). ` +
        `DELIBERATELY NOT CHECKED: /ws/market is ungated today and a browser WebSocket cannot ` +
        `send an Authorization header. If the read gate widens to the socket, this needs a ` +
        `query-param or subprotocol scheme — a separate piece of work, not a header.`,
    );
  }

  if (findings.length) {
    console.error(
      `auth-bearer: ${findings.length} call site(s) reach the bot API without a bearer ` +
        `(${checked} site(s) checked across ${files} file(s)):`,
    );
    for (const f of findings) console.error(`  ${f.file}:${f.line} — ${f.detail}`);
    console.error(
      `\nFix: route the call through \`api.ts::get\`, or pass \`authHeaders()\` as its headers. ` +
        `A gated route called without a bearer returns 401 and the surface goes dark with no ` +
        `build, type or test failure — which is exactly how the Data Explorer went dark.`,
    );
    process.exit(1);
  }

  console.log(
    `auth-bearer OK — ${checked} fetch() call site(s) across ${files} file(s) under webapp/src; ` +
      `every one carries the session bearer or is the named login exemption.`,
  );
}
