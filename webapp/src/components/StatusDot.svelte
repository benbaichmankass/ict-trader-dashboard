<script lang="ts">
  let { status = "flat", label = "" }: { status?: "pos" | "neg" | "flat" | "warn"; label?: string } =
    $props();
  const color = $derived(
    status === "pos" ? "var(--pos)" : status === "neg" ? "var(--neg)" : status === "warn" ? "#e0a800" : "var(--muted)",
  );
</script>

<span class="dot" title={label} style:background={color}></span>{#if label}<span class="lbl muted">{label}</span>{/if}

<style>
  .dot {
    display: inline-block;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    vertical-align: middle;
  }
  .lbl {
    margin-left: 6px;
    font-size: 12px;
  }
</style>
