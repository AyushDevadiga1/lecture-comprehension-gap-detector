/**
 * Visual review tier — capture the real app so a person can look at it.
 *
 * ## Why this exists
 *
 * Every other tier is blind in the same specific way. The unit tests assert on
 * text and attributes; the live tier asserts that real data reaches real
 * components; the E2E tier drives a real browser and asserts that a real proxied
 * SSE stream arrives. All of that is *behaviour*, and none of it is appearance:
 * layout, spacing, overflow, truncation, contrast, whether the light theme is
 * legible, whether a panel is readable at 1440px.
 *
 * That is not a theoretical gap. `7efdc4c` fixed a bug that put **330 minutes**
 * where a job's elapsed time should have read "26s". Every assertion in the repo
 * passed while the UI lied, because they assert that a value *exists* and never
 * that a *number* is right. A human looking at the drawer saw it in one glance.
 *
 * This spec is that glance, made repeatable. It boots the same real backend on a
 * throwaway database as the E2E tier, walks the app, and writes PNGs.
 *
 * ## Output is scratch
 *
 * `screenshots/` is gitignored and regenerated on every run. Review the images,
 * then delete them — do not commit them and do not let them accumulate. See the
 * "Review outputs, then delete them" rule in
 * `plan/REACT_HARDENING_HANDOFF.md`.
 *
 * The seeded clip files are deliberately absent, so the clip player renders
 * black. That is expected: this tier is about the client's URL contract and the
 * layout, not about ffmpeg.
 */

import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'screenshots')

test('capture the app for visual review', async ({ page }) => {
  mkdirSync(OUT, { recursive: true })

  // Desktop first: 1440 is the width the layout is designed against, and
  // overflow bugs hide at narrower widths, so this is not an arbitrary default.
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.goto('/student')
  await expect(page.getByText('Clip Library')).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(OUT, '01-student-top.png') })
  await page.screenshot({ path: path.join(OUT, '02-student-full.png'), fullPage: true })

  // The job drawer, open, with the live job card. This is the view that exposed
  // the timestamp bug.
  await page.getByRole('button', { name: 'View Background Jobs & Pipelines' }).click()
  await expect(page.getByText('SSE Live')).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: path.join(OUT, '03-drawer.png') })
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // The clip browser with a clip selected, so the player and the time-range
  // chips are both visible.
  await page.getByText('0:00 – 0:06').click()
  await page.waitForTimeout(1200)
  const clipCard = page
    .locator('text=Clip Library')
    .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
  await clipCard.scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(OUT, '04-clip-browser.png') })

  await page.goto('/faculty')
  await page.waitForTimeout(2500)
  await page.screenshot({ path: path.join(OUT, '05-faculty.png'), fullPage: true })

  // Narrow viewport, because truncation and overflow are the class of defect
  // that a 1440px screenshot cannot show and a test cannot assert.
  await page.setViewportSize({ width: 420, height: 900 })
  await page.goto('/student')
  await expect(page.getByText('Clip Library')).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: path.join(OUT, '06-student-narrow.png'), fullPage: true })

  console.log(`screenshots -> ${OUT}  (review them, then delete them)`)
})
