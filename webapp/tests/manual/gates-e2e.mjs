/**
 * MANUAL end-to-end check of Admin → Gates, driven in a real browser against a
 * MOCK bot API. Not a CI job (needs Playwright + Chromium), same as the other
 * files in tests/manual/.
 *
 * Establishes, against a local build + mock: the panel renders; drift /
 * unregistered rows are pinned on top and flagged; null renders as "—"; one
 * press of a decision button sends exactly one POST with {decision, note} and
 * the server's message / detail appears VERBATIM, then the row is re-read; an
 * "unreadable" registry shows the error, not an empty table; phone width has
 * no horizontal page scroll.
 *
 * Does NOT establish that the deployed page works against the real bot (the
 * mock is hand-written to the 2026-11-12 contract).
 *
 * Usage:  cd webapp && npm run build && PW_CHROMIUM=/usr/bin/google-chrome node tests/manual/gates-e2e.mjs
 */
import http from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = join(HERE, "..", "..", "dist");
const BASE = "/ict-trader-dashboard/";

const row = (o) => ({
  category: "risk", where: "src/risk.py:10", where_more: [], blocks: "new entries", real_money: null,
  authorization: null, authorization_class: null, operator_decision: "undecided", decision_note: null,
  decided_at: null, decided_by: null, decision_source: null, implementation_state: "as_is",
  implementation_pr: null, implementation_sha: null, mode_in_code: "blocks", registry_state: "registered",
  drift: null, drift_detail: null, hits_last_fired: null, hits_14d: null, hits_read_state: "not_measurable",
  hits_note: null, added_by: null, added_at: null, recommendation: null, effect: null,
  updated_at: "2026-11-12T10:00:00Z", ...o,
});
let gates = [
  row({ id: "clean_gate", hits_14d: 0, hits_read_state: "measured", implementation_pr: 42, implementation_sha: "abcdef0123456" }),
  row({ id: "drift_gate", drift: "site_missing", drift_detail: "site gone" }),
  row({ id: "unreg_gate", registry_state: "unregistered", drift: "unregistered" }),
];
let listMode = "read";
const posts = [];
let postReply = { code: 200, body: { ok: true, message: "Recorded: keep for clean_gate (note: 'fine').", recorded: true } };

const bot = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://mock");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Access-Control-Allow-Methods", "*");
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }
  const send = (code, body) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
  let m;
  if (url.pathname === "/api/bot/gates") {
    if (listMode === "unreadable") return send(200, { readState: "unreadable", as_of: "2026-11-12T10:00:00Z", error: "registry yaml parse error line 3", gates: [] });
    return send(200, {
      readState: "read", as_of: "2026-11-12T10:00:00Z",
      population: { total: 3, returned: 3, description: "all gates in the registry" },
      counts: { by_decision: { undecided: 3 }, by_state: { as_is: 3 }, by_category: { risk: 3 }, by_mode: { blocks: 3 }, real_money: 0, drift: 2, unregistered: 1 },
      refresh: { at: "2026-11-12T09:59:00Z", head_sha: "1234567890", read_state: "read", error: null },
      gates,
    });
  }
  if ((m = url.pathname.match(/^\/api\/bot\/gates\/([^/]+)\/decision$/)) && req.method === "POST") {
    let body = ""; for await (const c of req) body += c;
    posts.push({ id: decodeURIComponent(m[1]), body: JSON.parse(body), auth: req.headers.authorization ?? null });
    if (postReply.code === 200) gates = gates.map((g) => (g.id === m[1] ? { ...g, operator_decision: posts.at(-1).body.decision } : g));
    return send(postReply.code, postReply.body);
  }
  if ((m = url.pathname.match(/^\/api\/bot\/gates\/([^/]+)$/))) {
    const g = gates.find((x) => x.id === decodeURIComponent(m[1]));
    return send(200, { readState: "read", gate: g, history: [{ decision: g.operator_decision, note: "n1", decided_at: "2026-11-12T10:01:00Z", decided_by: "operator", source: "spa" }] });
  }
  // The first goto lands on Overview; give its list endpoints arrays (as work-brief-e2e does).
  const LIST = ["/positions", "/signals", "/trades/closed", "/order-packages", "/pnl/history", "/prop/fills", "/prop/tickets", "/notifications", "/logs"];
  if (LIST.some((l) => url.pathname.endsWith(l))) return send(200, []);
  return send(200, {});
});

