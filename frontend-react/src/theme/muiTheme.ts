import { createTheme } from '@mui/material/styles'
import type { Theme } from '@mui/material/styles'
import { palette, readableOn } from './tokens'
import { gradient, tint, token } from './alpha'
import type { Base, Palette as TokenPalette } from './tokens'

/**
 * The MUI theme, built from the token table.
 *
 * REACT_ARCHITECTURE.md §4: the theme is *generated* from the tokens
 * `frontend/theme.py` pins, so the React engine does not grow a second palette.
 * Nothing in this file names a colour: every value below is `p.<token>`, or a
 * `tint()`/`token()`/`gradient()` derived from `var(--lgc-*)`.
 *
 * The previous version hardcoded ~20 hexes, used an indigo/purple ramp that
 * shares no value with the Python palette, and set `background.default` to
 * `#0b0f19` — which is not even the `page` token, so the page background and the
 * theme already disagreed with each other.
 *
 * `contrastText` is **measured**, not chosen. The first version of this file
 * used `ink_light` for every slot, and the parity test caught it immediately:
 * `#f6f8fb` on the dark `info` token is 2.37:1, and `ink_dark` on the light
 * `warn` token is 3.19:1. Both below AA. `readableOn` is the whole reason this
 * module exists -- the ink is picked per colour rather than per palette.
 *
 * ## The aesthetic layer
 *
 * Everything below `shape` exists because MUI's shipped defaults are a second,
 * unopinionated design system: Roboto (the theme never set `typography` at
 * all, so every component that asks for a typography variant got Helvetica),
 * square-ish 4px radii, a grey material-elevation shadow that reads as a smudge
 * on a warm cream page, and a primary button with no resting shadow.
 *
 * The rules it follows, so it stays a *theme* rather than a pile of sx:
 *
 *   - **Type**: Inter everywhere (the family `index.html` actually loads),
 *     display headings at 800 with tight tracking, body at a comfortable 1.6
 *     line-height. Weights only go as high as the font file supports.
 *   - **Shape**: 10px controls, 16px cards/dialogs — two steps, not one per
 *     component, so silhouettes rhyme.
 *   - **Elevation**: no grey. Shadows are a wash of the *ink* token
 *     (`tint('ink-dark', n)`), which is near-black in both bases, so a card
 *     lifts the same way in light and dark without a single `rgba()` literal —
 *     which the ESLint colour rule would (correctly) reject anyway.
 *   - **Focus**: every interactive surface gets a visible teal ring derived
 *     from `info`, because a keyboard user currently has no idea where they are.
 *   - Motion is short (120–200ms) and only on properties that don't trigger
 *     layout; `prefers-reduced-motion` disables it globally in `index.css`.
 */

/** One slot: `main` from a token, `contrastText` measured against it. */
function slot(main: string, base: string) {
  return { main, contrastText: readableOn(main, base) }
}

function buildPalette(p: TokenPalette) {
  return {
    mode: p.base,
    primary: slot(p.info, p.base),
    secondary: slot(p.accent, p.base),
    success: slot(p.ok, p.base),
    warning: slot(p.warn, p.base),
    error: slot(p.bad, p.base),
    info: slot(p.info, p.base),
    background: { default: p.page, paper: p.surface },
    text: { primary: p.text, secondary: p.muted },
    divider: p.border,
  } as const
}

/** The shared type ramp — see the note above about Roboto. */
const typography = {
  fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  h1: { fontFamily: "'Space Grotesk', 'IBM Plex Sans', sans-serif", fontWeight: 700, letterSpacing: '-0.035em', lineHeight: 1.05 },
  h2: { fontFamily: "'Space Grotesk', 'IBM Plex Sans', sans-serif", fontWeight: 700, letterSpacing: '-0.025em', lineHeight: 1.12 },
  h3: { fontFamily: "'Space Grotesk', 'IBM Plex Sans', sans-serif", fontWeight: 600, letterSpacing: '-0.018em', lineHeight: 1.2 },
  h4: { fontFamily: "'Space Grotesk', 'IBM Plex Sans', sans-serif", fontWeight: 600, letterSpacing: '-0.015em', lineHeight: 1.22 },
  h5: { fontFamily: "'Space Grotesk', 'IBM Plex Sans', sans-serif", fontWeight: 600, letterSpacing: '-0.01em', lineHeight: 1.28 },
  h6: { fontFamily: "'Space Grotesk', 'IBM Plex Sans', sans-serif", fontWeight: 600, letterSpacing: '-0.005em', lineHeight: 1.32 },
  subtitle1: { fontWeight: 600, lineHeight: 1.5 },
  subtitle2: { fontWeight: 600, letterSpacing: '0.01em', lineHeight: 1.4 },
  body1: { lineHeight: 1.6 },
  body2: { lineHeight: 1.55 },
  button: { fontWeight: 600, letterSpacing: '-0.01em' },
  caption: { letterSpacing: '0.02em', lineHeight: 1.45 },
  overline: { fontWeight: 700, letterSpacing: '0.1em' },
}

