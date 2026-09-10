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
  // ROW-SCOPED binding (F-111). Models.svelte reads fields off `m`, the
  // each-block item bound to one registry ROW — not off a `$derived` alias —
  // so `paths` cannot express it and `rowPaths` does: resolve the array, then
  // require each read field to exist on at LEAST one row.
  //
  // At-least-one rather than all-rows, deliberately: enriched registry fields
  // are documented nullable, so a key legitimately carried by a subset must
  // not fail. The defect signature is 0 rows, not "fewer than all" — measured
  // 2026-08-20 across all 95 live rows, `stage` and `current_stage` were on
  // ZERO while `target_deployment_stage` was on 95. Coverage is PRINTED per
  // field so a 1-of-95 read is visible rather than silently passing.
  "Models.svelte": {
    fixture: "ml_registry.json",
    rowPaths: { m: "rows" },
  },
  // Work.svelte (Phase B). Bound BOTH ways: `paths` for the $derived aliases
  // off the whole payload, `rowPaths` for the each-block items. The fixture is
  // a REAL captured /api/bot/work response, not hand-written -- a hand-written
  // one would encode the same assumption the consumer might have got wrong.
  //
  // The three keys this route must not lose are exactly the ones a renderer
  // tends to drop: coverage.complete (the store is PARTIAL), wip.enforced (the
  // ceiling is DECLARED, not kept), and o.blockedOnState (a claim vs silence).
  // Binding them means a rename bot-side fails here instead of rendering blank.
  // ⚠️ TWO BINDINGS, because this ONE route reads TWO payloads. MI-238 folded
  // the manager checklist, the decision inbox and the live-sessions panel into
  // this page rather than adding a second work page beside it — the operator
  // asked for one place to look, and two adjacent nav entries called "Work" and
  // "Workflow" is exactly the ambiguity that defeats it.
  //
  // The reads deliberately stay in this ROUTE file rather than moving to
  // components/: this checker only scans src/routes, so extracting them would
  // silently drop their contract coverage — losing the guard that already
  // caught two defects on this page (a `reason` key that vanished from the
  // checklist route's healthy envelope, and a `summary` alias resolving against
  // the wrong payload).
  "Work.svelte": [
    {
      fixture: "work_store.json",
      root: "raw",
      paths: { raw: "", coverage: "coverage", wip: "wip" },
      rowPaths: { o: "objects", it: "intents" },
    },
    {
      fixture: "work_checklist.json",
      root: "checklist",
      // Three payloads on this page each have a `summary`, so the aliases are
      // named for their SOURCE (`chk` / `dec` / `ssum`). A bare `summary` alias
      // is how a field gets resolved against the wrong one — which is the
      // second defect this checker caught here.
      paths: { checklist: "", fresh: "freshness", chk: "summary",
               sess: "sessions", ssum: "sessions.summary" },
      rowPaths: { row: "items", l: "sessions.lanes" },
    },
    // ⚠️ THE DECISIONS PAYLOAD HAD NO BINDING, AND THAT IS THE COVERAGE GAP
    // THAT LET MI-254 SHIP. The page read `r.answerState` off a payload this
    // checker never saw, so when the bot grew two more states and a
    // `conversationalAnswer` block, nothing here noticed the page was still
    // filtering on `answerState !== "committed"` — a second definition of
    // "answered" in TypeScript that missed every decision answered in
    // conversation. Binding it means a rename or a dropped field fails HERE.
    //
    // ⚠️ `ca.condition` is the field most at risk of being quietly dropped:
    // OPEN-PRS.json's doctrine is that a verdict recorded WITHOUT its
    // condition is worse than a missing row, because it reads as complete.
    // The fixture deliberately keeps a row that carries one.
    {
      fixture: "work_decisions.json",
      root: "decisions",
      // `ca` is an OBJECT alias (`{@const ca = r.conversationalAnswer}`), not a
      // row array, so it belongs in `paths`. It points at index 2 DELIBERATELY:
      // that is the `answered_in_conversation` row, the only one in the fixture
      // carrying a real `condition`. Index 0 also has a `conversationalAnswer`
      // but its condition is null, and binding there would let a dropped
      // `condition` key pass unnoticed — which is the exact field OPEN-PRS's
      // doctrine says must never go missing.
      paths: { decisions: "", dec: "summary",
               ca: "requests.2.conversationalAnswer" },
      rowPaths: { r: "requests" },
    },
  ],
  // Workflow.svelte (MI-238) — the manager checklist + the decision inbox.
  // Bound BOTH ways, like Work.svelte: `paths` for the $derived aliases off the
  // whole payload, `rowPaths` for the each-block items.
  //
  // ⚠️ THE KEYS THIS ROUTE MUST NOT LOSE ARE THE PROVENANCE ONES, and they are
  // exactly the kind a renderer drops first because the page still "looks
  // right" without them: `it.status.basis` (an `in_flight` reached on `agree`
  // and one reached on `disagree` are the same value and different facts),
  // `it.sectioned` (whether the Telegram /status readout covers this row at
  // all), and the whole `freshness` block (a page serving a three-hour-old
  // checklist must not read identically to a live one). Binding them means a
  // rename bot-side fails HERE instead of rendering a confident blank.
  //
  // Both fixtures are REAL captured responses. ⚠️ Their `items` / `requests`
  // are TRIMMED for reviewability while their `summary` counts are the
  // untrimmed originals, so len(items) deliberately does not equal
  // summary.total — see each file's `_fixture_note`. That does not weaken the
  // check: this guard asks whether a key EXISTS, never how many rows carry it.
};

