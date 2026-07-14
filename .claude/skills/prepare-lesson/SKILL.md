---
name: prepare-lesson
description: >-
  Build a Learning-Center lesson (an interactive course = audio episodes + a
  graded quiz) end-to-end and publish it to all consumers. Use when the operator
  says "prepare a lesson", "make a course", "add a Chapter N course", "generate
  audio for <course>", or "turn <source> into a podcast+quiz". Covers writing the
  spec, running the Gemini generation workflow (fresh course OR add-audio-to-an-
  existing-course), hosting audio on the GitHub Release, and propagating the
  course JSON to the dashboard bundled fallback + the bot's central store. Also
  covers the NotebookLM deep-dive (Drive) path and the Gemini free-tier budget.
  NOT for the curriculum itself (data/learning_curriculum.json) — that's the
  reading-list track, this is the interactive audio+quiz course.
---

# prepare-lesson — build & publish a Learning course

A "course" is one JSON file: a title/subtitle + a list of **episodes** (each a
two-host audio script and/or a hosted audio file) + a graded **quiz**. Courses
are served centrally by the bot (`/api/bot/learning/courses[/{id}]`) and rendered
by the dashboard (`_render_course`) and Android (`CoursePlayer.kt`). This skill
is the repeatable pipeline from a source topic → a published course.

The generation tooling lives in **this repo** (`ict-trader-dashboard`):
`scripts/learning/generate_module.py` + `.github/workflows/generate-learning-module.yml`.
The API key never touches a local session — generation runs in GitHub Actions
with the repo's `GEMINI_API_KEY` secret.

## The course JSON shape

```jsonc
{
  "course_id": "elements-of-ai-ch3",        // [a-z0-9][a-z0-9_-]* — the URL id + filename
  "title": "…", "subtitle": "…",
  "attribution": "…", "source_url": "https://…",
  "hosts": {"a": "Maya", "b": "Theo"},       // the two podcast voices
  "episodes": [
    {
      "id": "ep1", "title": "…", "summary": "…", "minutes": 6,
      "script": [ {"s":"a","t":"…"}, {"s":"b","t":"…"} ],  // two-host dialogue
      // audio resolves in this order (first present wins):
      "audio":        "audio/…mp3",   // committed in-repo (rare)
      "drive_id":     "1AbC…",        // Google Drive file → /preview iframe (NotebookLM deep-dives)
      "audio_url":    "https://github.com/…/releases/download/learning-audio/…mp3", // hosted mp3 → <audio> + speed
      "transcript_url": "https://notebooklm.google.com/notebook/…" // optional link
    }
  ],
  "quiz": [ {"id":"q1","q":"…","options":["…"],"answer":0,"explain":"…"} ]
}
```

**Audio playback precedence (dashboard `_render_course`):** committed `audio`
→ `drive_id` (Drive's own player, **no speed control**) → `audio_url` (persistent
bar in *audio mode*, **with the 0.75–2× speed button**) → `script` (browser TTS).
Prefer `audio_url` (GitHub-Release-hosted mp3) for anything you generate — it's
the only path that gets the speed control and streams with range requests.

## Two ways to make a lesson

### A) Fresh course from a spec (Gemini writes the scripts + quiz + audio)

1. **Write a spec** under `scripts/learning/specs/<course_id>.json`. Fields:
   `course_id, title, subtitle, attribution, source_url, hosts{a,b}, audience,
   quiz_count, episodes[{id,title,focus,minutes}], sources`. The `sources` block
   is your concept notes — Gemini writes ORIGINAL explanations from them (never
   copies). `audience` is where you tie examples to the operator's world. See
   `scripts/learning/specs/elements-of-ai-ch2.json` for a complete example.
   Commit the spec on your branch first (the workflow checks it out).
2. **Dispatch** the workflow (see "Running the workflow" below) with
   `spec=scripts/learning/specs/<course_id>.json`, `audio=true`, `commit=true`.
3. It generates per-episode scripts + the quiz, synthesizes multi-speaker audio,
   hosts the mp3s on the `learning-audio` Release, rewrites each episode to an
   `audio_url`, and commits the course to branch `learning/course-<course_id>`.

### B) Add audio to an EXISTING course (keep the scripts, just voice them)

Use when the scripts already exist (hand-written, or a prior run) and you only
want real audio — **no regeneration**.

1. Dispatch with `from_course=data/courses/<course_id>.json`,
   `episodes=ep2,ep3` (omit `episodes` to voice every audio-less episode),
   `commit=true`. `--from-course` skips any episode that already has
   `drive_id`/`audio_url` unless you name it explicitly.
