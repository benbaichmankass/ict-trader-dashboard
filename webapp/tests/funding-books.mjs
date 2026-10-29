#!/usr/bin/env node
/**
 * Funding-book classifier check (UI-FOUR-BOOKS). Imports the real
 * src/lib/funding.ts (node 22 strips the types) and asserts the contract:
 * four books, data-driven off account_class + paper_role, an account with NO
 * paper_role lands in Paper testing, the old stored "paper" migrates to Paper
 * portfolio, and a paper row that cannot be placed matches NO toggle.
 * `--self-test` plants a broken classifier and requires the checks to fail.
 */
import { pathToFileURL } from "node:url";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const real = await import(pathToFileURL(join(HERE, "../src/lib/funding.ts")).href);

const CONFIG = { accounts: [
  { id: "live_a", account_class: "real_money" },
  { id: "prop_a", account_class: "prop" },
  { id: "pp_a", account_class: "paper", paper_role: "portfolio" },
  { id: "soak_a", account_class: "paper", paper_role: "soak" },
  { id: "demo_a", account_class: "paper", paper_role: "demo" },
  { id: "norole_a", account_class: "paper" },
] };

function run(m) {
  const fails = [];
  const eq = (name, got, want) => { if (got !== want) fails.push(`${name}: got ${got}, want ${want}`); };
  const b = m.accountBooks(CONFIG);
  eq("real", b.live_a, "real");
  eq("prop", b.prop_a, "prop");
  eq("portfolio", b.pp_a, "paper_portfolio");
  eq("soak", b.soak_a, "paper_testing");
  eq("demo", b.demo_a, "paper_testing");
  eq("no paper_role -> testing", b.norole_a, "paper_testing");
  eq("row paper+portfolio", m.bookOfRow({ accountClass: "paper", account: "pp_a" }, b), "paper_portfolio");
  eq("row paper+soak", m.bookOfRow({ accountClass: "paper", account: "soak_a" }, b), "paper_testing");
  eq("row paper, account not in config", m.bookOfRow({ accountClass: "paper", account: "new_x" }, b), "paper_testing");
  eq("row paper, no account", m.bookOfRow({ accountClass: "paper" }, b), "paper_unassigned");
  eq("row paper, config unreadable", m.bookOfRow({ accountClass: "paper", account: "pp_a" }, {}), "paper_unassigned");
  eq("row prop", m.bookOfRow({ accountClass: "prop", account: "prop_a" }, b), "prop");
  eq("row real", m.bookOfRow({ accountClass: "real_money", account: "live_a" }, b), "real");
  eq("row no class, no account", m.bookOfRow({}, b), "real");
  eq("migrate paper", m.normalizeFunding("paper"), "paper_portfolio");
  eq("migrate Paper portfolio label", m.normalizeFunding("Paper portfolio"), "paper_portfolio");
  eq("migrate garbage", m.normalizeFunding("All"), "real");
  eq("keep testing", m.normalizeFunding("paper_testing"), "paper_testing");
  eq("toggle order", m.FUNDING_BOOKS.join(","), "real,prop,paper_portfolio,paper_testing");
  return fails;
}

if (process.argv.includes("--self-test")) {
  // Plant the historical defect: paper == portfolio only, role-less → portfolio.
  const broken = { ...real, accountBooks: (c) => {
    const m = real.accountBooks(c); for (const k of Object.keys(m)) if (m[k] === "paper_testing") m[k] = "paper_portfolio"; return m;
  }, normalizeFunding: (v) => String(v) };
  const f = run(broken);
  if (!f.length) { console.error("SELF-TEST FAILED: broken classifier passed"); process.exit(1); }
  if (!run(real).length) console.log(`self-test ok (broken classifier tripped ${f.length} checks)`);
  else { console.error("SELF-TEST FAILED: real classifier fails"); process.exit(1); }
  process.exit(0);
}

const fails = run(real);
if (fails.length) { console.error("funding-books FAILED:\n  " + fails.join("\n  ")); process.exit(1); }
console.log("funding-books ok (4 books, role-less → testing, 'paper' migrates)");
