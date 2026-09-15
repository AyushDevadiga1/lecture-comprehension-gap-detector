"""
Lecture Structure pass — the root-cause redesign (see plan/LECTURE_STRUCTURE.md).

Replaces Stage 2 (chunk-atomic concept extraction) + Stage 2b (time-anchor
refinement) with ONE consolidated LLM read of the transcript that recovers the
lecture's *discourse structure*:

  extract_lecture_structure(docs)
      -> {"passages": [...], "concepts": [...], "links": [...]}

  passages   coherent teaching units — {"title", "kind", "start_s", "end_s",
             "summary", "text", "concepts": [{name, implicit,
             teach_start_s, teach_end_s}]}
  concepts   flattened per-concept teach-spans ("teaching passage", not chunk
             stamp or first-mention patch)
  links      prerequisite relations SPOKEN in the lecture ("recall ...",
             "before we can ...", "we use X to build Y") with verbatim
             `evidence`; added to the graph at confidence 0.9, classifier
             fills only the pairs the transcript never grounds.

The transcript is read in sliding windows with a rolling header of already-
covered passages, so a topic that spans a boundary is never split invisibly
and the model always sees the lecture it has already read. One deep read
replaces the scatter of per-concept calls; identical prompts at temperature
0 stay SQLite-cache hits. Pure module — no DB writes; the API layer persists.
"""

from __future__ import annotations

import json
import math
import re
from typing import Dict, List, Optional

from backend.pipeline.llm import complete

# A window keeps the excerpt inside the token budget (~2K tokens input) while
# being large enough for whole multi-minute topics. 25% overlap means a topic
# straddling a boundary is visible in both windows (merge collapses the copy).
WINDOW_CHARS = int(8000)
OVERLAP_FRAC = 0.25
# Output bounds keep each completion small and deterministic.
MAX_PASSAGES = 4
MAX_CONCEPTS_PER_PASSAGE = 6
MAX_LINKS = 8
MAX_TOKENS = 800
_HEADER_BUDGET = 8  # how many prior passage titles the rolling header carries

_KINDS = {"define", "explain", "worked_example", "review", "transition"}

SYSTEM_PROMPT = (
    "You analyze a university lecture transcript and recover its teaching "
    "structure. Transcript lines carry [start-end] timestamps in seconds. "
    "A PASSAGE is a coherent stretch where ONE topic is taught or explained "
    "— the unit a student would re-watch. For every passage report the exact "
    "time span where it is taught, not where it is merely mentioned.\n"
    "Reply with JSON only:\n"
    '{"passages":[{"title":"...","kind":"define|explain|worked_example|'
    'review|transition","start_s":<float>,"end_s":<float>,"summary":"one '
    'sentence",'
    '"continues":<bool>,"concepts":[{"name":"...","implicit":<bool>,'
    '"teach_start_s":<float>,"teach_end_s":<float>}],'
    '"links":[{"from":"...","to":"...","evidence":"verbatim quote"}]}]}\n'
    "Rules:\n"
    "(1) teach spans cover where a concept is EXPLAINED (definition, "
    "motivation, worked example); exclude passing mentions.\n"
    "(2) `implicit` = true when the concept is taught but never named aloud.\n"
    "(3) `links` are prerequisite relations the professor actually VOICES "
    "(\"recall\", \"before we can\", \"we use X to build Y\"); `from` precedes "
    "`to`; give the exact quote as `evidence`; only among concepts in this "
    "excerpt; leave empty when nothing is voiced.\n"
    "(4) a passage ending exactly at the excerpt's end is a `continues:true`\n"
    "(5) bounds: at most %d passages, at most %d concepts per passage, at "
    "most %d links.\n"
    "(6) transitions/welcome are passages with kind \"transition\" and no "
    "concepts.\n"
    "(7) return ONLY the JSON; no markdown, no commentary."
    % (MAX_PASSAGES, MAX_CONCEPTS_PER_PASSAGE, MAX_LINKS)
)


def _seg_fmt(seg) -> str:
    if isinstance(seg, dict):
        return f"[{seg.get('start_s', 0.0):.1f}-{seg.get('end_s', 0.0):.1f}s] {seg.get('text', '')}"
    return f"[{getattr(seg, 'start_s', 0.0):.1f}-{getattr(seg, 'end_s', 0.0):.1f}s] {getattr(seg, 'text', '')}"


