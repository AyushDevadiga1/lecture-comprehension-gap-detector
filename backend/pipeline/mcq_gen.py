"""
Stage 6c — LLM-generated MCQ dicts, preferred over evidence sentences.

Why: the evidence-sentence quiz (Stage 6b) quotes verbatim transcript chunks,
which is honest but often not *meaningful*: for implicit concepts whose names
never appear in the transcript, `make_mcq` keeps falling back to the longest
distinct segment, so on a real lecture the same filler/ads sentence becomes
every question's distractor. Instead, an LLM reads the transcript window where
the concept is taught (see `local_context`) and writes:

    {"question": "...", "answer": "...", "distractors": ["...", "...", "..."],
     "explanation": "...why the answer is right per the lecture",
     "rationales": ["...why each distractor is wrong", "...", "..."]}

* the answer is a definition that is true of the concept per the excerpt,
* the distractors are plausible-but-wrong statements about the same concept,
* `explanation` + per-distractor `rationales` power the submit feedback shown
  to students (stored beside the answer; never leaked by GET /quizzes),
* every call goes through llm.complete, so a regenerated quiz is served from
  the cache at zero cost.

This module is pure except for the injected completer (llm.complete by
default) and never touches the DB — the caller (routes.create_quiz) stores the
result. Any parse/network failure returns None so the caller falls back to the
pure evidence path: LLM generation can only upgrade a quiz, never break it.
"""

import bisect
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
- explanation: 1-2 sentences grounding the correct answer in the excerpt, so
  a student who got it wrong can learn from it.
- rationales: exactly 3 short sentences, one per distractor (same order),
  explaining why that distractor is wrong.
- Keep all four options distinct and each under about 60 words.

Transcript excerpt:
{context}

Respond with JSON only:
{{"question": "a natural question about {concept}",
  "answer": "the correct statement about {concept}",
  "distractors": ["plausible wrong statement 1",
                  "plausible wrong statement 2",
                  "plausible wrong statement 3"],
  "explanation": "why the answer is correct, per the excerpt",
  "rationales": ["why distractor 1 is wrong",
                 "why distractor 2 is wrong",
                 "why distractor 3 is wrong"]}}
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
    n: int = 6,
    max_chars: int = 2200,
) -> Optional[str]:
    """A compact excerpt of where `concept` is taught.

    Anchors on the first transcript segment whose time window contains the
    concept's start_s (the passage where it is introduced) and joins the next
    ``n`` segments. If the concept has no time window, falls back to the first
    segment that literally mentions the concept name. Returns None when no
    anchor exists (caller then skips the LLM and keeps the evidence path).

    `n`/`max_chars` are generous enough that the writer sees the full
    teach-in passage plus a few following segments, not just the anchor.

    Items may be dicts ({text, start_s, end_s}) or ORM objects exposing the
    same attributes. Segments are expected time-sorted (as persisted); when
    they are, the anchor search is a bisect (O(log n)) that reproduces the
    historical full scan exactly.
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
        idx = _anchor_index(
            [start_of(s) for s in segs], [end_of(s) for s in segs], start
        )
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


def _anchor_index(
    starts: Iterable[Optional[float]],
    ends: Iterable[Optional[float]],
    start: float,
) -> Optional[int]:
    """Index of `start`'s segment, exactly as local_context's historic scan.

    Returns the *first* segment whose [start_s, end_s) window contains
    ``start``; when none contains it, the segment whose start_s is nearest
    (ties resolve to the earlier index). ``starts``/``ends`` are expected to
    be non-decreasing (segments are persisted time-ordered), which turns each
    search into a bisect; if ``ends`` is not monotonic it falls back to the
    exact linear scans so behaviour never diverges from the historic code.
    """
    starts = list(starts)
    ends = list(ends)
    n = len(starts)
    if n == 0:
        return None
    monotonic = n == 1 or all(b >= a for a, b in zip(ends, ends[1:]))

    # first segment whose end_s is strictly past `start`; its window contains
    # `start` iff its start_s is not after it (bisect needs monotonic ends).
    if monotonic:
        k = bisect.bisect_right(starts, start)
        j = bisect.bisect_right(ends, start)
        if j < n and j < k and starts[j] is not None and starts[j] <= start:
            return j
    else:
        for i, (st, en) in enumerate(zip(starts, ends)):
            if st is not None and en is not None and st <= start < en:
                return i

    # nearest start_s on the (sorted) starts: exactly one of k-1/k is nearest;
    # the strict-< scan in the original kept the earlier index on ties.
    if monotonic:
        if n == 1:
            return 0
        k = bisect.bisect_right(starts, start)
        if k == 0:
            return 0
        if k >= n:
            return n - 1
        return k - 1 if (start - starts[k - 1]) <= (starts[k] - start) else k
    best = 0
    for i in range(1, n):
        if starts[i] is not None and abs(starts[i] - start) < abs(starts[best] - start):
            best = i
    return best


def _json_payload(text: str) -> Optional[str]:
    """Extract the JSON object from an LLM reply.

    Some models (e.g. Qwen on Groq) prefix their JSON with a `` thinking``
    reasoning block that contains its own braces, so we prefer the *last*
    top-level object: the model is asked for JSON only, the JSON comes last.
    Falls back to the first braced span when the last one won't parse.
    """
    m = _FENCE_RE.search(text)
    candidate = m.group(1) if m else _TRAILING_FILE_MARKERS.sub("", text)
    if not candidate:
        return None
    spans = []
    last = candidate.rfind("{")
    if last != -1 and candidate.rfind("}") > last:
        spans.append((last, candidate.rfind("}")))
    first = candidate.find("{")
    if first != -1 and first not in {s for s, _ in spans}:
        last_close = candidate.rfind("}")
        if last_close > first:
            spans.append((first, last_close))
    for start, end in spans:
        try:
            json.loads(candidate[start : end + 1])
        except (ValueError, TypeError):
            continue
        return candidate[start : end + 1]
    return None


def _parse_mcq(text: Optional[str]) -> Optional[Dict]:
    """Parse the LLM's JSON answer into a make_mcq-shaped dict.

    Returns None for any malformed/unusable payload so callers fall back to
    the evidence path. Option order is shuffled deterministically per question.
    """
    if not text or not isinstance(text, str):
        return None
    payload = _json_payload(text)
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    question = _clean(data.get("question"))
    answer = _clean(data.get("answer"))
    distractors = data.get("distractors")
    rat_list = data.get("rationales")
    if not isinstance(distractors, list):
        return None
    rat_list = rat_list if isinstance(rat_list, list) else []
    kept, seen = [], set()
    for i, d in enumerate(distractors):
        d = _clean(d)
        if not d or d == answer or d in seen:
            continue
        seen.add(d)
        rat = _clean(rat_list[i] if i < len(rat_list) else None, max_chars=220)
        kept.append((d, rat))
    if not question or not answer or len(kept) < 3:
        return None

    explanation = _clean(data.get("explanation"), max_chars=320)
    rationale = {d: r for d, r in kept if r}
    options = [answer] + [d for d, _ in kept][:3]
    random.Random(question).shuffle(options)
    return {
        "question": question,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "rationale": rationale,
    }


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

    The returned dict carries make_mcq's shape (question/options/answer) plus
    two teaching extras used by the submit feedback:
        explanation: Optional[str]  why the correct answer is true (per lecture)
        rationale:   {distractor_text: why_it_is_wrong}
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