const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const site = http.createServer((req, res) => {
  let p = new URL(req.url, "http://s").pathname;
  if (p.startsWith(BASE)) p = p.slice(BASE.length - 1);
  let file = join(DIST, p === "/" ? "index.html" : p);
  if (!existsSync(file)) file = join(DIST, "index.html");
  res.writeHead(200, { "Content-Type": MIME[extname(file)] ?? "application/octet-stream" });
  res.end(readFileSync(file));
});
await new Promise((r) => bot.listen(8899, r));
await new Promise((r) => site.listen(8898, r));

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`); };

const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
const page = await (await browser.newContext()).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.stack || String(e)));
const SITE = `http://localhost:8898${BASE}`;
const open = async () => {
  await page.goto(SITE, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => {
    localStorage.setItem("ict.botApiUrl", "http://localhost:8899");
    // A device session, so the POST's bearer can be checked (B2b).
    localStorage.setItem("metis.session.v1", JSON.stringify({ token: "ws_e2e", handle: "h", expiresAt: 4102444800 }));
  });
  await page.goto(`${SITE}#/Admin/Gates`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
};

await open();
const ids = await page.locator("tbody tr.main td.id .mono").allInnerTexts();
check("A1 three rows render", ids.length === 3, ids.join(","));
check("A2 drift + unregistered rows pinned on top", ids[0] === "drift_gate" && ids[1] === "unreg_gate" && ids[2] === "clean_gate", ids.join(","));
check("A3 flagged rows carry a visible flag", (await page.locator("tbody.flagged .flag").count()) === 2);
const cleanText = await page.locator("tbody", { hasText: "clean_gate" }).locator("tr.main").innerText();
check("A4 measured 0 hits renders 0, PR link + short sha shown", /\b0\b/.test(cleanText) && cleanText.includes("#42") && cleanText.includes("abcdef0"), cleanText.replace(/\s+/g, " "));
const driftText = await page.locator("tbody", { hasText: "drift_gate" }).locator("tr.main").innerText();
check("A5 null real-money / not-measurable hits render as —", driftText.includes("—") && !/unknown/i.test(driftText));
check("A6 as_of shown", await page.getByText(/as of 2026-11-12T10:00:00Z/).isVisible());

const cleanBody = page.locator("tbody", { hasText: "clean_gate" });
await cleanBody.locator("input.note").fill("fine");
await cleanBody.getByRole("button", { name: "Keep", exact: true }).click();
await page.waitForTimeout(800);
check("B1 one press -> exactly one POST, no confirm dialog", posts.length === 1, JSON.stringify(posts));
check("B2 POST body is {decision, note}", posts[0]?.body?.decision === "keep" && posts[0]?.body?.note === "fine");
check("B2b POST carries the operator session bearer", posts[0]?.auth === "Bearer ws_e2e", String(posts[0]?.auth));
check("B3 server message shown verbatim", await cleanBody.getByText("Recorded: keep for clean_gate (note: 'fine').").isVisible());
check("B4 row re-read shows new decision", (await cleanBody.locator(".dec").innerText()) === "Keep");

postReply = { code: 409, body: { detail: "gate drift_gate is drifted; decision refused until reconciled" } };
const driftBody = page.locator("tbody", { hasText: "drift_gate" });
await driftBody.getByRole("button", { name: "Remove", exact: true }).click();
await page.waitForTimeout(800);
check("B5 error detail shown verbatim", await driftBody.getByText("gate drift_gate is drifted; decision refused until reconciled").isVisible());

await cleanBody.locator("button.exp").click();
await page.waitForTimeout(600);
check("C1 expanded row shows history", await cleanBody.locator(".hist li").first().isVisible());

await page.setViewportSize({ width: 375, height: 800 });
await page.waitForTimeout(300);
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
check("D1 phone width: no horizontal page scroll", overflow <= 0, `overflow ${overflow}px`);
await page.setViewportSize({ width: 1280, height: 800 });

listMode = "unreadable";
await open();
check("E1 unreadable shows the error", await page.getByText(/registry yaml parse error line 3/).isVisible());
check("E2 unreadable shows no table", (await page.locator("table").count()) === 0);

check("Z no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close(); bot.close(); site.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${failed.length ? "FAILED" : "ALL PASS"} — ${results.length - failed.length}/${results.length}`);
process.exit(failed.length ? 1 : 0);
