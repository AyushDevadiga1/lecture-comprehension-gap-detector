"""Colour-system tests — ``frontend/theme.py`` and everything it feeds.

Two failures motivated this file, and both are invisible in a code review:

  * panels hardcoded *light* theme values (a ``#ffffff`` card, a ``#64748b``
    caption), so on the app's dark theme the page had a white slab in the middle
    of it with grey-on-grey text;
  * node labels were picked by eye. The RGB-lerp ramp once failed at 2.6:1.

So the properties are pinned here rather than the specific hex values:

  * every text token clears WCAG AA (4.5:1) on every surface it can land on, in
    both themes - a token is a *meaning*, and a panel may put it on any surface;
  * a node's ink is legible on that node's fill, for every rank and every hashed
    identity hue, in both themes - the guarantee the ramp has to keep;
  * the palette and the theme the app actually declares cannot drift apart;
  * and no module outside ``theme.py`` may name a colour, so this cannot rot back
    into a hundred hardcoded hexes.
"""

import re
from pathlib import Path

import pytest

from frontend import layout, render, theme

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"

#: Tokens that render *text*, so WCAG AA (4.5:1) applies.
TEXT_TOKENS = ("text", "muted", "ok", "warn", "bad", "info", "accent")
#: Surfaces any of those tokens can be painted on.
SURFACES = ("page", "surface", "surface_alt", "graph_bg")
#: Non-text marks: WCAG 1.4.11 asks 3:1 for a graphic that carries meaning.
STRUCTURAL = ("tick", "graph_edge", "covered")
DECORATIVE = ("border", "track")

AA_TEXT = 4.5
AA_NON_TEXT = 3.0

# A colour literal: #abc / #aabbcc, but not the &amp; of an HTML entity.
_HEX = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b")
_SKIP_FILES = {"theme.py"}


# ------------------------------------------------------------------ the maths

@pytest.mark.parametrize("pair,expected", [
    (("#000000", "#ffffff"), 21.0),
    (("#ffffff", "#ffffff"), 1.0),
])
def test_contrast_ratio_anchors(pair, expected):
    assert theme.contrast_ratio(*pair) == pytest.approx(expected, abs=0.01)


def test_contrast_is_order_independent():
    assert theme.contrast_ratio("#e6edf3", "#0e1117") == pytest.approx(
        theme.contrast_ratio("#0e1117", "#e6edf3"))


@pytest.mark.parametrize("bad", ["nope", "#12345", "", "#gggggg"])
def test_a_non_colour_is_rejected(bad):
    with pytest.raises(ValueError):
        theme.luminance(bad)


def test_shorthand_hex_is_accepted():
    assert theme.luminance("#fff") == pytest.approx(theme.luminance("#ffffff"))


# ---------------------------------------------------------------- the tokens

@pytest.mark.parametrize("base", ["dark", "light"])
@pytest.mark.parametrize("token", TEXT_TOKENS)
@pytest.mark.parametrize("surface", SURFACES)
def test_every_text_token_clears_aa_on_every_surface(base, token, surface):
    """A panel may put a token on any surface, so the pairing is the invariant.

    This is the check that would have failed on the old palette: `#64748b`
    muted grey was 4.4:1 on a white card and 2.6:1 once the page went dark.
    """
    pal = theme.palette(base)
    ratio = theme.contrast_ratio(getattr(pal, token), getattr(pal, surface))
    assert ratio >= AA_TEXT, (
        f"{base}: {token} {getattr(pal, token)} on {surface} "
        f"{getattr(pal, surface)} = {ratio:.2f}:1 (need {AA_TEXT})")


