import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { queryClient as defaultQueryClient } from './lib/queryClient'
import { AppTheme } from './theme/AppTheme'
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
    <QueryClientProvider client={client}>
      <AppTheme>
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
      </AppTheme>
    </QueryClientProvider>
  )
}

export default App
