<script lang="ts">
  // Generic segmented control (funding class, time window, …).
  let {
    options,
    value = $bindable(),
  }: { options: { value: string; label: string }[]; value: string } = $props();
</script>

<div class="seg" role="tablist">
  {#each options as o (o.value)}
    <button role="tab" aria-selected={value === o.value} class:active={value === o.value} onclick={() => (value = o.value)}>
      {o.label}
    </button>
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    gap: 2px;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 2px;
  }
  .seg button {
    background: none;
    border: none;
    color: var(--muted);
    padding: 5px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12.5px;
    white-space: nowrap;
  }
  .seg button.active {
    background: var(--panel);
    color: var(--text);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  }
</style>
