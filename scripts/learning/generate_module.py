#!/usr/bin/env python3
"""Generate a Learning-Center course module from source material via the Gemini API.

This is the "Path B" pipeline: open/permissioned source text  ->  a focused
learning module (two-host podcast script + graded quiz), and — optionally —
real multi-speaker audio. The output drops straight into the dashboard's course
schema (``data/courses/<course_id>.json`` + ``data/courses/audio/*.wav``) that
``streamlit_app.py`` already renders.

Auth reuses the bot's existing convention: the ``GEMINI_API_KEY`` env var, sent
via the ``X-goog-api-key`` header to the Gemini REST API (no SDK). Text models
default to the free-tier ``gemini-2.5-flash``; audio uses a preview TTS model.

Usage
-----
    export GEMINI_API_KEY=...            # free from https://aistudio.google.com/apikey
    python scripts/learning/generate_module.py spec.json                # script + quiz only
    python scripts/learning/generate_module.py spec.json --audio        # + multi-speaker audio
    python scripts/learning/generate_module.py spec.json --dry-run      # no API calls (schema smoke test)

Spec file (JSON) — see scripts/learning/example_spec.json:
    {
      "course_id": "my-module",
      "title": "...",
      "subtitle": "...",
      "attribution": "Source + license note (you are responsible for source rights).",
      "source_url": "...",
      "hosts": {"a": "Maya", "b": "Theo"},
      "episodes": [{"id": "ep1", "title": "...", "focus": "what to cover", "minutes": 12}],
      "quiz_count": 12,
      "sources": "<<< the open-source / CC / your-own material to teach from >>>"
    }

RIGHTS: only feed this sources you may transform — public-domain, Creative-Commons,
or your own. The pipeline produces ORIGINAL explanations, not copies, but it can't
grant you rights to the underlying material.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import wave
from pathlib import Path

import requests

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_TEXT_MODEL = os.environ.get("GEMINI_MODULE_MODEL", "gemini-2.5-flash")
_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
# Two distinct prebuilt Gemini voices for the two hosts.
_VOICE_A = os.environ.get("GEMINI_VOICE_A", "Kore")
_VOICE_B = os.environ.get("GEMINI_VOICE_B", "Puck")
_TIMEOUT = 120


# ── Gemini REST helpers ─────────────────────────────────────────────────────

def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        sys.exit("GEMINI_API_KEY is not set. Get a free key at "
                 "https://aistudio.google.com/apikey and `export GEMINI_API_KEY=...`.")
    return k


class _GeminiHTTPError(RuntimeError):
    """A non-200 from a Gemini generateContent call (carries the status)."""

    def __init__(self, model: str, status: int, text: str) -> None:
        super().__init__(f"Gemini {model} error {status}: {text[:300]}")
        self.model, self.status, self.text = model, status, text


def _post(model: str, body: dict) -> dict:
    r = requests.post(f"{_BASE}/{model}:generateContent",
                      headers={"X-goog-api-key": _key(),
                               "Content-Type": "application/json"},
                      json=body, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise _GeminiHTTPError(model, r.status_code, r.text)
    return r.json()


def _list_models() -> list[dict]:
    """The models this key can see (paginated ListModels)."""
    models: list[dict] = []
    page_token = ""
    for _ in range(10):  # safety bound
        url = f"{_BASE}?pageSize=200"
        if page_token:
            url += f"&pageToken={page_token}"
        r = requests.get(url, headers={"X-goog-api-key": _key()}, timeout=_TIMEOUT)
        if r.status_code != 200:
            sys.exit(f"Gemini ListModels error {r.status_code}: {r.text[:300]}")
        data = r.json()
        models.extend(data.get("models", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return models


def _candidate_models(preferred: str, want: str) -> list[str]:
    """Preference-ordered model names to TRY (first success wins).

    ``want`` is 'text' (generateContent, non-TTS) or 'tts' (audio). ListModels
    is only a hint — it happily lists models that 404 on the actual call (e.g.
    ``gemini-2.5-flash`` is "no longer available to NEW users" yet still
    listed), so we return an ordered list and the caller tries each until one
    returns 200 rather than trusting the listing.
    """
    usable = {}  # short name -> supported methods
    for m in _list_models():
        name = m.get("name", "").split("/")[-1]
        if name:
            usable[name] = m.get("supportedGenerationMethods", [])

    def _is_tts(n: str) -> bool:
        return "tts" in n.lower()

    # For TEXT we want a language model — exclude image/embedding/vision/etc.
    _non_text = ("image", "embedding", "embed", "aqa", "vision")

    def _eligible(n: str) -> bool:
        low = n.lower()
        if want == "tts":
            return _is_tts(n)
        return not _is_tts(n) and not any(t in low for t in _non_text)

    cands = [
        n for n, methods in usable.items()
        if "generateContent" in methods and _eligible(n)
    ]

    def _rank(n: str) -> tuple:
        low = n.lower()
        # Prefer: flash (text), non-preview, non-lite, then newest by version.
        return (
            0 if ("flash" in low or want == "tts") else 1,
            0 if "preview" not in low else 1,
            0 if "lite" not in low else 1,
            n,  # lexical — newer dated/versioned names sort later
        )

    ordered = sorted(cands, key=_rank)
    # Try dated/versioned aliases before the bare deprecated alias, but keep the
    # configured default in the running if it's actually usable.
    if preferred in usable and preferred not in ordered:
        ordered.append(preferred)
    ordered = [preferred] + [n for n in ordered if n != preferred] \
        if preferred in ordered else ordered
    # De-dupe, preserve order.
    seen, out = set(), []
    for n in ordered:
        if n not in seen:
            seen.add(n)
            out.append(n)
    if not out:
        sys.exit(f"No usable Gemini {want} model for this key. "
                 f"Available: {sorted(usable)}")
    return out


def _generate(candidates: list[str], body: dict) -> tuple[str, dict]:
    """POST ``body`` against each candidate model until one returns 200.

    A model can fail two ways that warrant trying the NEXT candidate:
      * catalog — 403/404/"not available"/"not found": listed but not granted.
      * quota — 429: models have independent free-tier quotas, so a sibling may
        still have headroom.
    Anything else (400 bad request, 5xx) is a genuine error and is surfaced.
    """
    errors, saw_quota = [], False
    for model in candidates:
        try:
            data = _post(model, body)
            if model != candidates[0]:
                print(f"      (using '{model}')")
            return model, data
        except _GeminiHTTPError as exc:
            low = exc.text.lower()
            catalog = exc.status in (403, 404) or "not available" in low or "not found" in low
            quota = exc.status == 429 or "quota" in low or "rate limit" in low
            errors.append(f"{model}: {exc.status} {exc.text[:200]}")
            if catalog:
                print(f"      (model '{model}' unavailable; trying next)")
                continue
            if quota:
                saw_quota = True
                print(f"      (model '{model}' quota exhausted; trying next)")
                continue
            raise  # a genuine error (bad request, 5xx) — surface it
    tail = "\n  ".join(errors)
    if saw_quota:
        sys.exit(
            "Every candidate Gemini model was quota-limited (HTTP 429). The "
            "free tier's per-model quota for this key is exhausted or unset.\n"
            "Fixes: wait for the daily free-tier reset, or enable billing on the "
            "key's Google Cloud project (https://aistudio.google.com/apikey → "
            "the project → set up billing) for a higher quota.\nTried:\n  " + tail)
    sys.exit("No usable Gemini model succeeded. Tried:\n  " + tail)


# ── Step 1: source -> module JSON (script + quiz) ───────────────────────────

_MODULE_INSTRUCTIONS = """\
You are an expert learning designer and podcast writer. Turn the SOURCE MATERIAL
into a focused, engaging learning module as STRICT JSON — no prose outside JSON.

