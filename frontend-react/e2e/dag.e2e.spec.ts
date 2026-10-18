/**
 * E2E — the prerequisite DAG in a REAL browser.
 *
 * ## What only this file can prove
 *
 * The unit tier (`DagView.test.tsx`) runs in jsdom, which never lays out: it
 * asserts structure through three layout shims (a measuring observer, a zoom
 * parser, fixed boxes) that stand in for what a browser always provides. None
 * of that proves a node is *visible*, that a click lands, or that the canvas
 * paints at all — reactflow keeps unmeasured nodes `visibility: hidden`, and
 * jsdom cannot tell a painted graph from an empty viewport with the right
 * DOM inside it.
 *
 * This file is the other half: real Chromium, real layout, the seeded `ml`
 * graph (3 nodes, 2 edges — one spoken with evidence, one inferred).
 *
 * ## The regression it would have caught
 *
 * Until this brick, the graph payload reached the UI and was rendered as an
 * edges *table*. A unit suite asserting on that table would have been green
 * over a missing visualisation — the same class of green-over-broken the
 * handoff §0 exists to prevent.
 */

import { expect, test } from '@playwright/test'

/** Anything the page logged as an error is a failure, collected per test. */
function watchConsole(page: import('@playwright/test').Page): string[] {
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  return errors
}

test.describe('the course graph draws and answers clicks', () => {
  test('nodes render, and a click shows spoken evidence', async ({ page }) => {
    const errors = watchConsole(page)

    await page.goto('/student/map')

    // The section the concept-map view renders around the canvas.
    await expect(page.getByText('Concept map', { exact: true }).first()).toBeVisible()

    // Real layout, real visibility: these are painted nodes, not DOM that
    // happens to exist. jsdom cannot make this assertion (see above).
    // Anchored on ", learner step" because the clip library has its own
    // buttons named "Slope 0:06 – 0:12" — a bare /Slope/ matches those too.
    const slope = page.getByRole('button', { name: /^Slope, learner step/ })
    await expect(slope).toBeVisible()
    await expect(
      page.getByRole('button', { name: /^Linear Regression, learner step/ }),
    ).toBeVisible()
    await expect(page.getByText(/3 concepts in total/)).toBeVisible()
    await expect(page.getByText(/acyclic/)).toBeVisible()

    // Click evidence: the spoken edge carries its sentence, the inferred one
    // its method. This is what hover showed in the Streamlit SVG. Grouped by
    // direction: what Slope needs first vs what it unlocks.
    await slope.click()
    await expect(page.getByText('Linear Regression → Slope')).toBeVisible()
    await expect(page.getByText(/NEEDS FIRST/)).toBeVisible()
    await expect(page.getByText('spoken in lecture')).toBeVisible()
    await expect(page.getByText(/coefficient on x/)).toBeVisible()

    expect(errors, `page logged errors:\n${errors.join('\n')}`).toEqual([])
  })

  test('unchecking transcript leaves only the inferred link', async ({ page }) => {
    const errors = watchConsole(page)

    await page.goto('/student/map')
    await expect(page.getByText(/Links drawn 2 \/ 2/)).toBeVisible()

    await page.getByRole('combobox', { name: 'Edge types' }).click()
    await page.getByRole('option', { name: /transcript/ }).click()
    await page.keyboard.press('Escape')

    await expect(page.getByText(/Links drawn 1 \/ 2/)).toBeVisible()

    expect(errors, `page logged errors:\n${errors.join('\n')}`).toEqual([])
  })

  test('the learner order lists the study sequence', async ({ page }) => {
    const errors = watchConsole(page)

    await page.goto('/student/map')
    await expect(page.getByText('Learner order', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('Multiple Regression').first()).toBeVisible()

    expect(errors, `page logged errors:\n${errors.join('\n')}`).toEqual([])
  })

  test('find-concept locates a node and opens its evidence', async ({ page }) => {
    const errors = watchConsole(page)

    await page.goto('/student/map')
    await expect(page.getByRole('button', { name: /^Slope, learner step/ })).toBeVisible()

    // Case-insensitive substring; centers the match and selects it, which is
    // what the evidence assertion below proves (selection drives the panel).
    await page.getByRole('textbox', { name: 'Find concept' }).fill('slo')
    await page.keyboard.press('Enter')

    await expect(page.getByText('Linear Regression → Slope')).toBeVisible()
    await expect(page.getByText('spoken in lecture')).toBeVisible()

    expect(errors, `page logged errors:\n${errors.join('\n')}`).toEqual([])
  })
})