def _window_excerpts(docs: List[Dict], window_chars: int, overlap_frac: float) -> List[Dict]:
    """Slide a character-budgeted window across `docs` with time overlap.

    Returns [{"start_s", "end_s", "text"}] windows. Each window covers roughly
    `window_chars` of transcript text; the next window starts so that the tail
    `overlap_frac` of the previous window is re-read (a topic straddling the
    boundary stays visible in both).
    """
    if not docs:
        return []
    excerpts: List[Dict] = []
    i0 = 0
    while i0 < len(docs):
        buf, size = [], 0
        i1 = i0
        for s in docs[i0:]:
            line = _seg_fmt(s)
            if buf and size + len(line) + 1 > window_chars:
                break
            buf.append(s)
            size += len(line) + 1
            i1 += 1
        start = float(docs[i0].get("start_s", 0.0))
        end = float(docs[i1 - 1].get("end_s", 0.0)) if i1 > i0 else start
        excerpts.append({
            "start_s": start,
            "end_s": end,
            "text": "\n".join(_seg_fmt(s) for s in buf),
        })
        if i1 >= len(docs):
            break
        # next window starts after spending (1 - overlap_frac) of the window
        keep_end = start + (end - start) * (1.0 - overlap_frac)
        i0 = next((k for k in range(i1 - 1, -1, -1)
                   if float(docs[k].get("end_s", 0.0)) <= keep_end), i0)
        i0 = max(i0 + 1, i1 - 1)
        if i0 >= len(docs):
            break
    return excerpts


def _prompt(excerpt: Dict, header: List[str]) -> str:
    head = "Earlier in the lecture, these passages were covered:\n" + "\n".join(
        f"- {h}" for h in header
    ) if header else "This is the first excerpt of the lecture."
    return (
        f"{head}\n\n"
        f"Transcript excerpt (timestamps in seconds):\n{excerpt['text']}\n\n"
        "Return the teaching structure of THIS excerpt as JSON.\n"
        '{"passages":[...]}'
    )


