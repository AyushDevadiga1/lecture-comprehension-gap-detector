import React from 'react'
import { Outlet } from 'react-router-dom'
import { Box, Container } from '@mui/material'
import { Navbar } from './Navbar'
import { JobDrawer } from '../common/JobDrawer'
import { JobCompletionHost } from '../common/JobCompletionHost'
import { AuthBanner } from '../common/AuthBanner'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { useAppStore } from '../../store/useAppStore'
import { useJobFeedConnection } from '../../lib/useJobFeed'

export const AppLayout: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  // Connects the feed and reads nothing. §1: a component that renders <Outlet/>
  // must not subscribe to job state, or every 1Hz tick re-renders the page and
  // restarts any playing <video>. JobDrawer and Navbar read the cache directly.
  useJobFeedConnection(selectedCourseId)

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Navbar />
      {/* §6: a 401 is one banner, never a dead "no courses" state. */}
      <AuthBanner />
      <Box component="main" sx={{ flexGrow: 1, py: { xs: 3, md: 5 } }}>
        <Container maxWidth="xl">
          {/* The per-route boundary. A dashboard that throws while rendering
              costs you the dashboard and nothing else: the navbar stays, the job
              drawer stays, and the drawer is usually where the answer is.
              `resetKeys` re-arms it on a course change, so one transient throw
              does not poison the route for the rest of the session. */}
          <ErrorBoundary
            title="This page failed to render"
            resetKeys={[selectedCourseId]}
          >
            <Outlet />
          </ErrorBoundary>
        </Container>
      </Box>
      <JobDrawer />
      {/* Announced here, in the page body — never inside the progress surface. */}
      <JobCompletionHost />
    </Box>
  )
}

