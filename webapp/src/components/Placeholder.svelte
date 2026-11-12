<script lang="ts">
  import { PAGE_DESC } from "../lib/nav";
  let { page }: { page: string } = $props();
</script>

<section>
  <h2>{page}</h2>
  <div class="panel pad">
    <p>{PAGE_DESC[page] ?? ""}</p>
    <p class="muted">This screen is being ported from the Streamlit dashboard — coming soon.</p>
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .pad { padding: 18px; }
  p { margin: 0 0 8px; }
</style>
