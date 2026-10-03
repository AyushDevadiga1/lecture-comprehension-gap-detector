import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './components/common/ErrorBoundary'
import './index.css'

/**
 * The mount point `#root`, named rather than cast.
 *
 * `document.getElementById('root') as HTMLElement` was a cast with nothing
 * behind it. If the id ever changes in `index.html` — or this module is imported
 * by something with a different document — `createRoot(null)` throws React's
 * "Target container is not a DOM element", which points at React rather than at
 * the template that caused it. Failing here names the real culprit.
 */
const container = document.getElementById('root')
if (!container) {
  throw new Error('main.tsx: no #root in the document — check index.html')
}

/**
 * The root boundary sits *outside* `<App />`, and therefore outside every
 * provider it installs — QueryClientProvider, AppTheme, the router. That is the
 * point: a failure in any of them, or in the Navbar or the job drawer, would
 * otherwise take down the entire tree and leave a blank page. The per-route
 * boundary in `AppLayout` cannot help there, because it is inside them.
 *
 * See `ErrorBoundary` for why its fallback is deliberately allowed to look
 * degraded: if `AppTheme` never mounted, the `--lgc-*` custom properties were
 * never written.
 */
ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <ErrorBoundary title="LecGap could not start">
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