Rules:
- Write ORIGINAL explanations that teach the concepts in the sources. Do NOT copy
  sentences from the source; explain in your own words.
- Each episode is a two-host dialogue between the two hosts named below. Alternate
  turns naturally (18-30 turns per episode). Host "a" and host "b" trade off
  explaining, questioning, and stress-testing ideas. Conversational, concrete,
  lightly witty — a good podcast, not a lecture.
- Ground examples in the listener's context when given (see AUDIENCE).
- The quiz has single-correct multiple-choice (or true/false) questions with a
  0-based "answer" index into "options" and a one-sentence "explain".

Output EXACTLY this JSON shape (no markdown fences):
{
  "episodes": [
    {"id": "<from plan>", "title": "<from plan or improved>",
     "script": [{"s": "a", "t": "..."}, {"s": "b", "t": "..."}, ...]}
  ],
  "quiz": [
    {"id": "q1", "q": "...", "options": ["...", "..."], "answer": 0, "explain": "..."}
  ]
}
"""


def _build_module_prompt(spec: dict) -> str:
    hosts = spec.get("hosts", {"a": "Host A", "b": "Host B"})
    plan = spec.get("episodes", [])
    plan_txt = "\n".join(
        f'  - id={e.get("id", f"ep{i+1}")} title="{e.get("title","")}" '
        f'focus="{e.get("focus","")}"'
        for i, e in enumerate(plan)
    ) or "  (design 3 well-sequenced episodes yourself)"
    return (
        f'HOSTS: host "a" = {hosts.get("a","Host A")}, host "b" = {hosts.get("b","Host B")}.\n'
        f'AUDIENCE: {spec.get("audience", "a smart non-technical operator of an automated trading system; tie examples to markets/algorithmic trading where natural.")}\n'
        f'QUIZ: produce exactly {spec.get("quiz_count", 10)} questions covering the whole module.\n'
        f'EPISODES TO PRODUCE:\n{plan_txt}\n\n'
        f'SOURCE MATERIAL:\n"""\n{spec.get("sources","").strip()}\n"""\n'
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} block.
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def generate_module_content(spec: dict, candidates: list[str]) -> tuple[str, dict]:
    body = {
        "system_instruction": {"parts": [{"text": _MODULE_INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": _build_module_prompt(spec)}]}],
        "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json",
                             "maxOutputTokens": 8192},
    }
    model, data = _generate(candidates, body)
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        sys.exit(f"Gemini returned no text. Raw: {json.dumps(data)[:600]}")
    return model, _extract_json(text)


# ── Step 2: script -> multi-speaker audio (optional) ────────────────────────

def _pcm_to_wav(pcm: bytes, path: Path, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)          # 16-bit
        w.setframerate(rate)
        w.writeframes(pcm)


def synthesize_episode(ep: dict, hosts: dict, tts_candidates: list[str]) -> tuple[bytes, int]:
    name_a, name_b = hosts.get("a", "Host A"), hosts.get("b", "Host B")
    transcript = "TTS the following two-host conversation naturally:\n" + "\n".join(
        f"{name_a if ln.get('s') == 'a' else name_b}: {ln.get('t','')}"
        for ln in ep.get("script", [])
    )
    body = {
        "contents": [{"parts": [{"text": transcript}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
                {"speaker": name_a, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": _VOICE_A}}},
                {"speaker": name_b, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": _VOICE_B}}},
            ]}},
        },
    }
    _model, data = _generate(tts_candidates, body)
    part = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [{}])[0]
    inline = part.get("inlineData") or part.get("inline_data") or {}
    b64 = inline.get("data")
    if not b64:
        sys.exit(f"TTS returned no audio for {ep.get('id')}. Raw: {json.dumps(data)[:600]}")
    rate = 24000
    m = re.search(r"rate=(\d+)", inline.get("mimeType", inline.get("mime_type", "")))
    if m:
        rate = int(m.group(1))
    return base64.b64decode(b64), rate


# ── Assembly + CLI ──────────────────────────────────────────────────────────

def _assemble(spec: dict, content: dict, model: str) -> dict:
    plan = {e.get("id"): e for e in spec.get("episodes", [])}
    episodes = []
    for ep in content.get("episodes", []):
        planned = plan.get(ep.get("id"), {})
        episodes.append({
            "id": ep.get("id"),
            "title": ep.get("title") or planned.get("title", ""),
            "summary": planned.get("summary", ep.get("summary", "")),
            "minutes": planned.get("minutes"),
            "script": ep.get("script", []),
        })
    return {
        "course_id": spec["course_id"],
        "title": spec.get("title", spec["course_id"]),
        "subtitle": spec.get("subtitle", ""),
        "attribution": spec.get("attribution", ""),
        "source_url": spec.get("source_url", ""),
        "hosts": spec.get("hosts", {"a": "Maya", "b": "Theo"}),
        "generated_by": f"gemini:{model}",
        "episodes": episodes,
        "quiz": content.get("quiz", []),
    }


def _mock_content(spec: dict) -> dict:
    """--dry-run stand-in so the file/audio plumbing is testable without a key."""
    eps = spec.get("episodes", [{"id": "ep1", "title": "Sample"}])
    return {
        "episodes": [{"id": e.get("id", f"ep{i+1}"), "title": e.get("title", "Sample"),
                      "script": [{"s": "a", "t": "This is a dry-run sample line."},
                                 {"s": "b", "t": "No Gemini call was made."}]}
                     for i, e in enumerate(eps)],
        "quiz": [{"id": "q1", "q": "Dry run?", "options": ["Yes", "No"], "answer": 0,
                  "explain": "This is a mock module."}],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a Learning course module via Gemini.")
    ap.add_argument("spec", help="path to the module spec JSON")
    ap.add_argument("--audio", action="store_true", help="also synthesize multi-speaker audio")
    ap.add_argument("--dry-run", action="store_true", help="skip API calls; emit a mock module")
    ap.add_argument("--out-dir", default=None, help="output dir (default: repo data/courses)")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if "course_id" not in spec:
        sys.exit("spec must include 'course_id'.")

    out_dir = Path(args.out_dir) if args.out_dir else (
        Path(__file__).resolve().parents[2] / "data" / "courses")
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        text_model, tts_cands = _TEXT_MODEL, [_TTS_MODEL]
        print("[1/2] Generating module content (dry-run)…")
        content = _mock_content(spec)
    else:
        text_cands = _candidate_models(_TEXT_MODEL, "text")
        tts_cands = _candidate_models(_TTS_MODEL, "tts") if args.audio else [_TTS_MODEL]
        print(f"[1/2] Generating module content (try order: {', '.join(text_cands[:4])}…)")
        text_model, content = generate_module_content(spec, text_cands)
    course = _assemble(spec, content, text_model)

    n_q = len(course.get("quiz", []))
    n_lines = sum(len(e.get("script", [])) for e in course["episodes"])
    print(f"      -> {len(course['episodes'])} episode(s), {n_lines} lines, {n_q} quiz Qs")

    if args.audio and not args.dry_run:
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        for ep in course["episodes"]:
            print(f"[2/2] Synthesizing audio for {ep['id']}…")
            pcm, rate = synthesize_episode(ep, course["hosts"], tts_cands)
            wav = audio_dir / f"{course['course_id']}-{ep['id']}.wav"
            _pcm_to_wav(pcm, wav, rate)
            ep["audio"] = f"audio/{wav.name}"
            print(f"      -> {wav} ({len(pcm)//1024} KB, {rate} Hz)")

    out = out_dir / f"{course['course_id']}.json"
    out.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. Wrote {out}")


if __name__ == "__main__":
    main()
