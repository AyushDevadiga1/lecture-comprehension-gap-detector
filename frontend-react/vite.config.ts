import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

/**
 * Dev proxy: FastAPI on :8000.
 *
 * The API mounts every route at the top level (`/courses`, `/lectures`, `/jobs`,
 * ...), so the client calls bare paths and the proxy makes them same-origin —
 * which is what lets `fetch` read the SSE stream on /jobs/stream. There is no
 * `/api` prefix; an earlier config had one with a rewrite that nothing used.
 */
const BACKEND = 'http://localhost:8000'

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
    exclude: [...configDefaults.exclude, 'src/**/*.live.test.{ts,tsx}'],
  },
})
