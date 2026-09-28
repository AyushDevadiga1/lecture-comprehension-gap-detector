import React from 'react'
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Badge,
  IconButton,
  Tooltip,
} from '@mui/material'
import { NavLink, useLocation } from 'react-router-dom'
import BoltIcon from '@mui/icons-material/Bolt'
import SchoolIcon from '@mui/icons-material/School'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import LayersIcon from '@mui/icons-material/Layers'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../api/courses'
import { useAppStore } from '../../store/useAppStore'
import { useActiveJobs, useFeedStatus } from '../../lib/useJobFeed'
import { queryKeys } from '../../lib/queryKeys'

export const Navbar: React.FC = () => {
  const location = useLocation()
  const { selectedCourseId, setSelectedCourseId, toggleJobDrawer } = useAppStore()
  // Reads the query cache, not the feed. The badge and the status dot are the
  // only Navbar elements that depend on job state.
  const activeJobs = useActiveJobs(selectedCourseId)
  const { mode } = useFeedStatus(selectedCourseId)
  const isConnected = mode === 'stream'

  // The error is read too, so a failed course list never renders as
  // "No courses found" — that text reads as *your data is gone* rather than
  // *you are not authorised*, and sends the reader hunting in the wrong place.
  // The 401 case is covered by the AuthBanner; this covers everything else.
  const {
    data: courseList = [],
    isError: coursesFailed,
  } = useQuery({
    queryKey: queryKeys.courses(),
    queryFn: () => coursesApi.list(),
  })


  return (
    <AppBar position="sticky" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar sx={{ justifyContent: 'space-between', px: { xs: 2, md: 4 } }}>
        {/* Brand */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box
            sx={{
              width: 36,
              height: 36,
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(99, 102, 241, 0.4)',
            }}
          >
            <AccountTreeIcon sx={{ color: '#fff', fontSize: 20 }} />
          </Box>
          <Box>
            <Typography
              variant="h6"
              sx={{
                fontWeight: 800,
                fontSize: '1.15rem',
                letterSpacing: '-0.02em',
                background: 'linear-gradient(90deg, #f8fafc 0%, #cbd5e1 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}
            >
              LecGap
            </Typography>
            <Typography variant="caption" sx={{ color: '#94a3b8', fontSize: '0.68rem', display: 'block', mt: -0.5 }}>
              Engine 2 &bull; Comprehension DAG
            </Typography>
          </Box>
        </Box>

        {/* Navigation Tabs */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Button
            component={NavLink}
            to="/student"
            startIcon={<SchoolIcon fontSize="small" />}
            variant={location.pathname.startsWith('/student') ? 'contained' : 'text'}
            sx={{
              color: location.pathname.startsWith('/student') ? '#fff' : 'text.secondary',
              backgroundColor: location.pathname.startsWith('/student') ? 'primary.main' : 'transparent',
            }}
          >
            Student Portal
          </Button>

          <Button
            component={NavLink}
            to="/faculty"
            startIcon={<LayersIcon fontSize="small" />}
            variant={location.pathname.startsWith('/faculty') ? 'contained' : 'text'}
            sx={{
              color: location.pathname.startsWith('/faculty') ? '#fff' : 'text.secondary',
              backgroundColor: location.pathname.startsWith('/faculty') ? 'primary.main' : 'transparent',
            }}
          >
            Faculty Insights
          </Button>
        </Box>

        {/* Right Tools: Course Selector + Jobs Drawer Trigger */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel id="course-select-label" sx={{ color: 'text.secondary' }}>
              Course
            </InputLabel>
            <Select
              labelId="course-select-label"
              value={selectedCourseId || ''}
              label="Course"
              onChange={(e) => setSelectedCourseId(e.target.value)}
              sx={{
                borderRadius: 2,
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                '& .MuiSelect-select': { py: 1, fontWeight: 600 },
              }}
            >
              {selectedCourseId && !courseList.some((c) => c.course_id === selectedCourseId) && (
                <MenuItem value={selectedCourseId} sx={{ display: 'none' }}>
                  {selectedCourseId.toUpperCase()}
                </MenuItem>
              )}
              {courseList.map((c) => (
                <MenuItem key={c.course_id} value={c.course_id}>
                  {c.course_id.toUpperCase()} ({c.total_lectures} lecs)
                </MenuItem>
              ))}
              {courseList.length === 0 && !selectedCourseId && (
                <MenuItem value="" disabled>
                  {coursesFailed ? 'Could not load courses' : 'No courses found'}
                </MenuItem>
              )}
            </Select>

          </FormControl>

          {/* Jobs drawer toggle with active count */}
          <Tooltip title="View Background Jobs & Pipelines">
            <IconButton onClick={toggleJobDrawer} color="inherit" sx={{ border: '1px solid rgba(255,255,255,0.08)' }}>
              <Badge badgeContent={activeJobs.length} color="primary">
                <BoltIcon sx={{ color: activeJobs.length > 0 ? '#38bdf8' : 'text.secondary' }} />
              </Badge>
            </IconButton>
          </Tooltip>

          {/* SSE Connection dot indicator */}
          <Tooltip title={isConnected ? 'SSE Live Connection Active' : 'Connecting to SSE Stream...'}>
            <Box
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                backgroundColor: isConnected ? '#10b981' : '#f59e0b',
                boxShadow: isConnected ? '0 0 10px #10b981' : 'none',
              }}
            />
          </Tooltip>
        </Box>
      </Toolbar>
    </AppBar>
  )
}
