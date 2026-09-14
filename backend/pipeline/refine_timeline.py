"""
Stage 2b — Time-anchor refinement (tight per-concept clips).

extract_spoken_concepts stamps every concept it found in a transcript chunk
with the chunk's full [start_s, end_s] — often several minutes of audio. That
makes Stage 5 clips ("watch this concept") useless long extracts, inflates the
coverage band on the lecture timeline, and blurs the transcript window the MCQ
writer (Stage 6c) reads for grounding.

For every concept whose window is materially wider than a teaching moment, one
cached LLM call reads a *bounded* excerpt of the lecture — pinned near the
concept's first verbatim mention, or evenly strided across the window for
implicit concepts that are never named — and answers with the exact time span
where the concept is actually taught:

    {"start_s": <float>, "end_s": <float>}

Refined spans are clamped inside the coarse window; any parse/range failure,
absent mention, or null answer keeps the coarse span. Refinement can only
PIN things down — it never widens a window and never breaks a concept.
"""

import json
import math
import re
from typing import Dict, List, Optional

from backend.pipeline.llm import complete

# Only refine windows wider than this — a 90s window is already tight enough
# to play and doesn't need a paid/rate-limited LLM call.
MIN_REFINE_S = 90.0
# Keep the LLM excerpt bounded (~6K chars) so the prompt fits the token window.
MAX_EXCERPT_CHARS = int(6000)
# A clip below this is un-watchable; tiny LLM answers are padded up to it,
# centered on the passage it did pin down.
MIN_TIGHT_S = 20.0
# A refined span must shrink the window by at least 40% to count as material.
MIN_SHRINK_FRAC = 0.6

SYSTEM_PROMPT = (
    "You pinpoint where a concept is TAUGHT inside a lecture transcript. "
    "Reply with JSON only: {\"start_s\": <float>, \"end_s\": <float>} — the "
    "exact time range of the passage where the concept is explained, not "
    "merely mentioned in passing. If it is not taught anywhere in the given "
    "excerpt, return {\"start_s\": null, \"end_s\": null}."
)

EXCERPT_PROMPT = """
Transcript excerpt (timestamps in seconds), from the lecture that teaches the
concept "{concept}":

{excerpt}

Return the exact [start_s, end_s] where "{concept}" is TAUGHT — include the
passage that explains it (typically 20-60 seconds), not just the single
sentence where the term is first defined.
JSON only: {{"start_s": <float>, "end_s": <float>}}
"""


def _txt(seg) -> str:
    return seg.get("text") or "" if isinstance(seg, dict) else (
        getattr(seg, "text", "") or ""
    )


def _seg_fmt(seg) -> str:
    if isinstance(seg, dict):
        return f"[{seg.get('start_s', 0.0):.1f}s-{seg.get('end_s', 0.0):.1f}s] {seg.get('text', '')}\n"
    return f"[{getattr(seg, 'start_s', 0.0):.1f}s-{getattr(seg, 'end_s', 0.0):.1f}s] {getattr(seg, 'text', '')}\n"


def _window_segments(segments: List, cs: Optional[float], ce: Optional[float]) -> List:
    if cs is None or ce is None:
        return []
    return [s for s in segments if s.get("start_s", 0) < ce and s.get("end_s", 0) > cs]


def _bounded_excerpt(segs: List, name: str, max_chars: int) -> str:
    """A compact excerpt localizing where `name` is taught.

    If the concept is ever named verbatim in the window, start from its first
    mention and keep consecutive segments (the teaching passage). Otherwise
    stride-sample across the whole window so the LLM still gets landmarks
    (each line carries its own timestamp). Always fits under `max_chars`.
    """
    if not segs:
        return ""
    total = sum(len(_seg_fmt(s)) for s in segs)
    if total > max_chars:
        mention = next((i for i, s in enumerate(segs) if name.lower() in _txt(s).lower()), None)
        if mention is not None:
            chosen, used = [], 0
            for s in segs[mention:]:
                if used and used + len(_seg_fmt(s)) > max_chars:
                    break
                chosen.append(s)
                used += len(_seg_fmt(s))
            segs = chosen
        else:
            step = max(1, math.ceil(total / max_chars))
            segs = segs[::step]
            # keep the line count sane for pathological tiny-segment cases
            while sum(len(_seg_fmt(s)) for s in segs) > max_chars and len(segs) > 2:
                segs = segs[::2]
    return "".join(_seg_fmt(s) for s in segs)


def _parse_span(text: str) -> Optional[Dict]:
    """Parse the LLM's JSON span; None on any malformed/absent answer."""
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text or "", re.DOTALL)
    payload = m.group(1) if m else (text or "")
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(payload[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    cs, ce = data.get("start_s"), data.get("end_s")
    if cs is None or ce is None:
        return None
    try:
        return {"start_s": float(cs), "end_s": float(ce)}
    except (TypeError, ValueError):
        return None


def _refine_one(name: str, cs: float, ce: float, segs: List, completer) -> Optional[Dict]:
    """Ask the cached LLM for the exact span; validate against [cs, ce]."""
    try:
        result = completer(
            SYSTEM_PROMPT,
            EXCERPT_PROMPT.format(concept=name, excerpt=_bounded_excerpt(segs, name, MAX_EXCERPT_CHARS)),
            temperature=0.0,
            max_tokens=120,
        )
        span = _parse_span(result.text)
    except Exception:
        return None
    if span is None:
        return None
    ns, ne = span["start_s"], span["end_s"]
    if not math.isfinite(ns) or not math.isfinite(ne):
        return None
    if not (cs - 1.0) <= ns or not ne <= (ce + 1.0) or ne <= ns:
        return None
    # The LLM often pins a single sentence (~5s). Stretch it to a watchable
    # minimum, centered on the passage it did anchor — never beyond the window.
    if ne - ns < MIN_TIGHT_S:
        mid = (ns + ne) / 2.0
        ns = max(cs, mid - MIN_TIGHT_S / 2.0)
        ne = min(ce, ns + MIN_TIGHT_S)
        if ne - ns < MIN_TIGHT_S / 2.0:
            return None
    if (ne - ns) > MIN_SHRINK_FRAC * (ce - cs) + MIN_TIGHT_S:
        return None
    return {"start_s": max(cs, ns), "end_s": min(ce, ne)}


def refine_concept_times(
    concepts: List[Dict],
    segments: List[Dict],
    completer=None,
) -> List[Dict]:
    """Pin each concept's [start_s, end_s] to the span where it is taught.

    Returns a new list (same order) with start_s/end_s updated where a valid
    tighter span was found; untouched (coarse) everywhere else. Never raises:
    every failure path keeps the coarse window. `completer` has llm.complete's
    signature and is injected for tests.
    """
    completer = completer or complete
    out: List[Dict] = []
    for c in concepts:
        cs, ce = c.get("start_s"), c.get("end_s")
        if cs is None or ce is None or (ce - cs) <= MIN_REFINE_S:
            out.append(dict(c))
            continue
        segs = _window_segments(segments, cs, ce)
        if not segs:
            out.append(dict(c))
            continue
        span = _refine_one(str(c.get("name", "")), float(cs), float(ce), segs, completer)
        if span is not None:
            c = dict(c)
            c["start_s"], c["end_s"] = span["start_s"], span["end_s"]
        out.append(c)
    return out