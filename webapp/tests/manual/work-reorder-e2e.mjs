/**
 * MANUAL end-to-end check of the Overview work-queue drag-and-drop (UI-WORK-QUEUE-DND).
 * NOT a CI job (needs Playwright + Chromium). Serves the LOCAL build over the real Pages origin (real
 * live GET data) and MOCKS only POST /api/bot/work/reorder — it never writes to the bot.
 * Establishes: every row has a drag handle; dragging a handle onto another row POSTs exactly
 * {id, direction, over}; a 409 refusal is shown verbatim and the snapshot re-read; a row click opens a
 * card; the Queued list is collapsed, opens, and a queued row can be dragged up into In flight.
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
  const reply = { status: 409, body: { accepted: false, error: "version_conflict", detail: "row changed under you, retry" } };
  const posts = [];
  let snapshotReads = 0;
  const cors = { "access-control-allow-origin": new URL(BASE).origin, "access-control-allow-credentials": "true", "access-control-allow-headers": "Accept, Accept-Language, Authorization, Content-Language, Content-Type", "access-control-allow-methods": "GET, POST" };
  await p.route("**/api/bot/work/reorder", (r) => {
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 200, headers: cors, body: "OK" });
    posts.push(JSON.parse(r.request().postData() ?? "null"));
    r.fulfill({ status: reply.status, contentType: "application/json", headers: cors, body: JSON.stringify(reply.body) });
  });
  p.on("request", (r) => { if (/\/api\/bot\/work\/snapshot/.test(r.url())) snapshotReads++; });
  await p.goto(BASE, { waitUntil: "domcontentloaded", timeout: 45000 });
  await p.waitForSelector(".workq .wrow .grip", { timeout: 45000 });
  const cards = p.locator(".workq .wcard");
  const flight = cards.nth(1).locator('[data-wlist="inflight"] .wrow');
  const nF = await flight.count();
  ok(nF > 1, `in-flight rows with drag handles: ${nF}`);
  ok((await p.locator('.workq button[aria-label$="up"]').count()) === 0, "no visible ▲/▼ buttons");

  // a row click opens a card with the full row
  await flight.first().locator(".rowtog").click();
  await p.waitForSelector(".workq .rcard dt", { timeout: 15000 });
  await p.waitForFunction(() => !/Loading the full row/.test(document.querySelector(".workq .rcard")?.textContent ?? ""), null, { timeout: 15000 });
  const card = await p.locator(".workq .rcard").first().innerText();
  ok(/priority_rank/.test(card) && /blocked_on/.test(card) && /due_by/.test(card) && /Notes/.test(card), "card shows rank / blocked_on / due_by / notes");
  await p.locator(".workq .wcards").screenshot({ path: join(OUT, `dnd-card-${name}.png`) });
  await flight.first().locator(".rowtog").click();

  // drag: last in-flight row onto the one above it → {id: last, direction: up, over: that row}
  const ids = (await cards.nth(1).locator('[data-wlist="inflight"] .wrow .wid').allInnerTexts()).map((x) => x.trim());
  await flight.nth(nF - 1).scrollIntoViewIfNeeded(); // both rows must be on screen (a drag only reaches visible rows)
  const grip = await flight.nth(nF - 1).locator(".grip").boundingBox();
  const top = await flight.nth(nF - 2).boundingBox();
  const before = snapshotReads;
  await p.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
  await p.mouse.down();
  await p.mouse.move(top.x + 40, top.y + 2, { steps: 8 });
  ok((await p.locator(".dnd-above").count()) === 1, "drop indicator shown above the target row");
  await p.mouse.up();
  await p.waitForSelector('.workq [role="alert"]', { timeout: 15000 });
  ok(posts.length === 1 && JSON.stringify(posts[0]) === JSON.stringify({ id: ids[nF - 1], direction: "up", over: ids[nF - 2] }), `POST ${JSON.stringify(posts[0])}`);
  const msg = await p.locator('.workq [role="alert"]').innerText();
  ok(msg.includes("HTTP 409: version_conflict: row changed under you, retry"), "refusal shown verbatim");
  await p.waitForTimeout(1500);
  ok(snapshotReads > before, "snapshot re-read after the drop");

  // queued list: collapsed → opens → drag a queued row up into In flight
  ok((await p.locator('.workq [data-wlist="queued"]').count()) === 0, "queued list starts collapsed");
  await p.locator(".workq .qhead").click();
  await p.waitForSelector('.workq [data-wlist="queued"] .wrow', { timeout: 20000 });
  await p.locator(".workq .qhead").scrollIntoViewIfNeeded();
  const q = p.locator('.workq [data-wlist="queued"] .wrow').first();
  const qid = (await q.locator(".wid").innerText()).trim();
  const qg = await q.locator(".grip").boundingBox();
  const f0 = await p.locator('.workq [data-wlist="inflight"] .wrow').last().boundingBox(); // the nearest in-flight row (the page autoscrolls for farther ones)
  await p.mouse.move(qg.x + qg.width / 2, qg.y + qg.height / 2);
  await p.mouse.down();
  await p.mouse.move(f0.x + 40, f0.y + 2, { steps: 10 });
  await p.mouse.up();
  await p.waitForFunction(() => document.querySelectorAll('[role="alert"]').length > 0, null, { timeout: 15000 });
  await p.waitForTimeout(800);
  ok(posts.length === 2 && posts[1].id === qid && posts[1].direction === "up", `queued row dropped into In flight → ${JSON.stringify(posts[1])}`);
  await p.locator(".workq .wcards").screenshot({ path: join(OUT, `dnd-queued-${name}.png`) });
}
await b.close();
console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
