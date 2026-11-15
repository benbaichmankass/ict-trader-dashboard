// Pipeline map v2 — normalise the bot's `structured` block (bot PR #26250, field
// `body.structured` on GET /api/bot/work/pipeline-map) into what the spine view draws.
// Everything here is defensive: the payload is read-only data from another repo, so any
// field may be missing or null. A missing value renders as "—" (format.ts DASH), never 0.

export type PmElement = {
  id: string;
  kind: string;
  label: string | null;
  sub: string | null;
  state: string | null;
  text: string | null;
  path: string | null;
  details: Record<string, unknown>;
};

export type PmStep = {
  id: string;
  n: number | null;
  name: string | null;
  title: string | null;
  technical: PmElement[];
  trading: PmElement[];
  technicalText: string | null;
  tradingText: string | null;
};

export type PmLoop = { id: string; label: string | null; from: string; to: string };

export type PmLane = PmLoop & {
  side: "left" | "right";
  lane: number; // 0 = closest to the spine columns
  fromIdx: number;
  toIdx: number;
};

export type PmModel = { steps: PmStep[]; loops: PmLane[]; lanesLeft: number; lanesRight: number; liveState: string | null };

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);

function element(raw: any, fallbackId: string): PmElement {
  const d = raw && typeof raw === "object" && raw.details && typeof raw.details === "object" && !Array.isArray(raw.details) ? raw.details : {};
  return {
    id: str(raw?.id) ?? fallbackId,
    kind: str(raw?.kind) ?? "other",
    label: str(raw?.label),
    sub: str(raw?.sub),
    state: str(raw?.state),
    text: str(raw?.text),
    path: str(raw?.path),
    details: d,
  };
}

/** Returns null when `structured` carries no steps — the caller then falls back to the markdown render. */
export function normalizePipeline(structured: any): PmModel | null {
  const rawSteps = Array.isArray(structured?.steps) ? structured.steps : [];
  if (!rawSteps.length) return null;
  const steps: PmStep[] = rawSteps
    .filter((s: any) => s && typeof s === "object")
    .map((s: any, i: number) => ({
      id: str(s.id) ?? `step-${i + 1}`,
      n: typeof s.n === "number" ? s.n : null,
      name: str(s.name),
      title: str(s.title),
      technical: (Array.isArray(s.technical) ? s.technical : []).map((e: any, j: number) => element(e, `t:${i}-${j}`)),
      trading: (Array.isArray(s.trading) ? s.trading : []).map((e: any, j: number) => element(e, `x:${i}-${j}`)),
      technicalText: str(s.technical_text),
      tradingText: str(s.trading_text),
    }))
    .sort((a: PmStep, b: PmStep) => (a.n ?? 1e9) - (b.n ?? 1e9));
  if (!steps.length) return null;

  const idx = new Map(steps.map((s, i) => [s.id, i]));
  // Loops whose endpoints are not real step ids cannot be drawn honestly — drop, never guess.
  const loops = (Array.isArray(structured?.loops) ? structured.loops : [])
    .filter((l: any) => l && idx.has(l.from) && idx.has(l.to) && l.from !== l.to)
    .map((l: any, i: number) => ({ id: str(l.id) ?? `loop-${i}`, label: str(l.label), from: l.from as string, to: l.to as string }));

  // Lane packing: loops alternate sides (longest spans first so they sit outermost-stable), and on
  // each side a loop takes the first lane whose existing spans do not overlap its own.
  const spans = loops
    .map((l: PmLoop) => ({ l, a: Math.min(idx.get(l.from)!, idx.get(l.to)!), b: Math.max(idx.get(l.from)!, idx.get(l.to)!) }))
    .sort((x: any, y: any) => y.b - y.a - (x.b - x.a) || x.a - y.a);
  const used: Record<"left" | "right", Array<Array<[number, number]>>> = { left: [], right: [] };
  const out: PmLane[] = [];
  spans.forEach((s: any, i: number) => {
    const side: "left" | "right" = i % 2 === 0 ? "right" : "left";
    const lanes = used[side];
    let k = lanes.findIndex((occ) => occ.every(([a, b]) => s.b < a || s.a > b));
    if (k < 0) {
      lanes.push([]);
      k = lanes.length - 1;
    }
    lanes[k].push([s.a, s.b]);
    out.push({ ...s.l, side, lane: k, fromIdx: idx.get(s.l.from)!, toIdx: idx.get(s.l.to)! });
  });
  return { steps, loops: out, lanesLeft: used.left.length, lanesRight: used.right.length, liveState: str(structured?.live_state) };
}

/** Render any detail value as text; null/empty → "—" is applied by the caller via DASH. */
export function detailText(v: unknown): string | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return null;
  }
}