@pytest.mark.parametrize("base", ["dark", "light"])
@pytest.mark.parametrize("token", STRUCTURAL)
def test_meaningful_marks_clear_the_non_text_floor(base, token):
    """Timeline ticks, graph edges and the covered/uncovered split carry meaning
    on their own, so they need 3:1 - not "it looks fine"."""
    pal = theme.palette(base)
    for surface in SURFACES:
        ratio = theme.contrast_ratio(getattr(pal, token), getattr(pal, surface))
        assert ratio >= AA_NON_TEXT, f"{base}: {token} on {surface} = {ratio:.2f}:1"

@pytest.mark.parametrize("base", ["dark", "light"])
@pytest.mark.parametrize("token", DECORATIVE)
def test_decorative_marks_are_at_least_visible(base, token):
    """A card border and the empty part of the timeline bar only have to be
    discernible from what is behind them, not AA-legible."""
    pal = theme.palette(base)
    for surface in SURFACES:
        ratio = theme.contrast_ratio(getattr(pal, token), getattr(pal, surface))
        assert ratio >= 1.1, f"{base}: {token} on {surface} = {ratio:.2f}:1"


@pytest.mark.parametrize("base,pred", [("dark", lambda l: l < 0.05),
                                       ("light", lambda l: l > 0.9)])
def test_each_palette_is_actually_the_theme_it_claims(base, pred):
    """The point of the exercise: a "dark theme" whose page is near-white is the
    exact bug this module exists to prevent."""
    lum = theme.luminance(theme.palette(base).page)
    assert pred(lum), f"{base} page luminance is {lum:.3f}"


def test_surfaces_step_up_in_lightness_on_both_themes():
    """A card must read as a card, so its surface is distinguishable from the
    page it sits on."""
    for base in ("dark", "light"):
        pal = theme.palette(base)
        assert pal.surface != pal.page
        assert pal.graph_bg in (pal.surface, pal.page)


def test_an_unknown_theme_base_falls_back_instead_of_raising():
    """A renderer must never fail because a theme is unknown."""
    assert theme.palette("solarized-lagoon") is theme.palette(theme.DEFAULT_BASE)
    assert theme.palette(None) is theme.palette(theme.DEFAULT_BASE)
    assert theme.palette("dark.sidebar") is theme.palette("dark")


# ---------------------------------------------------------------- the ink

@pytest.mark.parametrize("base", ["dark", "light"])
def test_readable_on_is_legible_on_every_hue_of_the_ramp(base):
    """The guarantee behind "the font is always complementary to its bg".

    A sweep over the whole hue circle at the palette's own node saturation and
    lightness - the only fills the app can actually produce. ``readable_on``
    compares the two ink candidates and returns the better, so this is a
    property of the code rather than of the current hue choices.
    """
    pal = theme.palette(base)
    worst = 99.0
    for step in range(72):
        hue = step / 72
        fill = theme.node_fill(hue, base=base)
        ratio = theme.contrast_ratio(theme.readable_on(fill, base=base), fill)
        worst = min(worst, ratio)
    assert worst >= AA_TEXT, f"{base}: worst node ink {worst:.2f}:1"


def test_readable_on_flips_with_the_background():
    """A dark fill must get light ink and a light fill dark ink - that flip is
    the whole mechanism, so pin both directions rather than only the outcome."""
    assert theme.luminance(theme.readable_on("#0b1220", base="dark")) > 0.5
    assert theme.luminance(theme.readable_on("#f6f8fa", base="dark")) < 0.5


@pytest.mark.parametrize("base", ["dark", "light"])
@pytest.mark.parametrize("mode", ["order", "identity"])
def test_rendered_node_labels_clear_aa(base, mode):
    """End to end through the renderer, including the hashed identity hues -
    the labels a professor actually reads."""
    for rank in range(8):
        fill, ink = render.node_colors("Conditional Expectation", rank, 8,
                                       mode=mode, base=base)
        assert fill != ink
        ratio = theme.contrast_ratio(ink, fill)
        assert ratio >= AA_TEXT, f"{base}/{mode} rank {rank}: {fill}/{ink} {ratio:.2f}:1"


