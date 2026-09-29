/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

/**
 * The LIVE test tier — real backend, real database, real components.
 *
 * Kept in a separate config on purpose. `vite.config.ts` (what `npm run verify`
 * runs) must stay fast and hermetic: it is the gate for every commit and it
 * must never need a spawned uvicorn or a Python interpreter. This config is
 * run explicitly with `npm run test:live`, and it is the tier that would have
 * caught the 2026-09-29 extract failure.
 *
 * It shares `setup.ts` deliberately. That file's fail-closed `fetch` still
 * applies here; live tests must explicitly opt back into the real `fetch` via
 * `useLiveBackend()`, so "I forgot to mock" cannot silently become "I hit the
 * network" in either tier.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts', './src/test/live/setupLive.ts'],
    globalSetup: ['./src/test/live/globalSetup.ts'],
    include: ['src/**/*.live.test.{ts,tsx}'],
    // A spawned uvicorn plus a real SQLite file; the default 5s is tight for
    // first-run module transform on a cold Windows cache.
    testTimeout: 30_000,
    hookTimeout: 90_000,
    // The live backend is a single shared resource — parallel files would race
    // on the same rows.
    fileParallelism: false,
  },
})
