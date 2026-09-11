/**
 * MANUAL end-to-end check of the SPA's auth path, driven in a real browser
 * against a MOCK bot API.
 *
 * ⚠️ THIS IS NOT A CI JOB, deliberately. It needs Playwright + a Chromium
 * download, which the three `webapp-*` CI checkers pointedly avoid (they are
 * zero-dependency plain node so they cannot rot on a lockfile or a browser
 * revision). Run it by hand when changing anything in `lib/auth.ts`,
 * `lib/api.ts::get`, `components/LoginPanel.svelte` or the Data Explorer's
 * gate branch.
 *
 * WHAT IT ESTABLISHES that a build and a typecheck cannot:
 *   A. signed out against a host that CANNOT mint (mirrors the live host as
 *      measured 2026-09-11): the Data Explorer shows a sign-in gate rather
 *      than a raw 401 line, no bearer is sent, and a 500 `auth_unavailable`
 *      is reported as a HOST-side problem rather than a bad password.
 *   B. against a host that DOES mint: the token is persisted, the password is
 *      NOT, the gated read carries `Authorization: Bearer`, and rows render.
 *   C. a stale/revoked token: the 401 clears it and returns the viewer to the
 *      form automatically.
 *   D. regression: the ~35 ungated reads still fire with no bearer, and the
 *      run produces no uncaught page errors.
 *
 * ⚠️ NOTE ON THE CORS PREFLIGHT. Attaching `Authorization` makes these
 * requests non-simple, so the browser sends an `OPTIONS` preflight first —
 * which legitimately carries NO Authorization header. Grade the GETs, not the
 * preflight; an earlier version of this harness graded both and read the
 * preflight as a missing bearer. The live host already returns
 * `access-control-allow-headers: ... Authorization ...` for the Pages origin
 * (probed 2026-09-11), so the preflight passes there.
 *
 * Usage:
 *   cd webapp && npm ci && npm run build
 *   node tests/manual/auth-e2e.mjs
 *
 * If Playwright's bundled Chromium is not installed, point at one:
 *   PW_CHROMIUM=/path/to/chrome node tests/manual/auth-e2e.mjs
 */
import http from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const DIST = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "dist");
const BASE = "/ict-trader-dashboard/";

// ---------------------------------------------------------------- mock bot
let mode = "auth_unavailable"; // | "mints"
const seen = []; // every request the SPA made to the bot

