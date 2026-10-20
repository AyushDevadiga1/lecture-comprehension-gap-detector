import React from 'react'
import { Outlet } from 'react-router-dom'
import { Box } from '@mui/material'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { AuthBanner } from '../common/AuthBanner'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { JobDrawer } from '../common/JobDrawer'
import { JobCompletionHost } from '../common/JobCompletionHost'
import { useAppStore } from '../../store/useAppStore'
import { useJobFeedConnection } from '../../lib/useJobFeed'
import { useRouteFocus } from '../../lib/useRouteFocus'

/**
 * The application shell: sidebar, banner, topbar, the routed view, and the two
 * job surfaces.
 *
 * This is `AppLayout` renamed, with the sidebar added. Two things it must keep
 * doing exactly as before:
 *
 *  1. It owns the SSE connection (`useJobFeedConnection`) and **reads nothing
 *     from it**. A component that renders `<Outlet/>` must never subscribe to
 *     job state, or every 1 Hz tick re-renders the page and restarts a playing
 *     `<video>` (§1 / §10). The sidebar's badge is a leaf read; the drawer and
 *     the completion host are siblings of the outlet, not ancestors.
 *  2. The error boundary sits *inside* the chrome, so a view that throws costs
 *     the view and nothing else — the sidebar and drawer stay usable, which is
 *     how you find out what broke.
 */
export const AppShell: React.FC = () => {
  const { selectedCourseId } = useAppStore()
  const mainRef = React.useRef<HTMLElement>(null)

  useJobFeedConnection(selectedCourseId)
  useRouteFocus(mainRef)

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar />

      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* §6: a 401 is one banner, never a dead "no courses" state. */}
        <AuthBanner />
        <Topbar />

        <Box
          component="main"
          ref={mainRef}
          tabIndex={-1}
          sx={{ flexGrow: 1, px: { xs: 2, md: 3 }, py: { xs: 2, md: 3 }, outline: 'none' }}
        >
          <ErrorBoundary title="This page failed to render" resetKeys={[selectedCourseId]}>
            <Outlet />
          </ErrorBoundary>
        </Box>
      </Box>

      <JobDrawer />
      {/* Announced here, in the page body — never inside the progress surface. */}
      <JobCompletionHost />
    </Box>
  )
}
