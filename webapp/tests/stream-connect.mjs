#!/usr/bin/env node
/**
 * Stream connect race: two acquireStream() calls in the same tick must open
 * exactly ONE EventSource.
 *
 * WHY THIS EXISTS
 * ---------------
 * lib/stream.ts::connect() guarded on `es`, but `es` is assigned only after
 * `await streamTicket()`. A second acquireStream(), or a scheduled retry firing
 * inside that await, passed the guard and opened a SECOND EventSource. The
 * first was orphaned: never closed, and still dispatching frames (found in
 * AM-UI's review of #246, 2026-11-13). The fix is a module-level `connecting`
 * flag. This test pins it.
 *
 * HOW
 * ---
 * Zero dependencies. The REAL src/lib/stream.ts is copied into a temp dir with
 * its three imports pointed at stubs:
 *   - svelte/store: a minimal writable/get
 *   - ./config: a fixed base URL
 *   - ./session: streamTicket() that resolves only when the test says so,
 *     which holds connect() inside its await
 * EventSource is stubbed as a global that counts constructions. Node 22 strips
 * the types on import, the same way funding-books.mjs loads funding.ts.
 *
 * `--self-test` plants the historical defect (the guard without `connecting`)
 * and requires this check to catch it. A gate that cannot fail proves nothing.
 *
 * Usage:  node webapp/tests/stream-connect.mjs [--self-test]
 */
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "..", "src", "lib", "stream.ts"), "utf8");

const STUB_STORE = `export function writable(v){const subs=new Set();return{set(n){v=n;subs.forEach(f=>f(v));},update(f){this.set(f(v));},subscribe(f){subs.add(f);f(v);return()=>subs.delete(f);}};}
export function get(s){let v;s.subscribe(x=>{v=x;})();return v;}`;
const STUB_CONFIG = `export function getBotApiUrl(){return "http://stub.invalid";}`;
const STUB_SESSION = `export async function streamTicket(){ return await globalThis.__ticketGate(); }`;

async function opensFor(source) {
  const dir = mkdtempSync(join(tmpdir(), "stream-connect-"));
  try {
    const rewired = source
      .replace(/from\s+"svelte\/store"/, 'from "./svelte-store.mjs"')
      .replace(/from\s+"\.\/config"/, 'from "./config.mjs"')
      .replace(/from\s+"\.\/session"/, 'from "./session.mjs"');
    for (const [spec, n] of [["./svelte-store.mjs", "svelte/store"], ["./config.mjs", "./config"], ["./session.mjs", "./session"]]) {
      if (!rewired.includes(`from "${spec}"`)) throw new Error(`stream.ts no longer imports ${n} the way this test rewires it — update the test`);
    }
    writeFileSync(join(dir, "stream.ts"), rewired);
    writeFileSync(join(dir, "svelte-store.mjs"), STUB_STORE);
    writeFileSync(join(dir, "config.mjs"), STUB_CONFIG);
    writeFileSync(join(dir, "session.mjs"), STUB_SESSION);

    let opened = 0;
    let closed = 0;
    globalThis.EventSource = class {
      constructor(url) { opened++; this.url = url; }
      addEventListener() {}
      close() { closed++; }
    };
    const waiters = [];
    globalThis.__ticketGate = () => new Promise((res) => waiters.push(res));

    const mod = await import(pathToFileURL(join(dir, "stream.ts")).href + `?v=${Math.random()}`);
    // Two views mount in the same tick: both call acquireStream() while the
    // first connect() is still waiting on its ticket.
    const r1 = mod.acquireStream();
    const r2 = mod.acquireStream();
    await new Promise((r) => setTimeout(r, 0));
    // Release every pending ticket mint, then let the connects finish.
    for (const w of waiters.splice(0)) w("t_stub");
    await new Promise((r) => setTimeout(r, 10));
    const result = { opened };
    r1(); r2();
    result.closedAfterRelease = closed;
    return result;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function plantDefect(src) {
  const guard = /if \(es \|\| connecting \|\| refs === 0\) return;/;
  if (!guard.test(src)) throw new Error("self-test: cannot find the connecting guard to remove — update the self-test");
  return src.replace(guard, "if (es || refs === 0) return;");
}

if (process.argv.includes("--self-test")) {
  const bad = await opensFor(plantDefect(SRC));
  if (bad.opened < 2) {
    console.error(`SELF-TEST FAIL: with the guard removed, ${bad.opened} EventSource(s) opened. The check cannot see the race.`);
    process.exit(1);
  }
  const good = await opensFor(SRC);
  if (good.opened !== 1) {
    console.error(`SELF-TEST FAIL: the real stream.ts opened ${good.opened} EventSource(s), not 1.`);
    process.exit(1);
  }
  console.log(`SELF-TEST PASS  (2/2: planted race caught, ${bad.opened} opened · real stream.ts opens 1)`);
} else {
  const r = await opensFor(SRC);
  if (r.opened !== 1) {
    console.error(`stream-connect: two acquireStream() calls in one tick opened ${r.opened} EventSource(s), want exactly 1`);
    process.exit(1);
  }
  if (r.closedAfterRelease !== 1) {
    console.error(`stream-connect: releasing both refs closed ${r.closedAfterRelease} EventSource(s), want 1`);
    process.exit(1);
  }
  console.log("stream-connect OK: two same-tick acquireStream() calls open exactly 1 EventSource, and releasing both closes it.");
}
