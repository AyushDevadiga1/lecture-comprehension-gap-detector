import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { existsSync, readFileSync } from 'node:fs'
import path from 'path'

/**
 * Dev proxy: FastAPI on :8000.
 *
 * The API mounts every route at the top level (`/courses`, `/lectures`, `/jobs`,
 * ...), so the client calls bare paths and the proxy makes them same-origin —
 * which is what lets `fetch` read the SSE stream on /jobs/stream. There is no
 * `/api` prefix; an earlier config had one with a rewrite that nothing used.
 *
 * The E2E tier needs the backend on a port of its own rather than fighting a
 * developer's already-running uvicorn on :8000. It used to pass that through
 * `LECGAP_BACKEND` in the environment, and that was unreliable here in a way
 * worth recording: through `webServer.env` the variable never reached Vite, and
 * in cmd.exe syntax (`set X=... && npm run dev`) it did not either, while in
 * POSIX syntax it made the shell fail outright. Three attempts, one variable.
 *
 * So it is a file instead. `playwright.config.ts` writes `.e2e/backend.url` when
 * it loads, which is before any webServer spawns and therefore before this
 * config is read by the dev server. No shell quoting, no env inheritance, and
 * the proxy cannot silently fall back to the wrong port — which is exactly the
 * failure it had, and exactly what this tier exists to catch.
 *
 * A first attempt at this read the file with `require('node:fs')` inside a
 * try/catch. Vite bundles this config as ESM, `require` is undefined, the
 * catch swallowed it, and the proxy fell back to :8000 — the same silent
 * failure a third time, from a different cause. Hence the import above, and
 * hence the log line: a fallback should be visible, not inferred from a symptom
 * three layers away.
 */
const E2E_TARGET_FILE = path.resolve(__dirname, '.e2e', 'backend.url')
const E2E_TARGET = existsSync(E2E_TARGET_FILE) ? readFileSync(E2E_TARGET_FILE, 'utf8').trim() : null
const BACKEND = E2E_TARGET ?? 'http://localhost:8000'

// eslint-disable-next-line no-console
console.log(`[vite.config] proxy target: ${BACKEND}${E2E_TARGET ? ' (from .e2e/backend.url)' : ' (default)'}`)

/** Every backend prefix the client may call, or that the browser may load. */
const PROXY_PREFIXES = [
  '/courses',
  '/lectures',
  '/quizzes',
  '/students',
  '/jobs',
  '/media',
  '/usage',
  '/health',
  '/llm',
] as const

const proxy = Object.fromEntries(
  PROXY_PREFIXES.map((prefix) => [prefix, { target: BACKEND, changeOrigin: true }]),
)

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // The live tier (`*.live.test.ts`) runs against a real spawned backend and
    // is configured by vitest.live.config.ts. It must NOT be collected here:
    // with no VITE_LECGAP_API_URL the client falls back to same-origin, every
    // request goes to jsdom's localhost:3000, and the suite fails on
    // ECONNREFUSED rather than on anything meaningful. Keeping the two tiers
    // disjoint is what lets `npm run verify` stay fast and hermetic.
    //
    // `e2e/` is excluded for the same reason with a sharper edge: those are
    // Playwright specs, and vitest collecting one fails with "Playwright Test did
    // not expect test.describe() to be called here" rather than with anything
    // that names the real problem.
    exclude: [...configDefaults.exclude, 'src/**/*.live.test.{ts,tsx}', 'e2e/**'],
  },
})
