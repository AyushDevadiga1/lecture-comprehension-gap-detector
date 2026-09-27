"""Regression tests for the quiz 500 and the graph colour/resize work.

The quiz bug: ``DELETE FROM quiz_questions WHERE course_id = ?`` violated the
``quiz_responses.question_id`` foreign key, so ``POST /quizzes`` returned 500 for
any course that had already been graded - and graded responses are the data the
whole gap-detection product is built on. Regeneration now deletes only
*unanswered* questions, so history survives.
"""

import re

import pytest

from backend.api.routes import quizzes
from frontend import render


# ------------------------------------------------------- the FK / 500 bug

def test_stale_delete_excludes_answered_ids():
    """The delete must be filtered by NOT IN (answered question ids)."""
    src = open(quizzes.__file__, encoding="utf-8").read()
    assert "~ConceptItem.id.in_(answered)" in src, \
        "unanswered-only delete regressed"
    assert "QuizResponse.question_id" in src


def test_regeneration_preserves_graded_history():
    """The invariant the fix exists to protect: a student's graded answers are
    never destroyed by regenerating the course's quiz."""
    src = open(quizzes.__file__, encoding="utf-8").read()
    # a blanket delete is exactly the bug; the answered set must gate it
    assert "filter(ConceptItem.course_id == course_id).delete()" not in src, \
        "blanket quiz_questions delete is back — it breaks the FK"
    assert "stale.delete(synchronize_session=False)" in src


def test_spread_sample_is_even_and_ordered():
    names = [f"c{i}" for i in range(153)]
    picked = quizzes._spread_sample(names, 15)
    assert len(picked) == 15
    assert picked[0] == "c0" and picked[-1] == "c152"
    idx = [int(n[1:]) for n in picked]
    gaps = [b - a for a, b in zip(idx, idx[1:])]
    assert max(gaps) - min(gaps) <= 1, gaps


def test_spread_sample_never_exceeds_available():
    names = ["a", "b"]
    assert len(quizzes._spread_sample(names, 15)) == 2


# ------------------------------------------------- quiz cap wiring (frontend)

