# 04 · One colour system — `frontend/theme.py`

**File:** `frontend/theme.py` (222 lines). **No Streamlit imports at module
level**, so the colour maths stays unit-testable; `current_base()` is the only
part that talks to a running app.

## Why it exists

Every panel used to hardcode its own hex values: a `#ffffff` card, a `#e2e8f0`
border, a `#64748b` caption. Those are *light*-theme values, so on the app's
dark theme the result was a white slab in the middle of a black page with
grey-on-grey text — and none of those pairs was ever contrast-checked.

Two rules replace that:

1. **Colours live here, once, as semantic tokens** (`text`, `muted`, `border`,
   `surface`, `warn`, …). Panels ask for a *meaning*, never a colour, so
   flipping the theme is a one-line change.
2. **A foreground is never chosen by eye.** `readable_on()` returns the
   blacker-or-whiter of two candidates by measured WCAG contrast, which makes
   "the font is always complementary to its background" a property of the code:
   for any background, the more extreme of the two candidates is at least
   ~4.6:1, and `tests/test_theme.py` pins the exact floor for every token
   against every surface it can appear on.

## The tokens

One `Palette` per base with 21 slots: `base, page, surface, surface_alt,
border, text, muted, ok, warn, bad, info, accent, graph_bg, graph_edge, track,
tick, covered, ink_light, ink_dark`, plus `node_light` / `node_sat` (HSL
lightness/saturation for node fills).

Key values (verified in source):

| Token | Dark | Light |
|---|---|---|
| `page` | `#0e1117` (matches `[theme] backgroundColor`) | `#ffffff` |
| `surface` | `#161b22` | `#f6f8fa` |
| `text` / `muted` | `#e6edf3` / `#9aa7b4` | `#1f2328` / `#59636e` |
| `ok` / `warn` / `bad` / `info` | `#57d364` / `#e3b341` / `#f85149` / `#58a6ff` | `#16642c` / `#8a5b00` / `#cf222e` / `#0b5cad` |
| `accent` | `#58a6ff` (same as `info`) | `#0b5cad` (same as `info`) |
| `covered` (timeline) | `#2ea043` | `#1a7f37` |
| `ink_light` / `ink_dark` | `#f6f8fb` / `#0a0e14` | `#ffffff` / `#0b1220` |
| `node_light` / `node_sat` | 0.28 / 0.42 | 0.74 / 0.46 |

Notes a presenter should know:

- The light status hues are deliberately a step darker than their usual web
  values, because they must clear 4.5:1 on the *darkest* surface they can land
  on (`surface_alt`), not just on white.
- `node_light = 0.28` (dark) is the lightest value that keeps the node block
  visible against the canvas (1.32:1) while every hue clears 5.7:1 against its
  own label.
- `accent` duplicates `info` in both palettes (see file 17, known gaps).

## Functions

- `palette(base)` — tokens for a base; unknown/missing bases fall back to dark.
- `current_base()` — reads `[theme] base` from `.streamlit/config.toml`
  through Streamlit's own config resolver (one place decides); outside a
  Streamlit run it returns the shipped default instead of raising.
- `current()` — tokens for the theme actually rendering.
- `luminance` / `contrast_ratio` — WCAG 2.1 relative luminance and ratio
  (order-independent, 1:1–21:1); rejects non-hex input loudly rather than
  silently becoming black.
- `hsl(h, s, light)` — hue turns + saturation/lightness → `#rrggbb`
  (via `colorsys.hls_to_rgb`; note the argument order is HLS under the hood).
- `readable_on(background, base)` — the better of the two inks, by measurement.
- `node_fill(hue, …)` / `node_pair(hue, …)` — themed fill, and `(fill, ink)`
  together so a node is always legible on itself.

## The declaration it follows

`.streamlit/config.toml` declares `base = "dark"`, `backgroundColor =
"#0e1117"`, `secondaryBackgroundColor = "#161b22"`, `textColor = "#e6edf3"`,
`primaryColor = "#58a6ff"` — the same values as the dark palette's `page`,
`surface`, `text`, and `info`. The Python twin of this guard is
`tests/test_theme.py::test_the_declared_theme_matches_the_palette`.
