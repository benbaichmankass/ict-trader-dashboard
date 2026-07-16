<script lang="ts">
  import { SECTIONS, PAGE_DESC, IMPLEMENTED_PAGES, gotoDetail } from "../lib/nav";

  let { section }: { section: string } = $props();
  const pages = $derived(SECTIONS[section] ?? []);
</script>

<section>
  <h2>{section}</h2>
  <p class="muted sub">Overview first — pick a card to drill in.</p>
  <div class="grid">
    {#each pages as p (p)}
      <button class="card panel" onclick={() => gotoDetail(section, p)}>
        <div class="title">
          {p}
          {#if !IMPLEMENTED_PAGES.has(p)}<span class="soon">soon</span>{/if}
        </div>
        <div class="desc muted">{PAGE_DESC[p] ?? ""}</div>
        <div class="open">Open →</div>
      </button>
    {/each}
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 6px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { margin: 0 0 8px; font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
  .card {
    text-align: left;
    padding: 14px;
    cursor: pointer;
    color: var(--text);
    display: flex;
    flex-direction: column;
    gap: 6px;
    transition: border-color 0.12s;
  }
  .card:hover { border-color: var(--accent); }
  .title { font-weight: 600; display: flex; align-items: center; gap: 8px; }
  .soon { font-size: 10px; color: var(--muted); border: 1px solid var(--border); border-radius: 5px; padding: 0 5px; }
  .desc { font-size: 12.5px; line-height: 1.4; flex: 1; }
  .open { color: var(--accent); font-size: 12px; }
</style>
