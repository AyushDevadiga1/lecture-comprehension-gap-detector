import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { screen } from '@testing-library/react'
import { renderWithProviders } from './test/render'
import { cssVariablesFor } from './theme/variables'
import { palette } from './theme/tokens'
import { resolveInitialBase } from './store/useAppStore'

/**
 * F3: `App.tsx` and `src/test/render.tsx` each hand-rolled a provider stack, and
 * they had already drifted — the harness used a bare `ThemeProvider` where the
 * app uses `AppTheme`, so `applyCssVariables` never ran under test and no test
 * ever rendered the real theme path.
 *
 * Sharing `AppProviders` fixes the instance. This file stops it recurring, and
 * records the reason the sharing is *partial*: the router must differ, because a
 * test needs to choose its starting path without touching `window.history`.
 */

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8')

/**
 * The file with its comments removed.
 *
 * These are source-text guards, so a docstring that *names* the thing it is
 * warning about would otherwise fail the check — and the natural way to write
 * "this used to call `buildTheme` here" is to say exactly that. Stripping
 * comments keeps the guard pointed at code, which is what it is for. (The same
 * trap exists in `lib/rerender.test.tsx`, which matches the raw substring
 * `jobFeed.` and so also matches prose.)
 */
const readCode = (p: string): string =>
  read(p)
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')

describe('one provider stack', () => {
  it('the app and the test harness both go through AppProviders', () => {
    expect(readCode('src/App.tsx'), 'App.tsx must use the shared stack').toContain('<AppProviders')
    expect(
      readCode('src/test/render.tsx'),
      'the harness must use the shared stack',
    ).toContain('<AppProviders')
  })

  it('neither stack re-declares the theme by hand', () => {
    // The exact drift: a bare ThemeProvider in one file and AppTheme in the
    // other. If either file builds a theme itself, they can diverge again.
    for (const p of ['src/App.tsx', 'src/test/render.tsx']) {
      const src = readCode(p)
      expect(src, `${p} must not import ThemeProvider`).not.toMatch(/from '@mui\/material\/styles'/)
      expect(src, `${p} must not call buildTheme`).not.toContain('buildTheme')
      expect(src, `${p} must not import CssBaseline`).not.toContain('CssBaseline')
    }
  })

  it('only the router differs, and it differs on purpose', () => {
    const app = readCode('src/App.tsx')
    const harness = readCode('src/test/render.tsx')

    expect(app).toContain('BrowserRouter')
    expect(harness).toContain('MemoryRouter')
    // A MemoryRouter in the app would be a serious regression: the app must
    // read the real URL, or the server has nothing to serve.
    expect(app).not.toContain('MemoryRouter')
  })

  it('rendering through the harness now exercises the real theme path', () => {
    // The behaviour the old harness could not reach: AppTheme writes the
    // custom properties that `index.css` and every `var(--lgc-*)` in `sx` depend
    // on. Before this, `document.documentElement` had none of them under test.
    //
    // Asserted against `resolveInitialBase()` rather than a literal 'dark', so
    // this does not become a second place that has to be updated if the shipped
    // default ever changes.
    const base = resolveInitialBase()

    renderWithProviders(<div>themed</div>)

    const root = document.documentElement
    expect(root.style.getPropertyValue('--lgc-page')).toBe(palette(base).page)
    expect(root.style.getPropertyValue('--lgc-text')).toBe(palette(base).text)
    // And the attribute a stylesheet can branch on without a media query.
    expect(root.getAttribute('data-theme')).toBe(base)
    expect(screen.getByText('themed')).toBeInTheDocument()
  })

  it('the custom properties it writes are the palette, not a second table', () => {
    renderWithProviders(<div>themed</div>)
    const vars = cssVariablesFor(resolveInitialBase())
    for (const [name, value] of Object.entries(vars)) {
      expect(
        document.documentElement.style.getPropertyValue(name),
        `${name} should match cssVariablesFor(${resolveInitialBase()})`,
      ).toBe(value)
    }
  })
})