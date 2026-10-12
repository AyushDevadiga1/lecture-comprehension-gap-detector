# 05 · Shared layout primitives — `frontend/layout.py`

**File:** `frontend/layout.py` (89 lines). The one place containment and card
styling live. Kept Streamlit-free where possible: the helpers that emit raw
HTML take strings, so they are unit-testable without a runtime.

## The runaway-page rule

Every long, wide, or unbounded block (clip lists, the learner-order sequence,
quiz feedback, the graph) goes through `scroll_box`, so a large result scrolls
**inside its own frame** instead of stretching the page and forcing the reader
to scroll forever. Centralising it means a new panel cannot reintroduce the
runaway-page problem by forgetting a wrapper.

## Primitives

- `scroll_box(inner_html, max_height=420, …)` — fixed-height (min 120 px),
  internally scrolling card. Colours from the palette, never literals (these
  helpers used to hardcode a white card and light border — the white-slab bug
  from file 04).
- `panel(inner_html, max_height=0, …)` — a bordered card, scroll-contained when
  a height is given.
- `definition_list(pairs, …)` — compact two-column key/value list (e.g. the
  learner-order study sequence): numbered muted index + text, hairline
  dividers.
- `video_box(url, height=240)` — one clip player in a fixed-height frame.
  Streamlit's `st.video` renders full-width with aspect-dependent page height;
  the bounded column keeps long clip lists navigable, and the frame matches the
  page surface so a player never sits in a light rectangle on a dark page.
- `escape(value)` — HTML-escape any value for panel markup.
- `_card_style(pal)` — the single card/border/background/padding definition
  every card shares, so the UI reads as one system.

## The escaping contract

`scroll_box` takes **trusted markup**; the caller is responsible for escaping
user data with `escape`. Panels follow this throughout (concept names, titles,
feedback text are all escaped at the HTML boundary).
