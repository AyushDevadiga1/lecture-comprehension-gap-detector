import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

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
    // Dev proxy — all /api/* calls are forwarded to FastAPI on :8000.
    // No CORS headers needed in dev; the browser sees requests on the same origin.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      // SSE stream lives under /jobs/stream — proxy it too so EventSource works
      '/jobs': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/lectures': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/courses': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/quizzes': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/students': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/usage': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
