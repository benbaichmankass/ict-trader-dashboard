/**
 * MANUAL end-to-end check of the Overview work-queue reorder controls (UI-WORK-QUEUE-REORDER).
 * NOT a CI job (needs Playwright + Chromium). It serves the LOCAL build over the real Pages origin
 * (so the bot's CORS allow-list applies and the snapshot is REAL live data) and MOCKS only
 * POST /api/bot/work/reorder — it never writes to the bot.
 *
 * Establishes: ▲/▼ on the Waiting-on-me and In-flight rows; the first row's ▲ and the last row's ▼
 * are disabled; one press sends exactly {id, direction, over} where `over` is the VISIBLE neighbour in that card; a 409 refusal's detail is shown verbatim;
 * the snapshot is re-read after every press (success or refusal); rows are lowest-rank-first, nulls last.
 *
 * Usage: cd webapp && npm run build && node tests/manual/work-reorder-e2e.mjs [outdir]
 */
import { chromium } from "playwright";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = join(HERE, "..", "..", "dist");
const BASE = "https://benbaichmankass.github.io/ict-trader-dashboard/";
const OUT = process.argv[2] ?? join(HERE, "out");
mkdirSync(OUT, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };

const b = await chromium.launch({ executablePath: process.env.PW_CHROMIUM });
for (const [name, opts] of [["desktop", { viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 1 }], ["phone", { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }]]) {
  console.log(`\n--- ${name}`);
  const p = await (await b.newContext(opts)).newPage();
  await p.route(BASE + "**", (r) => {
    const u = new URL(r.request().url());
    let f = join(DIST, u.pathname.slice("/ict-trader-dashboard/".length) || "index.html");
    if (!existsSync(f) || !extname(f)) f = join(DIST, "index.html");
    r.fulfill({ status: 200, contentType: MIME[extname(f)] ?? "application/octet-stream", body: readFileSync(f) });
  });
  let reorderReply = { status: 409, body: { detail: "rank conflict: row moved by another session, retry" } };
  const posts = [];
  let snapshotReads = 0;
  const cors = { "access-control-allow-origin": new URL(BASE).origin, "access-control-allow-credentials": "true", "access-control-allow-headers": "Accept, Accept-Language, Authorization, Content-Language, Content-Type", "access-control-allow-methods": "GET, POST" };
  await p.route("**/api/bot/work/reorder", (r) => {
    // the browser's CORS preflight is answered like the bot answers it; only the POST counts
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 200, headers: cors, body: "OK" });
    posts.push({ method: r.request().method(), body: r.request().postData() });
    r.fulfill({ status: reorderReply.status, contentType: "application/json", headers: cors, body: JSON.stringify(reorderReply.body) });
  });
  p.on("request", (r) => { if (/\/api\/bot\/work\/snapshot/.test(r.url())) snapshotReads++; });
  await p.goto(BASE, { waitUntil: "domcontentloaded", timeout: 45000 });
  await p.waitForSelector(".workq .wrow", { timeout: 45000 });

  const cards = p.locator(".workq .wcard");
  const waiting = cards.nth(0).locator(".wrow:has(.mv)");
  const nW = await waiting.count();
  const nF = await cards.nth(1).locator(".wrow:has(.mv)").count();
  ok(nW + nF > 0, `rows with controls: waiting=${nW}, in flight=${nF}`);
  if (nW > 0) {
    ok(await waiting.first().locator('button[aria-label$="up"]').isDisabled(), "first waiting row: ▲ disabled");
    ok(await waiting.last().locator('button[aria-label$="down"]').isDisabled(), "last waiting row: ▼ disabled");
  }
  if (nF > 0) {
    const fl = cards.nth(1).locator(".wrow:has(.mv)");
    ok(await fl.first().locator('button[aria-label$="up"]').isDisabled(), "first in-flight row: ▲ disabled");
    ok(await fl.last().locator('button[aria-label$="down"]').isDisabled(), "last in-flight row: ▼ disabled");
  }

  // a refusal
  const target = nW > 1 ? waiting.first() : cards.nth(1).locator(".wrow:has(.mv)").first();
  const id = (await target.locator(".wid").innerText()).trim();
  const before = snapshotReads;
  await target.locator('button[aria-label$="down"]').click();
  await p.waitForSelector('.workq [role="alert"]', { timeout: 15000 });
  const msg = await p.locator('.workq [role="alert"]').innerText();
  ok(posts.length === 1 && posts[0].method === "POST", "one POST sent");
  const rowsInCard = await target.locator("xpath=..").locator(".wrow:has(.mv) .wid").allInnerTexts();
  const idx = rowsInCard.map((x) => x.trim()).indexOf(id);
  const over = rowsInCard[idx + 1]?.trim();
  ok(over && posts[0] && JSON.stringify(JSON.parse(posts[0].body)) === JSON.stringify({ id, direction: "down", over }), `body is exactly {id, direction, over: the VISIBLE neighbour below} → ${posts[0]?.body}`);
  ok(msg.includes("HTTP 409: rank conflict: row moved by another session, retry") && msg.includes(id), `refusal shown verbatim: "${msg.replace(/\s+/g, " ").slice(0, 120)}"`);
  await p.waitForTimeout(1500);
  ok(snapshotReads > before, `snapshot re-read after a refusal (${before} → ${snapshotReads})`);
  await p.locator(".workq").screenshot({ path: join(OUT, `work-reorder-refusal-${name}.png`) });

  // a success clears the message
  reorderReply = { status: 200, body: { ok: true } };
  const before2 = snapshotReads;
  await target.locator('button[aria-label$="down"]').click();
  await p.waitForFunction(() => !document.querySelector('.workq [role="alert"]'), null, { timeout: 15000 });
  await p.waitForTimeout(1500);
  ok(posts.length === 2, "second press sent a second POST");
  ok(snapshotReads > before2, "snapshot re-read after a success");
  ok((await p.locator('.workq [role="alert"]').count()) === 0, "success: no error banner");
  await p.locator(".workq").screenshot({ path: join(OUT, `work-reorder-${name}.png`) });
}
await b.close();
console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