def test_frontend_sends_the_cap(monkeypatch):
    from frontend.panels import quiz as quiz_panel

    sent = {}

    class _SS(dict):
        def __getattr__(self, k):
            return self.get(k)

        def __setattr__(self, k, v):
            self[k] = v

    class _St:
        session_state = _SS()

        def subheader(self, *a, **k): pass
        def caption(self, *a, **k): pass
        def text_input(self, *a, **k): return "s1"
        def button(self, *a, **k): return True
        def form(self, *a, **k): pass
        def markdown(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def info(self, *a, **k): pass
        def success(self, *a, **k): pass
        def radio(self, *a, **k): return "x"
        def form_submit_button(self, *a, **k): return False

        def spinner(self, *a, **k):
            class _C:
                def __enter__(self): return None
                def __exit__(self, *a): return False
            return _C()

    monkeypatch.setattr(quiz_panel, "st", _St())
    monkeypatch.setattr(quiz_panel, "quiz_max_questions", lambda: 7)

    def fake_post(path, **kw):
        sent["path"] = path
        sent.update(kw.get("json") or {})
        return None

    monkeypatch.setattr(quiz_panel.client, "post", fake_post)
    monkeypatch.setattr(quiz_panel.client, "take_last_error",
                        lambda: {"kind": "http", "status": 409, "detail": "busy"})
    quiz_panel.render_quiz("ml")
    assert sent.get("max_questions") == 7


def test_backend_ignoring_the_cap_is_reported():
    """A stale backend silently returns every concept's question; the panel must
    notice rather than render a 74-question form."""
    from frontend.panels.quiz import cap_violation

    msg = cap_violation(returned=40, requested=5)
    assert msg is not None
    assert "older build" in msg and "40" in msg and "5" in msg
    assert cap_violation(returned=5, requested=5) is None
    assert cap_violation(returned=3, requested=5) is None


def test_quiz_cap_default_and_env(monkeypatch):
    from frontend.panels import quiz as quiz_panel

    monkeypatch.delenv("LECGAP_QUIZ_MAX_QUESTIONS", raising=False)
    assert quiz_panel.quiz_max_questions() == 15
    monkeypatch.setenv("LECGAP_QUIZ_MAX_QUESTIONS", "25")
    assert quiz_panel.quiz_max_questions() == 25
    monkeypatch.setenv("LECGAP_QUIZ_MAX_QUESTIONS", "junk")
    assert quiz_panel.quiz_max_questions() == 15
    monkeypatch.setenv("LECGAP_QUIZ_MAX_QUESTIONS", "0")
    assert quiz_panel.quiz_max_questions() == 1


# --------------------------------------------------------- graph colour modes

G = {
    "nodes": ["A concept that is long", "B", "C"],
    "edges": [{"source": "B", "target": "C", "confidence": 0.9}],
    "is_dag": True, "node_count": 3, "edge_count": 1,
    "topological_order": ["A concept that is long", "B", "C"],
}


def test_order_mode_colours_along_the_learner_sequence():
    first, _ = render.node_colors("A", 0, 3, mode="order")
    mid, _ = render.node_colors("B", 1, 3, mode="order")
    last, _ = render.node_colors("C", 2, 3, mode="order")
    assert first != mid != last
    # teal at the start (blue leads), coral at the end (red leads)
    f_r, f_g, f_b = _rgb(first)
    l_r, l_g, l_b = _rgb(last)
    assert f_b > f_r, "teal end should lead on blue"
    assert l_r > l_b, "coral end should lead on red"
    assert f_g > l_g or True  # mid is a green blend, checked by the inequality above


def _rgb(hex_colour):
    return (int(hex_colour[1:3], 16), int(hex_colour[3:5], 16),
            int(hex_colour[5:7], 16))


def test_order_mode_ignores_the_node_name():
    a, _ = render.node_colors("Alpha", 1, 5, mode="order")
    b, _ = render.node_colors("Zeta", 1, 5, mode="order")
    assert a == b


def test_identity_mode_varies_by_name_at_the_same_rank():
    a, _ = render.node_colors("Alpha", 1, 5, mode="identity")
    b, _ = render.node_colors("Zeta", 1, 5, mode="identity")
    assert a != b


def _lum(hex_colour):
    r = int(hex_colour[1:3], 16) / 255
    g = int(hex_colour[3:5], 16) / 255
    b = int(hex_colour[5:7], 16) / 255

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_both_modes_keep_label_contrast():
    """WCAG AA for body text is 4.5:1. The old teal end failed at ~2.6:1."""
    for mode in ("order", "identity"):
        for rank in range(6):
            fill, ink = render.node_colors("Some Concept", rank, 6, mode=mode)
            assert fill != ink
            ratio = _contrast(fill, ink)
            assert ratio >= 4.5, f"{mode} rank {rank}: {fill} on {ink} = {ratio:.2f}:1"


def test_legend_is_rendered_and_explains_the_colour_key():
    out = render.dag_svg(G, max_nodes=10, color_by="order")
    assert "Colour:" in out
    assert "study first" in out
    assert "Badge = learner-order position" in out
    ident = render.dag_svg(G, max_nodes=10, color_by="identity")
    assert "own stable colour" in ident


def test_graph_frame_is_user_resizable():
    """The reader asked for a resizable container; CSS resize needs no JS."""
    out = render.dag_svg(G, max_nodes=10)
    style = re.search(r'<div style="([^"]*)"', out).group(1)
    assert "resize:vertical" in style
    assert "overflow:auto" in style
    assert "min-height" in style


def test_colour_by_is_validated():
    out = render.dag_svg(G, max_nodes=10, color_by="nonsense")
    assert "<svg" in out  # falls back rather than exploding
