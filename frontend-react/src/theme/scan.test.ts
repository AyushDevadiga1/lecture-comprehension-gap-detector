import { describe, expect, it } from 'vitest'
import { cssVariablesFor, applyCssVariables } from './variables'
import { palette } from './tokens'
import { buildTheme } from './muiTheme'
import { contrastRatio } from './tokens'

/**
 * The runtime twin of the ESLint rule, and the React analogue of
 * `tests/test_theme.py::test_the_declared_theme_matches_the_palette`.
 *
 * Two jobs:
 *
 *   1. **No module names a colour.** ESLint's `no-restricted-syntax` catches a
 *      hex in a `.ts`/`.tsx` file. This catches the rest -- `.css`, and any file
 *      that arrives without being linted -- and reports `file:lineno`, which is
 *      how the Python scanner reports too.
 *   2. **The theme, the CSS and the palette are one value.** The drift the
 *      Python guards against is a declared background that disagrees with the
 *      palette; here the same three spellings (MUI slot, `var(--lgc-*)`, and the
 *      `page` token) must agree for both bases.
 */

/**
 * A hex colour, not counting one inside an HTML entity. The `(?<!&)` is the
 * Python's, from `tests/test_theme.py`.
 */
const HEX = /(?<!&)#[0-9a-fA-F]{3,8}\b/g

const THEME_DIR = 'src/theme/'

/**
 * `import.meta.glob` keys relative to *this* file, which lives in `src/theme/`
 * — so a sibling is `./name` and a descendant is `./sub/name`, while a file
 * outside the theme directory is `../lib/thing`. Resolve all three to a
 * repo-relative path before deciding anything, or the exemption silently
 * misses the siblings and the scan fails on the very files that are *supposed*
 * to hold the hexes.
 */
function resolveGlobPath(key: string): string {
  // Seeded with this file's own directory, since the keys are relative to it.
  const parts: string[] = ['src', 'theme']
  for (const segment of key.replace(/\\/g, '/').split('/')) {
    if (segment === '.' || segment === '') continue
    if (segment === '..') parts.pop()
    else parts.push(segment)
  }
  return parts.join('/')
}

const isThemeModule = (key: string): boolean => resolveGlobPath(key).includes(THEME_DIR)
const display = (key: string): string => resolveGlobPath(key).replace(/^src\//, '')

describe('no module names a colour', () => {
  const modules = import.meta.glob('../**/*.{ts,tsx,css}', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>

  it('there are files to scan', () => {
    expect(Object.keys(modules).length).toBeGreaterThan(10)
  })

  it('resolves a sibling and an outsider differently', () => {
    // Guards the helper above: if this broke, every scan below would pass or
    // fail for the wrong reason.
    expect(resolveGlobPath('./tokens.ts')).toBe('src/theme/tokens.ts')
    expect(resolveGlobPath('../lib/quiz.ts')).toBe('src/lib/quiz.ts')
    expect(resolveGlobPath('./sub/x.ts')).toBe('src/theme/sub/x.ts')
    expect(isThemeModule('./tokens.ts')).toBe(true)
    expect(isThemeModule('../lib/quiz.ts')).toBe(false)
  })

  it('src/index.css has no hex literal', () => {
    const hit = Object.entries(modules).find(([k]) => display(k) === 'index.css')
    expect(hit, 'index.css should be in the scan').toBeTruthy()
    const offenders: string[] = []
    hit![1].split('\n').forEach((line, i) => {
      for (const m of line.matchAll(HEX)) offenders.push(`index.css:${i + 1} ${m[0]}`)
    })
    expect(offenders).toEqual([])
  })

  for (const [key, src] of Object.entries(modules)) {
    if (isThemeModule(key)) continue
    if (key.includes('.test.')) continue

    it(`${display(key)} names no colour`, () => {
      const offenders: string[] = []
      src.split('\n').forEach((line, i) => {
        for (const m of line.matchAll(HEX)) {
          offenders.push(`${display(key)}:${i + 1} ${m[0]}`)
        }
      })
      expect(offenders).toEqual([])
    })
  }
})

describe('the theme, the CSS and the palette are one value', () => {
  for (const base of ['dark', 'light'] as const) {
    it(`${base}: the MUI background, the CSS variable and the page token agree`, () => {
      const p = palette(base)
      const theme = buildTheme(base)
      const vars = cssVariablesFor(base)

      expect(theme.palette.background.default).toBe(p.page)
      expect(theme.palette.background.paper).toBe(p.surface)
      expect(vars['--lgc-page']).toBe(p.page)
      expect(vars['--lgc-surface']).toBe(p.surface)
      expect(theme.palette.text.primary).toBe(p.text)
      expect(theme.palette.text.secondary).toBe(p.muted)
      expect(theme.palette.divider).toBe(p.border)
      expect(theme.palette.mode).toBe(base)
    })

    it(`${base}: the MUI text slots clear AA on the paper they sit on`, () => {
      // The MUI theme is the surface most of the UI actually paints, so this is
      // where a wrong token would be visible even if the palette were right.
      const theme = buildTheme(base)
      for (const slot of ['primary', 'secondary', 'success', 'warning', 'error', 'info'] as const) {
        const main = theme.palette[slot].main
        const contrastText = theme.palette[slot].contrastText
        expect(contrastRatio(contrastText, main), `${base} ${slot}`).toBeGreaterThanOrEqual(4.5)
      }
      expect(contrastRatio(theme.palette.text.secondary, theme.palette.background.default)).toBeGreaterThanOrEqual(4.5)
    })
  }
})

describe('applyCssVariables', () => {
  it('writes the palette onto the document root', () => {
    applyCssVariables('light')
    expect(document.documentElement.style.getPropertyValue('--lgc-page')).toBe(palette('light').page)
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('a stylesheet can branch on the base without a media query', () => {
    applyCssVariables('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