const bot = http.createServer((req, res) => {
  const url = new URL(req.url, "http://mock");
  const auth = req.headers.authorization ?? null;
  seen.push({ path: url.pathname, auth, method: req.method, t: Date.now() });

  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Access-Control-Allow-Methods", "*");
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }

  const json = (code, body) => {
    res.writeHead(code, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };

  if (url.pathname === "/api/auth/login") {
    if (mode === "auth_unavailable") return json(500, { detail: { error: "auth_unavailable" } });
    let raw = "";
    req.on("data", (c) => (raw += c));
    return req.on("end", () => {
      const body = JSON.parse(raw || "{}");
      if (body.password !== "correct-horse") return json(401, { detail: { error: "invalid_credentials" } });
      return json(200, { access_token: "MOCK.JWT.TOKEN", token_type: "bearer", expires_in: 3600 });
    });
  }

  // The two gated routes — fail closed exactly like db_explorer.py
  if (url.pathname.startsWith("/api/bot/db/")) {
    if (auth !== "Bearer MOCK.JWT.TOKEN") return json(401, { detail: { error: "invalid_session" } });
    if (url.pathname === "/api/bot/db/tables") {
      return json(200, { present: true, dbs: ["trade_journal"], tables: [{ name: "trades", rows: 5589, db: "trade_journal", columns: [] }] });
    }
    return json(200, { columns: ["id", "symbol"], rows: [{ id: 1, symbol: "BTCUSDT" }], total: 5589 });
  }

  // Everything else is ungated. List-shaped routes must return an ARRAY —
  // returning {} makes consumers throw, which is a MOCK artifact, not a defect.
  const LIST = ["/positions", "/signals", "/trades/closed", "/order-packages", "/pnl/history", "/prop/fills", "/prop/tickets", "/notifications", "/logs"];
  if (LIST.some((l) => url.pathname.endsWith(l))) return json(200, []);
  return json(200, {});
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

await new Promise((r) => bot.listen(8899, r));
await new Promise((r) => site.listen(8898, r));

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`); };

const browser = await chromium.launch(
  process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
);
const ctx = await browser.newContext();
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

const SITE = `http://localhost:8898${BASE}`;
const openDataExplorer = async () => {
  await page.goto(SITE, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => localStorage.setItem("ict.botApiUrl", "http://localhost:8899"));
  await page.goto(SITE, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  await openCard();
};

// The section-landing card IS a <button> whose accessible name starts with the
// page name; clicking it opens the detail route.
const openCard = async () => {
  await page.locator("aside").getByRole("button", { name: "Admin", exact: true }).click();
  await page.locator("button.card", { hasText: "Data Explorer" }).first().click();
  await page.waitForTimeout(1000);
};

console.log("\n--- A. signed out, host cannot mint (mirrors the LIVE host today) ---");
mode = "auth_unavailable";
await openDataExplorer();
const gateVisible = await page.getByText("This tab needs a signed-in session").isVisible().catch(() => false);
check("A1 Data Explorer shows the sign-in gate, not a raw 401 status line", gateVisible);
const dbCalls = seen.filter((s) => s.path.startsWith("/api/bot/db/") && s.method === "GET");
check("A2 the gated route was actually called", dbCalls.length > 0, `${dbCalls.length} call(s)`);
check("A3 no bearer was sent while signed out", dbCalls.every((c) => c.auth === null));

await page.getByRole("main").getByRole("button", { name: "Sign in" }).click();
await page.waitForTimeout(400);
const formVisible = await page.getByPlaceholder("operator email").isVisible().catch(() => false);
check("A4 the Sign in button opens the login form", formVisible);

await page.getByPlaceholder("operator email").fill("ben.baichmankass@gmail.com");
await page.getByPlaceholder("password").fill("anything");
await page.locator("form").getByRole("button", { name: /Sign/ }).click();
await page.waitForTimeout(700);
const hostMsg = await page.getByText(/auth environment is not fully configured/).isVisible().catch(() => false);
check("A5 a 500 auth_unavailable renders as a HOST-side problem, not a bad password", hostMsg);

console.log("\n--- B. host mints (what happens once the operator sets the envs) ---");
mode = "mints";
await page.getByPlaceholder("password").fill("correct-horse");
await page.locator("form").getByRole("button", { name: /Sign/ }).click();
await page.waitForTimeout(1200);
const stored = await page.evaluate(() => localStorage.getItem("ict.authSession"));
check("B1 the minted token is persisted", !!stored && stored.includes("MOCK.JWT.TOKEN"));
check("B2 the password is NOT persisted anywhere in localStorage", await page.evaluate(() => JSON.stringify(localStorage)).then((s) => !s.includes("correct-horse")));

seen.length = 0;
const markIdx = seen.length;
await openCard();
const preflights = seen.slice(markIdx).filter((s) => s.path.startsWith("/api/bot/db/") && s.method === "OPTIONS");
const authed = seen.slice(markIdx).filter((s) => s.path.startsWith("/api/bot/db/") && s.method === "GET");
console.log(`    (${preflights.length} CORS preflight(s) seen — expected: Authorization makes the request non-simple)`);
check("B3 the gated read now carries Authorization: Bearer", authed.length > 0 && authed.every((c) => c.auth === "Bearer MOCK.JWT.TOKEN"), JSON.stringify(authed.map((a) => a.auth)));
const rowsVisible = await page.getByText("trades").first().isVisible().catch(() => false);
check("B4 the Data Explorer renders its table list", rowsVisible);

console.log("\n--- C. an expired/revoked token returns the viewer to the form ---");
await page.evaluate(() => {
  const s = JSON.parse(localStorage.getItem("ict.authSession"));
  s.token = "STALE.TOKEN";
  localStorage.setItem("ict.authSession", JSON.stringify(s));
});
await page.goto(SITE, { waitUntil: "domcontentloaded" });
await openCard();
const cleared = await page.evaluate(() => localStorage.getItem("ict.authSession"));
check("C1 a 401 CLEARS the dead token", cleared === null, String(cleared));
const promptShown = await page.getByPlaceholder("operator email").isVisible().catch(() => false);
check("C2 a 401 returns the viewer to the login form automatically", promptShown);

console.log("\n--- D. regression: ungated tabs still work signed out ---");
await page.evaluate(() => localStorage.removeItem("ict.authSession"));
seen.length = 0;
await page.goto(SITE, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1200);
const ungated = seen.filter((s) => s.method === "GET" && !s.path.startsWith("/api/bot/db/") && !s.path.includes("/auth/"));
check("D1 ungated reads still fire with no bearer and no error", ungated.length > 0 && ungated.every((c) => c.auth === null), `${ungated.length} call(s)`);
check("D2 no uncaught page errors in the whole run", errors.length === 0, errors.join(" | "));

await browser.close();
bot.close(); site.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${failed.length ? "FAILED" : "ALL PASS"} — ${results.length - failed.length}/${results.length}`);
process.exit(failed.length ? 1 : 0);