export function buildTheme(base?: Base | string | null): Theme {
  const p = palette(base)

  return createTheme({
    palette: buildPalette(p),
    shape: { borderRadius: 10 },
    typography,

    // The body background comes from the same `page` token as everything else.
    // This is the React analogue of
    // `tests/test_theme.py::test_the_declared_theme_matches_the_palette`, which
    // pins the Streamlit config against `theme.py`: the value that paints the
    // page and the value the palette declares cannot drift, because there is
    // only one of it.
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            backgroundColor: p.page,
            color: p.text,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: { backgroundImage: 'none' },
        },
      },

      // ---------------------------------------------------------------- cards
      // The dashboards are built almost entirely from <Card>, so this one
      // override carries most of the surface language: a hairline border
      // plus one tight ink wash. The previous version stacked a 32px ambient
      // wash that read as floating panels; restraint here is what makes the
      // page feel flat and deliberate rather than decorated.
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            border: `1px solid ${token('border')}`,
            boxShadow: `0 1px 2px ${tint('ink-dark', 8)}`,
          },
        },
      },

      // --------------------------------------------------------------- buttons
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            textTransform: 'none',
            fontWeight: 600,
            paddingInline: 16,
            minHeight: 38,
            transition: 'background-color 160ms ease, box-shadow 160ms ease, transform 120ms ease',
            '&:active': { transform: 'translateY(0.5px)' },
            '&:focus-visible': {
              outline: `2px solid ${tint('info', 55)}`,
              outlineOffset: 2,
            },
          },
          contained: {
            boxShadow: 'none',
            '&:hover': { boxShadow: `0 4px 14px ${tint('ink-dark', 16)}` },
          },
          outlined: {
            borderColor: token('border'),
            '&:hover': {
              borderColor: token('info'),
              backgroundColor: tint('info', 6),
            },
          },
          text: {
            '&:hover': { backgroundColor: tint('info', 8) },
          },
          sizeLarge: { paddingInline: 24, minHeight: 44, fontSize: '1rem' },
          sizeSmall: { paddingInline: 12, minHeight: 32 },
        },
      },

      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 8, fontWeight: 600 },
        },
      },

      // ---------------------------------------------------------------- inputs
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            backgroundColor: tint('text', 3),
            '& .MuiOutlinedInput-notchedOutline': { borderColor: token('border') },
            '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: tint('info', 55) },
            '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: token('info') },
            '&.Mui-focused': { boxShadow: `0 0 0 3px ${tint('info', 18)}` },
          },
        },
      },
      MuiInputLabel: {
        styleOverrides: { root: { fontWeight: 500 } },
      },

      // ----------------------------------------------------------------- chrome
      MuiAppBar: {
        styleOverrides: {
          root: {
            // A translucent surface + blur: content scrolls under the sticky bar
            // with a soft cream/espresso fog instead of a hard cut.
            backgroundColor: tint('surface', 84),
            backgroundImage: 'none',
            color: token('text'),
            borderBottom: `1px solid ${token('border')}`,
            boxShadow: `0 1px 3px ${tint('ink-dark', 8)}`,
            backdropFilter: 'saturate(160%) blur(12px)',
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundColor: token('surface'),
            backgroundImage: 'none',
            borderLeft: `1px solid ${token('border')}`,
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 16,
            border: `1px solid ${token('border')}`,
            boxShadow: `0 1px 2px ${tint('ink-dark', 6)}, 0 24px 64px ${tint('ink-dark', 14)}`,
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            borderRadius: 8,
            fontSize: '0.78rem',
            fontWeight: 500,
            padding: '6px 10px',
            // Inverted ink pair: both values are tokens, so both bases get a
            // legible tooltip without a second rule.
            backgroundColor: token('text'),
            color: token('page'),
            boxShadow: `0 4px 14px ${tint('ink-dark', 20)}`,
          },
        },
      },

      // ---------------------------------------------------------------- tables
      MuiTableCell: {
        styleOverrides: {
          root: { borderBottomColor: token('border') },
          head: {
            backgroundColor: token('surface-alt'),
            color: token('text'),
            fontSize: '0.72rem',
            fontWeight: 700,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          },
        },
      },

      // -------------------------------------------------------------- progress
      // A token gradient, so the bar reads as brand rather than as stock MUI.
      MuiLinearProgress: {
        styleOverrides: {
          root: {
            borderRadius: 999,
            height: 8,
            backgroundColor: tint('text', 8),
            overflow: 'hidden',
          },
          bar: {
            borderRadius: 999,
            backgroundImage: gradient('info', 'ok'),
          },
        },
      },
    },
  })
}

/**
 * The theme the app ships with, for the times a theme is needed outside React
 * (the test harness, an `sx` computed at module scope). The live theme is
 * `<AppTheme>`, which follows the store.
 */
export const theme = buildTheme()
