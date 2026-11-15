#!/usr/bin/env node
/**
 * Work-queue reorder helpers (UI-WORK-QUEUE-REORDER). Imports the real src/lib/workReorder.ts
 * (node 22 strips the types). Contract with the bot lane WORK-REORDER-ROUTE: LOWER priority_rank is
 * HIGHER in the list, nulls last. `--self-test` runs the checks against a planted sort that puts
 * nulls FIRST, a refusal formatter that hides the server's detail, a refusal check that ignores accepted:false and a neighbour lookup that picks the
 * wrong side; all must fail.
 */
import { pathToFileURL, fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const real = await import(pathToFileURL(join(HERE, "../src/lib/workReorder.ts")).href);

function run(m) {
  const res = [];
  const t = (name, ok) => res.push({ name, ok: !!ok });
  const rows = [{ id: "a", priorityRank: 5 }, { id: "n1", priorityRank: null }, { id: "b", priorityRank: 1 }, { id: "n2" }, { id: "c", priorityRank: 5 }, { id: "d", priorityRank: 0 }];
  const ids = m.byRank(rows).map((r) => r.id).join(",");
  t("lower rank first (0 before 1 before 5)", ids.startsWith("d,b,"));
  t("nulls and absent ranks come last", ids.endsWith("n1,n2"));
  t("ties keep their incoming order (a before c)", ids.indexOf("a") < ids.indexOf("c"));
  t("byRank does not mutate its input", rows[0].id === "a" && rows.length === 6);
  t("first row cannot move up", m.canMove(3, 0, "up") === false);
  t("last row cannot move down", m.canMove(3, 2, "down") === false);
  t("middle row can move both ways", m.canMove(3, 1, "up") && m.canMove(3, 1, "down"));
  t("out-of-range index cannot move", m.canMove(3, 3, "up") === false && m.canMove(3, -1, "down") === false);
  t("a single row cannot move", m.canMove(1, 0, "up") === false && m.canMove(1, 0, "down") === false);
  const vis = [{ id: "x" }, { id: "y" }, { id: "z" }];
  t("neighbour above for up, below for down", m.neighbourId(vis, 1, "up") === "x" && m.neighbourId(vis, 1, "down") === "z");
  t("no neighbour at the edges", m.neighbourId(vis, 0, "up") === null && m.neighbourId(vis, 2, "down") === null);
  t("a neighbour without a usable id gives null (never a guessed id)", m.neighbourId([{ id: "x" }, {}], 0, "down") === null && m.neighbourId([{ id: "x" }, { id: "" }], 0, "down") === null);
  t("refusal shows the bot's error AND detail", m.refusalText({ status: 409, body: { accepted: false, error: "version_conflict", detail: "row changed, retry" } }) === "HTTP 409: version_conflict: row changed, retry");
  t("refusal with only a detail shows it verbatim", m.refusalText({ status: 409, body: { detail: "rank conflict: retry" } }) === "HTTP 409: rank conflict: retry");
  t("refusal with only an error code shows it", m.refusalText({ status: 409, body: { error: "at_top" } }) === "HTTP 409: at_top");
  t("a 2xx with accepted:false IS a refusal", m.isRefusal({ ok: true, body: { accepted: false, error: "at_top", detail: "x" } }) === true);
  t("a 2xx accepted answer is not a refusal", m.isRefusal({ ok: true, body: { accepted: true, changed: true } }) === false && m.isRefusal({ ok: true, body: null }) === false);
  t("a non-2xx is a refusal even with an odd body", m.isRefusal({ ok: false, body: null }) === true);
  t("refusal shows an object detail as JSON", m.refusalText({ status: 422, body: { detail: [{ msg: "bad" }] } }) === 'HTTP 422: [{"msg":"bad"}]');
  t("refusal falls back to the raw text", m.refusalText({ status: 502, body: null, text: "Bad Gateway" }) === "HTTP 502: Bad Gateway");
  t("refusal with nothing says so, never blank", m.refusalText({ status: 500, body: null, text: "" }) === "HTTP 500: no detail");
  return res;
}

const broken = {
  ...real,
  byRank: (rows) => [...rows].sort((a, b) => (a.priorityRank ?? -Infinity) - (b.priorityRank ?? -Infinity)),
  refusalText: (r) => `HTTP ${r.status}`,
  isRefusal: (r) => !r.ok, // forgets accepted:false on a 2xx
  neighbourId: (rows, idx, dir) => rows[dir === "up" ? idx + 1 : idx - 1]?.id ?? null, // the WRONG neighbour
};

const selfTest = process.argv.includes("--self-test");
const results = run(selfTest ? broken : real);
let bad = 0;
for (const r of results) { console.log((r.ok ? "PASS " : "FAIL ") + r.name); if (!r.ok) bad++; }
if (selfTest) {
  if (!bad) { console.error("SELF-TEST FAILED: the planted helpers passed every check"); process.exit(1); }
  console.log(`\nself-test ok: the planted helpers failed ${bad} check(s), as they must`);
  process.exit(0);
}
console.log(bad ? `\n${bad} FAILED` : `\nall ${results.length} passed`);
process.exit(bad ? 1 : 0);
