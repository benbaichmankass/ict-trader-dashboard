#!/usr/bin/env node
/**
 * Open-trade chart framing check (UI-LIVE-CHART-FRAMING). Imports the real
 * src/lib/chartFrame.ts (node 22 strips the types) and asserts the operator's rule,
 * verbatim, 2026-11-15:
 *   "open until current bar +5% on each side, as well as top-to-bottom from SL (first one
 *    if it's been moved) to TP (farthest if it has been moved), + 5% on each side"
 *
 * WHY: the card opened on two huge 15m bars because the chart framed itself once, on the
 * first non-empty candle array (a live bar or two, before history merged). The frame is now
 * computed from the trade's own facts; this pins the arithmetic so it cannot drift back.
 *
 * `--self-test` runs the same checks against a planted frame that forgets the 5% padding and
 * anchors on the CURRENT SL, and requires them to fail.
 */
import { pathToFileURL } from "node:url";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const real = await import(pathToFileURL(join(HERE, "../src/lib/chartFrame.ts")).href);

const near = (a, b, eps = 1e-6) => a != null && b != null && Math.abs(a - b) <= eps * Math.max(1, Math.abs(b));

function run(m) {
  const res = [];
  const t = (name, ok, detail = "") => res.push({ name, ok: !!ok, detail });
  const B = 900; // 15m
  const last = 1_800_000_000;
  const open = last - 24 * B; // opened 6h ago → 24 bars

  // 1. long, SL moved up (first = 62000), TP moved down (farthest = 68000): anchors are the FIRST SL and the FARTHEST TP.
  const long = {
    openSec: open, lastBarSec: last, barSec: B, side: "long", entry: 64000,
    sl: [{ price: 63000, fromSec: open + 8 * B }, { price: 62000, fromSec: open }],
    tp: [{ price: 67000, fromSec: open + 8 * B }, { price: 68000, fromSec: open }],
    currentSl: 63000, currentTp: 67000,
  };
  const f = m.frameFor(long);
  const span = 24 * B;
  t("x.from = open - 5% of span", f.x && near(f.x.from, open - 0.05 * span, 1e-9), JSON.stringify(f.x));
  t("x.to = current bar + 5% of span", f.x && near(f.x.to, last + 0.05 * span, 1e-9));
  const ySpan = 68000 - 62000;
  t("y.lo = FIRST SL - 5%", f.y && near(f.y.lo, 62000 - 0.05 * ySpan), JSON.stringify(f.y));
  t("y.hi = FARTHEST TP + 5%", f.y && near(f.y.hi, 68000 + 0.05 * ySpan));

  // 2. short: farthest TP is the LOWEST.
  const short = { ...long, side: "short", entry: 64000, sl: [{ price: 66000, fromSec: open }, { price: 65000, fromSec: open + 4 * B }], tp: [{ price: 60000, fromSec: open }, { price: 61500, fromSec: open + 4 * B }], currentSl: 65000, currentTp: 61500 };
  const g = m.frameFor(short);
  t("short: y spans first SL (66000) to farthest TP (60000), padded", g.y && near(g.y.lo, 60000 - 0.05 * 6000) && near(g.y.hi, 66000 + 0.05 * 6000), JSON.stringify(g.y));

  // 3. just opened: 2 bars of span must NOT produce a 2-bar frame.
  const fresh = m.frameFor({ ...long, openSec: last - 2 * B });
  t("a fresh trade still shows >= 20 bars (extra room goes LEFT)", fresh.x && (fresh.x.to - fresh.x.from) >= 20 * B && fresh.x.to > last, JSON.stringify(fresh.x));
  t("fresh trade: the right edge is still the current bar + 5%", fresh.x && near(fresh.x.to, last + 0.05 * 20 * B, 1e-9));

  // 4. frame tracks the current bar: a newer last bar moves the right edge.
  const later = m.frameFor({ ...long, lastBarSec: last + 4 * B });
  t("a new bar moves the right edge", later.x && later.x.to > f.x.to);

  // 5. no history (prop row / older bot): the SL/TP in force are the anchors.
  const cur = m.frameFor({ ...long, sl: [], tp: [], currentSl: 63000, currentTp: 67000 });
  t("no bracket history → current SL/TP anchor the y range", cur.y && near(cur.y.lo, 63000 - 0.05 * 4000) && near(cur.y.hi, 67000 + 0.05 * 4000), JSON.stringify(cur.y));

  // 6. degraded inputs.
  t("no anchors → y null (chart autoscales)", m.frameFor({ ...long, sl: [], tp: [], currentSl: null, currentTp: null, entry: null }).y === null);
  t("one anchor + entry still frames", (() => { const y = m.frameFor({ ...long, sl: [], tp: [], currentSl: null, currentTp: 67000 }).y; return y && y.hi > 67000 && y.lo < 64000; })());
  t("unknown open time → x null (caller falls back to fit)", m.frameFor({ ...long, openSec: null }).x === null);

  // 7. history depth + interval parsing.
  t("intervalSec 15m/1h/1d", m.intervalSec("15m") === 900 && m.intervalSec("1h") === 3600 && m.intervalSec("1d") === 86400);
  t("barsToLoad: 6h-old trade → the 200-bar floor", m.barsToLoad(open, last, B) === 200);
  t("barsToLoad: 5-day-old trade reaches back past the open", m.barsToLoad(last - 5 * 86400, last, B) > 5 * 96);
  t("barsToLoad: never above the API cap of 1000", m.barsToLoad(last - 90 * 86400, last, B) === 1000);
  return res;
}

// A frame that forgets the padding and anchors on the CURRENT SL — what a lazy version would do.
const broken = {
  ...real,
  frameFor: (i) => {
    const f = real.frameFor(i);
    const x = i.openSec == null ? null : { from: i.openSec, to: i.lastBarSec };
    const sl = i.currentSl ?? 0;
    const y = f.y ? { lo: Math.min(sl, f.y.hi), hi: f.y.hi } : null;
    return { x, y };
  },
};

const selfTest = process.argv.includes("--self-test");
const results = run(selfTest ? broken : real);
let bad = 0;
for (const r of results) {
  console.log((r.ok ? "PASS " : "FAIL ") + r.name + (r.ok ? "" : `  ${r.detail}`));
  if (!r.ok) bad++;
}
if (selfTest) {
  if (bad === 0) { console.error("SELF-TEST FAILED: the planted frame passed every check, so the checks catch nothing"); process.exit(1); }
  console.log(`\nself-test ok: the planted frame failed ${bad} check(s), as it must`);
  process.exit(0);
}
console.log(bad ? `\n${bad} FAILED` : `\nall ${results.length} passed`);
process.exit(bad ? 1 : 0);
