<script lang="ts">
  // Work → Pipeline map v2 (operator spec 2026-11-15): ONE straight vertical spine, each step a
  // demarcated band; technical-flow elements LEFT, trading-flow elements RIGHT; iteration loops
  // drawn as side lanes in the gutters (never across the spine); zoom/pan; click any step, element
  // or loop to open its details. Input is the bot's `structured` block (bot PR #26250), normalised
  // by lib/pipelineMap.ts. Null renders as "—".
  import { tick } from "svelte";
  import { DASH } from "../lib/format";
  import { BOT_REPO_BLOB } from "../lib/markdown";
  import { detailText, type PmElement, type PmLane, type PmModel, type PmStep } from "../lib/pipelineMap";

  let { model }: { model: PmModel } = $props();

  // ---- geometry (content coordinates; the whole map is one transformed layer) ----
  const W = 560; // width of the band column block (technical | spine | trading)
  const LANE = 26;
  const gl = $derived(16 + model.lanesLeft * LANE);
  const gr = $derived(16 + model.lanesRight * LANE);
  const totalW = $derived(gl + W + gr);

  let vp = $state<HTMLDivElement | null>(null);
  let bandsEl = $state<HTMLDivElement | null>(null);
  let bandEls = $state<HTMLElement[]>([]);
  let mids = $state<number[]>([]);
  let totalH = $state(0);

  let k = $state(1);
  let tx = $state(0);
  let ty = $state(0);

  type Sel = { kind: "step"; step: PmStep } | { kind: "element"; el: PmElement; step: PmStep; side: "technical" | "trading" } | { kind: "loop"; loop: PmLane };
  let sel = $state<Sel | null>(null);

  // A step can carry dozens of elements (live: 27 technical / 75 trading on one step). Show the first
  // CAP per side and let the reader expand, so one band never swamps the spine. Keys are step:side.
  const CAP = 8;
  let open = $state<Record<string, boolean>>({});
  const shown = (list: PmElement[], key: string) => (open[key] || list.length <= CAP + 1 ? list : list.slice(0, CAP));

  function measure() {
    if (!bandsEl) return;
    mids = bandEls.map((b) => (b ? b.offsetTop + b.offsetHeight / 2 : 0));
    totalH = bandsEl.offsetHeight;
  }

  function fit() {
    if (!vp) return;
    const r = vp.getBoundingClientRect();
    k = Math.min(1, r.width / totalW);
    tx = (r.width - totalW * k) / 2;
    ty = 0;
  }

  let fitted = false;
  $effect(() => {
    // re-measure when the model changes or the bands resize (wrapping chips change heights)
    void model;
    if (!bandsEl) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(bandsEl);
    tick().then(() => {
      measure();
      if (!fitted) {
        fitted = true;
        fit();
      }
    });
    return () => ro.disconnect();
  });

  // ---- zoom / pan ----
  const KMIN = 0.3;
  const KMAX = 3;
  function zoomAt(factor: number, cx: number, cy: number) {
    const nk = Math.min(KMAX, Math.max(KMIN, k * factor));
    const f = nk / k;
    tx = cx - (cx - tx) * f;
    ty = cy - (cy - ty) * f;
    k = nk;
  }
  function zoomBtn(factor: number) {
    if (!vp) return;
    const r = vp.getBoundingClientRect();
    zoomAt(factor, r.width / 2, r.height / 2);
  }

  const pointers = new Map<number, { x: number; y: number }>();
  let dragMoved = false;
  let pinchDist = 0;

  function onDown(e: PointerEvent) {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    dragMoved = false;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinchDist = Math.hypot(a.x - b.x, a.y - b.y);
    }
  }
  function onMove(e: PointerEvent) {
    const p = pointers.get(e.pointerId);
    if (!p || !vp) return;
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    if (pointers.size === 1) {
      if (!dragMoved && Math.hypot(dx, dy) < 4) return;
      if (!dragMoved) {
        dragMoved = true;
        try { vp.setPointerCapture(e.pointerId); } catch { /* not capturable — drag still works */ }
      }
      tx += dx;
      ty += dy;
      p.x = e.clientX;
      p.y = e.clientY;
    } else if (pointers.size === 2) {
      dragMoved = true;
      p.x = e.clientX;
      p.y = e.clientY;
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinchDist > 0 && d > 0) {
        const r = vp.getBoundingClientRect();
        zoomAt(d / pinchDist, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
      }
      pinchDist = d;
    }
  }
  function onUp(e: PointerEvent) {
    pointers.delete(e.pointerId);
    pinchDist = 0;
    // the click that follows a drag must not open a drawer
    if (dragMoved) setTimeout(() => (dragMoved = false), 0);
  }
  function onClickCapture(e: MouseEvent) {
    if (dragMoved) {
      e.stopPropagation();
      e.preventDefault();
    }
  }

  // wheel: ctrl/⌘ zooms; plain wheel pans the map and hands back to the page at its edges
  $effect(() => {
    if (!vp) return;
    const el = vp;
    const h = (e: WheelEvent) => {
      const r = el.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
        return;
      }
      const lo = Math.min(0, r.height - totalH * k - 24);
      const next = Math.min(24, Math.max(lo, ty - e.deltaY));
      if (next === ty) return; // at an edge: let the page scroll
      e.preventDefault();
      ty = next;
    };
    el.addEventListener("wheel", h, { passive: false });
    return () => el.removeEventListener("wheel", h);
  });

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") sel = null;
  }

  // ---- drawing helpers ----
  const stateTone = (s: string | null) => {
    const v = (s ?? "").toLowerCase();
    if (!v) return "none";
    if (/(fail|error|bad|down|blocked|broken|off|red|missing)/.test(v)) return "neg";
    if (/(warn|stale|soak|shadow|partial|hold|paper|pending|degraded|unknown)/.test(v)) return "warn";
    if (/(ok|live|ready|active|read|on|pass|green|granted|running|enabled)/.test(v)) return "pos";
    return "none";
  };

  const laneX = (l: PmLane) => (l.side === "right" ? gl + W + 12 + l.lane * LANE : gl - 12 - l.lane * LANE);
  const edgeX = (l: PmLane) => (l.side === "right" ? gl + W : gl);
  function loopPath(l: PmLane) {
    if (!mids.length) return "";
    const x = laneX(l);
    const e = edgeX(l);
    // distinct y offsets so a loop's start and end never sit on the same pixel row
    const y1 = (mids[l.fromIdx] ?? 0) - 7;
    const y2 = (mids[l.toIdx] ?? 0) + 7;
    return `M ${e} ${y1} H ${x} V ${y2} H ${e + (l.side === "right" ? 2 : -2)}`;
  }
  const short = (s: string | null, n: number) => (s === null ? DASH : s.length > n ? s.slice(0, n - 1) + "…" : s);
  const kindClass = (kind: string) => kind.replace(/[^a-z0-9]/gi, "").toLowerCase() || "other";

  const detailRows = $derived.by(() => {
    if (sel?.kind !== "element") return [] as [string, string][];
    return Object.entries(sel.el.details).map(([key, v]) => [key, detailText(v) ?? DASH] as [string, string]);
  });
