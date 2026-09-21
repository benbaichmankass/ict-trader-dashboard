/**
 * MANUAL end-to-end check of the daily-brief panel (A3b) on the Work page,
 * driven in a real browser against a MOCK bot API.
 *
 * ⚠️ THIS IS NOT A CI JOB, deliberately — same reasoning as
 * `tests/manual/auth-e2e.mjs`: it needs Playwright + Chromium, which the
 * zero-dependency `webapp-*` CI checkers pointedly avoid. Run it by hand when
 * changing `Work.svelte`'s brief panel or `api.ts::workBrief`.
 *
 * WHAT IT ESTABLISHES that a build and svelte-check cannot:
 *   A. a healthy brief: §0's content renders, the unrouted/due counts come
 *      from `pipelineStats` (not parsed out of the markdown), and both are
 *      visible on load with NO click and NO toggle expanded.
 *   B. a long §0 (over the character cap): the block is truncated, the
 *      HIDDEN CHARACTER COUNT is printed next to it (never a silent cut),
 *      and "Show all" reveals the rest.
 *   C. `present: false` (a build failure): the reason renders, and it is
 *      never confused with "nothing is due".
 *   D. a network-level failure reaching the route at all (not the same gap
 *      as C — this page must tell the two apart).
 *   E. `coverageComplete: false` is banner-visible, mirroring the work
 *      store's own coverage banner elsewhere on this page.
 *
 * WHAT IT DOES NOT ESTABLISH: that the DEPLOYED page renders this correctly
 * for a human on GitHub Pages against the real bot. That needs a human on a
 * real browser per this repo's CLAUDE.md — driving the deployed site
 * headlessly from this sandbox does not work (the agent proxy resets
 * tunnelled connections).
 *
 * Usage:
 *   cd webapp && npm ci && npm run build
 *   node tests/manual/work-brief-e2e.mjs
 *
 * If Playwright's bundled Chromium is not installed, point at one:
 *   PW_CHROMIUM=/opt/pw-browsers/chromium node tests/manual/work-brief-e2e.mjs
 */
import http from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = join(HERE, "..", "..", "dist");
const BASE = "/ict-trader-dashboard/";

// ---------------------------------------------------------------- mock bot
let briefResponder = () => json(200, healthyBrief());
const seen = [];

function json(code, body) {
  return { code, body };
}

function healthyBrief() {
  const longNote = "x".repeat(5000); // forces the truncation branch (cap: 4000)
  return {
    present: true,
    readState: "read",
    reason: null,
    forDate: "2026-09-21",
    generatedAt: "2026-09-21T16:01:15+00:00",
    markdown:
      "# DAILY BRIEF — 2026-09-21\n\n## §0 — WHAT CAME DUE\n\n" +
      "**2 item(s) due. Each needs a disposition today.**\n\n" +
      // The short item is FIRST, deliberately: it must be visible before any
      // truncation kicks in, so A4 tests "§0 renders" independently of B's
      // truncation-and-expand path.
      "- **PI-TEST-0002** [due] a short one · next: \`ask_operator\` · rerun: \`true\`\n" +
      `- **PI-TEST-0001** [routed → \`lane-a\`] ${longNote} · next: \`dispatch_lane\` · rerun: \`true\`\n\n` +
      "---\n\n## §1 — TAKEN UNDER MANDATE\n\n(elided for this mock)\n",
    inputs: { pipeline: "read", checklist: "read", mandates: "absent" },
    pipelineStats: {
      records: 6, items: 2, by_state: { queued: 0, due: 1, routed: 1, done: 0, killed: 0 },
      open: 2, due: 2, unrouted: 1, unreadable: 0, readable: true,
    },
    coverageComplete: false,
    freshness: {
      treeState: "synced", treeStamp: "tree: synced · abc1234 == origin/main as last fetched 1m ago",
      note: "Computed live from the working tree on every request (20s cache).",
    },
  };
}

function unbuiltBrief() {
  return {
    present: false, readState: "unreadable",
    reason: "brief build failed: PIPELINE.jsonl line 12: not valid JSON",
    markdown: null, inputs: {}, pipelineStats: null, coverageComplete: false,
  };
}

