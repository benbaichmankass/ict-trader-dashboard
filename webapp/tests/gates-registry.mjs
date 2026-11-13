#!/usr/bin/env node
/**
 * Gate-registry panel contract (Admin → Gates). Imports the real
 * src/lib/gates.ts (node 22 strips the types, as funding-books.mjs does) and
 * asserts what the operator asked the panel to guarantee:
 *   - drift / unregistered rows ALWAYS sort on top, server order kept otherwise;
 *   - null / missing renders as an em-dash, never 0 or "unknown" (a real 0 stays 0);
 *   - hits that are not_measurable never read as 0;
 *   - the decision POST's server answer is shown VERBATIM (message or detail);
 *   - empty filters are omitted from the query, never sent blank;
 *   - PR links point at JTA-Trader and shas are shortened.
 * The rows below are hand-written to the API contract (the backend was built in
 * parallel; no live response existed to capture). This checks the panel's own
 * logic, NOT that the bot's payload matches the contract.
 * `--self-test` plants a broken sorter / dash / answer and requires failures.
 */
import { pathToFileURL, fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const real = await import(pathToFileURL(join(HERE, "../src/lib/gates.ts")).href);

const ROWS = [
  { id: "a_ok", registry_state: "registered", drift: null },
  { id: "b_drift", registry_state: "registered", drift: "site_missing" },
  { id: "c_ok", registry_state: "registered", drift: null },
  { id: "d_unreg", registry_state: "unregistered", drift: null },
  { id: "e_ok", registry_state: "registered" },
];

function run(m) {
  const fails = [];
  const eq = (name, got, want) => { if (got !== want) fails.push(`${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); };
  const sorted = m.sortGates(ROWS).map((r) => r.id).join(",");
  eq("flagged on top, stable", sorted, "b_drift,d_unreg,a_ok,c_ok,e_ok");
  eq("sort does not mutate input", ROWS.map((r) => r.id).join(","), "a_ok,b_drift,c_ok,d_unreg,e_ok");
  eq("isFlagged drift", m.isFlagged(ROWS[1]), true);
  eq("isFlagged unregistered", m.isFlagged(ROWS[3]), true);
  eq("isFlagged clean", m.isFlagged(ROWS[0]), false);
  eq("dash null", m.dash(null), "—");
  eq("dash undefined", m.dash(undefined), "—");
  eq("dash empty", m.dash(""), "—");
  eq("dash real zero", m.dash(0), "0");
  eq("real money true", m.realMoneyText(true), "yes");
  eq("real money false", m.realMoneyText(false), "no");
  eq("real money null", m.realMoneyText(null), "—");
  eq("hits measured 0", m.hitsText({ id: "x", hits_14d: 0, hits_read_state: "measured" }), "0");
  eq("hits null", m.hitsText({ id: "x", hits_14d: null, hits_read_state: "measured" }), "—");
  eq("hits not measurable", m.hitsText({ id: "x", hits_14d: 0, hits_read_state: "not_measurable" }), "—");
  eq("query omits blanks", m.buildGatesQuery({ category: "", decision: "keep", state: "", real_money: "false" }), "decision=keep&real_money=false");
  eq("query empty", m.buildGatesQuery({}), "");
  eq("pr url", m.prUrl(123), "https://github.com/benbaichmankass/JTA-Trader/pull/123");
  eq("pr null", m.prUrl(null), null);
  eq("short sha", m.shortSha("0123456789abcdef"), "0123456");
  eq("short sha null", m.shortSha(null), "—");
  eq("answer ok message", m.serverAnswer(200, { ok: true, message: "Recorded keep for X." }, ""), "Recorded keep for X.");
  eq("answer detail string", m.serverAnswer(422, { detail: "decision must be one of keep|remove" }, ""), "decision must be one of keep|remove");
  eq("answer detail object", m.serverAnswer(400, { detail: { error: "bad" } }, ""), '{"error":"bad"}');
  eq("answer non-json", m.serverAnswer(502, null, "Bad Gateway"), "Bad Gateway");
  eq("decision label", m.decisionLabel("report_only"), "Report-only");
  eq("decision label null", m.decisionLabel(null), "—");
  eq("categories union", m.categoryOptions(["b"], { counts: { by_category: { a: 1 } }, gates: [{ id: "x", category: "c" }] }).join(","), "a,b,c");
  return fails;
}

if (process.argv.includes("--self-test")) {
  const broken = {
    ...real,
    sortGates: (rows) => [...rows], // flagged rows no longer pinned
    dash: (v) => (v == null ? "0" : String(v)), // null renders as 0
    serverAnswer: () => "Done.", // paraphrases instead of verbatim
  };
  const f = run(broken);
  if (f.length < 3) { console.error(`SELF-TEST FAILED: broken helpers tripped only ${f.length} checks`); process.exit(1); }
  const ok = run(real);
  if (ok.length) { console.error("SELF-TEST FAILED: real helpers fail:\n  " + ok.join("\n  ")); process.exit(1); }
  console.log(`self-test ok (broken helpers tripped ${f.length} checks)`);
  process.exit(0);
}

const fails = run(real);
if (fails.length) { console.error("gates-registry FAILED:\n  " + fails.join("\n  ")); process.exit(1); }
console.log("gates-registry ok (28 checks: flagged-on-top, em-dash, verbatim answer, query, links)");
