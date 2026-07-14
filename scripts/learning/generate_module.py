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


def _post(model: str, body: dict) -> dict:
    r = requests.post(f"{_BASE}/{model}:generateContent",
                      headers={"X-goog-api-key": _key(),
                               "Content-Type": "application/json"},
                      json=body, timeout=_TIMEOUT)
    if r.status_code != 200:
        sys.exit(f"Gemini {model} error {r.status_code}: {r.text[:500]}")
    return r.json()


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


def generate_module_content(spec: dict) -> dict:
    body = {
        "system_instruction": {"parts": [{"text": _MODULE_INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": _build_module_prompt(spec)}]}],
        "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json",
                             "maxOutputTokens": 8192},
    }
    data = _post(_TEXT_MODEL, body)
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        sys.exit(f"Gemini returned no text. Raw: {json.dumps(data)[:600]}")
    return _extract_json(text)


# ── Step 2: script -> multi-speaker audio (optional) ────────────────────────

def _pcm_to_wav(pcm: bytes, path: Path, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)          # 16-bit
        w.setframerate(rate)
        w.writeframes(pcm)


def synthesize_episode(ep: dict, hosts: dict) -> tuple[bytes, int]:
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
    data = _post(_TTS_MODEL, body)
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

def _assemble(spec: dict, content: dict) -> dict:
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
        "generated_by": f"gemini:{_TEXT_MODEL}",
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

    print(f"[1/2] Generating module content ({'dry-run' if args.dry_run else _TEXT_MODEL})…")
    content = _mock_content(spec) if args.dry_run else generate_module_content(spec)
    course = _assemble(spec, content)

    n_q = len(course.get("quiz", []))
    n_lines = sum(len(e.get("script", [])) for e in course["episodes"])
    print(f"      -> {len(course['episodes'])} episode(s), {n_lines} lines, {n_q} quiz Qs")

    if args.audio and not args.dry_run:
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        for ep in course["episodes"]:
            print(f"[2/2] Synthesizing audio for {ep['id']}…")
            pcm, rate = synthesize_episode(ep, course["hosts"])
            wav = audio_dir / f"{course['course_id']}-{ep['id']}.wav"
            _pcm_to_wav(pcm, wav, rate)
            ep["audio"] = f"audio/{wav.name}"
            print(f"      -> {wav} ({len(pcm)//1024} KB, {rate} Hz)")

    out = out_dir / f"{course['course_id']}.json"
    out.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. Wrote {out}")


if __name__ == "__main__":
    main()
