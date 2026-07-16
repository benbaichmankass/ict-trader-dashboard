// Headless render harness: serve the built SPA, mock every API call with
// fixtures, navigate to each route, screenshot. Lets me self-verify SPA
// structure/parity without a live API (which the sandbox can't reach).
//
//   node render/shoot.mjs                # shoots the default route set
//   node render/shoot.mjs '#/Overview'   # one route
//
// Requires `npm run build` first (serves dist/). Chromium from /opt/pw-browsers.
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { matchFixture } from "./fixtures.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DIST = join(HERE, "..", "dist");
const OUT = join(HERE, "shots");
const BASE = "/ict-trader-dashboard/";
const PORT = 4178;
const CHROME = process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const VIEWPORT = { width: 412, height: 915 }; // a phone, matching the operator's screenshots

const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2" };

// Static file server for dist/ under the base path (SPA fallback to index.html).
function serve() {
  return new Promise((resolve) => {
    const srv = createServer(async (req, res) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p.startsWith(BASE)) p = p.slice(BASE.length - 1);
      let file = join(DIST, p);
      if (p === "/" || !existsSync(file) || extname(file) === "") file = join(DIST, "index.html");
      try {
        const buf = await readFile(file);
        res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
        res.end(buf);
      } catch { res.writeHead(404); res.end("nf"); }
    });
    srv.listen(PORT, () => resolve(srv));
  });
}

const ROUTES = process.argv[2]
  ? [process.argv[2]]
  : ["#/Overview", "#/Activity/Positions", "#/Activity/Trades", "#/Performance/Performance", "#/Accounts/Accounts", "#/Accounts/Prop", "#/Admin/Health"];

function slug(r) { return r.replace(/[#/]+/g, "_").replace(/^_+|_+$/g, "") || "root"; }

const srv = await serve();
await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });

// Mock every API call with a fixture (404 → empty so the SPA shows its empty state, not an error).
await ctx.route("**/*", async (route) => {
  const url = route.request().url();
  if (url.includes("/api/")) {
    const body = matchFixture(url);
    if (body !== null) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  }
  return route.continue();
});

const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

for (const r of ROUTES) {
  errors.length = 0;
  await page.goto(`http://localhost:${PORT}${BASE}${r}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  const shot = join(OUT, `${slug(r)}.png`);
  await page.screenshot({ path: shot, fullPage: true });
  const errNote = errors.length ? ` — ${errors.length} console error(s): ${errors.slice(0, 2).join(" | ").slice(0, 200)}` : "";
  console.log(`shot ${r} → ${shot}${errNote}`);
}

await browser.close();
srv.close();
console.log("done");