function dig(obj, path) {
  if (!path) return obj;
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

/** Fields read as `alias?.field` for each alias we have a binding for. */
/** Strip // and /* *\/ comments so prose about a key is not read as a key.
 *
 * Load-bearing, not tidiness: the FIRST run of the row-scoped check reported
 * `m.stage` and `m.current_stage` absent from all 4 fixture rows — and both
 * hits were inside a comment in Models.svelte explaining that the old code
 * used to read exactly those names. A guard that flags the note describing a
 * fixed bug, as though the bug were still there, trains readers to ignore it.
 * (Same shape as the audit's own 40x miscount from a regex matching
 * docstrings.) String literals are deliberately NOT stripped: `obj["field"]`
 * is a real read, and this checker's regex does not match that form anyway.
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

function readsByAlias(rawSrc, aliases) {
  const src = stripComments(rawSrc);
  const out = {};
  for (const alias of aliases) {
    // Both `alias?.field` and `alias.field`. The optional-chained form is the
    // one that fails SILENTLY (undefined, rendered as an em-dash) and is what
    // this file was built for; the plain form throws only if the alias itself
    // is nullish, so a wrong KEY on a present object degrades just as quietly.
    // F-111 was the plain form, and a probe matching only `?.` would have
    // reported the Models route clean.
    const re = new RegExp(`\\b${alias}\\??\\.([a-zA-Z_][a-zA-Z0-9_]*)`, "g");
    out[alias] = new Set([...src.matchAll(re)].map((m) => m[1]));
  }
  return out;
}

function checkRoute(routeFile, binding, srcOverride) {
  const src = srcOverride ?? readFileSync(join(ROUTES, routeFile), "utf8");
  const payload = JSON.parse(readFileSync(join(FIXTURES, binding.fixture), "utf8"));
  const reads = readsByAlias(src, Object.keys(binding.paths ?? {}));
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
  let checked = Object.values(reads).reduce((n, s) => n + s.size, 0);

  for (const [alias, path] of Object.entries(binding.rowPaths ?? {})) {
    const rows = dig(payload, path);
    if (!Array.isArray(rows) || rows.length === 0) {
      problems.push(
        `${routeFile}: rowPaths alias '${alias}' -> '${path}' is not a ` +
          `non-empty array in ${binding.fixture} — refusing to report success ` +
          `over an empty population`,
      );
      continue;
    }
    const fields = readsByAlias(src, [alias])[alias];
    for (const f of [...fields].sort()) {
      const n = rows.filter((r) => r && typeof r === "object" && f in r).length;
      checked += 1;
      if (n === 0) {
        problems.push(
          `${routeFile}: reads '${alias}.${f}' — present on 0/${rows.length} ` +
            `rows of ${binding.fixture} .${path}. Available on row 0: ` +
            `${Object.keys(rows[0]).sort().join(", ")}`,
        );
      } else if (n < rows.length) {
        // Not a failure (enriched fields are nullable) but never silent.
        console.log(`  note: ${alias}.${f} present on ${n}/${rows.length} rows`);
      }
    }
  }
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

  // --- row-scoped path (F-111) -------------------------------------------
  const mb = BINDINGS["Models.svelte"];
  // The historical defect: the stage chain short-circuited at a field that
  // exists but is uniformly wrong, behind two that exist on ZERO rows.
  const mBroken = `function stage(m) { return m.stage ?? m.current_stage ?? m.status; }`;
  const d = checkRoute("Models.svelte", mb, mBroken);
  if (!d.problems.some((x) => x.includes("m.stage"))) {
    console.error("SELF-TEST FAIL: the F-111 defect was NOT caught", d.problems);
    return 1;
  }
  const mFixed = `function stage(m) { return m.target_deployment_stage ?? "-"; }`;
  const e = checkRoute("Models.svelte", mb, mFixed);
  if (e.problems.length !== 0) {
    console.error("SELF-TEST FAIL: the corrected stage read was rejected:", e.problems);
    return 1;
  }
  // A row binding pointing at a non-array must REFUSE, not quietly check zero.
  const f = checkRoute("Models.svelte", { ...mb, rowPaths: { m: "no_such_array" } },
    `function stage(m) { return m.anything; }`);
  if (f.problems.length === 0) {
    console.error("SELF-TEST FAIL: a row binding over an empty population passed");
    return 1;
  }

  // --- comment stripping (the false-positive control) ---------------------
  // A note ABOUT a removed key must not be read as a live read of it. Without
  // this, documenting a fix re-raises the finding it documents, and readers
  // learn to ignore the checker.
  const g = checkRoute("Models.svelte", mb,
    `// this used to read m.stage and m.current_stage, both absent
     /* and m.id too */
     function stage(m) { return m.target_deployment_stage ?? "-"; }`);
  if (g.problems.length !== 0) {
    console.error("SELF-TEST FAIL: commented-out key names were flagged as reads:",
      g.problems);
    return 1;
  }
  // ...but the checker must still SEE a real read on a line that also has a
  // trailing comment, or the stripper has over-reached.
  const h = checkRoute("Models.svelte", mb,
    `function stage(m) { return m.stage; } // a real dead read`);
  if (h.problems.length === 0) {
    console.error("SELF-TEST FAIL: stripping comments also hid a real read");
    return 1;
  }

  console.log("SELF-TEST PASS  (7/7: prop defect caught · prop fix accepted · " +
    "empty binding refused · F-111 caught · stage fix accepted · " +
    "empty row population refused · comments stripped without hiding real reads)");
  return 0;
}

function main() {
  if (process.argv.includes("--self-test")) process.exit(selfTest());

  const present = new Set(readdirSync(ROUTES));
  let problems = [];
  let checked = 0;
  for (const [routeFile, declared] of Object.entries(BINDINGS)) {
    if (!present.has(routeFile)) {
      problems.push(`binding declared for ${routeFile}, which does not exist`);
      continue;
    }
    // A route may declare ONE binding or a LIST of them — a route that reads
    // two payloads needs two. Normalising here keeps every existing
    // single-binding entry byte-identical in meaning.
    for (const binding of (Array.isArray(declared) ? declared : [declared])) {
      const r = checkRoute(routeFile, binding);
      problems = problems.concat(r.problems);
      checked += r.checked;
    }
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
