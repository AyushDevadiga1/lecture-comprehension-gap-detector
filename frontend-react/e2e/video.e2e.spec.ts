/**
 * E2E — the §10 gate: a playing `<video>` must survive a job tick.
 *
 * ## Why this file exists
 *
 * This is the reason the React rebuild was started, and it was the one claim
 * no tier could make. `plan/REACT_ARCHITECTURE.md` §1 exists because the
 * Streamlit engine re-rendered the whole page roughly once a second to read a
 * progress number, which restarted every playing video. §1's fix is that
 * progress arrives by push, into one query key, read through
 * `useSyncExternalStore` — so a job tick is not supposed to be the reason a
 * component re-renders, and `src/lib/rerender.test.tsx` proves the *render
 * counts* under a fake transport.
 *
 * Render counts are not playback. They cannot distinguish "React re-rendered
 * and the browser kept decoding" from "React re-rendered, the `<video>` node
 * was replaced, and it silently restarted at 0:00". Only a real decoder can
 * tell those apart, and every tier so far has mocked the transport out of
 * existence.
 *
 * So this spec does the thing the other three cannot: it plays an actual
 * decodable video, in a real browser, off a real HTTP range request through a
 * real proxy, while a real background job publishes real progress over a real
 * SSE stream — and then asserts on the media element's own state.
 *
 * ## What "survived" is asserted to mean
 *
 * Not "the video is still on screen". Specifically:
 *
 *   - the SAME DOM node is still there (no remount), tagged before the job ran;
 *   - `currentTime` never went backwards (no silent restart);
 *   - it never paused, and no `loadstart`/`emptied`/`seeking` fired (no reload);
 *   - it decoded real frames (`videoWidth > 0`), so this is playback and not a
 *     black rectangle that happens to have a duration;
 *   - all of the above sampled *while* job snapshots were arriving.
 *
 * The ticks are real. The job is a real `cut_clips` run — real ffmpeg, real
 * `update_job` writes, real heartbeats, real frames — not a synthetic event.
 * It is started through `POST /lectures/{id}/clips` with Playwright's request
 * fixture rather than by clicking, because the seeded running job already
 * marks that lecture busy and disables its button; the button's behaviour is
 * covered in `app.e2e.spec.ts`, and what is under test here is the media
 * element's response to the tick.
 *
 * It runs against lecture 2, deliberately. Cutting clips rewrites that
 * lecture's clip rows, which would legitimately invalidate and re-render the
 * clip list being watched — a real data change, not the render-loop defect this
 * file is about. Isolating the job to a different lecture is what makes a
 * failure here mean "a job tick restarted the video" and nothing else.
 */

import { expect, test } from '@playwright/test'

/** The lecture whose clips are played, and the one whose job is started. */
const PLAYING_LECTURE_CLIP = '0:00 – 0:06'
const JOB_LECTURE_ID = 2 // Multiple Regression: ready, has a concept, no clips

