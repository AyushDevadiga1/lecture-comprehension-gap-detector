/**
 * Runs in the worker BEFORE any test file is imported.
 *
 * `api/client.ts` captures its base URL into a module-level const at import
 * time (`const BASE = import.meta.env.VITE_LECGAP_API_URL ?? ''`), so the env
 * var has to exist before the first `import` of anything under `api/`. A
 * `beforeEach` is too late; static ESM imports are hoisted above it. Hence a
 * setup file.
 *
 * The port is only known after `globalSetup` ran, which is why it is read from
 * the file that globalSetup published rather than from a build-time constant.
 */

import { existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const PORT_FILE = path.join(tmpdir(), 'lecgap-live-tier', 'port.txt')

if (!existsSync(PORT_FILE)) {
  throw new Error(
    'live backend port file missing — globalSetup did not run. ' +
      'Use `npm run test:live`, not bare `vitest`.',
  )
}

const base = `http://127.0.0.1:${readFileSync(PORT_FILE, 'utf8').trim()}`
process.env.VITE_LECGAP_API_URL = base
// Same-origin default is what the dev proxy provides; the live tier bypasses
// the proxy on purpose so a failure here is the backend's, not Vite's.
process.env.VITE_LECGAP_API_KEY = ''

export {}