2. Same hosting + rewrite + commit-to-review-branch as (A).

### C) A NotebookLM deep-dive (a longer, higher-quality single episode)

NotebookLM produces an excellent long-form "deep dive" audio you can't get from
raw TTS. Manual, but worth it for a flagship episode:
1. Feed the source into a NotebookLM notebook, generate the Audio Overview.
2. Download it, drop it in the shared **learning Drive folder**, share
   "Anyone with the link → Viewer", copy the file id.
3. Add an episode with `drive_id: "<id>"` + `transcript_url:
   "<notebook url>"`. (Drive's player has no speed control — that's expected;
   only re-hosted mp3s do.)

## Running the workflow

Workflow: `.github/workflows/generate-learning-module.yml` (triggers:
`workflow_dispatch` + a `generate-module`-labelled issue). Dispatch on **`main`**
(workflow_dispatch reads its config from the default branch), so **merge any
change to the workflow/generator first**, then dispatch.

Dispatch via the GitHub MCP (`actions_run_trigger` → `run_workflow`), ref `main`,
inputs e.g.:
```json
{"from_course":"data/courses/elements-of-ai-ch1.json","episodes":"ep2,ep3","audio":"true","commit":"true"}
```
Or open an issue labelled `generate-module` with a body of `spec:` / `from_course:`
/ `episodes:` / `audio:` / `commit:` lines.

**Then:** poll the run (`actions_get get_workflow_run`); on success, verify the
`learning-audio` Release has the new mp3(s) (`get_release_by_tag`) and read the
committed course on branch `learning/course-<course_id>` (`get_file_contents`).
Confirm the mp3 is public + range-streamable — a valid one starts with `ID3` or
an MPEG frame-sync (0xFFEx) and a ranged GET returns HTTP 206.

## Publishing (propagate to all consumers)

The review branch only has the dashboard copy. Publish to BOTH stores:
1. **Dashboard** (bundled fallback) — bring the generated JSON onto your
   designated branch (`git checkout origin/learning/course-<id> --
   data/courses/<id>.json`), commit, PR → `main`, merge. Streamlit auto-redeploys.
2. **Bot** (central serve) — copy the SAME file to
   `ict-trading-bot/comms/learning/courses/<id>.json`, commit on the bot's
   designated branch, PR → `main`, merge. The VM picks it up via `ict-git-sync`
   (no restart — it's a content file). This is what `/api/bot/learning/courses`
   actually serves; the dashboard copy is only the pre-deploy fallback.

Keep the two byte-identical. Android needs no change — it reads the bot endpoint.

## Verify live

The dashboard renders only live, so the final check is on-device: Learning →
the course → an episode → **Open player** should play the audio and (for an
`audio_url` episode) show the **speed button** in the bottom bar. Fix-forward if
anything's off.

## Gemini pipeline notes (why the generator looks the way it does)

- **Model discovery, not trust.** ListModels lies (lists models that 404 on the
  actual call). `generate_module.py` tries a preference-ordered candidate list
  and skips 403/404 (catalog), 429 (per-model quota), and 5xx/timeout
  (transient), backing off and retrying — so a deprecated/again-renamed flash
  model never hard-stops a run.
- **Per-episode generation** keeps each response under the ~8k-token output cap
  (a whole module in one call truncates the JSON).
- **Chunked TTS.** A full episode is synthesized in ~8-turn chunks and the PCM
  concatenated (`_TTS_CHUNK_TURNS`, `_TTS_TIMEOUT=300`) — one call over a whole
  episode times out.
- **Hosting.** WAV → mp3 (ffmpeg) → `gh release upload` to tag `learning-audio`
  (CDN-backed, no repo/clone bloat, public + range + CORS). Drive stays the
  master for NotebookLM deep-dives; generated audio goes to the Release.

## Free-tier budget (know before you scale)

Lesson generation is **on-demand and infrequent** — a handful of text + TTS
calls per lesson — so it fits the Gemini free tier easily. Do NOT confuse it with
the always-on **AI-analyst** (`INSIGHTS_MODEL_MODE=gemini`), which fans out over
*every* strategy hourly and would blow the free tier — see the analyst notes in
`ict-trading-bot/src/runtime/insights/` and the budget analysis kept with the
operator. If you batch-generate many courses in one day, space the runs (the TTS
preview model has a low daily cap); a run that 429s will retry/back off but can
exhaust the day's quota.
