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
  import OrderPackages from "./routes/OrderPackages.svelte";
  import Insights from "./routes/Insights.svelte";
  import Roadmap from "./routes/Roadmap.svelte";
  import Prop from "./routes/Prop.svelte";
  import Health from "./routes/Health.svelte";
  import Logs from "./routes/Logs.svelte";
  import DataExplorer from "./routes/DataExplorer.svelte";
  import GPUSpend from "./routes/GPUSpend.svelte";
  import Models from "./routes/Models.svelte";
  import ExitLadder from "./routes/ExitLadder.svelte";
  import Backtesting from "./routes/Backtesting.svelte";
  import Promotion from "./routes/Promotion.svelte";
  import Runbooks from "./routes/Runbooks.svelte";
  import SectionLanding from "./components/SectionLanding.svelte";
  import Placeholder from "./components/Placeholder.svelte";
  import { nav, gotoSection, gotoDetail, SECTION_NAMES, SECTIONS, isSpecial, IMPLEMENTED_PAGES } from "./lib/nav";
  import { getBotApiUrl, setBotApiUrl } from "./lib/config";

  let showSettings = $state(false);
  let sidebarOpen = $state(false);
  let apiUrlInput = $state(getBotApiUrl());

  function saveSettings() {
    setBotApiUrl(apiUrlInput);
    location.reload();
  }

  // Map an implemented detail page name → its component.
  const DETAIL: Record<string, any> = {
    Performance,
    Reports,
    Strategies,
    News,
    Accounts,
    Positions,
    Trades,
    Signals,
    "Order Packages": OrderPackages,
    Insights,
    Prop,
    Health,
    Logs,
    "Data Explorer": DataExplorer,
    "GPU Spend": GPUSpend,
    Models,
    "Exit Ladder": ExitLadder,
    Backtesting,
    Promotion,
    Runbooks,
  };

  function pickSection(s: string) {
    gotoSection(s);
    sidebarOpen = false;
  }
</script>

<div class="layout">
  <!-- Left sidebar (8 sections), collapsible on mobile -->
  <aside class="sidebar" class:open={sidebarOpen}>
    <div class="brand">
      <span class="logo">◆</span><strong>ICT&nbsp;Trader</strong>
    </div>
    <div class="navlist">
      {#each SECTION_NAMES as s (s)}
        <button class="navitem" class:active={$nav.section === s} onclick={() => pickSection(s)}>{s}</button>
      {/each}
    </div>
    <div class="side-foot">
      <button class="gear" title="Settings" onclick={() => (showSettings = !showSettings)}>⚙ Settings</button>
    </div>
  </aside>

  {#if sidebarOpen}
    <div
      class="scrim"
      role="button"
      tabindex="-1"
      aria-label="Close menu"
      onclick={() => (sidebarOpen = false)}
      onkeydown={(e) => e.key === "Escape" && (sidebarOpen = false)}
    ></div>
  {/if}

  <div class="main-wrap">
    <header class="topbar">
      <button class="ham" aria-label="Menu" onclick={() => (sidebarOpen = !sidebarOpen)}>☰</button>
      <div class="crumbs">
        <button class="crumb" onclick={() => pickSection($nav.section)}>{$nav.section}</button>
        {#if $nav.detail}<span class="sep">/</span><span class="crumb cur">{$nav.detail}</span>{/if}
      </div>
    </header>

    {#if showSettings}
      <div class="settings panel">
        <label for="apiurl">Bot API base URL</label>
        <div class="row">
          <input id="apiurl" class="mono" bind:value={apiUrlInput} placeholder="https://ict-bot.duckdns.org" />
          <button class="save" onclick={saveSettings}>Save &amp; reload</button>
        </div>
        <p class="muted">Browser-direct HTTPS to the bot. Leave blank for the built-in default.</p>
      </div>
    {/if}

    <main>
      {#if $nav.section === "Overview"}
        <Overview />
      {:else if $nav.section === "Roadmap"}
        <Roadmap />
      {:else if isSpecial($nav.section)}
        <Placeholder page={$nav.section} />
      {:else if $nav.detail == null}
        <SectionLanding section={$nav.section} />
      {:else if IMPLEMENTED_PAGES.has($nav.detail) && DETAIL[$nav.detail]}
        {@const Comp = DETAIL[$nav.detail]}
        <div class="detail">
          <button class="back" onclick={() => pickSection($nav.section)}>← {$nav.section}</button>
          <Comp />
        </div>
      {:else}
        <div class="detail">
          <button class="back" onclick={() => pickSection($nav.section)}>← {$nav.section}</button>
          <Placeholder page={$nav.detail} />
        </div>
      {/if}
    </main>

    <footer class="muted">ICT Trader — Svelte SPA · <span class="mono">{getBotApiUrl()}</span></footer>
  </div>
</div>

<style>
  .layout { display: flex; min-height: 100vh; }
  .sidebar {
    width: 208px;
    flex-shrink: 0;
    background: var(--panel);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 14px 10px;
    position: sticky;
    top: 0;
    height: 100vh;
  }
  .brand { display: flex; align-items: center; gap: 8px; font-size: 16px; padding: 4px 8px 14px; }
  .logo { color: var(--accent); }
  .navlist { display: flex; flex-direction: column; gap: 2px; flex: 1; }
  .navitem {
    text-align: left;
    background: none;
    border: none;
    color: var(--muted);
    padding: 9px 10px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 13.5px;
  }
  .navitem:hover { color: var(--text); background: var(--panel-2); }
  .navitem.active { color: var(--text); background: var(--panel-2); font-weight: 600; }
  .side-foot { border-top: 1px solid var(--border); padding-top: 8px; }
  .gear { width: 100%; text-align: left; background: none; border: none; color: var(--muted); padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  .gear:hover { color: var(--text); }

  .main-wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; max-width: 1120px; }
  .topbar { display: flex; align-items: center; gap: 10px; padding: 12px 16px 6px; }
  .ham { display: none; background: none; border: 1px solid var(--border); color: var(--text); border-radius: 8px; width: 34px; height: 34px; font-size: 16px; cursor: pointer; }
  .crumbs { display: flex; align-items: center; gap: 8px; font-size: 14px; }
  .crumb { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 14px; padding: 0; }
  .crumb.cur { color: var(--text); font-weight: 600; }
  .sep { color: var(--muted); }

  main { padding: 8px 16px 20px; flex: 1; }
  .detail { display: flex; flex-direction: column; gap: 12px; }
  .back { align-self: flex-start; background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 5px 12px; cursor: pointer; font-size: 13px; }

  .settings { margin: 6px 16px; padding: 14px; }
  .settings label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 12px; }
  .row { display: flex; gap: 8px; }
  .settings input { flex: 1; background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 8px 10px; }
  .save { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 14px; cursor: pointer; }
  .settings p { margin: 8px 0 0; font-size: 12px; }

  footer { padding: 12px 16px; border-top: 1px solid var(--border); font-size: 12px; }
  .scrim { display: none; }

  @media (max-width: 760px) {
    .sidebar {
      position: fixed;
      left: 0;
      top: 0;
      z-index: 30;
      transform: translateX(-100%);
      transition: transform 0.18s ease;
      box-shadow: 2px 0 12px rgba(0, 0, 0, 0.3);
    }
    .sidebar.open { transform: translateX(0); }
    .ham { display: inline-flex; align-items: center; justify-content: center; }
    .scrim { display: block; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45); z-index: 20; border: none; }
  }
</style>
