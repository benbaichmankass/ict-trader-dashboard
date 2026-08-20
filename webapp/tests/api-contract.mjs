#!/usr/bin/env node
/**
 * API-contract check: every payload field a route READS must EXIST.
 *
 * WHY THIS EXISTS
 * ---------------
 * `Prop.svelte` read `rd?.daily_loss_remaining` and `rd?.static_dd_remaining`
 * from 2026-07-16 to 2026-08-20. Neither key has ever existed on
 * `/api/bot/prop/status`; the real names are `distance_to_daily_loss_usd` and
 * `distance_to_dd_floor_usd`. Both reads resolved to `null`, so the two
 * account-killer cushions rendered as an em-dash — indistinguishable from a
 * genuinely absent value — and the thin-cushion alert, guarded on `!= null`,
 * was UNREACHABLE for 35 days on the one panel that exists to warn before a
 * breach. The Streamlit app read the correct keys the whole time, so the two
 * frontends disagreed and nothing noticed.
 *
 * That is a CLASS, not an incident: a consumer reading a key with no writer.
 * The bot repo has four guards policing signal honesty and the closest one,
 * `provenance-consumer-guard`, catches only the MIRROR image — a key with a
 * writer and no consumer. Nothing checked this direction.
 *
 * WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
 * -------------------------------------------------
 * Scoped to exactly the pattern that broke:
 *
 *     const NAME = $derived(SRC?.field_name ?? ...)
 *
 * ...where `SRC` is itself `$derived` off a recorded payload. That is precise
 * and near-false-positive-free. It does NOT try to check every property access
 * in the file — an earlier ad-hoc sweep of that kind produced three false
 * positives on defensive fallback chains (`r.first_seen ?? r.first_ts`), and a
 * guard that cries wolf gets suppressed, which is worse than no guard.
 *
 * The fixtures are REAL RESPONSES, captured live and committed. A hand-written
 * fixture would encode the same assumption the consumer got wrong.
 *
 * Zero dependencies — plain node, so it runs in CI without an install step.
 *
 * Usage:  node webapp/tests/api-contract.mjs [--self-test]
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROUTES = join(HERE, "..", "src", "routes");
const FIXTURES = join(HERE, "fixtures");

/**
 * route file -> { rootVar: fixture, derivedVar: "path.inside.fixture" }
 *
 * `root` names the `$state` holding the whole response. `paths` maps each
 * `$derived` alias to the object inside that response it is bound to, so a read
 * off the alias is checked against the right sub-object.
 */
const BINDINGS = {
  "Prop.svelte": {
    fixture: "prop_status.json",
    root: "status",
    paths: { status: "", rd: "rule_distance" },
  },
};

function dig(obj, path) {
  if (!path) return obj;
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

/** Fields read as `alias?.field` for each alias we have a binding for. */
function readsByAlias(src, aliases) {
  const out = {};
  for (const alias of aliases) {
    const re = new RegExp(`\\b${alias}\\?\\.([a-zA-Z_][a-zA-Z0-9_]*)`, "g");
    out[alias] = new Set([...src.matchAll(re)].map((m) => m[1]));
  }
  return out;
}

function checkRoute(routeFile, binding, srcOverride) {
  const src = srcOverride ?? readFileSync(join(ROUTES, routeFile), "utf8");
  const payload = JSON.parse(readFileSync(join(FIXTURES, binding.fixture), "utf8"));
  const reads = readsByAlias(src, Object.keys(binding.paths));
  const problems = [];
  for (const [alias, fields] of Object.entries(reads)) {
    const target = dig(payload, binding.paths[alias]);
    if (target == null || typeof target !== "object") {
      // The binding points at something the fixture does not carry. That is a
      // defect in the BINDING, and it must fail loudly rather than silently
      // checking nothing — a check over an empty population is the exact
      // failure this file exists to prevent.
      problems.push(
        `${routeFile}: binding alias '${alias}' -> '${binding.paths[alias]}' ` +
          `resolves to nothing in ${binding.fixture}`,
      );
      continue;
    }
    for (const f of [...fields].sort()) {
      if (!(f in target)) {
        problems.push(
          `${routeFile}: reads '${alias}?.${f}' — absent from ` +
            `${binding.fixture}${binding.paths[alias] ? ` .${binding.paths[alias]}` : ""}. ` +
            `Available: ${Object.keys(target).sort().join(", ")}`,
        );
      }
    }
  }
  const checked = Object.values(reads).reduce((n, s) => n + s.size, 0);
  return { problems, checked };
}

function selfTest() {
  // A guard that cannot fail proves nothing. Plant the exact historical defect
  // and require the checker to catch it; then plant the corrected form and
  // require it to pass.
  const binding = BINDINGS["Prop.svelte"];
  const broken = `const rd = $derived(status?.rule_distance ?? null);
  const dailyLeft = $derived(rd?.daily_loss_remaining ?? null);`;
  const fixed = `const rd = $derived(status?.rule_distance ?? null);
  const dailyLeft = $derived(rd?.distance_to_daily_loss_usd ?? null);`;

  const a = checkRoute("Prop.svelte", binding, broken);
  if (a.problems.length === 0) {
    console.error("SELF-TEST FAIL: the 2026-07-16 defect was NOT caught");
    return 1;
  }
  const b = checkRoute("Prop.svelte", binding, fixed);
  if (b.problems.length !== 0) {
    console.error("SELF-TEST FAIL: the corrected form was rejected:", b.problems);
    return 1;
  }
  // And the binding itself must be pointed at something real.
  const c = checkRoute("Prop.svelte", { ...binding, paths: { rd: "no_such_block" } },
    "const x = $derived(rd?.anything ?? null);");
  if (c.problems.length === 0) {
    console.error("SELF-TEST FAIL: a binding pointing at nothing was accepted");
    return 1;
  }
  console.log("SELF-TEST PASS  (3/3: defect caught · fix accepted · empty binding refused)");
  return 0;
}

function main() {
  if (process.argv.includes("--self-test")) process.exit(selfTest());

  const present = new Set(readdirSync(ROUTES));
  let problems = [];
  let checked = 0;
  for (const [routeFile, binding] of Object.entries(BINDINGS)) {
    if (!present.has(routeFile)) {
      problems.push(`binding declared for ${routeFile}, which does not exist`);
      continue;
    }
    const r = checkRoute(routeFile, binding);
    problems = problems.concat(r.problems);
    checked += r.checked;
  }
  if (checked === 0) {
    // Never report a green over an empty population.
    console.error("api-contract: checked 0 fields — the extractor matched nothing. Refusing to pass.");
    process.exit(1);
  }
  if (problems.length) {
    console.error(`api-contract: ${problems.length} problem(s) over ${checked} checked field(s)\n`);
    for (const p of problems) console.error("  " + p);
    process.exit(1);
  }
  console.log(
    `api-contract: OK — ${checked} field read(s) across ` +
      `${Object.keys(BINDINGS).length} route(s) all exist in their recorded payloads.`,
  );
}

main();
