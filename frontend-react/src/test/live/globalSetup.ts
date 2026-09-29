/**
 * Global setup for the LIVE test tier: boot a real backend, once, for the whole
 * run.
 *
 * ## Why this exists
 *
 * All 297 existing React tests inject a fake transport (`mockFetch` replaces
 * `globalThis.fetch`). That makes them proof of *policy* and proof of nothing
 * about whether the app actually talks to a server. The bill came due on
 * 2026-09-29: an app whose extract worker raised `IntegrityError` on every
 * click passed 297 frontend and 710 backend tests.
 *
 * So this tier does the one thing the mocked tier cannot — it starts a real
 * `uvicorn` against a real (throwaway) SQLite database and lets the real
 * components render real responses.
 *
 * ## What it deliberately does NOT prove
 *
 * A browser's ability to read a *streaming* body through Vite's dev proxy, and
 * `requestAnimationFrame` coalescing under a throttled or backgrounded tab.
 * jsdom has `rAF`; a real browser under load is a different question. That
 * needs Playwright, which is a separate decision.
 *
 * ## Hygiene
 *
 * - Temp DB only. `data/lecgap.db` in the repo is never opened.
 * - A random free port, so a server the developer is already running is never
 *   touched or killed. We only ever kill the child this file spawned.
 * - No `--reload`: the reloader would fork a grandchild that outlives our
 *   kill, and a stray uvicorn holding a port is exactly the trap the handoff
 *   warns about.
 */

import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// <repo>/frontend-react/src/test/live/  ->  <repo>
const REPO = path.resolve(__dirname, '..', '..', '..', '..')
const PYTHON = 'D:\\Anaconda3\\envs\\lecgap\\python.exe'
const WORK = path.join(tmpdir(), 'lecgap-live-tier')
const DB = path.join(WORK, 'live.db')
const SEED = path.join(REPO, 'frontend-react', 'scripts', 'seed_live_db.py')
/** Where the chosen port is published for the test files to read. */
export const PORT_FILE = path.join(WORK, 'port.txt')

let child: ChildProcess | null = null

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address()
      const port = typeof addr === 'object' && addr ? addr.port : 0
      srv.close(() => (port ? resolve(port) : reject(new Error('no free port'))))
    })
  })
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function waitForHealth(port: number, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let last = 'never attempted'
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`)
      if (res.ok) {
        await res.json()
        return
      }
      last = `HTTP ${res.status}`
    } catch (err) {
      last = String(err)
    }
    await sleep(250)
  }
  throw new Error(`live backend never became healthy (${timeoutMs}ms). last: ${last}`)
}

/** SQLite URLs want forward slashes; a Windows path with backslashes is fragile. */
const DB_URL = `sqlite:///${DB.replace(/\\/g, '/')}`
void DB_URL

async function assertServingTheSeed(port: number): Promise<void> {
  /*
   * Fail loudly if the booted server is not the one we seeded.
   *
   * This check exists because it is easy to boot a server that is *not* on the
   * throwaway database and never notice: the tests still get plausible JSON,
   * just from the developer's real data, and then assert against numbers that
   * belong to somebody else's lectures. That is a silent, confusing failure —
   * so the mismatch is turned into a named error here, at boot.
   */
  const res = await fetch(`http://127.0.0.1:${port}/courses`)
  const rows = (await res.json()) as { course_id: string; total_lectures: number }[]
  const ml = rows.find((c) => c.course_id === 'ml')
  const ids = rows.map((c) => c.course_id).sort().join(',')
  if (ids !== 'ml,prob' || ml?.total_lectures !== 2) {
    throw new Error(
      `live backend is NOT serving the seeded database.\n` +
        `  expected: courses=[ml,prob] ml.total_lectures=2\n` +
        `  actual  : courses=[${ids}] ml.total_lectures=${ml?.total_lectures}\n` +
        `  db url  : ${DB_URL}\n` +
        `The spawned server is reading some other database. Refusing to run ` +
        `tests against it.`,
    )
  }
}

export async function setup(): Promise<void> {

  if (!existsSync(PYTHON)) {
    throw new Error(
      `project interpreter not found at ${PYTHON}. The live tier runs the real ` +
        `backend, so it needs the project env, not whatever is on PATH.`,
    )
  }
  rmSync(WORK, { recursive: true, force: true })
  mkdirSync(WORK, { recursive: true })

  const seed = spawnSync(PYTHON, [SEED, DB], {
    cwd: REPO,
    encoding: 'utf8',
  })
  if (seed.status !== 0) {
    throw new Error(`seed_live_db.py failed:\n${seed.stdout}\n${seed.stderr}`)
  }

  const port = await freePort()
  process.stderr.write(`[live] spawning: db=${DB} port=${port}\n`)
  // The DB path is passed as an ARGUMENT, not as LEGCAP_DATABASE_URL in `env`:
  // see scripts/run_live_server.py for why a cross-process env var cannot be
  // trusted to isolate this, and why the launcher re-verifies the binding.
  child = spawn(PYTHON, [path.join(REPO, 'frontend-react', 'scripts', 'run_live_server.py'), DB, String(port)], {
    cwd: REPO,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout?.on('data', (b) => process.stdout.write(`[live] ${b}`))
  child.stderr?.on('data', (b) => process.stderr.write(`[live] ${b}`))
  child.on('exit', (code, signal) => {
    if (code !== 0 && code !== null) {
      process.stderr.write(`[live] backend exited early: code=${code} signal=${signal}\n`)
    }
  })

  await waitForHealth(port)
  await assertServingTheSeed(port)
  writeFileSync(PORT_FILE, String(port), 'utf8')
  process.stderr.write(`[live] backend healthy on http://127.0.0.1:${port} (db: ${DB})\n`)
}

export async function teardown(): Promise<void> {
  if (child && child.exitCode === null) {
    child.kill()
    // Give it a moment to release the port before the next run claims one.
    for (let i = 0; i < 40 && child.exitCode === null; i += 1) await sleep(50)
    if (child.exitCode === null) child.kill('SIGKILL')
  }
  child = null
  rmSync(WORK, { recursive: true, force: true })
}

/** Read the base URL of the running live backend. Throws if it is not up. */
export function liveBaseUrl(): string {
  if (!existsSync(PORT_FILE)) {
    throw new Error(
      'live backend port file missing — globalSetup did not run. ' +
        'These tests must be run through `npm run test:live`, not bare `vitest`.',
    )
  }
  return `http://127.0.0.1:${readFileSync(PORT_FILE, 'utf8').trim()}`
}