@pytest.mark.parametrize("base", ["dark", "light"])
def test_a_node_is_distinguishable_from_the_canvas_behind_it(base):
    """Legible text is not enough: the block itself has to read as a node."""
    pal = theme.palette(base)
    for step in range(24):
        fill = theme.node_fill(step / 24, base=base)
        assert theme.contrast_ratio(fill, pal.graph_bg) >= 1.3


@pytest.mark.parametrize("base", ["dark", "light"])
def test_node_identity_is_stable_per_name(base):
    """Re-hashing per render would recolour the graph on every rerun."""
    assert (render.node_colors("Covariance", base=base)
            == render.node_colors("Covariance", base=base))


# ------------------------------------------------- the theme the app declares

def _declared_theme():
    """Parse [theme] out of .streamlit/config.toml (no toml dependency needed).

    Comments are stripped on a space-then-``#`` boundary only: a colour value
    *starts* with ``#``, so the naive "cut at the first hash" would swallow
    ``backgroundColor = "#0e1117"`` and this test would then compare against an
    empty string - i.e. pass for the wrong reason, or fail confusingly.
    """
    text = (FRONTEND.parent / ".streamlit" / "config.toml").read_text(
        encoding="utf-8")
    section = {}
    in_theme = False
    for line in text.splitlines():
        line = re.split(r"\s#", line, 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            in_theme = line == "[theme]"
            continue
        if in_theme and "=" in line:
            k, v = (part.strip() for part in line.split("=", 1))
            section[k] = v.strip('"')
    return section


def test_the_declared_theme_matches_the_palette():
    """The palette is only correct against the page it lands on, so the two must
    not be able to drift: change one without the other and this fails."""
    declared = _declared_theme()
    pal = theme.palette(declared["base"])
    assert declared["backgroundColor"].lower() == pal.page
    assert declared["secondaryBackgroundColor"].lower() == pal.surface
    assert declared["textColor"].lower() == pal.text
    assert declared["primaryColor"].lower() == pal.accent


def test_the_shipped_default_is_the_declared_theme():
    declared = _declared_theme()
    assert declared["base"] == theme.DEFAULT_BASE
    assert theme.palette() is theme.palette(declared["base"])


def test_current_base_reads_the_config_rather_than_guessing(monkeypatch):
    """No Streamlit runtime -> the shipped default, never an exception."""
    import streamlit as st

    monkeypatch.setattr(st, "get_option", lambda *_a, **_k: None)
    assert theme.current_base() == theme.DEFAULT_BASE
    monkeypatch.setattr(st, "get_option", lambda *_a, **_k: "light")
    assert theme.current_base() == "light"
    monkeypatch.setattr(st, "get_option", lambda *_a, **_k: "dark.sidebar")
    assert theme.current_base() == "dark"

    def _boom(*_a, **_k):
        raise RuntimeError("no runtime")

    monkeypatch.setattr(st, "get_option", _boom)
    assert theme.current_base() == theme.DEFAULT_BASE


# ------------------------------------------- nothing else may name a colour

@pytest.mark.parametrize("path", sorted(
    p for p in FRONTEND.rglob("*.py") if p.name not in _SKIP_FILES),
    ids=lambda p: p.name)
def test_no_module_outside_theme_hardcodes_a_colour(path):
    """The single-source rule, enforced.

    Every panel used to carry its own hex; a scanner is the only thing that
    stops a dozen new ones appearing the next time someone adds a panel.
    """
    found = []
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        for match in _HEX.finditer(line):
            found.append(f"{path.name}:{lineno} {match.group()} in {line.strip()}")
    assert not found, "colours belong in frontend/theme.py:\n" + "\n".join(found)


# ------------------------------------------------- the panels inherit it

@pytest.mark.parametrize("base", ["dark", "light"])
def test_a_card_is_themed_not_white(base):
    """The single worst artefact this replaces: a hardcoded white card with a
    light border, rendered as a slab in the middle of the dark page."""
    pal = theme.palette(base)
    html = layout.panel("hello", base=base)
    assert f"background:{pal.surface}" in html
    assert f"border:1px solid {pal.border}" in html
    assert f"color:{pal.text}" in html
    assert "#ffffff" not in html.lower() or base == "light"


@pytest.mark.parametrize("base", ["dark", "light"])
def test_the_scroll_box_and_definition_list_are_themed(base):
    pal = theme.palette(base)
    box = layout.scroll_box("x", base=base)
    assert f"background:{pal.surface}" in box
    rows = layout.definition_list([(0, "Bias term")], base=base)
    assert f"color:{pal.muted}" in rows
    assert f"color:{pal.text}" in rows


@pytest.mark.parametrize("base", ["dark", "light"])
def test_the_timeline_is_themed(base):
    pal = theme.palette(base)
    out = render.lecture_html(
        [{"idx": 0, "start_s": 0.0, "end_s": 10.0, "text": "hello world"}],
        [{"name": "Bias", "start_s": 1.0, "end_s": 4.0}],
        "Lecture 1", base=base)
    assert f"color:{pal.text}" in out
    assert f"fill=\"{pal.track}\"" in out
    assert f"fill=\"{pal.tick}\"" in out
    assert f"fill=\"{pal.covered}\"" in out
    assert f"color:{pal.muted}" in out


def test_a_timeline_band_label_is_legible_on_its_own_band():
    """The band is coloured by learner order, so its label cannot use a fixed
    ink - it has to be measured against the band it landed on."""
    out = render.lecture_html(
        [{"idx": 0, "start_s": 0.0, "end_s": 20.0, "text": "x"}],
        [{"name": f"Concept {i}", "start_s": float(i), "end_s": float(i) + 1}
         for i in range(8)],
        "L", base="dark")
    for match in re.finditer(r'rx="3" fill="(#[0-9a-f]{6})"><title>[^<]*</title>'
                             r'</rect><text[^>]*fill="(#[0-9a-f]{6})"', out):
        fill, ink = match.group(1), match.group(2)
        assert theme.contrast_ratio(ink, fill) >= AA_TEXT, f"{ink} on {fill}"


@pytest.mark.parametrize("base", ["dark", "light"])
def test_the_dag_canvas_is_themed(base):
    pal = theme.palette(base)
    graph = {
        "nodes": ["Bias", "Gradient descent"],
        "edges": [{"source": "Bias", "target": "Gradient descent",
                   "confidence": 0.9}],
        "is_dag": True, "node_count": 2, "edge_count": 1,
        "topological_order": ["Bias", "Gradient descent"],
    }
    out = render.dag_svg(graph, base=base)
    assert f'fill="{pal.graph_bg}"' in out
    assert f"background:{pal.graph_bg}" in out
    assert f'stroke="{pal.graph_edge}"' in out
    assert f"color:{pal.text}" in out


@pytest.mark.parametrize("base", ["dark", "light"])
def test_the_dag_notice_uses_a_status_token(base):
    """The 'no links of this type' notice is a warning, so it takes ``warn``."""
    graph = {
        "nodes": ["A", "B", "C"],
        "edges": [{"source": "A", "target": "B", "confidence": 0.9,
                   "source_method": "classifier"}],
        "is_dag": True, "node_count": 3, "edge_count": 1,
        "topological_order": ["A", "B", "C"],
    }
    out = render.dag_svg(graph, methods=["transcript"], base=base)
    assert f"color:{theme.palette(base).warn}" in out
    assert "No links of the selected type" in out


def test_a_graph_with_no_nodes_still_renders_in_theme_colour():
    out = render.dag_svg({"nodes": []}, base="dark")
    pal = theme.palette("dark")
    assert f"color:{pal.text}" in out
    assert f"background:{pal.graph_bg}" in out
