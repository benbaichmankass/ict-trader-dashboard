#!/usr/bin/env node
/**
 * Research-catalog contract: every field ResearchCatalog.svelte / ExplorerOverview
 * READS must EXIST in a real captured `GET /api/bot/research/catalog` response,
 * and every catalog URL must stay a path the bot serves.
 *
 * Same class as api-contract.mjs (a consumer reading a key with no writer renders
 * an em-dash that looks like "no data"), applied to the Data Explorer's new
 * surface. The fixture is a REAL response, committed — a hand-written one would
 * encode the same assumption the consumer might have got wrong.
 *
 * Checks, narrowly:
 *   1. `it.X` / `r.X` item reads in ResearchCatalog.svelte  -> key in some fixture item
 *   2. `resp.X` / `resp?.X` top-level reads                  -> key in the fixture
 *   3. `stay.X` reads                                        -> key in fixture.stayOnTop
 *   4. api.ts catalog paths are the two documented routes
 *   5. catalog.ts exports the facet + sort lists the API accepts
 *
 * Zero deps. `--self-test` plants a nonexistent read and requires a catch, and
 * the checker refuses to pass over an empty population.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");
const fx = JSON.parse(readFileSync(join(HERE, "fixtures", "research_catalog.json"), "utf8"));

const itemKeys = new Set(fx.items.flatMap((i) => Object.keys(i)));
const topKeys = new Set(Object.keys(fx));
const stayKeys = new Set(Object.keys(fx.stayOnTop));
// Nested objects the component descends into, checked one level deep.
const nested = {
  rule: new Set(fx.items.flatMap((i) => Object.keys(i.rule ?? {}))),
  dataUsed: new Set(fx.items.flatMap((i) => Object.keys(i.dataUsed ?? {}))),
  links: new Set(fx.items.flatMap((i) => Object.keys(i.links ?? {}))),
};

function reads(src, prefix) {
  const out = new Set();
  const re = new RegExp(`\\b${prefix}\\??\\.([A-Za-z_][A-Za-z0-9_]*)`, "g");
  for (const m of src.matchAll(re)) out.add(m[1]);
  return out;
}

export function check(componentSrc) {
  const bad = [];
  const checked = { n: 0 };
  const verify = (names, known, label) => {
    for (const k of names) {
      checked.n++;
      if (!known.has(k)) bad.push(`${label}.${k}`);
    }
  };
  verify(reads(componentSrc, "it"), new Set([...itemKeys, "id"]), "item");
  verify(reads(componentSrc, "resp"), topKeys, "response");
  verify(reads(componentSrc, "stay"), stayKeys, "stayOnTop");
  for (const [obj, known] of Object.entries(nested)) {
    verify(reads(componentSrc, `it\\??\\.${obj}`), known, `item.${obj}`);
  }
  return { bad, checked: checked.n };
}

const selfTest = process.argv.includes("--self-test");
const comp = readFileSync(join(SRC, "components", "ResearchCatalog.svelte"), "utf8");

if (selfTest) {
  const planted = check(comp + "\n{it.totallyMadeUpField} {resp?.nopeKey} {stay.ghost}");
  const ok = ["item.totallyMadeUpField", "response.nopeKey", "stayOnTop.ghost"].every((x) => planted.bad.includes(x));
  const empty = check("");
  if (!ok) { console.error("SELF-TEST FAILED: planted defects not caught:", planted.bad); process.exit(1); }
  if (empty.checked !== 0) { console.error("SELF-TEST FAILED: empty source should check nothing"); process.exit(1); }
  console.log("self-test ok: planted unknown reads caught");
  process.exit(0);
}

const res = check(comp);
let failed = false;
if (res.checked < 20) { console.error(`REFUSING: only ${res.checked} reads checked — extraction broke, not a pass`); failed = true; }
if (res.bad.length) { console.error("Reads with no writer in the real response:", res.bad); failed = true; }

const api = readFileSync(join(SRC, "lib", "api.ts"), "utf8");
for (const p of ["/api/bot/research/catalog?", "/api/bot/research/catalog/${encodeURIComponent(id)}"]) {
  if (!api.includes(p)) { console.error("api.ts missing route:", p); failed = true; }
}
const cat = readFileSync(join(SRC, "lib", "catalog.ts"), "utf8");
for (const w of ["theme", "status", "verdict", "goal", "backend", "kind", "stuck", "lastActivity", "priority"]) {
  if (!cat.includes(`"${w}"`)) { console.error("catalog.ts missing facet/sort:", w); failed = true; }
}
// Every facet the UI offers must be a facet the response actually counts.
for (const f of ["theme", "status", "verdict", "goal", "backend", "kind", "stuck"]) {
  if (!fx.facets[f]) { console.error("fixture has no facet counts for", f); failed = true; }
}
if (failed) process.exit(1);
console.log(`catalog contract ok: ${res.checked} reads verified against a real response`);
