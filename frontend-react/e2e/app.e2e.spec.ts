/**
 * E2E — the app in a REAL browser, against a real Vite dev server proxying to a
 * real backend.
 *
 * ## What only this file can prove
 *
 * `npm run test:live` runs the real components in jsdom under Node, so the SSE
 * reader is undici's, not a browser's, and the Vite proxy is not in the path at
 * all. The handoff §0 lists five things no mocked test could establish. This
 * file is the answer to the three that need a browser:
 *
 *   - can a browser read a streaming `fetch` body **through a proxy**?
 *   - does Vite's dev proxy actually stream `/jobs/stream`, or buffer it?
 *   - is anything on the backend reachable from the dev server at all?
 *
 * It is also the first time any assertion in this repo has run against the
 * rendered result of a real page load. Everything before it was jsdom.
 *
 * ## The regression it would have caught
 *
 * `de74a02`: `JobFeed.connect()` assigned `this.sink` and then called
 * `disconnect()`, which nulls it, so the feed never delivered a snapshot to the
 * UI. The drawer read "Disconnected" forever. The seeded running job below
 * appears here only if a real browser parsed a real proxied SSE stream and
 * rendered it.
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

test.describe('the app in a real browser, through the real proxy', () => {
  test('renders real data, and the job feed reaches the UI', async ({ page }) => {
    const errors = watchConsole(page)

    await page.goto('/student')

    // --- the read path, through the proxy ---------------------------------
    // These lecture titles exist only in the E2E throwaway database.
    await expect(page.getByText('Linear Regression').first()).toBeVisible()
    await expect(page.getByText('Multiple Regression').first()).toBeVisible()

    // The snapshot numbers the seeded database implies.
    await expect(page.getByText('2 (2 ready)')).toBeVisible()
    await expect(page.getByText('2 Edges')).toBeVisible()
    await expect(page.getByText('2 / 2 OK')).toBeVisible()

    // --- the busy guard, from real job state ------------------------------
    // Two rows, one carrying the running job, so exactly one Extract button is
    // disabled. This is the "no double-fired work" rule on a real page.
    //
    // Checked BEFORE the drawer is opened, deliberately: an open MUI Drawer is
    // modal and marks the rest of the page `aria-hidden`, so `getByRole` finds
    // nothing behind it. A role query that returns 0 here is the a11y tree
    // behaving correctly, not a missing button.
    const extract = page.getByRole('button', { name: 'Extract Concepts' })
    await expect(extract).toHaveCount(2)
    await expect(extract.nth(0)).toBeEnabled()
    await expect(extract.nth(1)).toBeDisabled()

    // --- the SSE stream, through Vite's proxy -----------------------------
    // Open the drawer the way a person does. The accessible name is the
    // button's `aria-label`; a MUI Tooltip does not supply one, which is why
    // Navbar.tsx now carries explicit labels.
    await page.getByRole('button', { name: 'View Background Jobs & Pipelines' }).click()

    // "SSE Live" is driven by the feed's mode, which only becomes `stream`
    // after a real frame has been parsed out of a real proxied response body.
    // If Vite buffered the SSE response, or the browser could not read a
    // streaming body through the proxy, this chip stays on "Disconnected".
    await expect(page.getByText('SSE Live')).toBeVisible({ timeout: 30_000 })

    // The seeded in-flight job. `useActiveJobs` filters terminal rows out, so
    // this card can only exist if a live snapshot reached the React Query cache.
    await expect(page.getByText(/Persisting concepts/)).toBeVisible()
    // The card header is `#<id> • extract` (JobDrawer renders `&bull;`). The
    // bullet is what distinguishes it from the lecture table's `#1`/`#2`/`#3`
    // id column, which a bare `/#\d+/` also matches — hence not that.
    await expect(page.getByText(/#\d+\s*•/)).toBeVisible()

    expect(errors, `page logged errors:\n${errors.join('\n')}`).toEqual([])
  })

  test('the clip browser lists real clips and gives the player a real URL', async ({ page }) => {
    // The other half of the display story: clips existed in the database and
    // `GET /lectures/{id}/clips` worked, but nothing in the UI called it —
    // playback was only reachable through the quiz remediation path. A user
    // who had cut 24 clips had no browser for them.
    await page.goto('/student')

    await expect(page.getByText('Clip Library')).toBeVisible()
    // Two seeded clips, both ok. Asserted on the time ranges because the
    // concept names also appear in the lecture table above.
    await expect(page.getByText('0:00 – 0:06')).toBeVisible()
    await expect(page.getByText('0:06 – 0:12')).toBeVisible()
    await expect(page.getByText('2 playable')).toBeVisible()

    await page.getByText('0:00 – 0:06').click()

    const video = page.locator('video')
    await expect(video).toHaveCount(1)
    // Canonical URL, never the stored filesystem path (ARCHITECTURE §3).
    await expect(video).toHaveAttribute('src', /^\/media\/clips\//)
    // The player element itself is wired to the media route; the bytes are not
    // asserted because the seeded clip files are deliberately absent, and this
    // test is about the client's URL contract, not about ffmpeg.
    const src = await video.getAttribute('src')
    expect(src).not.toContain('\\')
  })

  test('a browser can read the streaming endpoint through the proxy', async ({ page }) => {
    // The narrower claim, isolated from the app: fetch /jobs/stream from inside
    // the page (so it is same-origin and therefore proxied) and read the body
    // incrementally. If the proxy buffered the response, `retry: 2000` and the
    // first `event: jobs` frame would arrive together at the very end rather
    // than promptly, and `bodyUsed` would be read-only in a way that shows it.
    await page.goto('/student')

    const probe = await page.evaluate(async () => {
      const started = performance.now()
      const res = await fetch('/jobs/stream?interval_s=1&course_id=ml', {
        headers: { Accept: 'text/event-stream' },
      })
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let seen = ''
      while (!seen.includes('event: jobs') && performance.now() - started < 20_000) {
        const { value, done } = await reader.read()
        if (done) break
        seen += decoder.decode(value, { stream: true })
      }
      await reader.cancel().catch(() => {})
      return {
        status: res.status,
        elapsedMs: Math.round(performance.now() - started),
        sawRetry: /retry:\s*\d+/.test(seen),
        sawJobsEvent: seen.includes('event: jobs'),
        // A full-array snapshot, change-gated: one event carrying every row.
        payloadIsArray: (() => {
          const line = seen.split('\n').find((l) => l.startsWith('data: '))
          return line ? Array.isArray(JSON.parse(line.slice(6))) : false
        })(),
      }
    })

    expect(probe.status).toBe(200)
    expect(probe.sawRetry).toBe(true)
    expect(probe.sawJobsEvent).toBe(true)
    expect(probe.payloadIsArray).toBe(true)
    // Proves it was incremental rather than buffered-then-dumped.
    expect(probe.elapsedMs).toBeLessThan(15_000)
  })
})
