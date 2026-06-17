# AI Traders Models Roadmap — dashboard pointer

> **Source of truth:** [`benbaichmankass/ict-trading-bot` → `docs/AI-TRADERS-ROADMAP.md`](https://github.com/benbaichmankass/ict-trading-bot/blob/main/docs/AI-TRADERS-ROADMAP.md)
>
> The master AI traders models roadmap and its sprint plans live in the
> trading-bot repo. The bot owns the AI/ML lifecycle (datasets, training,
> model registry, deployment tiers); the dashboard is a pure consumer of
> the data feeds and surfaces those results read-only.

## What lives where

This file only records **where dashboard-relevant AI/ML work lives** — it
does not restate the bot's milestone numbers (those go stale). For the
current milestone/sprint status, read `ict-trading-bot/ROADMAP.md`.

| Artifact | Repo | Path |
|---|---|---|
| Master plan | `ict-trading-bot` | `docs/AI-TRADERS-ROADMAP.md` |
| Current milestone/sprint status | `ict-trading-bot` | `ROADMAP.md` |
| Workstream sprint plans | `ict-trading-bot` | `docs/sprint-plans/ai-traders/` |
| AI/ML architecture | `ict-trading-bot` | `docs/ARCHITECTURE-CANONICAL.md` |

## Dashboard repo scope

This repo (`ict-trader-dashboard`) **does not own** any part of the AI
lifecycle. It is the read-only **Streamlit app** (the earlier React+Vercel
SPA was retired in PR #32). When new ML surfaces require dashboard work —
for example a model registry tab, drift charts, or a shadow-mode score
panel — those arrive as separate dashboard sprints that consume Tier-1
endpoints published by the bot. The Models, Promotion, and Insights tabs
are the current dashboard surfaces over the bot's ML lifecycle.

## Non-negotiable rules (apply to dashboard surfaces too)

When the dashboard eventually renders model status / influence, it must
respect the same rules the bot owns:

- Display only what the bot publishes; never call training / promotion
  endpoints from the dashboard.
- Never imply a model is influencing live trading unless its registry
  stage is `advisory` (the canonical live-influence stage on the 3-stage
  ladder `candidate → shadow → advisory`; the legacy stage names —
  `live_approved` / `limited_live` etc. — alias to it bot-side via
  `ml.manifest.canonical_stage`).
- Treat all model output as advisory in the UI until the operator
  explicitly opts the displayed model into live influence.

See the upstream master plan for the full set.
