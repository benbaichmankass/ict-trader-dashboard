<script lang="ts">
  import type { Position } from "../lib/api";
  import { money, num, signClass, DASH } from "../lib/format";

  let { positions }: { positions: Position[] } = $props();

  function fundingLabel(p: Position): string {
    const c = (p.accountClass ?? "").toLowerCase();
    if (c === "prop") return "Prop";
    if (c === "paper") return "Paper";
    if (c === "real_money") return "Real";
    return c || DASH;
  }
</script>

{#if positions.length === 0}
  <div class="empty muted">No open positions.</div>
{:else}
  <div class="scroll">
    <table>
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Side</th>
          <th>Funding</th>
          <th>Account</th>
          <th class="r">Qty</th>
          <th class="r">Entry</th>
          <th class="r">uPnL</th>
        </tr>
      </thead>
      <tbody>
        {#each positions as p (p.id)}
          <tr>
            <td class="sym">{p.symbol}</td>
            <td class={(p.side ?? "").toLowerCase() === "sell" ? "neg" : "pos"}>
              {(p.side ?? "").toLowerCase() === "sell" ? "SHORT" : "LONG"}
            </td>
            <td>{fundingLabel(p)}</td>
            <td class="muted">{p.account ?? DASH}</td>
            <td class="r mono">{num(p.qty, 4)}</td>
            <td class="r mono">{money(p.entryPrice)}</td>
            <td class="r mono {signClass(p.unrealizedPnl)}">{money(p.unrealizedPnl, { sign: true })}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .scroll {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  th,
  td {
    padding: 8px 10px;
    text-align: left;
    white-space: nowrap;
  }
  th {
    color: var(--muted);
    font-weight: 500;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
  }
  tbody tr {
    border-bottom: 1px solid var(--border);
  }
  .r {
    text-align: right;
  }
  .sym {
    font-weight: 600;
  }
  .empty {
    padding: 16px;
  }
</style>
