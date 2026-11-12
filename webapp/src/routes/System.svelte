<script lang="ts">
  // Admin → System (UI-REDESIGN-2026-11 addendum 4): the STATIC parts of the JTA
  // console's System page, ported as-is — the hand-drawn architecture map and the
  // pipeline stages. The live parts (strategies / ML models / signals catalog from
  // the console's system_catalog tool) follow once an SPA-readable route exists.
  // ⚠️ Public repo: host IPs from the console's copy are deliberately removed.
</script>

<section>
  <h2>System</h2>
  <div class="blk">
    <h3>Architecture</h3>
    <div class="wrap arch-svg">
<svg viewBox="0 0 780 520" role="img" aria-labelledby="arch-t arch-d" style="width:100%;min-width:720px;height:auto;display:block">
<title id="arch-t">System architecture</title>
<desc id="arch-d">Exchanges feed the live trader VM, which runs the trade pipeline, web API and Caddy; the trainer VM runs the ML lifecycle and the console connector; the IB gateway VM is isolated; GitHub main syncs to the VMs every five minutes; the operator reaches the system through the dashboard, Telegram and this console.</desc>
<defs><marker id="sys-ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--muted)"/></marker></defs>
<style>
 .bx{fill:var(--panel);stroke:var(--border);stroke-width:1.2}
 .gp{fill:none;stroke:var(--accent);stroke-width:1.4;stroke-dasharray:5 4}
 .gp2{fill:none;stroke:var(--muted);stroke-width:1.2;stroke-dasharray:5 4}
 .t1{font:600 12px inherit;fill:var(--text)} .t2{font:400 10px ui-monospace, SFMono-Regular, Menlo, monospace;fill:var(--muted)} .tg{font:600 11px ui-monospace, SFMono-Regular, Menlo, monospace;fill:var(--accent);letter-spacing:.04em}
 .ar{stroke:var(--muted);stroke-width:1.3;fill:none;marker-end:url(#sys-ah)}
 .db{fill:var(--panel-2);stroke:var(--border);stroke-width:1.2}
</style>
<!-- exchanges -->
<rect class="bx" x="12" y="40" width="150" height="150" rx="6"/>
<text class="tg" x="24" y="60">EXCHANGES</text>
<text class="t1" x="24" y="86">Bybit</text><text class="t2" x="24" y="101">crypto, demo + live</text>
<text class="t1" x="24" y="124">Alpaca</text><text class="t2" x="24" y="139">equities, paper + live</text>
<text class="t1" x="24" y="162">Interactive Brokers</text><text class="t2" x="24" y="177">futures, via gateway VM</text>
<!-- live VM -->
<rect class="gp" x="196" y="20" width="352" height="330" rx="8"/>
<text class="tg" x="208" y="40">ict-bot-arm · LIVE TRADER</text>
<rect class="bx" x="210" y="54" width="324" height="156" rx="6"/>
<text class="t1" x="222" y="74">ict-trader-live.service</text><text class="t2" x="222" y="89">src/main.py → src/runtime/pipeline.py, 24/7</text>
<text class="t2" x="222" y="112">1 market data → 2 strategies → 3 decider</text>
<text class="t2" x="222" y="128">4 risk gate → 5 order validation</text>
<text class="t2" x="222" y="144">6 broker execution → 7 journal + state</text>
<text class="t2" x="222" y="168">two gates: account mode, strategy execution</text>
<text class="t2" x="222" y="184">(live | dry_run, live | shadow)</text>
<rect class="bx" x="210" y="222" width="156" height="52" rx="6"/><text class="t1" x="222" y="242">ict-web-api.service</text><text class="t2" x="222" y="258">FastAPI :8001</text>
<rect class="bx" x="378" y="222" width="156" height="52" rx="6"/><text class="t1" x="390" y="242">caddy.service</text><text class="t2" x="390" y="258">HTTPS front door</text>
<rect class="db" x="210" y="288" width="156" height="46" rx="6"/><text class="t1" x="222" y="308">trade_journal.db</text><text class="t2" x="222" y="323">+ runtime_logs/</text>
<rect class="bx" x="378" y="288" width="156" height="46" rx="6"/><text class="t1" x="390" y="308">ict-git-sync.timer</text><text class="t2" x="390" y="323">pulls main every 5 min</text>
<!-- trainer VM -->
<rect class="gp" x="584" y="20" width="184" height="226" rx="8"/>
<text class="tg" x="596" y="40">trainer-vm · ML</text>
<rect class="bx" x="598" y="54" width="156" height="66" rx="6"/><text class="t1" x="610" y="74">ML lifecycle</text><text class="t2" x="610" y="89">datasets, training</text><text class="t2" x="610" y="104">registry, 3 stages</text>
<rect class="db" x="598" y="130" width="156" height="38" rx="6"/><text class="t1" x="610" y="153">trainer_store.db</text>
<rect class="bx" x="598" y="178" width="156" height="56" rx="6"/><text class="t1" x="610" y="198">console connector</text><text class="t2" x="610" y="213">/mcp, Google sign-in</text><text class="t2" x="610" y="226">read-only tools</text>
<!-- IB gateway -->
<rect class="gp2" x="584" y="268" width="184" height="82" rx="8"/>
<text class="tg" x="596" y="288">ib-gateway · ISOLATED</text>
<text class="t1" x="598" y="312">IB Gateway</text><text class="t2" x="598" y="327">private subnet only</text>
<!-- bottom row -->
<rect class="bx" x="12" y="392" width="170" height="100" rx="6"/><text class="tg" x="24" y="412">GITHUB</text><text class="t1" x="24" y="434">main branch</text><text class="t2" x="24" y="449">code, config, registers</text><text class="t2" x="24" y="464">Actions workflows</text>
<rect class="bx" x="206" y="392" width="170" height="100" rx="6"/><text class="tg" x="218" y="412">OPERATOR</text><text class="t1" x="218" y="434">Svelte dashboard</text><text class="t2" x="218" y="449">browser-direct to Caddy</text><text class="t2" x="218" y="464">Telegram bot, the console</text>
<rect class="bx" x="400" y="392" width="170" height="100" rx="6"/><text class="tg" x="412" y="412">COMMS</text><text class="t1" x="412" y="434">comms/requests</text><text class="t2" x="412" y="449">repo asks, Telegram</text><text class="t2" x="412" y="464">answers back to repo</text>
<!-- arrows: market data in, IB orders, model artifacts, dashboard to Caddy, git sync -->
<path class="ar" d="M162,100 L208,110"/><path class="ar" d="M162,150 L208,150"/>
<path class="ar" d="M584,309 L550,309"/><text class="t2" x="560" y="300" text-anchor="middle">IB</text>
<path class="ar" d="M598,87 L536,87"/><text class="t2" x="567" y="80" text-anchor="middle">models</text>
<path class="ar" d="M372,392 L372,252 L376,252"/>
<path class="ar" d="M182,420 L190,420 L190,372 L456,372 L456,336"/><text class="t2" x="250" y="366">git pull</text>
</svg>
    </div>
    <ul class="arch-list"><li><b>Exchanges</b>: Bybit (crypto, demo and live), Alpaca (equities, paper and live), Interactive Brokers (futures, via the gateway VM). They feed the live trader.</li><li><b>ict-bot-arm, live trader</b>: ict-trader-live.service runs the 24/7 pipeline (market data, strategies, decider, risk gate, order validation, broker execution, journal); ict-web-api.service (FastAPI :8001); caddy.service (HTTPS front door); trade_journal.db and runtime_logs; ict-git-sync.timer pulls main every 5 min.</li><li><b>trainer-vm, ML</b>: datasets, training and registry (3 stages); trainer_store.db; the console connector (/mcp, Google sign-in, read-only tools). Models flow to the live trader.</li><li><b>ib-gateway, isolated</b> (private subnet only): IB Gateway; the trader reaches it over the private subnet.</li><li><b>GitHub main</b>: code, config, registers; Actions workflows; the VMs pull it.</li><li><b>Operator</b>: Svelte dashboard (browser-direct to Caddy), Telegram bot, the console.</li><li><b>Comms</b>: repo asks and Telegram, answers written back to the repo.</li></ul>
    <div class="sub">Static diagram drawn by hand, not a live read — ported from the JTA console's System page. Sources: the bot repo's docs/ARCHITECTURE-CANONICAL.md (doc last verified 2026-09-07) and docs/reference/vm-topology.md (topology as of 2026-06-14; that doc's own status is unverified). Check both before relying on a detail.</div>
  </div>
  <div class="blk">
    <h3>Pipeline stages</h3>
    <ol class="sub" style="margin:0;padding-left:1.2rem"><li>Market data intake</li><li>Strategy evaluation</li><li>Strategy output normalization and the decider</li><li>Risk gating</li><li>Runtime order validation</li><li>Broker execution</li><li>Logging and state updates (7.1 external liveness watchdog)</li><li>Operator visibility and control</li></ol>
  </div>
  <div class="blk">
    <h3>Live catalog</h3>
    <div class="sub">Strategies, ML models and the signals catalog are live reads on the console (system_catalog). They are not ported yet: no SPA-readable route serves them.</div>
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  h2 { margin: 0; font-size: 18px; }
  .blk { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; display: grid; gap: 8px; min-width: 0; }
  .blk > * { min-width: 0; }
  h3 { margin: 0; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
  .wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
  .sub { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  :global(.arch-list) { display: none; margin: 0; padding-left: 1.1rem; font-size: 13px; }
  :global(.arch-list li) { margin: 4px 0; }
  @media (max-width: 640px) { .arch-svg { display: none; } :global(.arch-list) { display: block; } }
</style>
