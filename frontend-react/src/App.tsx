import React, { Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import type { QueryClient } from '@tanstack/react-query'
import { queryClient as defaultQueryClient } from './lib/queryClient'
import { AppProviders } from './AppProviders'
import { AppShell } from './components/layout/AppShell'
import { NotFound } from './components/common/NotFound'
import { LoadingScreen } from './components/common/LoadingScreen'

/**
 * The route table.
 *
 * One route per concern, every view code-split, so a visit fetches the view it
 * asked for and nothing else. `/student` and `/faculty` redirect to their index
 * views: those paths were the only two that existed before the revamp, so
 * bookmarks, the browser tests and NotFound's button keep working.
 *
 * The order of the sidebar (`src/nav.ts`) and the order here are deliberately
 * independent — the nav table owns *where the links go*, this file owns *what
 * renders*. Both are listed in `revamp-plan/01-architecture.md`.
 */

const OverviewView = React.lazy(() =>
  import('./features/student/views/OverviewView').then((m) => ({ default: m.OverviewView })),
)
const LecturesView = React.lazy(() =>
  import('./features/student/views/LecturesView').then((m) => ({ default: m.LecturesView })),
)
const MapView = React.lazy(() =>
  import('./features/student/views/MapView').then((m) => ({ default: m.MapView })),
)
const LectureDetailView = React.lazy(() =>
  import('./features/student/views/LectureDetailView').then((m) => ({ default: m.LectureDetailView })),
)
const QuizView = React.lazy(() =>
  import('./features/student/views/QuizView').then((m) => ({ default: m.QuizView })),
)
const RemediationView = React.lazy(() =>
  import('./features/student/views/RemediationView').then((m) => ({ default: m.RemediationView })),
)
const ClipsView = React.lazy(() =>
  import('./features/student/views/ClipsView').then((m) => ({ default: m.ClipsView })),
)
const AnalyticsView = React.lazy(() =>
  import('./features/faculty/views/AnalyticsView').then((m) => ({ default: m.AnalyticsView })),
)
const HeatmapView = React.lazy(() =>
  import('./features/faculty/views/HeatmapView').then((m) => ({ default: m.HeatmapView })),
)
const DivergenceView = React.lazy(() =>
  import('./features/faculty/views/DivergenceView').then((m) => ({ default: m.DivergenceView })),
)
const CoverageView = React.lazy(() =>
  import('./features/faculty/views/CoverageView').then((m) => ({ default: m.CoverageView })),
)
const JobsView = React.lazy(() =>
  import('./features/system/views/JobsView').then((m) => ({ default: m.JobsView })),
)
const SystemView = React.lazy(() =>
  import('./features/system/views/SystemView').then((m) => ({ default: m.SystemView })),
)

/** One Suspense boundary per route: a chunk loads into its own slot. */
function view(element: React.ReactNode): React.ReactElement {
  return <Suspense fallback={<LoadingScreen message="Loading view…" />}>{element}</Suspense>
}

interface AppProps {
  /** Injectable so a test can pass an isolated cache; the app uses the singleton. */
  client?: QueryClient
}

export const App: React.FC<AppProps> = ({ client = defaultQueryClient }) => {
  return (
    // The query client and the theme stack live in `AppProviders`, shared with
    // `src/test/render.tsx`. The router stays here because it is the one thing
    // that genuinely differs between the app and a test.
    <AppProviders client={client}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route index element={<Navigate to="/student/overview" replace />} />

            <Route path="student">
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview" element={view(<OverviewView />)} />
              <Route path="lectures" element={view(<LecturesView />)} />
              <Route path="map" element={view(<MapView />)} />
              <Route path="lecture" element={view(<LectureDetailView />)} />
              <Route path="quiz" element={view(<QuizView />)} />
              <Route path="remediation" element={view(<RemediationView />)} />
              <Route path="clips" element={view(<ClipsView />)} />
            </Route>

            <Route path="faculty">
              <Route index element={<Navigate to="analytics" replace />} />
              <Route path="analytics" element={view(<AnalyticsView />)} />
              <Route path="heatmap" element={view(<HeatmapView />)} />
              <Route path="divergence" element={view(<DivergenceView />)} />
              <Route path="coverage" element={view(<CoverageView />)} />
            </Route>

            <Route path="jobs" element={view(<JobsView />)} />
            <Route path="system" element={view(<SystemView />)} />

            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProviders>
  )
}

export default App
