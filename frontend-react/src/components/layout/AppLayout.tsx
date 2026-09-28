import React from 'react'
import { Outlet } from 'react-router-dom'
import { Box, Container } from '@mui/material'
import { Navbar } from './Navbar'
import { JobDrawer } from '../common/JobDrawer'
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
      <Box component="main" sx={{ flexGrow: 1, py: { xs: 3, md: 5 } }}>
        <Container maxWidth="xl">
          <Outlet />
        </Container>
      </Box>
      <JobDrawer />
    </Box>
  )
}
