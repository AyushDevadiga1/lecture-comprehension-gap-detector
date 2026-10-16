"""One colour system for the whole frontend.

Why this module exists
----------------------
Every panel used to hardcode its own hex values: a ``#ffffff`` card, a
``#e2e8f0`` border, a ``#64748b`` caption, an ``#b45309`` warning. Those are all
*light* theme values, so on the app's dark theme the result was a white slab in
the middle of a black page with grey-on-grey text on it - and every one of those
pairs was chosen without ever being checked.

Two rules replace that:

  1. **Colours live here, once, as semantic tokens** (``text``, ``muted``,
     ``border``, ``surface``, ``warn``, ...). Panels ask for a *meaning*, never a
     colour, so flipping the theme is a one-line change here.
  2. **A foreground is never chosen by eye.** :func:`readable_on` returns the
     blacker-or-whiter of two candidates by measured WCAG contrast, which is
     what makes "the font is always complementary to its background" a property
     of the code rather than a hope: for *any* background, the more extreme of
     the two candidates is at least ~4.6:1, and ``tests/test_theme.py`` pins the
     exact floor for every token against every surface it can appear on.

The palette follows the theme the app declares in ``.streamlit/config.toml``
(``base = "dark"``), so the values below and the real page background are the
same thing. Nothing here imports Streamlit at module level, so the colour maths
stays unit-testable; :func:`current_base` is the only part that talks to a
running app.
"""

import colorsys

DARK = "dark"
LIGHT = "light"

# WCAG 2.1 relative-luminance sRGB constants.
_C = (0.2126, 0.7152, 0.0722)


# --------------------------------------------------------------------- maths

