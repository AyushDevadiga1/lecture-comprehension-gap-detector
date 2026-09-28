import React from 'react'
import { Outlet } from 'react-router-dom'
import { Box, Container } from '@mui/material'
import { Navbar } from './Navbar'
import { JobDrawer } from '../common/JobDrawer'
import { useAppStore } from '../../store/useAppStore'
import { useJobFeed } from '../../lib/jobFeed'

export const AppLayout: React.FC = () => {
  const { selectedCourseId } = useAppStore()

  // Maintain live SSE connection scoped to current course
  useJobFeed(selectedCourseId)

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
