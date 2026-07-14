# Learning-module generator (Gemini pipeline)

Turns source material into a Learning-Center **course module** — a two-host
podcast script + a graded quiz, and optionally **real multi-speaker audio** —
that drops straight into `data/courses/<course_id>.json` (+ `data/courses/audio/`)
which the dashboard already renders.

This is the automated "Path B" alternative to authoring modules by hand or via
NotebookLM. It reuses the bot's existing Gemini convention: the `GEMINI_API_KEY`
env var against the Gemini REST API (no SDK; uses `requests`).

## One-time setup
1. Get a **free** Gemini API key: https://aistudio.google.com/apikey
2. `export GEMINI_API_KEY=...`

(Text generation runs on the free-tier `gemini-2.5-flash`. Audio uses a preview
TTS model and may have tighter limits — start with text-only.)

## Use
```bash
# 1) copy the example and fill in `sources` (open/CC/your-own material only):
cp scripts/learning/example_spec.json my_spec.json

# 2) generate the module (script + quiz):
python scripts/learning/generate_module.py my_spec.json

# 3) add real multi-speaker audio too:
python scripts/learning/generate_module.py my_spec.json --audio

# no key handy? validate the plumbing without any API call:
python scripts/learning/generate_module.py my_spec.json --dry-run --out-dir /tmp/out
```
Output: `data/courses/<course_id>.json` (+ `data/courses/audio/<id>-<ep>.wav` with
`--audio`). Add it to the Learning tab by featuring its `course_id` (same way
`elements-of-ai-ch1` is featured in `page_learning`).

## Rights
Only feed this **public-domain, Creative-Commons, or your-own** material. It
produces original explanations, not copies — but it can't grant you rights to
the underlying sources. Keep the `attribution` field accurate.

## Knobs (env)
| Var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | required |
| `GEMINI_MODULE_MODEL` | `gemini-2.5-flash` | text model for script + quiz |
| `GEMINI_TTS_MODEL` | `gemini-2.5-flash-preview-tts` | multi-speaker audio model |
| `GEMINI_VOICE_A` / `GEMINI_VOICE_B` | `Kore` / `Puck` | the two host voices |

## Notes / caveats
- Gemini TTS is in **preview** and can drift in quality on long clips; episodes
  are synthesized one call each. If a long episode sounds off, split it into
  shorter episodes in the spec.
- Always review the generated script + quiz before shipping — it's a strong first
  draft, not a final authority. The dashboard renders whatever JSON you commit.
- The player auto-uses a committed `audio` file when present, and falls back to
  the browser's built-in text-to-speech otherwise.
