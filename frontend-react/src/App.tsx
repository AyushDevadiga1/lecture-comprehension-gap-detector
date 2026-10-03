import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import type { QueryClient } from '@tanstack/react-query'
import { queryClient as defaultQueryClient } from './lib/queryClient'
import { AppProviders } from './AppProviders'
import { AppLayout } from './components/layout/AppLayout'
import { StudentDashboard } from './features/student/StudentDashboard'
import { FacultyDashboard } from './features/faculty/FacultyDashboard'
import { NotFound } from './components/common/NotFound'

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
          <Route path="/" element={<AppLayout />}>
            <Route index element={<Navigate to="/student" replace />} />
            <Route path="student" element={<StudentDashboard />} />
            <Route path="faculty" element={<FacultyDashboard />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProviders>
  )
}

export default App
