import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './lib/queryClient'
import { theme } from './theme/theme'
import { AppLayout } from './components/layout/AppLayout'
import { StudentDashboard } from './pages/StudentDashboard'
import { FacultyDashboard } from './pages/FacultyDashboard'
import { NotFound } from './pages/NotFound'

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
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
      </ThemeProvider>
    </QueryClientProvider>
  )
}

export default App
