"""Shared layout primitives — the one place containment and card styling live.

Every long, wide, or unbounded block in the app (clip lists, the learner-order
sequence, quiz feedback, the graph) goes through :func:`scroll_box` so a large
result scrolls inside its own frame instead of stretching the page and forcing
the reader to scroll forever. Centralising it means a new panel cannot
reintroduce the runaway-page problem by forgetting a wrapper.

Colours come from :mod:`frontend.theme` - never from a literal here. These
helpers used to hardcode a white card and a light border, which on the app's dark
theme rendered as a white slab with grey text on it.

Kept Streamlit-free where possible: the helpers that emit raw HTML take strings,
so they are unit-testable without a Streamlit runtime.
"""

import html as _html

from frontend import theme


def _card_style(pal) -> str:
    """One card/border/background, shared so every card looks like one system."""
    return (f"border:1px solid {pal.border};border-radius:10px;"
            f"background:{pal.surface};color:{pal.text};"
            f"padding:10px 12px;margin:4px 0")


def scroll_box(inner_html: str, max_height: int = 420, extra_style: str = "",
               base: str = None) -> str:
    """Wrap already-escaped HTML in a fixed-height, internally scrolling box.

    ``inner_html`` is trusted markup (the caller is responsible for escaping any
    user data). Use :func:`escape` for that.
    """
    h = max(120, int(max_height))
    pal = theme.palette(base)
    style = (f"max-height:{h}px;overflow:auto;{_card_style(pal)}")
    if extra_style:
        style = f"{style};{extra_style}"
    return f'<div style="{style}">{inner_html}</div>'


def escape(value) -> str:
    """HTML-escape any value for embedding in panel markup."""
    return _html.escape(str(value))


def panel(inner_html: str, max_height: int = 0, extra_style: str = "",
          base: str = None) -> str:
    """A bordered card, optionally scroll-contained."""
    if max_height:
        return scroll_box(inner_html, max_height, extra_style, base=base)
    style = _card_style(theme.palette(base))
    if extra_style:
        style = f"{style};{extra_style}"
    return f'<div style="{style}">{inner_html}</div>'


def definition_list(pairs, max_height: int = 0, base: str = None) -> str:
    """A compact two-column key/value list, e.g. the learner-order sequence."""
    pal = theme.palette(base)
    rows = []
    for i, (k, v) in enumerate(pairs, 1):
        rows.append(
            f'<div style="display:flex;gap:10px;padding:2px 0;'
            f'border-bottom:1px solid {pal.border}">'
            f'<span style="min-width:34px;font-weight:700;color:{pal.muted}">{i}</span>'
            f'<span style="color:{pal.text}">{escape(v)}</span></div>'
        )
    return panel("".join(rows), max_height=max_height, base=base)


def video_box(url: str, height: int = 240, base: str = None) -> str:
    """A single clip player in a fixed-height frame.

    Streamlit's ``st.video`` renders a full-width player whose page height
    depends on the aspect ratio; wrapping the players in a bounded column keeps
    a long clip list navigable. The frame matches the page surface so a player
    does not sit in a light rectangle on a dark page.
    """
    pal = theme.palette(base)
    return (
        f'<div style="max-height:{int(height)}px;overflow:hidden;'
        f'border:1px solid {pal.border};border-radius:8px;margin:4px 0;'
        f'background:{pal.page}">'
        f'<video controls preload="metadata" style="width:100%;height:100%;'
        f'display:block" src="{escape(url)}"></video></div>'
    )
