"""
Stage 6c — LLM-generated MCQ dicts, preferred over evidence sentences.

Why: the evidence-sentence quiz (Stage 6b) quotes verbatim transcript chunks,
which is honest but often not *meaningful*: for implicit concepts whose names
never appear in the transcript, `make_mcq` keeps falling back to the longest
distinct segment, so on a real lecture the same filler/ads sentence becomes
every question's distractor. Instead, an LLM reads the transcript window where
the concept is taught (see `local_context`) and writes:

    {"question": "...", "answer": "...", "distractors": ["...", "...", "..."]}

* the answer is a definition that is true of the concept per the excerpt,
* the distractors are plausible-but-wrong statements about the same concept,
* every call goes through llm.complete, so a regenerated quiz is served from
  the cache at zero cost.

This module is pure except for the injected completer (llm.complete by
default) and never touches the DB — the caller (routes.create_quiz) stores the
result. Any parse/network failure returns None so the caller falls back to the
pure evidence path: LLM generation can only upgrade a quiz, never break it.
"""

import json
import random
import re
from typing import Dict, Iterable, Optional

from backend.pipeline.llm import LLMResult, complete

_SYSTEM = (
    "You are an expert educational-assessment writer. "
    "Respond with valid JSON only, no prose, no code fences."
)

PROMPT = """
Write one multiple-choice quiz question about a single concept from a lecture.

The transcript excerpt below teaches the concept "{concept}". Write an MCQ
that tests whether a student understood that concept as taught.

Requirements:
- question: a natural question naming the concept (e.g. "Which best describes
  '{concept}' as taught in the lecture?").
- answer: ONE sentence that is TRUE of the concept according to the excerpt.
  Prefer a compact definition over a verbatim quote.
- distractors: exactly 3 statements that are PLAUSIBLE but WRONG about the
  concept. They must look like realistic quiz answers, not obviously absurd
  filler, and must not be paraphrases of the true answer.
- Keep all four options distinct and each under about 60 words.

Transcript excerpt:
{context}

Respond with JSON only:
{{"question": "a natural question about {concept}",
  "answer": "the correct statement about {concept}",
  "distractors": ["plausible wrong statement 1",
                  "plausible wrong statement 2",
                  "plausible wrong statement 3"]}}
"""

_SPACE_RE = re.compile(r"\s+")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_FILE_MARKERS = re.compile(
    r"(Transcript excerpt|Respond with JSON|You are an expert).*", re.S
)


def _clean(text: Optional[str], max_chars: int = 520) -> Optional[str]:
    """Normalize whitespace and cap a string for use as quiz text."""
    if not text or not isinstance(text, str):
        return None
    flat = _SPACE_RE.sub(" ", text).strip()
    return flat[:max_chars].rstrip()


def local_context(
    segments: Iterable,
    concept,
    n: int = 3,
    max_chars: int = 1400,
) -> Optional[str]:
    """A compact excerpt of where `concept` is taught.

    Anchors on the first transcript segment whose time window contains the
    concept's start_s (the passage where it is introduced) and joins the next
    ``n`` segments. If the concept has no time window, falls back to the first
    segment that literally mentions the concept name. Returns None when no
    anchor exists (caller then skips the LLM and keeps the evidence path).

    Items may be dicts ({text, start_s, end_s}) or ORM objects exposing the
    same attributes.
    """
    if concept is None:
        return None
    name = getattr(concept, "name", None) or (concept if isinstance(concept, str) else None)
    start = getattr(concept, "start_s", None)

    def txt(s) -> str:
        return s.get("text") or "" if isinstance(s, dict) else (
            getattr(s, "text", "") or ""
        )

    def start_of(s) -> Optional[float]:
        return s.get("start_s") if isinstance(s, dict) else getattr(s, "start_s", None)

    def end_of(s) -> Optional[float]:
        return s.get("end_s") if isinstance(s, dict) else getattr(s, "end_s", None)

    segs = list(segments)
    idx = None
    if start is not None:
        for i, s in enumerate(segs):
            st, en = start_of(s), end_of(s)
            if st is not None and en is not None and st <= start < en:
                idx = i
                break
        if idx is None:
            best = None
            for i, s in enumerate(segs):
                st = start_of(s)
                if st is None:
                    continue
                if best is None or abs(st - start) < abs(start_of(segs[best]) - start):
                    best = i
            idx = best
    if idx is None and name:
        for i, s in enumerate(segs):
            if name.lower() in txt(s).lower():
                idx = i
                break
    if idx is None:
        return None

    parts, total = [], 0
    for s in segs[idx : idx + n]:
        t = _clean(txt(s), max_chars)
        if not t:
            continue
        if total and total + len(t) > max_chars:
            break
        parts.append(t)
        total += len(t)
    return " ... ".join(parts) if parts else None


def _parse_mcq(text: Optional[str]) -> Optional[Dict]:
    """Parse the LLM's JSON answer into a make_mcq-shaped dict.

    Returns None for any malformed/unusable payload so callers fall back to
    the evidence path. Option order is shuffled deterministically per question.
    """
    if not text or not isinstance(text, str):
        return None
    m = _FENCE_RE.search(text)
    payload = m.group(1) if m else _TRAILING_FILE_MARKERS.sub("", text)
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(payload[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    question = _clean(data.get("question"))
    answer = _clean(data.get("answer"))
    distractors = data.get("distractors")
    if not isinstance(distractors, list):
        return None
    seen: set = set()
    uniq = []
    for d in distractors:
        d = _clean(d)
        if d and d != answer and d not in seen:
            seen.add(d)
            uniq.append(d)
    if not question or not answer or len(uniq) < 3:
        return None

    options = [answer] + uniq[:3]
    random.Random(question).shuffle(options)
    return {"question": question, "options": options, "answer": answer}


def generate_mcq(
    concept: str,
    context: Optional[str],
    completer=None,
    temperature: float = 0.3,
    max_tokens: int = 480,
) -> Optional[Dict]:
    """Ask the (cached) LLM to write one MCQ about ``concept``.

    ``completer`` has llm.complete's signature (system, user, *, ...) and
    returns an object with a ``.text`` attribute (LLMResult). Any failure —
    network, quota, malformed JSON — returns None, never raises.
    """
    if not context or not context.strip():
        return None
    completer = completer or complete
    try:
        result: LLMResult = completer(
            _SYSTEM,
            PROMPT.format(concept=concept, context=context),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _parse_mcq(result.text)
    except Exception:
        return None