const bot = http.createServer((req, res) => {
  const url = new URL(req.url, "http://mock");
  seen.push({ path: url.pathname, t: Date.now() });
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Access-Control-Allow-Methods", "*");
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }

  const send = (code, body) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };

  if (url.pathname === "/api/bot/work/brief") {
    if (briefResponder === "RESET") { res.socket.destroy(); return; }
    const r = briefResponder();
    return send(r.code, r.body);
  }
  if (url.pathname === "/api/bot/work") return send(200, { present: true, objects: [], intents: [] });
  if (url.pathname === "/api/bot/work/checklist") {
    return send(200, { present: true, items: [], summary: { total: 0 }, sessions: { lanes: [], summary: {} } });
  }
  if (url.pathname === "/api/bot/work/decisions") return send(200, { requests: [], summary: {} });
  // The first `goto` (before the hash is set) briefly mounts Overview before
  // navigating to #/Work — give its list-shaped reads an array, same as
  // auth-e2e.mjs's mock, so that mount doesn't throw an unrelated console
  // error this harness would otherwise misattribute to the brief panel.
  const LIST = ["/positions", "/signals", "/trades/closed", "/order-packages", "/pnl/history", "/prop/fills", "/prop/tickets", "/notifications", "/logs"];
  if (LIST.some((l) => url.pathname.endsWith(l))) return send(200, []);
  return send(200, {});
});

// ------------------------------------------------------------ static server
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const site = http.createServer((req, res) => {
  let p = new URL(req.url, "http://s").pathname;
  if (p.startsWith(BASE)) p = p.slice(BASE.length - 1);
  let file = join(DIST, p === "/" ? "index.html" : p);
  if (!existsSync(file)) file = join(DIST, "index.html");
  res.writeHead(200, { "Content-Type": MIME[extname(file)] ?? "application/octet-stream" });
  res.end(readFileSync(file));
});

await new Promise((r) => bot.listen(8897, r));
await new Promise((r) => site.listen(8896, r));

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`); };

const browser = await chromium.launch(
  process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
);
const ctx = await browser.newContext();
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.stack || String(e)));

const SITE = `http://localhost:8896${BASE}`;
const openWork = async () => {
  await page.goto(SITE, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => localStorage.setItem("ict.botApiUrl", "http://localhost:8897"));
  await page.goto(`${SITE}#/Work`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
};

console.log("\n--- A. a healthy brief: §0 + unrouted/due counts visible with no click ---");
briefResponder = () => json(200, healthyBrief());
await openWork();
check("A1 the panel title is visible", await page.getByText("Today's brief").isVisible().catch(() => false));
const statsText = await page.locator(".briefstats").first().innerText().catch(() => "");
check("A2 the unrouted count (from pipelineStats, not the markdown) reads 1",
  /1\s*\n?\s*unrouted/i.test(statsText), statsText.replace(/\n/g, " "));
check("A3 §0's own heading is visible", await page.getByText("§0 — what came due").isVisible().catch(() => false));
check("A4 the short due item's text made it onto the page", await page.getByText("a short one").isVisible().catch(() => false));

console.log("\n--- B. a long §0 truncates WITH a printed hidden-character count ---");
const anyTruncNotice = await page.getByText(/Truncated —/).first().innerText().catch(() => "");
check("B1 a truncation notice is shown", !!anyTruncNotice, anyTruncNotice);
check("B2 the notice carries a character COUNT, not just the word 'truncated'", /\d/.test(anyTruncNotice), anyTruncNotice);
const beforeExpand = await page.locator(".mdblock").first().innerText();
await page.getByRole("button", { name: "Show all" }).first().click();
await page.waitForTimeout(200);
const afterExpand = await page.locator(".mdblock").first().innerText();
check("B3 'Show all' reveals more than was shown before", afterExpand.length > beforeExpand.length,
  `${beforeExpand.length} -> ${afterExpand.length}`);

console.log("\n--- C. present:false renders the reason, never as 'nothing is due' ---");
briefResponder = () => json(200, unbuiltBrief());
await openWork();
check("C1 the failure reason string is on the page",
  await page.getByText("PIPELINE.jsonl line 12").isVisible().catch(() => false));
check("C2 the panel says this is NOT the same as nothing being due",
  await page.getByText(/not.*nothing being due|not.*statement that nothing/i).first().isVisible().catch(() => false));

console.log("\n--- D. a network failure reaching the route is distinguished from C ---");
briefResponder = "RESET";
await openWork();
const d1 = await page.getByText(/Couldn't reach the brief/).isVisible().catch(() => false);
check("D1 an unreachable route reports 'couldn't reach', not the build-failure wording", d1);

console.log("\n--- E. coverageComplete:false is banner-visible on a healthy brief ---");
briefResponder = () => json(200, healthyBrief());
await openWork();
const panelText = await page.locator(".briefpanel").first().innerText().catch(() => "");
check("E1 the coverage banner is visible", panelText.includes("Not the whole of the system's state"));

check("Z no uncaught page errors across the whole run", errors.length === 0, errors.join(" | "));

await browser.close();
bot.close(); site.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${failed.length ? "FAILED" : "ALL PASS"} — ${results.length - failed.length}/${results.length}`);
process.exit(failed.length ? 1 : 0);