def _parse_json(text: str) -> Optional[Dict]:
    """Fence-strip + last-object JSON parse (mirrors mcq_gen._parse_mcq)."""
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text or "", re.DOTALL)
    payload = m.group(1) if m else (text or "")
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(payload[start: end + 1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _parse_passages(text: str, excerpt: Dict) -> List[Dict]:
    """Validate, clamp, and bound one window's answered passages."""
    data = _parse_json(text)
    if not data or not isinstance(data.get("passages"), list):
        return []
    lo, hi = float(excerpt["start_s"]), float(excerpt["end_s"])
    out: List[Dict] = []
    for p in data["passages"][:MAX_PASSAGES]:
        if not isinstance(p, dict) or not p.get("title"):
            continue
        try:
            ps, pe = float(p.get("start_s")), float(p.get("end_s"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(ps) and math.isfinite(pe)) or pe <= ps:
            continue
        ps, pe = _clamp(ps, lo, hi), _clamp(pe, lo, hi)
        if pe <= ps:
            continue
        kind = p.get("kind") if p.get("kind") in _KINDS else "explain"
        concepts = []
        for c in p.get("concepts") or []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            try:
                cs, ce = float(c.get("teach_start_s")), float(c.get("teach_end_s"))
            except (TypeError, ValueError):
                cs = ce = 0.0
            cs, ce = _clamp(cs, ps, pe), _clamp(ce, ps, pe)
            if ce <= cs:
                cs, ce = ps, pe
            concepts.append({
                "name": str(c["name"]).strip(),
                "implicit": bool(c.get("implicit", False)),
                "teach_start_s": round(cs, 1),
                "teach_end_s": round(ce, 1),
            })
        links = []
        for l in (p.get("links") or [])[:MAX_LINKS]:
            if not isinstance(l, dict) or not l.get("from") or not l.get("to"):
                continue
            links.append({
                "from": str(l["from"]).strip(),
                "to": str(l["to"]).strip(),
                "evidence": str(l.get("evidence") or "").strip()[:300],
            })
        out.append({
            "title": str(p["title"]).strip(),
            "kind": kind,
            "start_s": round(ps, 1),
            "end_s": round(pe, 1),
            "summary": str(p.get("summary") or "").strip()[:240],
            "continues": bool(p.get("continues", False)),
            "concepts": concepts[:MAX_CONCEPTS_PER_PASSAGE],
            "links": links,
        })
    return out


def _span_overlap(a, b) -> float:
    """Intersection length of two spans as a fraction of the shorter span."""
    lo = max(a["start_s"], b["start_s"])
    hi = min(a["end_s"], b["end_s"])
    if hi <= lo:
        return 0.0
    return (hi - lo) / max(1e-9, min(a["end_s"] - a["start_s"], b["end_s"] - b["start_s"]))


def _title_sim(a: str, b: str) -> float:
    """Cheap deterministic title similarity (token Jaccard) for merge; the
    full integration additionally uses name-embedding dedup at graph level."""
    ta = {w for w in re.findall(r"\w+", a.lower())}
    tb = {w for w in re.findall(r"\w+", b.lower())}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _join_text(docs: List[Dict], start_s: float, end_s: float) -> str:
    return " ".join(
        (s.get("text") or "").strip()
        for s in docs
        if s.get("start_s", 0) < end_s and s.get("end_s", 0) > start_s
    ).strip()


def _assemble(window_out: List[Dict], docs: List[Dict]) -> Dict:
    """Merge window fragments into one structure: dedupe overlapping passages,
    flatten concepts to teach-spans, dedupe links."""
    merged: List[Dict] = []
    for p in window_out:
        dup = None
        for m in merged:
            if _span_overlap(m, p) > 0.7 or _title_sim(m["title"], p["title"]) >= 0.8:
                dup = m
                break
        if dup is None:
            merged.append(dict(p))
        else:
            dup["end_s"] = max(dup["end_s"], p["end_s"])
            dup["start_s"] = min(dup["start_s"], p["start_s"])
            dup["continues"] = dup["continues"] or p["continues"]
            seen = {c["name"] for c in dup["concepts"]}
            for c in p["concepts"]:
                if c["name"] not in seen:
                    dup["concepts"].append(c)
                    seen.add(c["name"])
            for l in p["links"]:
                if not any(l["from"] == x["from"] and l["to"] == x["to"] for x in dup["links"]):
                    dup["links"].append(l)

    passages: List[Dict] = []
    seen_c: Dict[str, Dict] = {}
    links: List[Dict] = []
    for p in merged:
        idx = len(passages)
        p = dict(p)
        p["concepts"] = [dict(c) for c in p["concepts"]]
        p["text"] = _join_text(docs, p["start_s"], p["end_s"])
        p["concepts"] = [
            {
                "name": c["name"],
                "implicit": c["implicit"],
                "start_s": c["teach_start_s"],
                "end_s": c["teach_end_s"],
                "passage_index": idx,
            }
            for c in p["concepts"]
            if c["name"]
        ]
        for c in p["concepts"]:
            if c["name"] not in seen_c:
                seen_c[c["name"]] = c
        for l in p["links"]:
            if not any(l["from"] == x["from"] and l["to"] == x["to"] for x in links):
                links.append(dict(l))
        passages.append(p)

    return {
        "passages": passages,
        "concepts": list(seen_c.values()),
        "links": links,
    }


def extract_lecture_structure(
    docs: List[Dict],
    completer=None,
    *,
    window_chars: int = WINDOW_CHARS,
    overlap_frac: float = OVERLAP_FRAC,
) -> Dict:
    """One consolidated read of the transcript -> lecture structure.

    Returns {"passages", "concepts", "links"} (see module docstring). One LLM
    call per sliding window (never one per concept). Windows keep rolling
    context of already-covered passages. Never raises: a window that fails to
    parse is skipped (the worker may degrade such a window to coarse spans).
    `completer` has llm.complete's signature and is injected for tests.
    """
    completer = completer or complete
    if not docs:
        return {"passages": [], "concepts": [], "links": []}

    window_out: List[Dict] = []
    prior: List[str] = []
    for excerpt in _window_excerpts(docs, window_chars, overlap_frac):
        try:
            result = completer(
                SYSTEM_PROMPT,
                _prompt(excerpt, prior[-_HEADER_BUDGET:]),
                temperature=0.0,
                max_tokens=MAX_TOKENS,
            )
            parsed = _parse_passages(result.text, excerpt)
        except Exception:
            parsed = []
        window_out.extend(parsed)
        prior.extend(f"{p['title']} [{p['start_s']:.0f}-{p['end_s']:.0f}s]" for p in parsed)

    return _assemble(window_out, docs)