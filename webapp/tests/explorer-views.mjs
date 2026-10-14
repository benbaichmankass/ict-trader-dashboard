#!/usr/bin/env node
/**
 * Explorer-views contract: every column / facet / search key declared in
 * src/lib/explorerViews.ts must be a property the bot actually returns for that
 * route (checked against REAL captured rows, numeric values zeroed so no P&L or
 * balance is committed), and the ExplorerOverview component may only read keys
 * documented in the /api/bot/db/overview contract.
 *
 * Same class as api-contract.mjs: a consumer reading a key with no writer renders
 * an em-dash that looks like "no data". `--self-test` plants a bogus key in each
 * checker and requires a catch; the checker refuses to pass over an empty population.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");
const fx = JSON.parse(readFileSync(join(HERE, "fixtures", "explorer_rows.json"), "utf8"));

// Fields the SPA's api.ts derives client-side (normalizeClosedTrade: pnl <- realizedPnl,
// strategy <- pattern). They are real reads with a named writer, just not on the wire.
const DERIVED = { trades: new Set(["pnl", "strategy"]), signals: new Set(), packages: new Set() };

// Documented /api/bot/db/overview keys (bot repo docs/plans/DATA-EXPLORER-SPA-HANDOFF.md, 2026-10-14).
const OVERVIEW_KEYS = new Set([
  "present", "generatedAt", "dbs", "summary", "notProvided",
  "tables", "emptyTables", "unknownRowCount", "dbsUnreadable", "dbsMissing",
  "db", "file", "readState", "reason", "sizeBytes", "walBytes", "journalMode", "integrity", "state", "result",
  "name", "rows", "rowsState", "empty", "columnCount", "newestRowColumn", "newestRowAt", "newestRowState", "ageSeconds", "rowsEstimate",
]);

function viewBlock(src, constName) {
  const m = src.match(new RegExp(`export const ${constName}: View = \\{([\\s\\S]*?)\\n\\};`));
  return m ? m[1] : "";
}
function keysOf(block) {
  const out = new Set();
  for (const m of block.matchAll(/key:\s*"([A-Za-z_][A-Za-z0-9_]*)"/g)) out.add(m[1]);
  for (const arr of block.matchAll(/(?:facets|search):\s*\[([^\]]*)\]/g))
    for (const k of arr[1].matchAll(/"([A-Za-z_][A-Za-z0-9_]*)"/g)) out.add(k[1]);
  const idk = block.match(/idKey:\s*"([^"]+)"/);
  if (idk) out.add(idk[1]);
  const ds = block.match(/defaultSort:\s*"([^"]+)"/);
  if (ds) out.add(ds[1]);
  return out;
}

export function checkViews(src) {
  const bad = [];
  let n = 0;
  for (const [name, constName] of [["trades", "TRADES_VIEW"], ["signals", "SIGNALS_VIEW"], ["packages", "PACKAGES_VIEW"]]) {
    const known = new Set(fx[name].flatMap((r) => Object.keys(r)));
    for (const k of keysOf(viewBlock(src, constName))) {
      n++;
      if (!known.has(k) && !DERIVED[name].has(k)) bad.push(`${name}.${k}`);
    }
  }
  return { bad, n };
}

export function checkOverview(src) {
  const bad = [];
  let n = 0;
  // Property reads off the overview payload variables used in the component.
  for (const m of src.matchAll(/\b(?:ov|d|t|summary|ig)\??\.([A-Za-z_][A-Za-z0-9_]*)/g)) {
    const k = m[1];
    // skip array/object methods and locally derived names
    if (["map", "join", "length", "filter", "flatMap", "tables", "text", "tone"].includes(k) && k !== "tables") continue;
    n++;
    if (!OVERVIEW_KEYS.has(k)) bad.push(`overview.${k}`);
  }
  return { bad, n };
}

const viewsSrc = readFileSync(join(SRC, "lib", "explorerViews.ts"), "utf8");
const ovSrc = readFileSync(join(SRC, "components", "ExplorerOverview.svelte"), "utf8");

if (process.argv.includes("--self-test")) {
  const v = checkViews(viewsSrc.replace('{ key: "symbol", label: "Symbol" },', '{ key: "symbol", label: "Symbol" },\n { key: "bogusKey", label: "x" },'));
  const o = checkOverview(ovSrc + "\n{ov?.madeUp} {t.alsoFake}");
  const e = checkViews("");
  if (!v.bad.some((b) => b.endsWith(".bogusKey"))) { console.error("SELF-TEST FAILED: bogus view key not caught"); process.exit(1); }
  if (!(o.bad.includes("overview.madeUp") && o.bad.includes("overview.alsoFake"))) { console.error("SELF-TEST FAILED: bogus overview read not caught", o.bad); process.exit(1); }
  if (e.n !== 0) { console.error("SELF-TEST FAILED: empty source should check nothing"); process.exit(1); }
  console.log("self-test ok: planted unknown keys caught");
  process.exit(0);
}

const v = checkViews(viewsSrc);
const o = checkOverview(ovSrc);
let failed = false;
if (v.n < 25) { console.error(`REFUSING: only ${v.n} view keys checked — extraction broke`); failed = true; }
if (o.n < 15) { console.error(`REFUSING: only ${o.n} overview reads checked — extraction broke`); failed = true; }
if (v.bad.length) { console.error("View keys with no writer in the real rows:", v.bad); failed = true; }
if (o.bad.length) { console.error("Overview reads outside the documented contract:", o.bad); failed = true; }
// Only the one chokepoint may fetch: the explorer components must go through api.*
for (const f of ["ExplorerTrades", "ExplorerSignals", "ExplorerPackages", "ExplorerOverview", "FacetTable"]) {
  if (/\bfetch\s*\(/.test(readFileSync(join(SRC, "components", `${f}.svelte`), "utf8"))) { console.error(f, "calls fetch() directly"); failed = true; }
}
if (failed) process.exit(1);
console.log(`explorer-views ok: ${v.n} view keys vs real rows, ${o.n} overview reads vs documented contract`);
