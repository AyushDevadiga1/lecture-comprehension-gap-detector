/**
 * CSS custom properties, generated from the token table.
 *
 * The one rule: **no module outside `src/theme/` may name a colour**
 * (REACT_ARCHITECTURE.md §4, the Python twin being
 * `tests/test_theme.py::test_no_module_outside_theme_hardcodes_a_colour`, which
 * fails the suite if any module other than `theme.py` contains a hex). Panels
 * ask for a token — `var(--lgc-surface)` or a MUI slot — and never a hue.
 *
 * Injected onto `documentElement` rather than handed to MUI's `cssVariables`,
 * because that option's scoping behaviour is version-dependent and this needs
 * to be testable without a browser: `cssVariablesFor(base)` is a pure function
 * and this file is the only thing that touches the DOM.
 */

import { palette } from './tokens'
import type { Base } from './tokens'

/** Every custom property, for a base. Pure. */
export function cssVariablesFor(base?: Base | string | null): Record<string, string> {
  const p = palette(base ?? undefined)
  return {
    '--lgc-base': p.base,
    '--lgc-page': p.page,
    '--lgc-surface': p.surface,
    '--lgc-surface-alt': p.surface_alt,
    '--lgc-border': p.border,
    '--lgc-text': p.text,
    '--lgc-muted': p.muted,
    '--lgc-ok': p.ok,
    '--lgc-warn': p.warn,
    '--lgc-bad': p.bad,
    '--lgc-info': p.info,
    '--lgc-accent': p.accent,
    '--lgc-graph-bg': p.graph_bg,
    '--lgc-graph-edge': p.graph_edge,
    '--lgc-track': p.track,
    '--lgc-tick': p.tick,
    '--lgc-covered': p.covered,
    '--lgc-ink-light': p.ink_light,
    '--lgc-ink-dark': p.ink_dark,
  }
}

/** Write the variables for `base` onto the document root. */
export function applyCssVariables(base?: Base | string | null): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  for (const [name, value] of Object.entries(cssVariablesFor(base))) {
    root.style.setProperty(name, value)
  }
  // Lets a stylesheet branch on the base without a class or a media query.
  root.setAttribute('data-theme', palette(base ?? undefined).base)
}
