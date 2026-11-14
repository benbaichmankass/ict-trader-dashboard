<script lang="ts">
  // Work → Pipeline map (bot lane PIPELINE-MAP, 2026-11-14; operator: "a map of the
  // trading pipeline ... displayed on the UI, on the Work tab"). Backend:
  // GET /api/bot/work/pipeline-map → { path, read_state, markdown, last_commit, file_mtime }.
  // The doc is docs/reference/trading-pipeline-map.md in the bot repo; this view only
  // renders it (HTML-escaped markdown, src/lib/markdown.ts) and draws its mermaid
  // flow diagram. Mermaid loads lazily from jsDelivr; if it cannot load, the diagram's
  // source text stays visible — never a blank panel. A missing value renders "—".
  import { api } from "../lib/api";
  import { agoFromIso, DASH } from "../lib/format";
  import { renderMarkdown, BOT_REPO_BLOB } from "../lib/markdown";

  const MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs";

  let status = $state<number | null>(null);
  let body = $state<any>(null);
  let err = $state<string | null>(null);
  let diagramNote = $state<string | null>(null);
  let host = $state<HTMLDivElement | null>(null);

  const html = $derived(body?.markdown ? renderMarkdown(body.markdown, body.path ?? "") : "");

  async function load() {
    err = null;
    try {
      const r = await api.workPipelineMap();
      status = r.status;
      body = r.body;
    } catch (e: any) {
      err = String(e?.message ?? e);
    }
  }
  load();

  async function drawDiagrams(el: HTMLDivElement) {
    const nodes = Array.from(el.querySelectorAll<HTMLElement>("pre.mermaid"));
    if (!nodes.length) return;
    try {
      const mod: any = await import(/* @vite-ignore */ MERMAID_URL);
      const mermaid = mod.default ?? mod;
      const dark = !document.documentElement.classList.contains("light");
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
      await mermaid.run({ nodes });
      diagramNote = null;
    } catch (e: any) {
      diagramNote = `Diagram renderer could not load (${String(e?.message ?? e).slice(0, 80)}); showing its source.`;
    }
  }

  $effect(() => {
    if (host && html) queueMicrotask(() => host && drawDiagrams(host));
  });
</script>

<div class="pm">
  <div class="head">
    <h3>Trading pipeline map</h3>
    {#if body?.path}
      <a class="small" href={BOT_REPO_BLOB + body.path} target="_blank" rel="noopener noreferrer">open in repo</a>
    {/if}
    <button class="small" onclick={load}>refresh</button>
  </div>
  {#if err}
    <div class="na">Could not reach the API: {err}</div>
  {:else if status === 404}
    <div class="na">The pipeline-map route is not deployed on the bot yet (HTTP 404).</div>
  {:else if status !== null && status !== 200}
    <div class="na">The bot answered HTTP {status}.</div>
  {:else if body && body.read_state !== "read"}
    <div class="na">The map could not be read on the bot (read state: {body.read_state ?? DASH}).</div>
  {:else if body}
    <div class="meta small">
      Last changed {body.last_commit?.date ? agoFromIso(body.last_commit.date) : DASH}
      {#if body.last_commit?.sha}· commit <code>{String(body.last_commit.sha).slice(0, 10)}</code>{/if}
      {#if body.last_commit?.subject}· {body.last_commit.subject}{/if}
      {#if body.last_commit?.read_state && body.last_commit.read_state !== "read"}· git history {body.last_commit.read_state}{/if}
    </div>
    {#if diagramNote}<div class="na small">{diagramNote}</div>{/if}
    <div class="md" bind:this={host}>{@html html}</div>
  {:else}
    <div class="small muted">Loading…</div>
  {/if}
</div>

<style>
  .pm { display: flex; flex-direction: column; gap: 8px; }
  .head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  h3 { margin: 0; }
  .small { font-size: 12px; }
  .muted, .meta { color: var(--muted); }
  button { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; cursor: pointer; }
  a { color: var(--accent, #4c8dff); }
  .na { color: var(--muted); border-left: 3px solid var(--border); padding: 6px 10px; font-size: 13px; }
  .md { font-size: 13.5px; line-height: 1.5; max-width: 100%; overflow-wrap: anywhere; }
  .md :global(h1) { font-size: 20px; margin: 4px 0 8px; }
  .md :global(h2) { font-size: 16px; margin: 18px 0 6px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
  .md :global(h3) { font-size: 14px; margin: 12px 0 4px; }
  .md :global(p) { margin: 6px 0; }
  .md :global(blockquote) { margin: 6px 0; padding: 4px 10px; border-left: 3px solid var(--border); color: var(--muted); }
  .md :global(code) { background: var(--panel-2); padding: 1px 4px; border-radius: 4px; font-size: 12px; }
  .md :global(pre.code) { background: var(--panel-2); padding: 8px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
  .md :global(pre.mermaid) { background: var(--panel-2); padding: 8px; border-radius: 6px; overflow-x: auto; text-align: center; }
  .md :global(.mdtable) { overflow-x: auto; margin: 6px 0; }
  .md :global(table) { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  .md :global(th), .md :global(td) { border: 1px solid var(--border); padding: 5px 7px; vertical-align: top; text-align: left; }
  .md :global(th) { background: var(--panel-2); }
  .md :global(ul), .md :global(ol) { margin: 4px 0 4px 20px; padding: 0; }
  .md :global(a) { color: var(--accent, #4c8dff); }
</style>
