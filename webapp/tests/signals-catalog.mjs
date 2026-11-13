#!/usr/bin/env node
/**
 * Signals Catalog contract (UI-UPGRADE-1 item 8, bot #25199).
 *
 * 1. Every field routes/SignalsCatalog.svelte reads off an item (`it.`), the
 *    response (`resp.`), the population block (`pop.`) or a group chip (`g.`)
 *    must exist in a REAL captured /api/bot/signals/catalog response
 *    (fixtures/signals_catalog.json, captured live 2026-11-12). A key with no
 *    writer renders as "—", indistinguishable from "no data" — same class as
 *    api-contract.mjs / catalog-contract.mjs.
 * 2. The render helpers in lib/signalsCatalog.ts map null/undefined/"" to "—",
 *    never "0" or "unknown", and keep a real 0 as "0".
 * 3. The query builder only sends the params the route accepts.
 *
 * Zero dependencies. lib/signalsCatalog.ts is plain TS with type-only syntax;
 * it is stripped with a regex and evaluated as an ES module (no tsc needed).
 *
 * Usage: node webapp/tests/signals-catalog.mjs [--self-test]
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");
const fx = JSON.parse(readFileSync(join(HERE, "fixtures", "signals_catalog.json"), "utf8"));

const known = {
  it: new Set(fx.items.flatMap((i) => Object.keys(i))),
  resp: new Set(Object.keys(fx)),
  pop: new Set(Object.keys(fx.population)),
  g: new Set(fx.groups.flatMap((g) => Object.keys(g))),
  "resp\\??\\.filters": new Set(Object.keys(fx.filters)),
  "it\\??\\.freshness": new Set(fx.items.flatMap((i) => Object.keys(i.freshness ?? {}))),
};
const JS_PROPS = new Set(["length"]);

function reads(src, prefix) {
  const out = new Set();
  const re = new RegExp(`(?<![\\w.])${prefix}\\??\\.([A-Za-z_][A-Za-z0-9_]*)`, "g");
  for (const m of src.matchAll(re)) if (!JS_PROPS.has(m[1])) out.add(m[1]);
  return out;
}

export function check(src) {
  const bad = [];
  let n = 0;
  for (const [prefix, keys] of Object.entries(known)) {
    for (const k of reads(src, prefix)) {
      if ((prefix === "it" && k === "freshness") || (prefix === "resp" && k === "filters")) { n++; continue; }
      n++;
      if (!keys.has(k)) bad.push(`${prefix.replace("\\??\\.", ".")}.${k}`);
    }
  }
  return { bad, checked: n };
}

async function loadHelpers() {
  const ts = readFileSync(join(SRC, "lib", "signalsCatalog.ts"), "utf8");
  const js = ts
    .replace(/^export (type|interface) [\s\S]*?^}\n?/gm, "")
    .replace(/^export type .*;\n/gm, "")
    .replace(/ as const;/g, ";")
    .replace(/\(o: SignalsCatalogQuery\): string/g, "(o)")
    .replace(/\(v: unknown\): string/g, "(v)")
    .replace(/\(s: unknown\): string/g, "(s)")
    .replace(/\(f: [^)]*\): string/g, "(f)")
    .replace(/\(v: unknown, n = 90\): string/g, "(v, n = 90)")
    .replace(/\(v: unknown, k = 3\): string/g, "(v, k = 3)")
    .replace(/\(x\) => \(x === null/g, "(x) => (x === null");
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}

const selfTest = process.argv.includes("--self-test");
const comp = readFileSync(join(SRC, "routes", "SignalsCatalog.svelte"), "utf8");

if (selfTest) {
  const planted = check(comp + "\n{it.madeUpField} {resp?.nopeKey} {pop.ghost} {g.phantom}");
  const want = ["it.madeUpField", "resp.nopeKey", "pop.ghost", "g.phantom"];
  if (!want.every((x) => planted.bad.includes(x))) { console.error("SELF-TEST FAILED: planted reads not caught:", planted.bad); process.exit(1); }
  if (check("").checked !== 0) { console.error("SELF-TEST FAILED: empty source should check nothing"); process.exit(1); }
  const h = await loadHelpers();
  if (h.cell(null) !== "—" || h.cell(0) === "—") { console.error("SELF-TEST FAILED: helper probe cannot distinguish"); process.exit(1); }
  console.log("self-test ok: planted unknown reads caught; helper probe distinguishes null from 0");
  process.exit(0);
}

let failed = false;
const res = check(comp);
if (res.checked < 20) { console.error(`REFUSING: only ${res.checked} reads checked — extraction broke, not a pass`); failed = true; }
if (res.bad.length) { console.error("Reads with no writer in the real response:", res.bad); failed = true; }

const h = await loadHelpers();
const eq = (got, want, label) => { if (got !== want) { console.error(`${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); failed = true; } };
for (const v of [null, undefined, "", "   ", NaN]) eq(h.cell(v), "—", `cell(${String(v)})`);
eq(h.cell(0), "0", "cell(0)");
eq(h.cell("unmeasured"), "unmeasured", "cell(str)");
eq(h.listCell([]), "—", "listCell([])");
eq(h.listCell(null), "—", "listCell(null)");
eq(h.listCell(["a", null, "b"]), "a, b", "listCell(list)");
eq(h.listShort(["a", "b", "c", "d", "e"]), "a, b, c +2", "listShort(5)");
eq(h.listShort([]), "—", "listShort([])");
eq(h.ageCell(null), "—", "ageCell(null)");
eq(h.ageCell(0), "0s", "ageCell(0)");
eq(h.ageCell(7200), "2h", "ageCell(7200)");
eq(h.freshnessCell({ state: "unmeasured", last_value_at: null, age_s: null }), "unmeasured", "freshness unmeasured");
eq(h.freshnessCell({ state: "fresh", age_s: 90 }), "fresh · 1m", "freshness fresh");
eq(h.freshnessCell(null), "—", "freshness(null)");
eq(h.truncate(null), "—", "truncate(null)");
eq(h.truncate("x".repeat(200), 10).length, 10, "truncate length");
for (const v of ["0", "unknown"]) {
  for (const f of ["cell", "listCell", "listShort", "ageCell", "freshnessCell", "truncate"]) {
    if (h[f](null) === v || h[f](undefined) === v) { console.error(`${f}(null) rendered ${v}`); failed = true; }
  }
}
eq(h.buildSignalsCatalogQuery({}), "limit=100", "query default");
eq(h.buildSignalsCatalogQuery({ offset: 100, family: "ml", kind: "ml_feature", q: " atr ", consumer: "none" }),
  "limit=100&offset=100&family=ml&kind=ml_feature&q=atr&consumer=none", "query full");
eq(h.buildSignalsCatalogQuery({ consumer: "any", q: "  " }), "limit=100", "query any/blank");
for (const k of Object.keys(fx.filters)) {
  if (!h.buildSignalsCatalogQuery({ family: "a", kind: "b", q: "c", consumer: "model" }).includes(`${k}=`)) {
    console.error("query builder never sends the route's filter:", k); failed = true;
  }
}

// The consumer values offered must be the route's own vocabulary (probed live
// 2026-11-12: any|strategy|model|none; anything else silently becomes "any").
const ROUTE_CONSUMERS = ["any", "strategy", "model", "none"];
const offered = h.CONSUMER_OPTIONS.map((o) => o.value);
if (JSON.stringify(offered) !== JSON.stringify(ROUTE_CONSUMERS)) { console.error("consumer options drifted from the route vocabulary:", offered); failed = true; }

const api = readFileSync(join(SRC, "lib", "api.ts"), "utf8");
if (!api.includes("/api/bot/signals/catalog?")) { console.error("api.ts missing /api/bot/signals/catalog route"); failed = true; }

if (failed) process.exit(1);
console.log(`signals catalog contract ok: ${res.checked} reads verified against a real response; helpers render null as "—"`);
