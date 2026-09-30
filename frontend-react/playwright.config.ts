/**
 * Playwright config — the E2E tier: a REAL browser, a REAL Vite dev server, a
 * REAL backend, and the real SSE stream through the real proxy.
 *
 * ## Why this exists and what only it can prove
 *
 * `npm run test:live` boots a real backend and proves the app renders real data
 * and that a real SSE stream is parsed. It runs in jsdom under Node, so it
 * cannot answer the question the handoff §0 keeps naming:
 *
 *   - can a browser read a *streaming* `fetch` body through a proxy at all?
 *   - does Vite's dev proxy actually stream `/jobs/stream`, or buffer it?
 *   - does `requestAnimationFrame` coalescing survive a real page?
 *   - is anything reachable on :8000 from :5173?
 *
 * Those are browser questions. This is the tier that answers them, and it is
 * what finally makes the app's central claim — live progress without reloading —
 * something other than an assertion about mocks.
 *
 * ## Ports
 *
 * Deliberately NOT 8000 and NOT 5173. Both belong to a developer's running
 * server, and the handoff records a session in which an agent started a uvicorn,
 * judged it not-up, and killed a process the user was still using. These are
 * fixed unusual ports so `webServer` owns and cleans up only what it started.
 *
 * ## Browser
 *
 * Pinned to @playwright/test 1.58.0, which expects chromium revision 1208 — the
 * build already in `%LOCALAPPDATA%\ms-playwright`. So this needs no browser
 * download. If you bump the Playwright version, expect `npx playwright install
 * chromium` to become necessary.
 */

import { defineConfig } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'path'

// Playwright loads this as an ES module, so `__dirname` does not exist. Vitest
// transpiles its config to CJS, which is why `__dirname` works there and fails
// here — an easy hour to lose.
const HERE = path.dirname(fileURLToPath(import.meta.url))

const BACKEND_PORT = 8123
const WEB_PORT = 5199
const REPO = path.resolve(HERE, '..')
const DB = path.join(REPO, 'frontend-react', '.e2e', 'e2e.db')
/** Forward slashes: this string is executed, not imported. */
const PYTHON = 'D:/Anaconda3/envs/lecgap/python.exe'
const LAUNCHER = 'frontend-react/scripts/run_live_server.py'

// Tell the dev server where its backend is, by file rather than by environment
// variable -- see the long note in vite.config.ts for the three dead ends that
// motivated it. Written here, at config load, which is before any webServer
// spawns and therefore before the dev server reads its own config.
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`
mkdirSync(path.dirname(DB), { recursive: true })
writeFileSync(path.join(path.dirname(DB), 'backend.url'), BACKEND_URL, 'utf8')

export default defineConfig({
  testDir: './e2e',
  // A real SSE stream plus a dev server: give it room, and never run the
  // browser specs in parallel against one backend's rows.
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],

  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
    // Assert nothing in the page logged an error; a silent React error boundary
    // is exactly how "the app is broken but the tests are green" happens.
    actionTimeout: 15_000,
  },

  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],

  webServer: [
    {
      // The real backend, on its own database, seeded in-process before it
      // serves. `run_live_server.py` takes the DB path as an argument and
      // re-verifies the engine binding, refusing to serve if it bound anywhere
      // else.
      //
      // The interpreter is spelled out: `python` on PATH is 3.13 or 3.11, not the
      // `lecgap` env this backend needs.
      command: `"${PYTHON}" ${LAUNCHER} ${DB} ${BACKEND_PORT} --seed`,
      cwd: REPO,
      url: `http://127.0.0.1:${BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // The real Vite dev server, proxying to the backend above. This is the hop
      // under test: if the proxy buffered the SSE response, the drawer would sit
      // on "Disconnected" and the first assertion below fails.
      //
      // `--host 127.0.0.1` is required, not decorative: Vite binds `localhost`,
      // which on this machine resolves to ::1 first, so a config pointing at
      // http://127.0.0.1:<port> times out even though the server is up.
      //
      // The backend's address reaches the dev server via `.e2e/backend.url`,
      // written above at config load. Three attempts at passing it as an
      // environment variable failed on this machine -- via `webServer.env`, and
      // in both cmd.exe and POSIX shell syntax -- and each failure was silent in
      // the worst way: the page loaded (the HTML comes from Vite) while every
      // proxied request was refused against the default http://localhost:8000.
      command: `npm run dev -- --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      cwd: path.join(REPO, 'frontend-react'),
      url: `http://127.0.0.1:${WEB_PORT}/student`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})

export { BACKEND_PORT, WEB_PORT, DB }