def _channels(hex_colour: str):
    """``(r, g, b)`` in 0..1 from ``#rgb`` / ``#rrggbb``."""
    text = str(hex_colour).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"not a hex colour: {hex_colour!r}")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _linearise(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    """WCAG relative luminance (0 = black, 1 = white)."""
    r, g, b = (_linearise(c) for c in _channels(hex_colour))
    return _C[0] * r + _C[1] * g + _C[2] * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio, 1:1 .. 21:1. Order-independent."""
    a, b = luminance(foreground), luminance(background)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def hsl(h: float, s: float, light: float) -> str:
    """``h`` in 0..1 turns, ``s``/``light`` in 0..1 -> ``#rrggbb``."""
    r, g, b = colorsys.hls_to_rgb(h % 1.0, light, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


# ----------------------------------------------------------------- palettes

class Palette:
    """Semantic colour tokens for one theme base.

    Attribute names are the *meaning* a panel asks for, never a hue, so no panel
    has to know whether "a missing clip file" is amber on light or amber on dark.
    """

    __slots__ = ("base", "page", "surface", "surface_alt", "border", "text",
                 "muted", "ok", "warn", "bad", "info", "accent", "graph_bg",
                 "graph_edge", "track", "tick", "covered", "ink_light",
                 "ink_dark", "node_light", "node_sat")

    def __init__(self, base, **kw):
        self.base = base
        for name in self.__slots__[1:]:
            setattr(self, name, kw[name])

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__slots__}


# Dark: the app's declared theme. Surfaces step up in lightness so a card reads
# as a card; text steps down from near-white, and every value is contrast-checked
# in tests/test_theme.py rather than eyeballed.
#
# The brand palette is frontend-react/references/color_scheme.txt — a *light*
# scheme — so the dark base is its espresso counterpart: deepEspresso (#2c2520)
# is the card surface, the page steps down to a near-black warm brown, `text`
# is the alabaster inverted, and info/accent sit on deepSeaTeal's hue (~174°)
# lightened until it clears AA on the darkest surface it can land on.
# ink_light/ink_dark and node_light/node_sat are unchanged: the golden node
# tables in frontend-react/src/theme/theme.test.ts were measured from this
# module with exactly these four values.
_DARK = Palette(
    DARK,
    page="#15110d",          # matches [theme] backgroundColor
    surface="#2c2520",       # deepEspresso — cards, scroll boxes
    surface_alt="#362e26",   # table header stripe, hover/secondary bands
    border="#453b31",
    text="#f6f1e9",
    muted="#a99e91",
    ok="#57d364",
    warn="#e3b341",
    bad="#ff7b72",           # #f85149 failed AA on the warmer surface_alt
    info="#14b8a6",
    accent="#14b8a6",
    graph_bg="#15110d",      # the page: a recessed canvas inside an espresso card
    graph_edge="#8f8577",
    track="#453b31",         # the "not covered" part of the timeline
    tick="#857b6e",
    covered="#2ea043",       # concept-covered spans on the timeline
    ink_light="#f6f8fb",     # the two ink candidates a node may get
    ink_dark="#0a0e14",
    # A node is a dark tinted block, not a light slab. 0.28 is not arbitrary: it
    # is the lightest value that still keeps the block itself visible against the
    # canvas (1.32:1) while every hue clears 5.7:1 against its own label. Darker
    # hides the node, lighter costs label legibility.
    node_light=0.28,
    node_sat=0.42,
)

# Light: the same tokens for base = "light" — the theme the reference palette
# (frontend-react/references/color_scheme.txt) actually describes. Four of its
# six values land verbatim: warmAlabaster page, pureCream surface, tealLight
# bands, deepEspresso text, deepSeaTeal accent. sandDrift (#eae3d8) is the one
# value used as a *source* rather than a literal: as border/track it sits only
# 1.08:1 against surface_alt, just under the 1.1:1 decorative floor these tests
# enforce, so it is darkened 6% to #dcd5cb (1.24:1).
#
# The status hues are a step darker than their usual web values precisely because
# they have to clear 4.5:1 on the *darkest* surface they can land on
# (surface_alt), not just on white: the usual #1a7f37 / #9a6700 / #0969da sit at
# 4.2-4.5:1 there.
_LIGHT = Palette(
    LIGHT,
    page="#faf7f2",          # warmAlabaster
    surface="#ffffff",       # pureCream
    surface_alt="#e2efef",   # tealLight: table headers, hover bands
    border="#dcd5cb",        # sandDrift darkened 6% (see above)
    text="#2c2520",          # deepEspresso
    muted="#6e6459",
    ok="#16642c",
    warn="#8a5b00",
    bad="#c0212a",
    info="#0f766e",          # deepSeaTeal
    accent="#0f766e",        # deepSeaTeal
    graph_bg="#ffffff",
    graph_edge="#7a7167",
    track="#dcd5cb",
    tick="#6f675d",
    covered="#1a7f37",
    ink_light="#ffffff",
    ink_dark="#0b1220",
    node_light=0.74,
    node_sat=0.46,
)

_PALETTES = {DARK: _DARK, LIGHT: _LIGHT}

#: The base the app ships with, also declared in .streamlit/config.toml.
DEFAULT_BASE = DARK


def palette(base: str = None) -> Palette:
    """Tokens for a theme base. Unknown/missing bases fall back to dark."""
    if base is None:
        return _PALETTES[DEFAULT_BASE]
    return _PALETTES.get(str(base).lower().split(".")[0], _PALETTES[DEFAULT_BASE])


def current_base() -> str:
    """The theme the running app is actually using.

    Reads ``[theme] base`` from ``.streamlit/config.toml`` through Streamlit's own
    config so there is exactly one place that decides dark vs light. Outside a
    Streamlit run (unit tests, the pure renderers) it returns the shipped default
    instead of raising - a renderer must never fail because a theme is unknown.
    """
    try:
        import streamlit as st

        base = st.get_option("theme.base")
    except Exception:  # noqa: BLE001 - no runtime, or no such option
        base = None
    if not base:
        return DEFAULT_BASE
    return str(base).lower().split(".")[0]


def current() -> Palette:
    """Tokens for the theme the app is actually rendering."""
    return palette(current_base())


# ------------------------------------------------------------- ink selection

def readable_on(background: str, base: str = None) -> str:
    """The ink to put *on* ``background`` - the point of this whole module.

    Picks whichever of the palette's two ink candidates measures better against
    the background, so a node label, a badge or a filled chip is legible whatever
    colour it landed on. Because the candidates sit near the two ends of the
    luminance range, the better of the two is always at least ~4.6:1 - the
    property ``tests/test_theme.py`` pins.
    """
    pal = palette(base if base is not None else current_base())
    light, dark = pal.ink_light, pal.ink_dark
    if contrast_ratio(light, background) >= contrast_ratio(dark, background):
        return light
    return dark


def node_fill(hue: float, base: str = None, sat: float = None) -> str:
    """A node's fill for a hue, at the lightness the current theme wants."""
    pal = palette(base if base is not None else current_base())
    return hsl(hue, pal.node_sat if sat is None else sat, pal.node_light)


def node_pair(hue: float, base: str = None, sat: float = None):
    """``(fill, ink)`` for a node: a themed fill plus a measured-legible ink."""
    fill = node_fill(hue, base=base, sat=sat)
    return fill, readable_on(fill, base=base if base is not None else current_base())
