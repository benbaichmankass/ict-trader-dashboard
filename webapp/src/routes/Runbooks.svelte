<script lang="ts">
  // Runbooks & references — a static index of the durable operating documents.
  //
  // Deliberately makes NO api call. Every other Admin page renders live bot
  // state and can therefore be down when the bot is; this one is the page you
  // reach for WHEN something is down, so it must not share that failure mode.
  //
  // The operating-machinery schematic is a private Claude artifact: the URL is
  // unguessable and opening it still requires being signed in as its owner, so
  // publishing the link on a public Pages site exposes the link, never the
  // content. Recorded here so a future edit does not assume otherwise.

  const REPO = "https://github.com/benbaichmankass/Metis-Insights";

  const primary = {
    href: "https://claude.ai/code/artifact/929c5267-a297-40a3-9b91-b8c3b39bd813",
    title: "The Operating Machinery",
    blurb:
      "Which session to run for which job, the 32-skill catalog, the 124-workflow " +
      "automation map, and the ordered work plan for the remaining gaps.",
    note: "Private artifact — opens for the account that owns it.",
  };

  const refs: { href: string; title: string; blurb: string }[] = [
    {
      href: `${REPO}/issues/6927`,
      title: "Claude coordination board",
      blurb:
        "The live board every running session posts START / QUESTION / DONE to. " +
        "Faster than the committed merge queue — this is where concurrent work is visible.",
    },
    {
      href: `${REPO}/blob/main/docs/claude/DUE.md`,
      title: "What is due today",
      blurb:
        "Rendered each morning at 05:50 UTC from six registers: open items, operator-owed " +
        "decisions, queued research, probe results, red crons, unlanded automation.",
    },
    {
      href: `${REPO}/blob/main/docs/claude/PROBES.json`,
      title: "Probe results",
      blurb:
        "Committed at 05:20 UTC — each monitoring row's declared observation, graded " +
        "pass / fail / could_not_run. A could_not_run is a row nobody is currently watching.",
    },
    {
      href: `${REPO}/blob/main/docs/claude/OPEN-ITEMS.json`,
      title: "Open items",
      blurb:
        "What is in flight: a fix deployed but not yet proven, a soak accruing, a decision " +
        "pending. The register a session must read before it plans.",
    },
    {
      href: `${REPO}/blob/main/docs/claude/operator-owed-register.json`,
      title: "Decisions owed to you",
      blurb: "Rows waiting on an operator call rather than on more work.",
    },
    {
      href: `${REPO}/blob/main/docs/CLAUDE-RULES-CANONICAL.md`,
      title: "Operating rules (canonical)",
      blurb:
        "Permission tiers, the autonomy mandate, honesty, session discipline. " +
        "The highest-precedence document in the hierarchy.",
    },
  ];
</script>

<section>
  <div class="head">
    <h2>Runbooks <span class="muted sub">· durable references, no live data</span></h2>
  </div>

  <a class="card primary" href={primary.href} target="_blank" rel="noopener noreferrer">
    <div class="eyebrow">Schematic</div>
    <h3>{primary.title}</h3>
    <p>{primary.blurb}</p>
    <span class="note">{primary.note}</span>
  </a>

  <div class="grid">
    {#each refs as r (r.href)}
      <a class="card" href={r.href} target="_blank" rel="noopener noreferrer">
        <h3>{r.title}</h3>
        <p>{r.blurb}</p>
      </a>
    {/each}
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
  h2 { margin: 0; font-size: 18px; }
  .sub { font-size: 12px; font-weight: 400; }
  .muted { color: var(--muted); }

  .grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }

  .card {
    display: block; text-decoration: none; color: inherit;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px 16px;
  }
  .card:hover { border-color: var(--accent); }
  .card:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .card h3 { margin: 0 0 4px; font-size: 15px; }
  .card p { margin: 0; font-size: 13px; line-height: 1.5; color: var(--muted); }

  .primary { border-left: 3px solid var(--accent); }
  .eyebrow {
    font-size: 11px; letter-spacing: 0.09em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 5px;
  }
  .note { display: block; margin-top: 8px; font-size: 12px; color: var(--muted); }
</style>
