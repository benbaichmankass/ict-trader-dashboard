<script lang="ts">
  import Overview from "./routes/Overview.svelte";
  import Trades from "./routes/Trades.svelte";
  import Performance from "./routes/Performance.svelte";
  import Positions from "./routes/Positions.svelte";
  import Strategies from "./routes/Strategies.svelte";
  import Accounts from "./routes/Accounts.svelte";
  import Signals from "./routes/Signals.svelte";
  import News from "./routes/News.svelte";
  import Reports from "./routes/Reports.svelte";
  import { view, goto, VIEWS } from "./lib/nav";
  import { getBotApiUrl, setBotApiUrl } from "./lib/config";

  let showSettings = $state(false);
  let apiUrlInput = $state(getBotApiUrl());

  function saveSettings() {
    setBotApiUrl(apiUrlInput);
    location.reload();
  }
</script>

<div class="shell">
  <header>
    <div class="brand">
      <span class="logo">◆</span>
      <strong>ICT&nbsp;Trader</strong>
    </div>
    <nav>
      {#each VIEWS as v (v.id)}
        <button class:active={$view === v.id} onclick={() => goto(v.id)}>{v.label}</button>
      {/each}
    </nav>
    <button class="gear" title="Settings" onclick={() => (showSettings = !showSettings)}>⚙</button>
  </header>

  {#if showSettings}
    <div class="settings panel">
      <label for="apiurl">Bot API base URL</label>
      <div class="row">
        <input id="apiurl" class="mono" bind:value={apiUrlInput} placeholder="https://ict-bot.duckdns.org" />
        <button onclick={saveSettings}>Save &amp; reload</button>
      </div>
      <p class="muted">Browser-direct HTTPS to the bot. Leave blank to use the built-in default.</p>
    </div>
  {/if}

  <main>
    {#if $view === "overview"}
      <Overview />
    {:else if $view === "trades"}
      <Trades />
    {:else if $view === "performance"}
      <Performance />
    {:else if $view === "positions"}
      <Positions />
    {:else if $view === "strategies"}
      <Strategies />
    {:else if $view === "accounts"}
      <Accounts />
    {:else if $view === "signals"}
      <Signals />
    {:else if $view === "news"}
      <News />
    {:else if $view === "reports"}
      <Reports />
    {/if}
  </main>

  <footer class="muted">
    ICT Trader — Svelte SPA · <span class="mono">{getBotApiUrl()}</span>
  </footer>
</div>

<style>
  .shell {
    max-width: 1100px;
    margin: 0 auto;
    padding: 12px 16px 40px;
  }
  header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0 14px;
    flex-wrap: wrap;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
  }
  .logo {
    color: var(--accent);
  }
  nav {
    display: flex;
    gap: 4px;
    flex: 1;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  nav button {
    background: none;
    border: none;
    color: var(--muted);
    padding: 7px 12px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13.5px;
    white-space: nowrap;
  }
  nav button.active {
    color: var(--text);
    background: var(--panel-2);
  }
  .gear {
    background: none;
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    width: 34px;
    height: 34px;
    cursor: pointer;
    font-size: 16px;
    flex-shrink: 0;
  }
  .settings {
    padding: 14px;
    margin-bottom: 14px;
  }
  .settings label {
    display: block;
    margin-bottom: 6px;
    color: var(--muted);
    font-size: 12px;
  }
  .row {
    display: flex;
    gap: 8px;
  }
  .settings input {
    flex: 1;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 8px 10px;
  }
  .settings button,
  .row button {
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 8px 14px;
    cursor: pointer;
  }
  .settings p {
    margin: 8px 0 0;
    font-size: 12px;
  }
  footer {
    margin-top: 24px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
    font-size: 12px;
  }
</style>
