import React, { useEffect, useMemo } from 'react'
import { ThemeProvider } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import { useAppStore } from '../store/useAppStore'
import { buildTheme } from './muiTheme'
import { applyCssVariables } from './variables'
import type { Base } from './tokens'

/**
 * Supplies the generated theme, following the store's base.
 *
 * Two things happen here and they are deliberately the *same* token table:
 *   - the MUI theme is built from `palette(base)`, and
 *   - the CSS custom properties are written to `documentElement` from
 *     `palette(base)`.
 *
 * That is what makes drift impossible rather than merely unlikely: the page
 * background, a MUI `sx` colour and a `var(--lgc-*)` in `index.css` are three
 * spellings of one value. The Python twin of this guard is
 * `tests/test_theme.py::test_the_declared_theme_matches_the_palette`.
 *
 * `<CssBaseline />` is inside the provider so its `body` override sees the same
 * `page` token.
 */
export const AppTheme: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const base = useAppStore((s) => s.base)
  const theme = useMemo(() => buildTheme(base), [base])

  useEffect(() => {
    applyCssVariables(base)
  }, [base])

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  )
}

export type { Base }