test.describe('§10: a playing video survives a job tick', () => {
  test('keeps decoding while real job snapshots arrive', async ({ page, request }) => {
    // --- 1. play a real clip ----------------------------------------------
    await page.goto('/student')
    await expect(page.getByText('Clip Library')).toBeVisible()
    await page.getByText(PLAYING_LECTURE_CLIP).click()

    const video = page.locator('video')
    await expect(video).toHaveCount(1)

    // Real decode, not just a well-formed src: `videoWidth` is non-zero only
    // once the browser has actual frames. This is the assertion that the
    // preceding commit's fixture exists for — before it, this test could only
    // have got as far as a black player at 0:00.
    await expect
      .poll(() => video.evaluate((v) => (v as HTMLVideoElement).videoWidth), {
        timeout: 30_000,
      })
      .toBeGreaterThan(0)

    await expect
      .poll(() => video.evaluate((v) => (v as HTMLVideoElement).currentTime), {
        timeout: 15_000,
      })
      .toBeGreaterThan(0)

    // --- 2. tag the node, then start recording ----------------------------
    // The tag is how "the same element survived" is checked. Render counts and
    // visibility cannot distinguish a retained node from a replaced one.
    await video.evaluate((v) => {
      const el = v as HTMLVideoElement & { dataset: DOMStringMap }
      el.dataset.lecgapGate = 'original'
    })

    // Records, in the page, on every animation frame: the playhead, and any
    // media event that would mean the element was disturbed. Sampled here
    // rather than polled from Node so the observations interleave with the
    // ticks instead of racing them.
    await page.evaluate(() => {
      const v = document.querySelector('video') as HTMLVideoElement
      const w = window as unknown as {
        __gate: { times: number[]; events: string[]; playing: boolean[] }
      }
      const g = { times: [] as number[], events: [] as string[], playing: [] as boolean[] }
      w.__gate = g
      for (const name of ['loadstart', 'emptied', 'seeking', 'pause', 'ended', 'stalled']) {
        v.addEventListener(name, () => {
          g.events.push(`${name}@${v.currentTime.toFixed(2)}`)
        })
      }
      const frame = () => {
        g.times.push(v.currentTime)
        g.playing.push(!v.paused)
        if (g.times.length < 4000) requestAnimationFrame(frame)
      }
      requestAnimationFrame(frame)
    })

    const before = await video.evaluate((v) => (v as HTMLVideoElement).currentTime)

    // --- 3. open the drawer, so ticks are visible --------------------------
    // Opened after playback starts: the drawer is modal and marks the page
    // behind it `aria-hidden`, so clicking the clip row through it would not
    // work. It does not pause the video, which is part of what is being shown.
    await page.getByRole('button', { name: 'View Background Jobs & Pipelines' }).click()
    await expect(page.getByText('SSE Live')).toBeVisible({ timeout: 30_000 })

    const snapshotNo = page.getByText(/^Snapshot #\d+$/)
    await expect(snapshotNo).toBeVisible({ timeout: 30_000 })
    const snapshotsBefore = Number(
      (await snapshotNo.textContent())!.replace(/\D/g, ''),
    )

    // --- 4. start a REAL job ----------------------------------------------
    const started = await request.post(`/lectures/${JOB_LECTURE_ID}/clips`)
    expect(
      started.status(),
      `POST /lectures/${JOB_LECTURE_ID}/clips did not queue work: ${await started.text()}`,
    ).toBe(202)

    // --- 5. ticks actually arrive -----------------------------------------
    // Without this the test could pass with a video that never had to survive
    // anything: the job could fail to start, the stream could be dead, and a
    // video nobody disturbed looks exactly like one that was disturbed and
    // survived. So the arrival of job data is asserted before the media
    // assertions below mean anything.
    await expect
      .poll(
        async () => Number((await snapshotNo.textContent())!.replace(/\D/g, '')),
        { timeout: 60_000, message: 'no further job snapshot reached the UI' },
      )
      .toBeGreaterThan(snapshotsBefore)

    // --- 6. the video, after all that -------------------------------------
    const gate = await page.evaluate(() => {
      const v = document.querySelector('video') as HTMLVideoElement
      const w = window as unknown as {
        __gate: { times: number[]; events: string[]; playing: boolean[] }
      }
      return {
        times: w.__gate.times,
        events: w.__gate.events,
        allPlaying: w.__gate.playing.every(Boolean),
        currentTime: v.currentTime,
        paused: v.paused,
        readyState: v.readyState,
        videoWidth: v.videoWidth,
        ended: v.ended,
        // Same node? The tag survives only if React updated the element it
        // already had rather than replacing it.
        sameNode: v.dataset.lecgapGate === 'original',
      }
    })

    // Real frames decoded, and still decoding.
    expect(gate.videoWidth).toBeGreaterThan(0)
    expect(gate.readyState).toBeGreaterThanOrEqual(3)

    // The node was never replaced — this is the assertion the jsdom
    // render-count test cannot make.
    expect(gate.sameNode, 'the <video> element was remounted by a job tick').toBe(true)

    // Playback never stopped. Checked over the whole sampled window rather
    // than at one instant, because a tick that pauses and resumes within one
    // frame would be invisible to an end-of-test sample.
    expect(gate.allPlaying, 'the video paused at some point during the job').toBe(true)
    expect(gate.paused).toBe(false)
    expect(gate.ended).toBe(false)

    // The playhead only ever moved forward. A remount or a src reassignment
    // resets this to 0, and a backwards step would be a seek; either is a
    // restart wearing a different name.
    expect(gate.times.length).toBeGreaterThan(10)
    for (let i = 1; i < gate.times.length; i += 1) {
      expect(
        gate.times[i],
        `playhead went backwards at sample ${i}: ${gate.times[i - 1]} -> ${gate.times[i]}`,
      ).toBeGreaterThanOrEqual(gate.times[i - 1] - 1e-6)
    }

    // It carried on from where it was, past the point it had reached before the
    // job started.
    expect(gate.currentTime).toBeGreaterThan(before)

    // And nothing ever asked the browser to reload the media.
    expect(
      gate.events,
      `media events fired during the job: ${gate.events.join(', ')}`,
    ).toEqual([])
  })
})