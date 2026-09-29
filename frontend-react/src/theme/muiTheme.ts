import { createTheme } from '@mui/material/styles'
import type { Theme } from '@mui/material/styles'
import { palette, readableOn } from './tokens'
import type { Base, Palette as TokenPalette } from './tokens'

/**
 * The MUI theme, built from the token table.
 *
 * REACT_ARCHITECTURE.md §4: the theme is *generated* from the tokens
 * `frontend/theme.py` pins, so the React engine does not grow a second palette.
 * Nothing in this file names a colour: every value below is `p.<token>`.
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

export function buildTheme(base?: Base | string | null): Theme {
  const p = palette(base)

  return createTheme({
    palette: buildPalette(p),
    shape: { borderRadius: 10 },

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
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            textTransform: 'none',
            fontWeight: 600,
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 6, fontWeight: 500 },
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
