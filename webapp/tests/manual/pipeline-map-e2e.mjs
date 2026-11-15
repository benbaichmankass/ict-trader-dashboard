/**
 * MANUAL end-to-end check of the Work → Pipeline map v2 spine view, driven in a
 * real browser against a MOCK bot API serving `tests/fixtures/pipeline_map_structured.json`.
 *
 * ⚠️ NOT A CI JOB (needs Playwright + Chromium; same reasoning as auth-e2e.mjs).
 * The fixture is a HAND-WRITTEN example of the `structured` schema from bot PR #26250
 * (not a live capture — the live route had no `structured` yet on 2026-11-15).
 *
 * Establishes: A. the spine renders ≥11 bands in order, technical LEFT of the spine and trading
 * RIGHT; B. loop lanes sit entirely outside the band block (never cross the spine); C. clicking an
 * element opens the drawer, null fields show "—"; D. zoom changes the layer scale; E. with no
 * `structured`, the old markdown render is the page (fallback); F. screenshots: desktop + phone.
 *
 * Usage:  cd webapp && npm run build && node tests/manual/pipeline-map-e2e.mjs [outdir]
 */
import http from "node:http";
import { readFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = join(HERE, "..", "..", "dist");
const BASE = "/ict-trader-dashboard/";
const OUT = process.argv[2] ?? join(HERE, "out");
mkdirSync(OUT, { recursive: true });
const fixture = JSON.parse(readFileSync(join(HERE, "..", "fixtures", "pipeline_map_structured.json"), "utf8"));
let withStructured = true;

const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json" };
const srv = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*" };
  if (req.method === "OPTIONS") { res.writeHead(204, cors); return res.end(); }
  if (u.pathname.startsWith("/api/bot/work/pipeline-map")) {
    const b = { ...fixture };
    if (!withStructured) delete b.structured;
    res.writeHead(200, { ...cors, "content-type": "application/json" });
    return res.end(JSON.stringify(b));
  }
  if (u.pathname.startsWith("/api/") || u.pathname.startsWith("/ws")) { res.writeHead(404, cors); return res.end("{}"); }
  let p = u.pathname.startsWith(BASE) ? u.pathname.slice(BASE.length) : u.pathname.slice(1);
  let f = join(DIST, p || "index.html");
  if (!existsSync(f) || !extname(f)) f = join(DIST, "index.html");
  res.writeHead(200, { "content-type": MIME[extname(f)] ?? "application/octet-stream" });
  res.end(readFileSync(f));
});
await new Promise((r) => srv.listen(8898, r));
const SITE = `http://localhost:8898${BASE}`;

const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM });
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };

async function open(page) {
  await page.goto(SITE, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => localStorage.setItem("ict.botApiUrl", "http://localhost:8898"));
  await page.goto(`${SITE}#/Work`, { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: "Pipeline map" }).first().click();
}

// ---- desktop
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
await open(page);
await page.waitForSelector(".band");
const bands = await page.locator(".band").count();
ok(bands >= 11, `A. ${bands} step bands rendered (≥11)`);
const geo = await page.evaluate(() => {
  const line = document.querySelector(".line").getBoundingClientRect();
  const sx = line.left + line.width / 2;
  const chipsL = [...document.querySelectorAll(".side.tech .chip")].map((e) => e.getBoundingClientRect().right);
  const chipsR = [...document.querySelectorAll(".side.trade .chip")].map((e) => e.getBoundingClientRect().left);
  const bandsR = [...document.querySelectorAll(".band")].map((e) => e.getBoundingClientRect());
  const bl = Math.min(...bandsR.map((r) => r.left)), br = Math.max(...bandsR.map((r) => r.right));
  const loops = [...document.querySelectorAll(".loop .vis")].map((e) => e.getBoundingClientRect());
  const outside = loops.every((r) => r.right <= bl + 2 || r.left >= br - 2 || true);
  // strict: the vertical lane segments (loop path minus its horizontal stubs) – check each path's x-extent endpoints
  const laneXs = [...document.querySelectorAll(".loop .vis")].map((e) => { const d = e.getAttribute("d"); return Number(d.match(/H ([\d.]+) V/)[1]); });
  return { sx, maxTechRight: Math.max(...chipsL), minTradeLeft: Math.min(...chipsR), laneXs, bl, br, bandWidth: br - bl, nLoops: loops.length };
});
ok(geo.maxTechRight < geo.sx, `A. all technical chips left of the spine (${geo.maxTechRight.toFixed(0)} < ${geo.sx.toFixed(0)})`);
ok(geo.minTradeLeft > geo.sx, `A. all trading chips right of the spine (${geo.minTradeLeft.toFixed(0)} > ${geo.sx.toFixed(0)})`);
ok(geo.nLoops === fixture.structured.loops.length, `B. ${geo.nLoops}/${fixture.structured.loops.length} loops drawn`);
const layerLeft = await page.evaluate(() => { const k = parseFloat(document.querySelector(".layer").style.transform.split("scale(")[1]); const gl = parseFloat(document.querySelector(".bands").style.marginLeft); const w = parseFloat(document.querySelector(".bands").style.width); return { k, gl, w }; });
ok(geo.laneXs.every((x) => x < layerLeft.gl || x > layerLeft.gl + layerLeft.w), `B. every loop lane x is outside the band block [${layerLeft.gl}, ${layerLeft.gl + layerLeft.w}] → never crosses the spine (lanes at ${geo.laneXs.join(", ")})`);
await page.screenshot({ path: join(OUT, "pipeline-map-desktop.png") });

// C. element click → drawer, null → —
await page.locator(".chip", { hasText: "Auto-approve" }).first().click();
const drawer = await page.locator(".drawer").innerText();
ok(/Auto-approve/.test(drawer) && /Status\s*—/.test(drawer) && /Summary\s*—/.test(drawer), "C. drawer opens; null status/summary render as —");
ok(/granted/.test(drawer), "C. generic details key/values listed");
await page.screenshot({ path: join(OUT, "pipeline-map-desktop-drawer.png") });
await page.keyboard.press("Escape");
ok((await page.locator(".drawer").count()) === 0, "C. Escape closes the drawer");

// loop click
await page.locator(".loop").first().click({ force: true });
ok(/Loop/.test(await page.locator(".drawer").innerText()), "C. loop opens a drawer");
await page.keyboard.press("Escape");

// D. zoom
const k0 = layerLeft.k;
await page.getByRole("button", { name: "Zoom in" }).click();
const k1 = await page.evaluate(() => parseFloat(document.querySelector(".layer").style.transform.split("scale(")[1]));
ok(k1 > k0, `D. zoom in changes scale (${k0.toFixed(2)} → ${k1.toFixed(2)})`);
await page.getByRole("button", { name: "fit" }).click();

// ---- phone
const pctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const ph = await pctx.newPage();
await open(ph);
await ph.waitForSelector(".band");
const hscroll = await ph.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
ok(hscroll, "F. phone: no horizontal page scroll");
await ph.screenshot({ path: join(OUT, "pipeline-map-phone.png") });
await ph.locator(".chip").first().tap();
ok((await ph.locator(".drawer").count()) === 1, "F. phone: tap opens the drawer (bottom sheet)");
await ph.screenshot({ path: join(OUT, "pipeline-map-phone-drawer.png") });

// ---- E. fallback
withStructured = false;
await open(page);
await page.waitForSelector(".md");
ok((await page.locator(".band").count()) === 0 && /fixture markdown/.test(await page.locator(".md").innerText()), "E. no `structured` → markdown render only");

await browser.close();
srv.close();
console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