</script>

<svelte:window onkeydown={onKey} />

<div class="spine">
  <div class="cols small">
    <span>◀ Technical flow</span>
    <span class="mid">Pipeline (top → bottom)</span>
    <span class="r">Trading flow ▶</span>
  </div>
  <div class="toolbar small">
    <button onclick={() => zoomBtn(1.25)} aria-label="Zoom in">＋</button>
    <button onclick={() => zoomBtn(0.8)} aria-label="Zoom out">－</button>
    <button onclick={fit} aria-label="Fit to width">fit</button>
    <span class="muted">{Math.round(k * 100)}% · drag to pan · pinch or Ctrl/⌘+wheel to zoom · tap anything to open it</span>
  </div>

  <div
    class="vp"
    bind:this={vp}
    role="group"
    aria-label="Trading pipeline map"
    onpointerdown={onDown}
    onpointermove={onMove}
    onpointerup={onUp}
    onpointercancel={onUp}
    onclickcapture={onClickCapture}
  >
    <div class="layer" style="width:{totalW}px; transform: translate({tx}px, {ty}px) scale({k});">
      <!-- the one spine -->
      <div class="line" style="left:{gl + W / 2 + 1.5}px; height:{totalH}px"></div>

      <div class="bands" bind:this={bandsEl} style="margin-left:{gl}px; width:{W}px">
        {#each model.steps as step, i (step.id)}
          <section class="band" bind:this={bandEls[i]} data-step={step.id}>
            <button class="bhead" onclick={() => (sel = { kind: "step", step })}>
              <span class="bname">{step.name ?? DASH}</span>
              <span class="node">{step.n ?? DASH}</span>
              <span class="btitle">{step.title ?? DASH}</span>
            </button>
            <div class="row">
              <div class="side tech">
                {#each shown(step.technical, step.id + ":technical") as el, ei (ei)}
                  <button class="chip" data-kind={kindClass(el.kind)} onclick={() => (sel = { kind: "element", el, step, side: "technical" })}>
                    <span class="dot {stateTone(el.state)}"></span>
                    <span class="lbl">{el.label ?? DASH}</span>
                    {#if el.sub}<span class="sub">{el.sub}</span>{/if}
                  </button>
                {:else}
                  <span class="none">{DASH}</span>
                {/each}
                {#if step.technical.length > CAP + 1}
                  <button class="more" onclick={() => (open[step.id + ":technical"] = !open[step.id + ":technical"])}>
                    {open[step.id + ":technical"] ? "show fewer" : `+${step.technical.length - CAP} more`}
                  </button>
                {/if}
              </div>
              <div class="gap"></div>
              <div class="side trade">
                {#each shown(step.trading, step.id + ":trading") as el, ei (ei)}
                  <button class="chip" data-kind={kindClass(el.kind)} onclick={() => (sel = { kind: "element", el, step, side: "trading" })}>
                    <span class="dot {stateTone(el.state)}"></span>
                    <span class="lbl">{el.label ?? DASH}</span>
                    {#if el.sub}<span class="sub">{el.sub}</span>{/if}
                  </button>
                {:else}
                  <span class="none">{DASH}</span>
                {/each}
                {#if step.trading.length > CAP + 1}
                  <button class="more" onclick={() => (open[step.id + ":trading"] = !open[step.id + ":trading"])}>
                    {open[step.id + ":trading"] ? "show fewer" : `+${step.trading.length - CAP} more`}
                  </button>
                {/if}
              </div>
            </div>
          </section>
        {/each}
      </div>

      <!-- iteration loops: side lanes in the gutters, outside the band block -->
      <svg class="lanes" width={totalW} height={totalH} viewBox="0 0 {totalW} {totalH}" aria-label="Iteration loops">
        <defs>
          <marker id="pm-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
          </marker>
        </defs>
        {#each model.loops as l (l.id)}
          {@const x = laneX(l)}
          {@const my = ((mids[l.fromIdx] ?? 0) + (mids[l.toIdx] ?? 0)) / 2}
          <g class="loop" role="button" tabindex="0" aria-label={"Loop " + (l.label ?? l.id)} onclick={() => (sel = { kind: "loop", loop: l })} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (sel = { kind: "loop", loop: l })}>
            <path d={loopPath(l)} class="hit" />
            <path d={loopPath(l)} class="vis" marker-end="url(#pm-arrow)" />
            <text x={x + (l.side === "right" ? 12 : -4)} y={my} transform="rotate(-90 {x + (l.side === "right" ? 12 : -4)} {my})" text-anchor="middle">{short(l.label, 34)}</text>
          </g>
        {/each}
      </svg>
    </div>
  </div>
</div>

{#if sel}
  <button class="scrim" aria-label="Close details" onclick={() => (sel = null)}></button>
  <aside class="drawer" aria-label="Details">
    <div class="dhead">
      <strong>
        {#if sel.kind === "step"}Step {sel.step.n ?? DASH} · {sel.step.name ?? DASH}
        {:else if sel.kind === "element"}{sel.el.label ?? DASH}
        {:else}Loop{/if}
      </strong>
      <button class="x" onclick={() => (sel = null)} aria-label="Close">✕</button>
    </div>
    <div class="dbody small">
      {#if sel.kind === "step"}
        <div class="kv"><span>Title</span><span>{sel.step.title ?? DASH}</span></div>
        <div class="kv"><span>Id</span><span class="mono">{sel.step.id}</span></div>
        <div class="kv"><span>Technical ({sel.step.technical.length})</span><span>{sel.step.technicalText ?? DASH}</span></div>
        <div class="kv"><span>Trading ({sel.step.trading.length})</span><span>{sel.step.tradingText ?? DASH}</span></div>
      {:else if sel.kind === "element"}
        <div class="kv"><span>Flow</span><span>{sel.side === "technical" ? "Technical (left)" : "Trading (right)"} · step {sel.step.n ?? DASH} {sel.step.name ?? ""}</span></div>
        <div class="kv"><span>Kind</span><span>{sel.el.kind}</span></div>
        <div class="kv"><span>Id</span><span class="mono">{sel.el.id}</span></div>
        <div class="kv"><span>Status</span><span>{sel.el.state ?? DASH}</span></div>
        <div class="kv"><span>Summary</span><span>{sel.el.sub ?? DASH}</span></div>
        <div class="kv"><span>Text</span><span>{sel.el.text ?? DASH}</span></div>
        {#if sel.side === "technical"}
          <div class="kv">
            <span>Path</span>
            <span>{#if sel.el.path}<a class="mono" href={BOT_REPO_BLOB + sel.el.path} target="_blank" rel="noopener noreferrer">{sel.el.path}</a>{:else}{DASH}{/if}</span>
          </div>
        {/if}
        <h4>Details</h4>
        {#each detailRows as [key, v] (key)}
          <div class="kv"><span>{key}</span><span>{v}</span></div>
        {:else}
          <div class="muted">{DASH}</div>
        {/each}
      {:else}
        <div class="kv"><span>Label</span><span>{sel.loop.label ?? DASH}</span></div>
        <div class="kv"><span>From</span><span class="mono">{sel.loop.from}</span></div>
        <div class="kv"><span>To</span><span class="mono">{sel.loop.to}</span></div>
        <div class="kv"><span>Id</span><span class="mono">{sel.loop.id}</span></div>
      {/if}
    </div>
  </aside>
{/if}

<style>
  .spine { display: flex; flex-direction: column; gap: 6px; }
  .small { font-size: 12px; }
  .muted { color: var(--muted); }
  .cols { display: grid; grid-template-columns: 1fr auto 1fr; color: var(--muted); font-weight: 600; letter-spacing: 0.03em; }
  .cols .mid { text-align: center; }
  .cols .r { text-align: right; }
  .toolbar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  button { font: inherit; color: var(--text); }
  .toolbar button { background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; padding: 3px 9px; cursor: pointer; }

  .vp { position: relative; height: 78vh; min-height: 420px; overflow: hidden; border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); touch-action: none; cursor: grab; user-select: none; }
  .vp:active { cursor: grabbing; }
  .layer { position: absolute; top: 0; left: 0; transform-origin: 0 0; will-change: transform; padding-bottom: 24px; }
  .line { position: absolute; top: 0; width: 3px; margin-left: -1.5px; background: var(--accent); opacity: 0.55; border-radius: 2px; }
  .bands { position: relative; display: flex; flex-direction: column; gap: 14px; padding-top: 12px; }

  .band { background: color-mix(in srgb, var(--panel-2) 80%, transparent); border: 1px solid var(--border); border-left: 4px solid var(--accent); border-radius: 8px; padding: 0 0 8px; position: relative; }
  .bhead { display: grid; grid-template-columns: 1fr 34px 1fr; align-items: center; width: 100%; background: var(--panel-2); border: 0; border-bottom: 1px solid var(--border); border-radius: 6px 6px 0 0; padding: 6px 8px; cursor: pointer; }
  .node { background: var(--accent); color: #fff; font-weight: 700; font-size: 12px; width: 26px; height: 26px; border-radius: 13px; display: inline-flex; align-items: center; justify-content: center; justify-self: center; position: relative; z-index: 2; box-shadow: 0 0 0 3px var(--panel); }
  .bname { font-weight: 700; font-size: 13px; text-align: right; padding-right: 6px; overflow-wrap: anywhere; }
  .btitle { color: var(--muted); font-size: 11.5px; text-align: left; padding-left: 6px; overflow-wrap: anywhere; }
  .row { display: grid; grid-template-columns: 1fr 34px 1fr; padding: 8px 8px 0; align-items: start; }
  .side { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
  .side.tech { align-items: flex-start; }
  .side.trade { align-items: flex-end; }
  .none { color: var(--muted); padding: 2px 6px; }
  .more { font-size: 11.5px; background: transparent; border: 1px dashed var(--border); border-radius: 6px; color: var(--accent); padding: 2px 8px; cursor: pointer; }

  .chip { display: inline-flex; flex-wrap: wrap; align-items: baseline; gap: 2px 5px; max-width: 100%; text-align: left; font-size: 12px; line-height: 1.3; padding: 4px 8px; border-radius: 6px; cursor: pointer; background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--kc, var(--muted)); overflow-wrap: anywhere; }
  .chip:hover { background: color-mix(in srgb, var(--kc, var(--accent)) 14%, var(--panel)); }
  .chip:focus-visible, .bhead:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .chip .sub { color: var(--muted); font-size: 11px; }
  .chip[data-kind="module"], .chip[data-kind="service"] { --kc: var(--accent); }
  .chip[data-kind="rule"] { --kc: #d19a2f; }
  .chip[data-kind="leg"] { --kc: #8e7cf0; }
  .chip[data-kind="account"] { --kc: var(--pos); }
  .chip[data-kind="model"] { --kc: #e07bd0; }
  .chip[data-kind="mandate"] { --kc: #4cc2d6; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); display: inline-block; align-self: center; }
  .dot.pos { background: var(--pos); }
  .dot.neg { background: var(--neg); }
  .dot.warn { background: #d19a2f; }
  .dot.none { opacity: 0.35; }

  .lanes { position: absolute; top: 0; left: 0; pointer-events: none; color: var(--muted); overflow: visible; }
  .loop { pointer-events: all; cursor: pointer; }
  .loop .vis { fill: none; stroke: currentColor; stroke-width: 1.6; stroke-dasharray: 5 3; }
  .loop .hit { fill: none; stroke: transparent; stroke-width: 14; }
  .loop text { fill: var(--muted); font-size: 10px; pointer-events: none; }
  .loop:hover .vis, .loop:focus-visible .vis { stroke: var(--accent); color: var(--accent); }
  .loop:hover text { fill: var(--text); }

  .scrim { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); border: 0; z-index: 40; cursor: default; }
  .drawer { position: fixed; z-index: 41; top: 0; right: 0; bottom: 0; width: min(380px, 100vw); background: var(--panel); border-left: 1px solid var(--border); box-shadow: -8px 0 24px rgba(0, 0, 0, 0.3); display: flex; flex-direction: column; }
  .dhead { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border); }
  .x { background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; padding: 2px 8px; }
  .dbody { padding: 10px 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
  .dbody h4 { margin: 10px 0 2px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .kv { display: grid; grid-template-columns: 96px 1fr; gap: 8px; align-items: baseline; border-bottom: 1px solid var(--border); padding-bottom: 5px; overflow-wrap: anywhere; }
  .kv > span:first-child { color: var(--muted); }

  @media (max-width: 640px) {
    .cols .mid { display: none; }
    .cols { grid-template-columns: 1fr 1fr; }
    .vp { height: 70vh; }
    .drawer { top: auto; left: 0; width: 100%; max-height: 62vh; border-left: 0; border-top: 1px solid var(--border); border-radius: 12px 12px 0 0; box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.3); }
  }
</style>
