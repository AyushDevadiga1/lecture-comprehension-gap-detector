#!/usr/bin/env node
/**
 * Negative control for the §10 gate.
 *
 * ## Why
 *
 * `e2e/video.e2e.spec.ts` is the first assertion in this repo that can tell
 * "React re-rendered and the browser kept decoding" apart from "React
 * re-rendered, the `<video>` was replaced, and it silently restarted at 0:00".
 * That makes it the most load-bearing test here — and this project's history
 * is a series of green tiers over a broken app: 297 vitest and 710 pytest while
 * every button was dead (`de74a02`), 734 + 317 + 12 + 3 all green while the job
 * drawer showed a job as 330 minutes old (`7efdc4c`).
 *
 * A gate nobody has seen fail is a gate whose failure mode is unknown. So this
 * deliberately breaks the product in the smallest way that would restart
 * playback, runs the real gate, and requires it to FAIL.
 *
 * ## The regression
 *
 * The video element is keyed by clip id (`key={playing.id}`), which is what
 * makes React reuse the existing DOM node across re-renders. Note that
 * `StudentDashboard` *does* call `useJobList`, so it really does re-render on
 * every job tick, and `ClipBrowser` is a plain unmemoized child — a tick walks
 * straight through to the video's owner. Playback survives only because
 * reconciliation reuses the node and `src` is unchanged, so no reload is
 * issued. That is a real and fragile mechanism, not a formality.
 *
 * So the regression makes the key unstable, which is the smallest edit that
 * forces a remount and a restart. Nothing else about the app changes.
 *
 * ## Usage
 *
 *   npm run verify:video-gate
 *
 * Patches source, runs the one spec, restores, and exits non-zero if the gate
 * did NOT catch it. Must not run concurrently with a real gate run or with a
 * dev server serving the files it edits.
 */

import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const APP = path.resolve(HERE, '..')
const TARGET = path.join(APP, 'src', 'features', 'student', 'ClipBrowser.tsx')

const ANCHOR = 'key={playing.id}'
/** Unstable on purpose: React remounts, so the browser reloads and restarts. */
const REGRESSION = 'key={`${playing.id}-${Math.random()}`}'

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { cwd: APP, encoding: 'utf8', shell: false, ...opts })
  if (r.error) {
    // `npx` is a shell script and is NOT on PATH as an executable on Windows, so
    // spawnSync returns ENOENT and `status` is null. That is a harness bug, and
    // it looks exactly like "the gate did not fail" — the first version of this
    // script reported INCONCLUSIVE for that reason and it was nearly mistaken
    // for the gate being unsound. So an absent interpreter is fatal and loud.
    throw new Error(`could not run ${cmd}: ${r.error.message}`)
  }
  return { status: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' }
}

/** The Playwright CLI, resolved the way npm resolves it. */
const PLAYWRIGHT_CLI = path.join(APP, 'node_modules', '@playwright', 'test', 'cli.js')

if (!existsSync(PLAYWRIGHT_CLI)) {
  console.error(`REFUSING TO RUN: ${PLAYWRIGHT_CLI} does not exist. Run npm install first.`)
  process.exit(2)
}

const original = readFileSync(TARGET, 'utf8')
if (!original.includes(ANCHOR)) {
  console.error(
    `REFUSING TO RUN: the anchor ${JSON.stringify(ANCHOR)} is not in ${path.basename(TARGET)}.\n` +
      'The negative control cannot inject its regression, so it would "pass" by\n' +
      'never testing anything. If that line was refactored, update this script.',
  )
  process.exit(2)
}

writeFileSync(TARGET, original.replace(ANCHOR, REGRESSION), 'utf8')
console.log(`[control] injected unstable key into ${path.basename(TARGET)}`)

// Cleared first so a stale "passed" from an earlier real run cannot be read as
// this run's result. The file is written by Playwright itself.
const lastRun = path.join(APP, 'test-results', '.last-run.json')
rmSync(lastRun, { force: true })

let gateFailed = false
let output = ''
let status = null
try {
  const r = run(process.execPath, [PLAYWRIGHT_CLI, 'test', 'e2e/video.e2e.spec.ts', '--reporter=list'])
  output = r.stdout + r.stderr
  status = r.status
  gateFailed = r.status !== 0
} finally {
  writeFileSync(TARGET, original, 'utf8')
  const restored = readFileSync(TARGET, 'utf8')
  if (restored !== original) {
    console.error('[control] FAILED TO RESTORE ClipBrowser.tsx — restoring from git.')
    run('git', ['checkout', '--', path.relative(APP, TARGET)])
  }
  console.log('[control] restored ClipBrowser.tsx')
}

// Playwright's reporter writes progress to a TTY this capture largely misses,
// so `output` can be thin. The on-disk last-run record is the primary evidence
// that the spec ran and which test failed, and it is printed in full.
let lastRunJson = null
try {
  lastRunJson = JSON.parse(readFileSync(lastRun, 'utf8'))
} catch {
  /* absent or unreadable: handled by the check below */
}

console.log(`\n[control] gate exit status: ${status}`)
console.log(`[control] last-run.json: ${JSON.stringify(lastRunJson)}`)

// A non-zero exit is necessary but not sufficient: the gate must have failed
// for the RIGHT reason. A timeout, a webServer that never came up, or an
// unrelated compile error would also exit non-zero, and "the gate can fail"
// would then be true only in the useless sense that it fails when the harness
// is broken.
//
// Playwright records failing tests as opaque hashes, not names, so the name
// cannot be matched against last-run.json. Requiring `status === 'failed'` AND
// that the reporter named our test is the workable equivalent: the first says a
// test ran and went red, the second says it was *this* spec rather than another
// file picked up by the same run.
const namedTheTest = output.includes('keeps decoding while real job snapshots arrive')
const failedByAssertion = lastRunJson?.status === 'failed' && namedTheTest

console.log(`\n${output.split('\n').filter((l) => l.trim()).slice(-30).join('\n')}`)

if (gateFailed && failedByAssertion) {
  console.log(
    '\n[control] PASS — the gate ran, and its own assertion caught the remounting\n' +
      '<video>. It can fail, and it fails for the right reason.',
  )
  process.exit(0)
}

if (gateFailed && !failedByAssertion) {
  console.error(
    '\n[control] INCONCLUSIVE — the spec exited non-zero, but not because its own\n' +
      'assertion failed. A timeout, a webServer that never started or an\n' +
      'unrelated error would look identical. This proves nothing either way.',
  )
  process.exit(1)
}

console.error(
  '\n[control] FAIL — the gate passed while the video was being remounted on every\n' +
    'render. video.e2e.spec.ts is not testing what it claims to test. Fix the\n' +
    'spec before trusting it.',
)
process.exit(1)