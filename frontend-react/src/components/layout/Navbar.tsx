import React, { useEffect } from 'react'
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
import LightModeIcon from '@mui/icons-material/LightMode'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import { useQuery } from '@tanstack/react-query'
import { courses as coursesApi } from '../../api/courses'
import { useAppStore } from '../../store/useAppStore'
import { useActiveJobs, useFeedStatus } from '../../lib/useJobFeed'
import { feedStatus } from '../../lib/feedStatus'
import { queryKeys } from '../../lib/queryKeys'
import { gradient, tint } from '../../theme/alpha'

export const Navbar: React.FC = () => {
  const location = useLocation()
  const { selectedCourseId, setSelectedCourseId, toggleJobDrawer, base, toggleBase } = useAppStore()
  // Reads the query cache, not the feed. The badge and the status dot are the
  // only Navbar elements that depend on job state.
  const activeJobs = useActiveJobs(selectedCourseId)
  const { mode } = useFeedStatus(selectedCourseId)
  // One description of the feed, shared with the drawer. This used to be
  // `mode === 'stream'`, which reported a feed that had *given up* as
  // "Connecting to SSE Stream…" — forever, and indistinguishably from a slow
  // start. See lib/feedStatus.ts.
  const feed = feedStatus(mode)

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

  // Auto-select the first available course when no course is stored yet (fresh
  // install, private-mode, or the stored id was cleared). This runs once per
  // course-list load so it does not race with a deliberate user deselect.
  useEffect(() => {
    if (selectedCourseId == null && courseList.length > 0) {
      setSelectedCourseId(courseList[0]!.course_id)
    }
  }, [courseList, selectedCourseId, setSelectedCourseId])

  // If the stored course no longer exists on the server (deleted between
  // sessions), fall back to the first available one. Prevents a permanently
  // broken state where every query silently fires with a 404-producing id.
  useEffect(() => {
    if (
      selectedCourseId != null &&
      courseList.length > 0 &&
      !courseList.some((c) => c.course_id === selectedCourseId)
    ) {
      setSelectedCourseId(courseList[0]!.course_id)
    }
  }, [courseList, selectedCourseId, setSelectedCourseId])

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
              background: gradient('info', 'ok', 135),
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: `0 4px 12px ${tint('info', 40)}`,
            }}
          >
            <AccountTreeIcon sx={{ color: 'primary.contrastText', fontSize: 20 }} />
          </Box>
          <Box>
            <Typography
              variant="h6"
              sx={{
                fontWeight: 800,
                fontSize: '1.15rem',
                letterSpacing: '-0.02em',
                // gradient() returns a CSS gradient string; without a non-transparent
                // background, -webkit-text-fill-color: transparent renders nothing.
                background: gradient('info', 'ok', 135),
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}
            >
              LecGap
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem', display: 'block', mt: -0.5 }}>
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
              color: location.pathname.startsWith('/student') ? 'primary.contrastText' : 'text.secondary',
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
              color: location.pathname.startsWith('/faculty') ? 'primary.contrastText' : 'text.secondary',
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
                // A wash of `text`, not a hardcoded white at 4%.
                // A white wash is invisible the moment anyone flips to the light
                // base — white on a white select is no wash at all.
                backgroundColor: tint('text', 4),
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

          {/* Theme base. The choice is remembered and defaults to the OS
              preference; see `resolveInitialBase`.

              `aria-label` on both icon buttons below is load-bearing, not
              decoration. A MUI `Tooltip` does NOT give its child an accessible
              name — it sets `aria-describedby` while open, and the title is
              otherwise unreachable — so an `IconButton` wrapping only an icon
              with no `aria-label` is an unnamed control: invisible to a screen
              reader, and unaddressable by role in a test. The E2E tier found
              this by timing out on `getByRole('button', { name: ... })`. */}
          <Tooltip title={base === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            <IconButton
              onClick={toggleBase}
              color="inherit"
              aria-label={base === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              sx={{ border: '1px solid', borderColor: 'divider' }}
            >
              {base === 'dark' ? <LightModeIcon fontSize="small" /> : <DarkModeIcon fontSize="small" />}
            </IconButton>
          </Tooltip>

          {/* Jobs drawer toggle with active count */}
          <Tooltip title="View Background Jobs & Pipelines">
            <IconButton
              onClick={toggleJobDrawer}
              color="inherit"
              aria-label="View Background Jobs & Pipelines"
              sx={{ border: '1px solid', borderColor: 'divider' }}
            >
              <Badge badgeContent={activeJobs.length} color="primary">
                <BoltIcon sx={{ color: activeJobs.length > 0 ? 'info.main' : 'text.secondary' }} />
              </Badge>
            </IconButton>
          </Tooltip>

          {/* Feed connection indicator. The dot is decorative; the tooltip carries the
              meaning, and `aria-label` repeats it so the state is not trapped in
              a hover — a screen reader gets "Feed status: <detail>" rather than
              silence. */}
          <Tooltip title={feed.detail}>
            <Box
              role="status"
              aria-label={`Feed status: ${feed.detail}`}
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                backgroundColor:
                  feed.tone === 'ok'
                    ? 'success.main'
                    : feed.tone === 'degraded'
                      ? 'warning.main'
                      : 'text.disabled',
                boxShadow: feed.tone === 'ok' ? '0 0 10px var(--lgc-ok)' : 'none',
              }}
            />
          </Tooltip>
        </Box>
      </Toolbar>
    </AppBar>
  )
}
